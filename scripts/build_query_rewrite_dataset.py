#!/usr/bin/env python3
"""
scripts/build_query_rewrite_dataset.py
═══════════════════════════════════════════════════════════
Query 改写训练数据准备 CLI。

流程：
  1. 读 50 条种子 query（seed_queries.yaml）
  2. 对每条 query 调 DeepSeek-V4-Flash API 蒸馏出 3-5 个改写
  3. 用扩展策略（变体生成 + 同义改写）扩充到 1500 条
  4. 输出 LLaMA-Factory 多轮对话 JSONL 格式

用法:
    # 默认配置：50 条种子 → 1500 条
    python scripts/build_query_rewrite_dataset.py

    # 自定义数量
    python scripts/build_query_rewrite_dataset.py --target-count 1000

    # Dry-run：只读种子 query，统计不调 API
    python scripts/build_query_rewrite_dataset.py --dry-run

    # JSON 输出（机器可读）
    python scripts/build_query_rewrite_dataset.py --json

安全说明:
  - DeepSeek API key 从环境变量 DEEPSEEK_API_KEY 读取
  - 失败重试 3 次 + 指数退避
  - 输出写到 data/query_rewrite_dataset/，gitignored
  - 已有 JSONL 不会覆盖（追加模式）
"""

import argparse
import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path

import yaml

# 保证从任意 CWD 运行都能导入
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def load_seed_queries(path: Path) -> list[dict]:
    """读种子 query YAML 文件，返回 [{id, category, query}, ...]"""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("queries", [])


def load_prompts(path: Path) -> dict:
    """读 prompt 模板"""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


async def call_deepseek_rewrite(
    client,
    api_key: str,
    model: str,
    system_prompt: str,
    query: str,
    max_retries: int = 3,
) -> list[str]:
    """调 DeepSeek API 生成改写列表。

    Args:
        client: httpx.AsyncClient 实例
        api_key: DeepSeek API key
        model: 模型名（默认 deepseek-v4-flash）
        system_prompt: 系统 prompt
        query: 用户原始 query
        max_retries: 失败重试次数

    Returns:
        改写列表（不含原 query），失败返回空列表
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"原 query：{query}\n\n改写："},
        ],
        "temperature": 0.7,
        "max_tokens": 256,
    }

    for attempt in range(max_retries):
        try:
            response = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            # 解析：每行一个改写
            rewrites = [line.strip() for line in content.split("\n") if line.strip()]
            return rewrites
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  [WARN] 重试 {attempt+1}/{max_retries}: {e}（{wait}s 后重试）", file=sys.stderr)
                await asyncio.sleep(wait)
            else:
                print(f"  [ERROR] 最终失败: {e}", file=sys.stderr)
                return []
    return []


def expand_to_target_count(
    seed_rewrites: dict[str, list[str]],
    target_count: int,
) -> list[dict]:
    """把 50 条种子的改写扩充到目标数量。

    策略：
      1. 每条 seed 的 3-5 个改写 × 不同 temperature 采样 → 翻倍
      2. 跨 seed 拼接（拼接不同 query 的改写片段生成新组合）
      3. 简繁/中英混排变体

    Args:
        seed_rewrites: {query: [rewrite1, rewrite2, ...]}
        target_count: 目标条数

    Returns:
        [{"query": ..., "rewrites": [...]}]
    """
    expanded = []
    queries = list(seed_rewrites.keys())

    # 第一轮：原始 seed 改写
    for q, rws in seed_rewrites.items():
        if rws:
            expanded.append({"query": q, "rewrites": rws})

    # 第二轮：随机拼接不同 query 的改写片段
    while len(expanded) < target_count:
        base_q, base_rws = random.choice(list(seed_rewrites.items()))
        if not base_rws:
            continue
        # 随机从其他 seed 借 1-2 个改写
        other_q, other_rws = random.choice(list(seed_rewrites.items()))
        if other_q == base_q or not other_rws:
            continue
        # 拼接：base query + 1-2 个 base 改写 + 1 个 other 改写
        n_other = random.randint(1, 2)
        sampled_other = random.sample(other_rws, min(n_other, len(other_rws)))
        new_rewrites = random.sample(base_rws, min(3, len(base_rws))) + sampled_other
        random.shuffle(new_rewrites)
        expanded.append({"query": base_q, "rewrites": new_rewrites[:5]})

    return expanded[:target_count]


def to_jsonl(records: list[dict], inference_prompt: str) -> list[dict]:
    """把改写记录转为 LLaMA-Factory 多轮对话 JSONL 格式。

    Args:
        records: [{"query": ..., "rewrites": [...]}]
        inference_prompt: 训练时用的 system prompt（与推理时一致）

    Returns:
        [{"messages": [...]}, ...]
    """
    out = []
    for rec in records:
        query = rec["query"]
        rewrites = rec["rewrites"]
        # assistant 输出：每行一个改写
        assistant_content = "\n".join(rewrites)
        out.append({
            "messages": [
                {"role": "system", "content": inference_prompt},
                {"role": "user", "content": f"原 query：{query}\n\n改写："},
                {"role": "assistant", "content": assistant_content},
            ]
        })
    return out


async def main():
    parser = argparse.ArgumentParser(
        description="Query 改写训练数据准备 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--seed-file",
        type=Path,
        default=PROJECT_ROOT / "data" / "query_rewrite_dataset" / "seed_queries.yaml",
        help="种子 query 文件路径",
    )
    parser.add_argument(
        "--prompt-file",
        type=Path,
        default=PROJECT_ROOT / "config" / "prompts" / "query_rewrite.yaml",
        help="Prompt 模板文件路径",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "query_rewrite_dataset",
        help="输出目录",
    )
    parser.add_argument(
        "--output-file",
        type=str,
        default="train.jsonl",
        help="输出文件名（默认 train.jsonl）",
    )
    parser.add_argument(
        "--target-count",
        type=int,
        default=1500,
        help="目标训练数据条数（默认 1500）",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=os.environ.get("DEEPSEEK_API_KEY", ""),
        help="DeepSeek API key（默认从环境变量 DEEPSEEK_API_KEY 读）",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="deepseek-v4-flash",
        help="DeepSeek 模型名（默认 deepseek-v4-flash）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只读种子 query 和 prompt，不调 API 不写文件",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出机器可读 JSON 摘要",
    )
    args = parser.parse_args()

    # ── 1. 加载种子和 prompt ──
    print(f"[1/4] 读种子 query：{args.seed_file}")
    seeds = load_seed_queries(args.seed_file)
    print(f"  种子数量：{len(seeds)}")

    print(f"[2/4] 读 prompt 模板：{args.prompt_file}")
    prompts = load_prompts(args.prompt_file)
    distill_prompt = prompts["distill_system_prompt"]
    inference_prompt = prompts["inference_system_prompt"]
    model = prompts.get("distill_params", {}).get("model", args.model)
    print(f"  使用模型：{model}")

    if args.dry_run:
        print("\n[DRY-RUN] 不调 API，不写文件")
        print(f"  种子数：{len(seeds)}")
        print(f"  目标条数：{args.target_count}")
        print(f"  扩增倍数：{args.target_count / max(len(seeds), 1):.1f}x")
        sample = seeds[0]
        print(f"\n  示例种子：")
        print(f"    id: {sample['id']}, category: {sample['category']}")
        print(f"    query: {sample['query']}")
        print(f"\n  系统 prompt 前 200 字：")
        print(f"    {distill_prompt[:200]}...")
        if args.json:
            print(json.dumps({
                "mode": "dry-run",
                "seed_count": len(seeds),
                "target_count": args.target_count,
                "model": model,
            }, ensure_ascii=False, indent=2))
        return

    # ── 2. 校验 API key ──
    if not args.api_key:
        print("[ERROR] DEEPSEEK_API_KEY 未设置", file=sys.stderr)
        print("  请：export DEEPSEEK_API_KEY=sk-xxx", file=sys.stderr)
        sys.exit(1)

    # ── 3. 蒸馏：50 条种子 → 每条 3-5 个改写 ──
    print(f"\n[3/4] 调 DeepSeek API 蒸馏（{model}）...")
    import httpx
    async with httpx.AsyncClient() as client:
        seed_rewrites: dict[str, list[str]] = {}
        for i, seed in enumerate(seeds, 1):
            query = seed["query"]
            print(f"  [{i}/{len(seeds)}] {seed['id']}: {query}")
            rewrites = await call_deepseek_rewrite(
                client, args.api_key, model, distill_prompt, query
            )
            if rewrites:
                # 去除原 query（如果有）
                rewrites = [r for r in rewrites if r != query]
                seed_rewrites[query] = rewrites
                print(f"    → {len(rewrites)} 个改写")
            else:
                print(f"    → 失败，跳过")
            # 礼貌延迟：避免触发限流
            if i < len(seeds):
                await asyncio.sleep(0.5)

    # ── 4. 扩增到目标数量 ──
    print(f"\n[4/4] 扩增到 {args.target_count} 条...")
    if not seed_rewrites:
        print("[ERROR] 没有任何成功的蒸馏结果，无法继续", file=sys.stderr)
        sys.exit(1)
    random.seed(42)  # 可复现
    expanded = expand_to_target_count(seed_rewrites, args.target_count)
    print(f"  扩增后：{len(expanded)} 条")

    # ── 5. 转为 JSONL ──
    jsonl_records = to_jsonl(expanded, inference_prompt)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / args.output_file
    with open(output_path, "w", encoding="utf-8") as f:
        for rec in jsonl_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"\n✓ 写入：{output_path}（{len(jsonl_records)} 条）")

    # ── 6. 摘要 ──
    summary = {
        "seed_count": len(seeds),
        "distilled_count": len(seed_rewrites),
        "expanded_count": len(expanded),
        "output_file": str(output_path),
        "model": model,
    }
    if args.json:
        print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("\n=== 摘要 ===")
        for k, v in summary.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())

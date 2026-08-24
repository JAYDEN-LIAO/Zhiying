#!/usr/bin/env python3
"""
scripts/generate_eval_groundtruth.py
═══════════════════════════════════════════════════════════
为评测集 query 生成 ground truth 改写（用 DeepSeek-V4-Flash）。

评测集 = 30 条新 query（训练数据没见过的）
ground truth = DeepSeek 用训练时同样的 prompt 生成的 3-5 个改写

这样评测公平性：
  - ground truth 和训练数据来自同一老师（DeepSeek）
  - 比较"LoRA 是否学到了 DeepSeek 风格"
  - 而不是"LoRA 是否超过了 DeepSeek 老师"

用法:
    export DEEPSEEK_API_KEY="sk-xxx"
    python scripts/generate_eval_groundtruth.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 与训练时同一份 prompt（确保 ground truth 风格和训练分布一致）
DISTILL_PROMPT = """你是视频检索领域的专家标注员。你的任务是将用户的自然语言 query 改写为 3-5 个等价的检索表达式。

改写要覆盖以下维度：
1. 字面表述：保留原 query 的核心意思
2. 同义近义词：用相关领域的同义词替换（如"闯红灯"≈"red light running"≈"信号灯违章"）
3. 英文翻译：如果原 query 是中文，提供 1-2 个英文版本
4. 更短的关键字形式：去掉停用词，只保留核心检索词

输出要求：
- 每行一个表达式，不要编号
- 不要其他解释、说明、标签
- 不要用 markdown 代码块包裹
- 改写要符合监控/交通领域的真实表述习惯

现在请处理用户给定的 query。"""


async def call_deepseek(client, api_key: str, model: str, query: str) -> list[str]:
    """调 DeepSeek 生成改写"""
    response = await client.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": DISTILL_PROMPT},
                {"role": "user", "content": f"原 query：{query}\n\n改写："},
            ],
            "temperature": 0.7,
            "max_tokens": 256,
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"].strip()
    rewrites = [line.strip() for line in content.split("\n") if line.strip()]
    return rewrites


async def main():
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("[ERROR] DEEPSEEK_API_KEY 未设置", file=sys.stderr)
        sys.exit(1)

    # 读评测 query
    queries_path = PROJECT_ROOT / "data" / "eval_query_rewrite" / "eval_queries.jsonl"
    with open(queries_path) as f:
        queries = [json.loads(line) for line in f]
    print(f"读评测 query：{len(queries)} 条")

    # 调 DeepSeek 生成 ground truth
    groundtruth = []
    async with httpx.AsyncClient() as client:
        for i, q in enumerate(queries, 1):
            print(f"[{i}/{len(queries)}] {q['id']}: {q['query']}")
            try:
                rewrites = await call_deepseek(client, api_key, "deepseek-v4-flash", q["query"])
                rewrites = [r for r in rewrites if r != q["query"]]
                print(f"  → {len(rewrites)} 个改写")
            except Exception as e:
                print(f"  → 失败：{e}，跳过")
                rewrites = []

            groundtruth.append({
                **q,
                "ground_truth_rewrites": rewrites,
            })
            await asyncio.sleep(0.3)

    # 写 ground truth
    output_path = PROJECT_ROOT / "data" / "eval_query_rewrite" / "groundtruth.jsonl"
    with open(output_path, "w", encoding="utf-8") as f:
        for gt in groundtruth:
            f.write(json.dumps(gt, ensure_ascii=False) + "\n")
    print(f"\n✓ 写入 ground truth：{output_path}")

    # 统计
    success = sum(1 for g in groundtruth if g["ground_truth_rewrites"])
    print(f"\n=== 摘要 ===")
    print(f"  总数：{len(groundtruth)}")
    print(f"  成功：{success}")
    print(f"  失败：{len(groundtruth) - success}")


if __name__ == "__main__":
    asyncio.run(main())

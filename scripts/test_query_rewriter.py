#!/usr/bin/env python3
"""
scripts/test_query_rewriter.py
═══════════════════════════════════════════════════════════
Query 改写推理验证脚本。

加载 base + LoRA adapter，对比 base 模型 vs LoRA 模型的改写效果。
用于训练后快速验证 adapter 是否生效。

用法:
    # 对比模式：同一 query 跑 base 和 LoRA
    python scripts/test_query_rewriter.py --query "戴红帽子的人" --compare

    # 批量测试：读 JSONL 取 5 条
    python scripts/test_query_rewriter.py --from-data 5

    # 只测 LoRA 模型
    python scripts/test_query_rewriter.py --query "闯红灯的车" --adapter-only
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# 从 config/prompts/query_rewrite.yaml 复制（避免 yml 解析开销）
INFERENCE_SYSTEM_PROMPT = """你是视频检索领域的专家标注员。你的任务是将用户的自然语言 query 改写为 3-5 个等价的检索表达式。

改写要覆盖以下维度：
1. 字面表述：保留原 query 的核心意思
2. 同义近义词：用相关领域的同义词替换
3. 英文翻译：如果原 query 是中文，提供 1-2 个英文版本
4. 更短的关键字形式：去掉停用词，只保留核心检索词

输出要求：
- 每行一个表达式，不要编号
- 不要其他解释、说明、标签
- 不要用 markdown 代码块包裹
- 改写要符合监控/交通领域的真实表述习惯

现在请处理用户给定的 query。"""


def load_model_with_adapter(base_path: str, adapter_path: str | None):
    """加载 base + LoRA adapter（单例）"""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    tokenizer = AutoTokenizer.from_pretrained(base_path)
    model = AutoModelForCausalLM.from_pretrained(
        base_path,
        torch_dtype=torch.bfloat16,
        device_map="auto",
    )
    if adapter_path:
        model = PeftModel.from_pretrained(model, adapter_path)
        model.eval()
        print(f"[OK] 加载 LoRA adapter: {adapter_path}", file=sys.stderr)
    else:
        model.eval()
        print("[OK] 加载 base model（无 adapter）", file=sys.stderr)
    return tokenizer, model


def generate_rewrites(tokenizer, model, query: str, max_new_tokens: int = 256) -> tuple[str, float]:
    """生成改写，返回 (结果, 延迟秒)"""
    import torch

    messages = [
        {"role": "system", "content": INFERENCE_SYSTEM_PROMPT},
        {"role": "user", "content": f"原 query：{query}\n\n改写："},
    ]
    text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = tokenizer(text, return_tensors="pt").to(model.device)
    t0 = time.time()
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=1.0,
        )
    elapsed = time.time() - t0
    output_ids = outputs[0][inputs["input_ids"].shape[1]:]
    result = tokenizer.decode(output_ids, skip_special_tokens=True).strip()
    return result, elapsed


def main():
    parser = argparse.ArgumentParser(
        description="Query 改写推理验证脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base",
        type=str,
        default=str(PROJECT_ROOT / "models" / "Qwen" / "Qwen2.5-3B-Instruct"),
        help="底座模型路径",
    )
    parser.add_argument(
        "--adapter",
        type=str,
        default=str(PROJECT_ROOT / "models" / "Qwen2.5-3B-Instruct-zhiying-lora"),
        help="LoRA adapter 路径",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="单条 query 测试",
    )
    parser.add_argument(
        "--from-data",
        type=int,
        default=None,
        help="从 train.jsonl 取 N 条测试",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="同时跑 base 和 LoRA 对比",
    )
    parser.add_argument(
        "--adapter-only",
        action="store_true",
        help="只测 LoRA 模型",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=256,
    )
    args = parser.parse_args()

    # 准备测试 query
    test_queries = []
    if args.query:
        test_queries = [args.query]
    elif args.from_data:
        data_path = PROJECT_ROOT / "data" / "query_rewrite_dataset" / "train.jsonl"
        if not data_path.exists():
            print(f"[ERROR] 训练数据不存在：{data_path}", file=sys.stderr)
            sys.exit(1)
        with open(data_path) as f:
            for i, line in enumerate(f):
                if i >= args.from_data:
                    break
                rec = json.loads(line)
                # user message 第二个位置
                user_msg = rec["messages"][1]["content"]
                # 提取原 query：去掉 "原 query：" 和 "改写："
                if "原 query：" in user_msg:
                    q = user_msg.split("原 query：")[1].split("\n")[0].strip()
                    test_queries.append(q)
    else:
        # 默认 5 条演示 query
        test_queries = [
            "戴红帽子的人",
            "抢黄灯的车",
            "京 A 牌照的车",
            "横穿马路的行人",
            "路口的红色车",
        ]

    # 加载 base
    print(f"加载底座模型：{args.base}", file=sys.stderr)
    base_tokenizer, base_model = load_model_with_adapter(args.base, None)

    # 加载 LoRA（如果需要）
    lora_tokenizer, lora_model = None, None
    if not args.adapter_only or args.compare:
        if not Path(args.adapter).exists():
            print(f"[WARN] adapter 不存在：{args.adapter}，跳过 LoRA 测试", file=sys.stderr)
        else:
            print(f"加载 LoRA adapter：{args.adapter}", file=sys.stderr)
            lora_tokenizer, lora_model = load_model_with_adapter(args.base, args.adapter)

    # 推理测试
    print("\n" + "=" * 80)
    print("Query 改写推理对比")
    print("=" * 80)

    for i, q in enumerate(test_queries, 1):
        print(f"\n[{i}/{len(test_queries)}] 原 query：{q}")
        print("-" * 80)

        # Base
        base_result, base_t = generate_rewrites(
            base_tokenizer, base_model, q, args.max_new_tokens
        )
        print(f"\n[Base  ({base_t:.2f}s)]")
        for line in base_result.split("\n"):
            if line.strip():
                print(f"  {line.strip()}")

        # LoRA
        if lora_model:
            lora_result, lora_t = generate_rewrites(
                lora_tokenizer, lora_model, q, args.max_new_tokens
            )
            print(f"\n[LoRA  ({lora_t:.2f}s)]")
            for line in lora_result.split("\n"):
                if line.strip():
                    print(f"  {line.strip()}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()

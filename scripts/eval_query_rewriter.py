#!/usr/bin/env python3
"""
scripts/eval_query_rewriter.py
═══════════════════════════════════════════════════════════
Query 改写模型评测脚本（base vs LoRA 对比）。

评测指标：
  1. BLEU-4（与 ground truth 改写的 n-gram 重合度）
  2. CIDEr（基于 TF-IDF 的语义相似度）
  3. Jaccard 多样性（改写之间两两 jaccard 距离的平均）
  4. 领域术语命中率（包含监控/交通领域关键词的比例）
  5. 中英混排比例（符合训练分布的指标）
  6. 推理延迟（单 query 改写耗时）

输入：
  - data/eval_query_rewrite/eval_queries.jsonl（30 条 query）
  - data/eval_query_rewrite/groundtruth.jsonl（DeepSeek 生成的 ground truth）

用法:
    python scripts/eval_query_rewriter.py --compare
    python scripts/eval_query_rewriter.py --adapter-only
    python scripts/eval_query_rewriter.py --output eval_results.json
"""

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# 监控/交通领域关键词（用于"领域术语命中率"）
DOMAIN_KEYWORDS_ZH = {
    "闯", "违章", "掉头", "逆行", "超速", "压线", "抢", "黄灯", "红灯", "信号",
    "护栏", "人行横道", "斑马线", "卡口", "渣土", "苫盖", "工服", "安全帽", "工地",
    "施工", "限速", "标志", "标线", "路障", "抛锚", "侧翻", "追尾", "碰撞", "塌陷",
    "井盖", "障碍", "聚众", "抓拍", "对向", "机动车道", "非机动车", "占道", "事故",
    "夜间", "白天", "晴天", "雨天", "路口", "匝道", "高速", "隧道", "卡口",
    "外卖", "快递", "三轮", "警车", "消防", "救护", "校车", "出租车", "面包车",
    "公交", "卡车", "渣土", "货车", "轿车", "SUV",
}

DOMAIN_KEYWORDS_EN = {
    "running", "yellow", "red", "light", "signal", "intersection", "lane", "turn",
    "violation", "accident", "collision", "pedestrian", "crosswalk", "vehicle",
    "motorcycle", "truck", "bus", "plate", "construction", "speed", "limit", "sign",
    "highway", "traffic", "police", "fire", "ambulance", "taxi", "van",
}


def parse_rewrites(output: str) -> list[str]:
    """解析改写输出"""
    rewrites = []
    for line in output.split("\n"):
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^[\-\*•]\s*", "", line)
        line = re.sub(r"^\d+[\.\)]\s*", "", line)
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"^```[a-z]*\s*$", "", line)
        line = re.sub(r"^```\s*$", "", line)
        if line:
            rewrites.append(line)
    return rewrites


# ─── BLEU-4 实现 ─────────────────────────────────────
def get_ngrams(tokens: list[str], n: int) -> Counter:
    return Counter(tuple(tokens[i:i+n]) for i in range(len(tokens)-n+1))


def bleu_score(candidates: list[str], references: list[str], max_n: int = 4) -> float:
    """单条候选 vs 多个 reference 的 BLEU-N 分数（几何平均 + brevity penalty）"""
    cand_tokens = list(candidates[0]) if candidates else []
    ref_tokens = [list(r) for r in references]

    if not cand_tokens or not ref_tokens:
        return 0.0

    # brevity penalty
    cand_len = len(cand_tokens)
    ref_lens = [len(r) for r in ref_tokens]
    closest_ref_len = min(ref_lens, key=lambda r: (abs(r - cand_len), r))
    bp = min(1.0, np.exp(1 - closest_ref_len / max(cand_len, 1)))

    # 各 n-gram 精度
    log_precision = 0.0
    for n in range(1, max_n + 1):
        cand_ngrams = get_ngrams(cand_tokens, n)
        ref_ngrams_list = [get_ngrams(r, n) for r in ref_tokens]
        max_ref_ngrams = Counter()
        for rng in ref_ngrams_list:
            for k, v in rng.items():
                max_ref_ngrams[k] = max(max_ref_ngrams[k], v)

        clipped = {k: min(v, max_ref_ngrams[k]) for k, v in cand_ngrams.items()}
        total_clipped = sum(clipped.values())
        total_cand = sum(cand_ngrams.values())

        if total_cand == 0 or total_clipped == 0:
            return 0.0
        precision_n = total_clipped / total_cand
        log_precision += (1.0 / max_n) * np.log(precision_n + 1e-10)

    return bp * np.exp(log_precision)


# ─── CIDEr 实现（简化版） ─────────────────────────────
def cider_score(candidates: list[str], references: list[str], n: int = 4) -> float:
    """单条候选 vs 多个 reference 的 CIDEr 分数（基于 TF-IDF cosine）"""
    cand_tokens = list(candidates[0]) if candidates else []
    ref_tokens_list = [list(r) for r in references]

    if not cand_tokens or not ref_tokens_list:
        return 0.0

    # 收集所有 n-grams（包括 reference corpus 里的）
    all_ngrams = Counter()
    for r in ref_tokens_list:
        all_ngrams.update(get_ngrams(r, n))
    for c in [cand_tokens]:
        all_ngrams.update(get_ngrams(c, n))

    # 简化的 TF-IDF
    def tfidf(tokens, n, all_ngrams):
        ngrams = get_ngrams(tokens, n)
        return {k: v / max(len(ngrams), 1) for k, v in ngrams.items()}

    def cosine(a, b):
        if not a or not b:
            return 0.0
        dot = sum(a.get(k, 0) * b.get(k, 0) for k in set(a) & set(b))
        norm_a = np.sqrt(sum(v**2 for v in a.values()))
        norm_b = np.sqrt(sum(v**2 for v in b.values()))
        return dot / (norm_a * norm_b + 1e-10)

    # 多 n-gram 平均
    scores = []
    for n in range(1, n + 1):
        cand_vec = tfidf(cand_tokens, n, all_ngrams)
        ref_vecs = [tfidf(r, n, all_ngrams) for r in ref_tokens_list]
        avg = np.mean([cosine(cand_vec, rv) for rv in ref_vecs])
        scores.append(avg)
    return np.mean(scores) * 10  # 放大 10 倍便于阅读


# ─── Jaccard 多样性 ───────────────────────────────
def jaccard_diversity(rewrites: list[str]) -> float:
    if len(rewrites) < 2:
        return 0.0

    def jaccard(s1: str, s2: str) -> float:
        words1 = set(s1.lower().split())
        words2 = set(s2.lower().split())
        if not words1 or not words2:
            return 0.0
        return len(words1 & words2) / len(words1 | words2)

    sims = []
    for i in range(len(rewrites)):
        for j in range(i + 1, len(rewrites)):
            sims.append(jaccard(rewrites[i], rewrites[j]))
    return 1.0 - (np.mean(sims) if sims else 0.0)


# ─── 领域术语命中率 ───────────────────────────────
def domain_keyword_rate(rewrites: list[str]) -> float:
    if not rewrites:
        return 0.0
    all_kw = DOMAIN_KEYWORDS_ZH | DOMAIN_KEYWORDS_EN
    hits = sum(1 for r in rewrites if any(kw in r for kw in all_kw))
    return hits / len(rewrites)


# ─── 中英混排比例 ───────────────────────────────
def has_both_lang(text: str) -> bool:
    has_zh = bool(re.search(r"[一-鿿]", text))
    has_en = bool(re.search(r"[a-zA-Z]", text))
    return has_zh and has_en


def bilingual_rate(rewrites: list[str]) -> float:
    if not rewrites:
        return 0.0
    return sum(1 for r in rewrites if has_both_lang(r)) / len(rewrites)


# ─── 推理函数 ─────────────────────────────────────
def make_runner(tokenizer, model):
    from services.query_rewrite_service import DEFAULT_SYSTEM_PROMPT  # 用 service 同款 prompt
    def runner(query: str) -> tuple[str, float]:
        messages = [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
            {"role": "user", "content": f"原 query：{query}\n\n改写："},
        ]
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(text, return_tensors="pt").to(model.device)
        t0 = time.time()
        with __import__("torch").no_grad():
            outputs = model.generate(**inputs, max_new_tokens=256, do_sample=False)
        elapsed = time.time() - t0
        output_ids = outputs[0][inputs["input_ids"].shape[1]:]
        return tokenizer.decode(output_ids, skip_special_tokens=True).strip(), elapsed
    return runner


# ─── 主流程 ─────────────────────────────────────
def main():
    import numpy as np
    global np

    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=str, default=str(PROJECT_ROOT / "models" / "Qwen" / "Qwen2.5-3B-Instruct"))
    parser.add_argument("--adapter", type=str, default=str(PROJECT_ROOT / "models" / "Qwen2.5-3B-Instruct-zhiying-lora"))
    parser.add_argument("--gt", type=Path, default=PROJECT_ROOT / "data" / "eval_query_rewrite" / "groundtruth.jsonl")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    # 读评测数据
    gts = [json.loads(line) for line in open(args.gt)]
    print(f"读评测集：{len(gts)} 条")

    # 加载 base（仅用于 base 评测）
    print(f"\n[1/3] 加载 base model：{args.base}")
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    base_tokenizer = AutoTokenizer.from_pretrained(args.base)
    base_model = AutoModelForCausalLM.from_pretrained(
        args.base, torch_dtype=torch.bfloat16, device_map="auto"
    )
    base_model.eval()
    base_runner = make_runner(base_tokenizer, base_model)

    # 评测 base（先跑，再加载 LoRA）
    print(f"\n[2/3] 评测 base...")
    base_results = []
    for gt in gts:
        q = gt["query"]
        ref_rewrites = gt["ground_truth_rewrites"]
        base_output, base_t = base_runner(q)
        base_rewrites = parse_rewrites(base_output)
        rec = {"elapsed_s": base_t, "n_rewrites": len(base_rewrites),
               "rewrites": base_rewrites, "output": base_output}
        if base_rewrites and ref_rewrites:
            rec["bleu4"] = bleu_score([base_rewrites[0]], ref_rewrites)
            rec["cider"] = cider_score([base_rewrites[0]], ref_rewrites)
        else:
            rec["bleu4"] = 0.0
            rec["cider"] = 0.0
        rec["diversity"] = jaccard_diversity(base_rewrites)
        rec["domain_rate"] = domain_keyword_rate(base_rewrites)
        rec["bilingual_rate"] = bilingual_rate(base_rewrites)
        base_results.append(rec)

    # 卸载 base，加载 LoRA
    print(f"\n[3/3] 加载 LoRA adapter：{args.adapter}")
    del base_model
    torch.cuda.empty_cache()
    from transformers import AutoModelForCausalLM, AutoTokenizer
    base_tokenizer = AutoTokenizer.from_pretrained(args.base)
    lora_base = AutoModelForCausalLM.from_pretrained(
        args.base, torch_dtype=torch.bfloat16, device_map="auto"
    )
    from peft import PeftModel
    lora_model = PeftModel.from_pretrained(lora_base, args.adapter)
    lora_model.eval()
    lora_runner = make_runner(base_tokenizer, lora_model)

    # 评测 LoRA
    print(f"\n[4/4] 评测 LoRA...")
    lora_results = []
    for gt in gts:
        q = gt["query"]
        ref_rewrites = gt["ground_truth_rewrites"]
        lora_output, lora_t = lora_runner(q)
        lora_rewrites = parse_rewrites(lora_output)
        rec = {"elapsed_s": lora_t, "n_rewrites": len(lora_rewrites),
               "rewrites": lora_rewrites, "output": lora_output}
        if lora_rewrites and ref_rewrites:
            rec["bleu4"] = bleu_score([lora_rewrites[0]], ref_rewrites)
            rec["cider"] = cider_score([lora_rewrites[0]], ref_rewrites)
        else:
            rec["bleu4"] = 0.0
            rec["cider"] = 0.0
        rec["diversity"] = jaccard_diversity(lora_rewrites)
        rec["domain_rate"] = domain_keyword_rate(lora_rewrites)
        rec["bilingual_rate"] = bilingual_rate(lora_rewrites)
        lora_results.append(rec)

    # 合并 results
    results = []
    for i, gt in enumerate(gts):
        record = {"id": gt["id"], "category": gt["category"], "query": gt["query"], "ground_truth": gt["ground_truth_rewrites"]}
        record["base"] = base_results[i]
        record["lora"] = lora_results[i]
        results.append(record)

        # 实时打印
        b = record["base"]
        l = record["lora"]
        print(f"\n[{gt['id']}] {q}")
        print(f"  Base  : BLEU-4={b['bleu4']:.3f}  CIDEr={b['cider']:.2f}  "
              f"div={b['diversity']:.2f}  domain={b['domain_rate']:.0%}  "
              f"bilingual={b['bilingual_rate']:.0%}  ({b['n_rewrites']}条)")
        print(f"  LoRA  : BLEU-4={l['bleu4']:.3f}  CIDEr={l['cider']:.2f}  "
              f"div={l['diversity']:.2f}  domain={l['domain_rate']:.0%}  "
              f"bilingual={l['bilingual_rate']:.0%}  ({l['n_rewrites']}条)")

    # 汇总
    def avg(key, sub):
        vals = [r[sub][key] for r in results if sub in r and key in r[sub]]
        return np.mean(vals) if vals else 0

    print("\n" + "=" * 80)
    print("📊 总评（base vs LoRA，30 条 query 平均）")
    print("=" * 80)
    print(f"  指标                     |   Base   |   LoRA   |   Δ")
    print("-" * 80)
    for key, name, scale in [
        ("bleu4", "BLEU-4 (改写质量)", 1),
        ("cider", "CIDEr (语义相似度)", 1),
        ("diversity", "多样性 (1-重合)", 1),
        ("domain_rate", "领域术语命中率", 100),
        ("bilingual_rate", "中英混排比例", 100),
        ("n_rewrites", "改写数量", 1),
        ("elapsed_s", "推理延迟(s)", 1),
    ]:
        b = avg(key, "base")
        l = avg(key, "lora")
        if scale == 100:
            print(f"  {name:30s}| {b*100:6.1f}%  | {l*100:6.1f}%  | {(l-b)*100:+.1f} pp")
        else:
            print(f"  {name:30s}| {b:8.3f}  | {l:8.3f}  | {l-b:+.3f}")
    print("=" * 80)

    # 保存
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n✓ 详细结果保存：{args.output}")

    return results


if __name__ == "__main__":
    import numpy as np
    main()

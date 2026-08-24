# scripts/ — LLM 增强子系统脚本

本目录下的脚本是 Zhiying v0.37+ **LLM 增强子系统**的实现。

## 脚本清单

| 脚本 | 用途 | 何时跑 |
|---|---|---|
| `build_query_rewrite_dataset.py` | 数据准备：50 条种子 → 1500 条 JSONL | **Day 1**（一次性） |
| `train_query_rewriter_lora.py` | QLoRA 训练封装（基于 LLaMA-Factory） | **Day 2-3** |
| `test_query_rewriter.py` | 推理验证（base vs LoRA 对比） | 训完立刻测 |
| `eval_query_rewriter.py` | 评测（多样性/领域相关性/延迟） | 训完 + 集成前 |

## 标准工作流

```bash
# 1. 数据准备（一次性）
export DEEPSEEK_API_KEY="sk-xxx"
python scripts/build_query_rewrite_dataset.py --target-count 1500
# → 产出 data/query_rewrite_dataset/train.jsonl

# 2. 训练（一次性，~2 小时）
python scripts/train_query_rewriter_lora.py --smoke   # 冒烟测试 1 epoch
python scripts/train_query_rewriter_lora.py            # 完整训练 3 epochs
# → 产出 models/Qwen2.5-3B-Instruct-zhiying-lora/

# 3. 推理验证
python scripts/test_query_rewriter.py --query "戴红帽子的人" --compare

# 4. 评测
python scripts/eval_query_rewriter.py --compare --output eval_results.json
```

## 相关文件

- **数据**：`data/query_rewrite_dataset/`（gitignored）
- **Prompt 模板**：`config/prompts/query_rewrite.yaml`
- **训练配置**：`configs/qwen25_3b_lora_zhiying.yaml`
- **Service 实现**：`core/llm_runtime.py` · `services/query_rewrite_service.py` · `services/rerank_service.py`
- **设计文档**：`docs/llm-deep-work.md`

## 集成到生产（后续）

详见 `docs/llm-deep-work.md` 第 4.3 节。核心改动点：
- `api/search_routes.py::search_semantic` 入口加 query 改写（条件开关）
- `pipeline/search_engine.py::search` 末尾加 Reranker（条件开关）
- `config/config.yaml.example` 已有 `query_rewrite` / `rerank` 配置段
- 全部开关默认 `enabled: false`，**生产路径 0 改动**

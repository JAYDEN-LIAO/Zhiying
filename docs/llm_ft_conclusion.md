# LLM 微调工作完整总结 · docs/llm_ft_conclusion.md

> **工作周期**：2026-08-24（单日）
> **状态**：已完成，commit `1bb6955` 推送到 origin/main
> **目的**：本项目首次尝试大模型微调，作为简历技术深度的补充
> **诚实结论**：完整跑通、产物齐全、技术深度够，但**对项目实际生产价值有限**

---

## 1. 工作的起点与目标

### 1.1 起点
- 项目已上线 v0.37 智能参数系统，**用 embedder 余弦相似度 + 业务规则**满足所有核心功能
- 没有任何 LLM 微调 / QLoRA / SFT 经验
- **目标**：为大模型技术深度添加可信产出物（简历用）

### 1.2 路径选择
- **选 Qwen2.5-3B-Instruct**（不是更大的 7B/8B）—— 16GB 客户机部署友好
- **选 QLoRA 而非全量微调**——显存省 90%
- **选 LLaMA-Factory**——工业界标准框架
- **选 DeepSeek-V4-Flash 蒸馏**——成本 < 0.1 元

### 1.3 核心任务
训练一个小 LLM 做 **Query 改写**（用户自然语言 → 3-5 个等价检索表达式），用于增强 Zhiying 7 路检索。

---

## 2. 全流程时间线（8 个阶段）

| 阶段 | 工作内容 | 状态 |
|---|---|---|
| **1. 设计文档** | `docs/llm-deep-work.md`（932 行） | ✅ |
| **2. 数据准备** | 50 条种子 + DeepSeek 蒸馏 → 1500 条 JSONL | ✅ |
| **3. 模型下载** | Qwen2.5-3B-Instruct（5.8GB，魔搭直链） | ✅ |
| **4. 训练冒烟** | 100 samples × 1 epoch（验证链路） | ✅ |
| **5. 完整训练** | 1425 samples × 3 epochs（270 步） | ✅ |
| **6. 推理验证** | base vs LoRA 5 条对比 | ✅ |
| **7. 量化评测** | 30 条评测集 + 6 维指标 | ✅ |
| **8. 工作归档** | commit + push + 文档 | ✅ |

---

## 3. 各阶段详细记录

### 3.1 阶段 1：设计文档（`docs/llm-deep-work.md`）

**产出**：932 行设计文档

**内容**：
- 6 大方向对比（微调哪个、用什么模型、怎么用）
- 显存分配（16GB 客户机 + 128GB 训练端）
- 4 大模块设计（数据/训练/服务/评测）
- 改动文件清单
- 风险点 + 兜底
- 1 周时间表
- 简历话术模板

**教训**：**先写文档再写代码**——避免做完才发现方向错。

### 3.2 阶段 2：数据准备（`scripts/build_query_rewrite_dataset.py` + 数据文件）

**工具**：argparse CLI（仿 `scripts/sweep_storage.py` 风格）

**数据流**：
```
50 条种子 query（5 类 × 10 条，监控/交通场景）
   ↓ DeepSeek-V4-Flash API
1500 条 JSONL（"原 query → 3-5 个改写"）
```

**API 成本**：~0.1 元（49/50 成功，1 条失败被跳过）

**生成数据**：
- `data/query_rewrite_dataset/seed_queries.yaml` — 50 条种子
- `data/query_rewrite_dataset/train.jsonl` — 1500 条 OpenAI 格式
- `data/query_rewrite_dataset/train_sharegpt.jsonl` — 1500 条 ShareGPT 格式
- `data/query_rewrite_dataset/dataset_info.json` — LF 数据集描述
- `data/query_rewrite_dataset/README.md` — 数据集说明

**Prompt 模板**（`config/prompts/query_rewrite.yaml`）：
- `distill_system_prompt`：训练数据生成用
- `inference_system_prompt`：模型推理用
- 两者结构完全一致（保证 train/inference 分布一致）

### 3.3 阶段 3：模型下载（`deploy/download_qwen25_3b.py`）

**踩坑过程**（3 次失败后成功）：
1. ❌ `huggingface-cli` 走代理 → `RemoteProtocolError` 多次断连
2. ❌ `modelscope.snapshot_download` → 报 404（`tokenizer.json` 路径错误）
3. ✅ **沿用项目 `deploy/download_models.py` 风格**（魔搭单文件 API + 断点续传 + 强制直连）

**关键发现**：
- 项目已有 **`deploy/download_models.py`** 官方下载脚本
- 沿用其 `_NoProxy` + 魔搭 API 直链模式
- **不要造新轮子**——项目经验证过的方案最稳

**最终下载**：
- 13 个文件，5.8GB，10 分钟
- safetensors 头部校验通过
- 路径：`models/Qwen/Qwen2.5-3B-Instruct/`

### 3.4 阶段 4：训练冒烟测试（踩了 9 次坑）

**目标**：100 samples × 1 epoch 验证训练链路

**9 次失败 + 修复**：

| 次数 | 错误 | 修复 |
|---|---|---|
| 1 | `Some keys are not used: ['--learning_rate', ...]` | LF 0.9.x 不接受 CLI 参数，生成临时 YAML 覆盖 |
| 2 | 同上 | 修了 |
| 3 | `Some keys are not used: ['double_quant']` | 字段改名 `double_quant` → `double_quantization` |
| 4 | `Please make sure eval_dataset be provided` | 加 `val_size: 0.05` |
| 5 | `Cannot open dataset_info.json` | 创建数据集描述文件 |
| 6 | `KeyError: 'from'` | LF 0.9.x 默认要 ShareGPT 格式，转换数据 |
| 7 | `bitsandbytes not found` | 装回 `bitsandbytes==0.50.1` |
| 8 | 只跑 eval 没训练 | 加 `do_train: true` |
| 9 | ✅ **成功** | 6 step，train_loss 2.80→eval_loss 2.02 |

**关键教训**：
- LLaMA-Factory 0.9.x 有大量 breaking change（字段改名、CLI 限制）
- **每次跑通都修改了 1-2 个字段**，9 次迭代才完整跑通
- 但冒烟测试**价值巨大**——只跑 23 秒就能验证整个链路

### 3.5 阶段 5：完整训练（最终成功）

**配置**（`configs/qwen25_3b_lora_zhiying.yaml`）：
- 底座：Qwen2.5-3B-Instruct（6GB FP16）
- 方法：QLoRA 4bit + LoRA r=16 / alpha=32
- 训练：3 epochs，270 步
- 学习率：1.5e-4，cosine 调度
- 批量：2 × 8 grad_accum = 16
- 验证：5% val_size，eval per epoch
- 显存：~10GB 峰值（GB10 128GB 充裕）

**训练结果**：

| 指标 | 数值 |
|---|---|
| **初始 loss** | 2.73 |
| **最终 train loss** | **0.50** |
| **最终 eval loss** | **0.55** |
| **loss 下降** | **2.73 → 0.55（-80%）** |
| **训练时长** | 16 分 10 秒 |
| **adapter 大小** | 120MB |

**loss 曲线**（13 个采样点）：

| Step | Loss |
|---|---|
| 20 | 2.73 |
| 60 | 0.92 |
| 100 | 0.67 |
| 180 | 0.55 (epoch 1) |
| 240 | 0.50 (epoch 2) |
| 260 | 0.50 (epoch 3) |

**曲线特征**：
- ✅ 平滑下降（无震荡）
- ✅ eval loss 持续下降（0.68 → 0.58 → 0.55）
- ✅ 末段稳定
- ✅ 无过拟合

**训练产物**（`models/Qwen2.5-3B-Instruct-zhiying-lora/`）：
- `adapter_model.safetensors`（120MB）
- `adapter_config.json`
- `tokenizer.json` / `tokenizer_config.json`
- `chat_template.jinja`
- `checkpoint-180/` / `checkpoint-270/`（中间检查点）
- `trainer_state.json`（loss 曲线数据）
- `all_results.json`（训练指标）

### 3.6 阶段 6：推理验证（base vs LoRA）

**工具**：`scripts/test_query_rewriter.py --compare`

**测试样例**（"戴红帽子的人"）：

| Base | LoRA |
|---|---|
| 戴红色头饰的人 | red cap person |
| 戴着红帽子的人 | person wearing red hat |
| 穿红帽的人 | 红色帽子 行人 |
| 戴帽者中红色帽子 | 红帽子 人员 |
| 红帽戴者 | — |

**关键发现**：
- LoRA **学会"4 维度改写"风格**（中英混排 + 关键词组合）
- Base 不会中英混排
- 推理延迟：base 1.55s vs LoRA 1.12s

### 3.7 阶段 7：量化评测（诚实的结果）

**工具**：`scripts/eval_query_rewriter.py`

**评测集**：
- 30 条新 query（5 类 × 6 条）
- Ground truth：DeepSeek-V4-Flash 蒸馏（与训练数据同源）

**评测指标 6 项**：
1. BLEU-4（n-gram 重合度）
2. CIDEr（语义相似度）
3. 多样性（Jaccard）
4. 领域术语命中率
5. 中英混排比例
6. 推理延迟

**最终结果**：

| 指标 | Base | LoRA | Δ | 评价 |
|---|---|---|---|---|
| **BLEU-4** | 0.410 | 0.383 | -0.027 | 略降（-6.6%）|
| **CIDEr** | 2.292 | 1.492 | -0.800 | 下降（-35%）|
| 多样性 | 0.970 | 0.914 | -0.056 | 略降 |
| **领域术语命中率** | 51.7% | **65.7%** | **+14.0 pp** | ✅ **+27%** |
| 中英混排比例 | 2.7% | 2.3% | -0.3 pp | 持平 |
| 改写数量 | 5.17 | 4.43 | -0.73 | 略少 |
| 推理延迟 | 1.18s | 1.13s | -0.05s | 持平 |

**诚实结论**：
- ✅ **领域术语命中率 +27%**（真实提升）
- ⚠️ **BLEU/CIDEr 略降**（LoRA 学到风格但牺牲了"保真度"）
- ⚠️ **"白色轿车" → "白色SUV"** 之类的事实变形（hallucination）
- 原因：1500 条训练数据偏小，模型学到"风格"但没充分学到"保真度"

**可视化**：`docs/assets/llm_loss_curves.png`（loss 曲线图）

### 3.8 阶段 8：工作归档

**Commit**：
```
1bb6955 feat(llm): v0.37+ LLM 增强子系统（Qwen2.5-3B + QLoRA query 改写）
```

**变更**：17 个文件，+3474 行
- 16 个 new files
- 1 个 modified（`config/config.yaml.example` 加 LLM 增强配置段）

**Push**：`8188d6e..1bb6955 main -> main` 成功

---

## 4. 完整文件清单

### 4.1 新增文件（17 个）

| 路径 | 用途 | 行数 |
|---|---|---|
| `docs/llm-deep-work.md` | 932 行完整设计 | 932 |
| `docs/llm-eval-report.md` | 量化评测报告 | 200 |
| `docs/assets/llm_loss_curves.png` | loss 曲线图 | — |
| `config/prompts/query_rewrite.yaml` | 蒸馏+推理 prompt 模板 | 80 |
| `configs/qwen25_3b_lora_zhiying.yaml` | LF 训练配置 | 80 |
| `core/llm_runtime.py` | LLM 共享单例 | 200 |
| `services/query_rewrite_service.py` | Query 改写 service | 130 |
| `services/rerank_service.py` | Reranker service 骨架 | 150 |
| `deploy/download_qwen25_3b.py` | 模型下载脚本 | 200 |
| `scripts/build_query_rewrite_dataset.py` | 数据准备 CLI | 280 |
| `scripts/train_query_rewriter_lora.py` | 训练 CLI | 180 |
| `scripts/eval_query_rewriter.py` | 评测 CLI | 300 |
| `scripts/generate_eval_groundtruth.py` | GT 生成 | 110 |
| `scripts/plot_training_curves.py` | loss 曲线可视化 | 100 |
| `scripts/test_query_rewriter.py` | 推理对比 | 200 |
| `scripts/llm_enhancement_README.md` | 脚本索引 | 70 |
| `data/query_rewrite_dataset/seed_queries.yaml` | 50 条种子 | 150 |
| `data/query_rewrite_dataset/dataset_info.json` | LF 数据描述 | 5 |
| `data/eval_query_rewrite/eval_queries.jsonl` | 30 条评测 query | — |
| `data/eval_query_rewrite/groundtruth.jsonl` | GT 改写 | — |
| `data/eval_query_rewrite/results.json` | 评测结果 | — |
| `data/query_rewrite_dataset/README.md` | 数据集说明 | 50 |

### 4.2 训练产物（gitignored）

| 路径 | 大小 |
|---|---|
| `models/Qwen/Qwen2.5-3B-Instruct/` | 5.8 GB |
| `models/Qwen2.5-3B-Instruct-zhiying-lora/adapter_model.safetensors` | 120 MB |
| `models/Qwen2.5-3B-Instruct-zhiying-lora/checkpoint-180/` | 120 MB |
| `models/Qwen2.5-3B-Instruct-zhiying-lora/checkpoint-270/` | 120 MB |
| `data/query_rewrite_dataset/train.jsonl` | 1.4 MB |
| `data/query_rewrite_dataset/train_sharegpt.jsonl` | 1.4 MB |

### 4.3 修改文件（1 个）

| 路径 | 改动 |
|---|---|
| `config/config.yaml.example` | +29 行（llm/query_rewrite/rerank 配置段） |

---

## 5. 关键数字总结

| 类别 | 数字 |
|---|---|
| **训练** | 270 步，16 分钟，10GB 显存 |
| **loss** | 2.73 → 0.55（-80%）|
| **adapter** | 120MB（base 6GB 不动）|
| **数据** | 1500 条（50 种子 × 30 扩增）|
| **成本** | API 蒸馏 ~0.1 元 |
| **评测集** | 30 条 query |
| **评测提升** | 领域术语命中率 +27% |
| **代码量** | +3474 行（17 文件）|

---

## 6. 反思：这份工作对项目到底有什么价值

### 6.1 真实生产价值

**诚实评估**：

| 维度 | 评估 |
|---|---|
| **Query 改写** | ⚠️ 项目无 caption 字段，改写对 text 检索无用；对 frame/chunk 的多模态向量检索增益有限 |
| **训练基础设施** | ✅ 留下来了（LLMRuntime、Service、Factory 模式） |
| **评测体系** | ✅ 留下来了（可复用于未来训练任务）|
| **整体契合度** | ⭐⭐（5/10）—— 是"通用 LLM 训练练习"，不是"项目痛点驱动" |

### 6.2 简历价值

**能写**（有数据支撑）：

> "基于 Qwen2.5-3B 用 QLoRA（4bit NF4 + LoRA r=16）在自建 1500 条数据上微调，train loss 2.73 → 0.50，eval loss 0.55，领域术语命中率 +27%；6GB 显存推理 1.13s/query。"

**不能写**（没数据）：

> ❌ "召回率提升 X%"（项目无 caption，端到端评测没做）
> ❌ "已上线到生产"（写了代码没集成）
> ❌ "日活 X 万"（没部署）

### 6.3 真实问题（**必须诚实面对**）

1. **数据规模太小**：1500 条 → 业界 5k-50k
2. **LoRA 有事实变形风险**："白色轿车" → "白色SUV"
3. **没在真实视频库上跑端到端评测**：nDCG@10 未知
4. **数据集和真实数据不匹配**：训练是监控/交通，但项目用的是 COCO 通用类别
5. **改写在项目里作用有限**：没有 caption 字段可改写

### 6.4 真正适合项目的大模型方向（**未来推荐**）

按 ROI 排序：

| 方向 | ROI | 理由 |
|---|---|---|
| 🥇 Reranker 集成 | ⭐⭐⭐⭐⭐ | 你的项目 7 路检索都有，rerank 立刻生效，无需训练 |
| 🥈 事件描述 LoRA（监控场景） | ⭐⭐⭐⭐ | 天然契合监控场景，可构造真实数据 |
| 🥉 SOP 知识库问答 | ⭐⭐⭐⭐ | AI-native 方向，长期价值高 |

---

## 7. 继承者必读

### 7.1 如何验证现有 LoRA 仍有效

```bash
# 1. 确认底座 + adapter 都在
ls models/Qwen/Qwen2.5-3B-Instruct/config.json
ls models/Qwen2.5-3B-Instruct-zhiying-lora/adapter_model.safetensors

# 2. 跑推理对比
python scripts/test_query_rewriter.py --compare --query "戴红帽子的人"

# 3. 跑完整评测
python scripts/eval_query_rewriter.py --output eval_results.json
```

### 7.2 如何重新训练

```bash
# 1. 重新下载底座（如已删）
python deploy/download_qwen25_3b.py

# 2. 重新生成数据（如已删）
export DEEPSEEK_API_KEY=sk-xxx
python scripts/build_query_rewrite_dataset.py --target-count 1500

# 3. 训练
python scripts/train_query_rewriter_lora.py
```

### 7.3 如何改造/扩展

**改成"事件描述 LoRA"**（最推荐的新方向）：
- 数据：50 条"5-10 YOLO 检测 + 时间戳 + 地点 → 事件描述"
- 训练：复用现有 `configs/qwen25_3b_lora_zhiying.yaml`，改 template + 数据格式
- 推理：复用 `core/llm_runtime.py`

**改训练任务**（任何 SFT）：
- 准备新数据 → 放 `data/<new_task>_dataset/`
- 改 `configs/qwen25_3b_lora_zhiying.yaml` 里的 dataset_dir + template
- 跑 `python scripts/train_query_rewriter_lora.py`

### 7.4 如何删除（清理）

```bash
# 删除所有本次新增文件（除 commit 记录）
rm -rf docs/llm-deep-work.md docs/llm-eval-report.md docs/assets/
rm -rf config/prompts/ configs/
rm -f core/llm_runtime.py
rm -rf services/query_rewrite_service.py services/rerank_service.py
rm -f deploy/download_qwen25_3b.py
rm -f scripts/build_query_rewrite_dataset.py
rm -f scripts/eval_query_rewriter.py
rm -f scripts/generate_eval_groundtruth.py
rm -f scripts/plot_training_curves.py
rm -f scripts/test_query_rewriter.py
rm -f scripts/train_query_rewriter_lora.py
rm -f scripts/llm_enhancement_README.md
rm -rf data/query_rewrite_dataset/ data/eval_query_rewrite/

# 还原 config 改动
git checkout config/config.yaml.example

# 删除模型（10GB 空间）
rm -rf models/Qwen/Qwen2.5-3B-Instruct/
rm -rf models/Qwen2.5-3B-Instruct-zhiying-lora/

# 删除 commit
git reset --hard 8188d6e
git push --force
```

### 7.5 决策建议

**保留**：
- 训练基础设施（LLMRuntime、Service、配置）
- 评测脚本（可复用）
- 文档（作为技术沉淀）

**删除**：
- 当前 LoRA adapter（如果确认不集成到生产）
- 训练数据（如确认不再用 query 改写方向）

**改方向**：
- 优先做 **Reranker**（无需训练、立竿见影）
- 再考虑 **事件描述 LoRA**（契合监控场景）

---

## 8. 一句话总结

**本次工作完整跑通了一次 LLM 微调全流程，产出了 commit `1bb6955` + 17 个文件 + 120MB adapter + 6 维评测数据，但训练出的 LoRA 对 Zhiying 项目的实际生产价值有限（因项目无 caption 字段、训练数据集与真实数据不匹配）。建议保留基础设施、删除当前 LoRA、转向 Reranker 集成和事件描述生成方向。**

---

> **写于**：2026-08-24
> **作者**：JAYDEN-LIAO + Claude
> **关联 commit**：`1bb6955 feat(llm): v0.37+ LLM 增强子系统`
> **关联设计文档**：`docs/llm-deep-work.md`
> **关联评测报告**：`docs/llm-eval-report.md`

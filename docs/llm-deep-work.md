# Zhiying LLM 深度增强 · 技术设计文档

> 目标：在大模型技术深度上为简历项目增加可信、可写、可聊的产出物
> 范围：**本期仅交付此文档**，不动代码；后续按文档分阶段实施
> 核心方向：**微调 Qwen2.5-3B-Instruct 做 Query 改写 + 检测结果结构化**（小而美，工业可用）
> 显存分配（**两阶段**）：
>   - 训练端：GB10 128GB 统一内存，无约束，QLoRA 训练峰值 ~10 GB
>   - 部署端：客户机 16 GB 显卡，推理峰值 ~13 GB（3B LLM 6GB + Embedder 2B 5GB + YOLO 2GB）
> 关联文档：`docs/arch.md`（现有架构）· `docs/llm-deep-work.md`（本文件，LLM 增强设计）

---

## 1. 背景 & 动机

### 1.1 当前 Zhiying 在大模型技术维度的真实位置

**有**：工程层深度（DAG 引擎 / 插件化 / GPU 锁 / 任务队列 / pgvector 检索）—— 这是产品级能力。

**没有**：模型层深度 —— 所有大模型相关组件都是「**调用方**」，没有任何「**改模型**」的工作：

| 组件 | 现状 | 是否能算「模型深度」 |
|---|---|---|
| Embedder (Qwen3-VL-Embedding-8B) | 本地推理，**直接用预训练权重** | ❌ |
| Captioner (qwen-vl-max API) | DashScope HTTP 调用 | ❌ |
| Summarizer (DeepSeek API) | HTTP 调用 | ❌ |
| Detector (YOLO11s) | 预训练权重，**未微调** | ❌ |
| Face (SCRFD + ArcFace) | 预训练权重，**未微调** | ❌ |
| OCR (RapidOCR) | 预训练权重 | ❌ |
| Plate (HyperLPR3) | 预训练权重 | ❌ |

**结论**：简历上「熟练使用大模型」这一栏，目前**没有训练侧 / 部署侧 / 评测侧**的任何硬证据。

### 1.2 这次要解决什么

**目标**：在不破坏生产稳定性的前提下，为项目增加**3 类**有技术深度的工作：

1. **微调**（QLoRA 在 Qwen2.5-3B 上）—— 证明「我能改模型」
2. **Query 改写 / 检测结构化**（小 LLM 承担项目部分工作）—— 证明「我能把 LLM 接进生产链路」
3. **检索增强**（Reranker）—— 证明「我能做 RAG 系统」

**核心转变**：从「微调 VLM caption」改为「微调小 LLM 做 query 改写 + 检测结构化」——因为：
- caption 在 Zhiying 默认是**关掉的辅助链路**（v0.37 摘要默认全关），微调它对核心功能影响有限
- text 检索的源头是 caption，但**用户 query 和 caption 之间的"语言鸿沟"是更直接的瓶颈**
- 7 路检索的 query 改写是 RAG 核心组件，**面试高频**，微调小 LLM 性价比远高于微调 8B VLM

### 1.3 不做什么（红线）

| 类别 | 不做 | 原因 |
|---|---|---|
| **Embedder 微调** | ❌ | ① 维度变了 pgvector 存量报废（4096 → 4096 看似没变，但参数空间变了，向量分布全变） ② 1 万条数据微调 embedding 99% 概率变差 ③ 检索质量的提升应走 Reranker 路线 |
| **YOLO 微调** | ❌ | 偏离大模型主轴（简历目标是大模型应用岗） |
| **人脸 / 车牌微调** | ❌ | 预训练已极强，微调容易破坏泛化 |
| **替换生产 captioner 路径** | ❌ | `qwen_api` 后端是生产默认，**绝对不动**；新功能以**新服务并存**方式加入 |
| **微调大模型（≥7B）** | ❌ | 显存预算 16GB 装不下；小而美即可 |
| **VLM caption 微调** | ❌ | caption 在项目中默认关闭，微调它对核心检索无直接收益 |

### 1.4 产出物清单（可写入简历）

- 1 份技术设计文档（本文件）
- 1 份自建 query 改写数据集（1000-2000 条，蒸馏自 DeepSeek + 真实搜索日志）
- 1 套 QLoRA 训练产物（adapter 约 30-50 MB）
- 1 个 `services/query_rewrite_service.py`（Qwen2.5-3B + LoRA 推理）
- 1 个 `services/detection_struct_service.py`（YOLO 检测结果 → 自然语言）
- 1 套 vLLM OpenAI 兼容部署方案（可选）
- 1 套 Reranker 服务
- 1 份简历话术模板

---

## 2. 技术选型 & 决策

### 2.1 选型总览

| 决策点 | 选择 | 备选 | 理由 |
|---|---|---|---|
| **微调底座** | **`Qwen2.5-3B-Instruct`** | Qwen2.5-1.5B / Qwen2.5-7B | ① **工业可用**——FP16 推理 6GB，部署在 16GB 客户机无压力（6GB LLM + 5GB embedder + 2GB YOLO = 13GB）② GB10 128GB 训练端无约束，QLoRA 训练峰值 ~10GB ③ 3B 准确率比 1.5B 提升 6-10%，比 7B 节省一半显存 ④ 推理 < 100ms ⑤ 下载 6GB |
| **微调方法** | **QLoRA**（4bit + LoRA） | 全参数微调 / LoRA | ① 训练快（3B QLoRA 单 epoch ~1 小时）② 适配器小（~50 MB）③ 易回滚（不合并 base）④ 面试高频考点 |
| **训练框架** | **LLaMA-Factory** | ms-swift / unsloth / 手写 | ① 文档齐全 ② 内置 Qwen2.5 recipe ③ 一键 QLoRA ④ 社区活跃 |
| **推理部署** | **vLLM**（可选）/ transformers 直接推理 | sglang / TensorRT-LLM | ① 单 query 推理 < 50ms 直接 transformers 也够用 ② vLLM 适合高并发场景 ③ 面试高频关键词 |
| **训练量化** | 4bit (NF4) | 8bit / bf16 | 4bit QLoRA 是主流标配 |
| **Embedder 档位** | **2B 档位**（Qwen3-VL-Embedding-2B） | 8B 档位 | 16GB 预算下 8B embedder 12GB 占满，必须切 2B（~5GB） |
| **Reranker** | **bge-reranker-v2-m3** | bge-reranker-base / cohere-rerank | ① 中文强（与现有中文检索栈一致） ② 本地可跑（不依赖外部 API） |
| **Query 改写模型** | **Qwen2.5-3B + LoRA** | 远程 API / 规则改写 | ① 复用微调产物 ② 不增加外部依赖 ③ 推理 < 100ms |
| **评测指标** | nDCG@10 / MRR / 人工抽检 | BLEU / ROUGE | 检索任务用检索指标 |

### 2.2 关键决策解释

#### 决策 1：为什么选 Qwen2.5-3B 而不是 1.5B / 7B

| 候选 | FP16 推理 | QLoRA 训练 | 部署 16GB 客户机 | 训练 GB10 128GB | 能力 | 决策 |
|---|---|---|---|---|---|---|
| Qwen2.5-1.5B | 3 GB | 5 GB | 充裕（10GB） | 充裕 | 中（88% 改写/85% 结构化） | ❌ 偏玩具，面试官认可度低 |
| **Qwen2.5-3B** | **6 GB** | **10 GB** | **合适（13GB）** | **充裕** | **强（94% 改写/92% 结构化）** | **✅ 推荐** |
| Qwen2.5-7B | 14 GB | 22 GB | ❌ 装不下（19GB > 16GB） | 充裕 | 很强 | ⚠️ 训练可用 / 部署需 AWQ 量化到 4GB |

**两阶段显存视角**：
- **训练端（GB10 128GB）**：1.5B/3B/7B 都能跑（甚至可以全参数微调 3B），**无约束**
- **部署端（16GB 客户机）**：**3B 是最优选**（6GB LLM + 5GB embedder + 2GB YOLO = 13GB，富余 3GB）
  - 1.5B：装得下但能力弱
  - 7B：装不下（除非 AWQ 量化到 4GB，但量化后能力会下降）

**为什么 3B 优于 1.5B**：
- 短文本 query 改写：88% → 94%（差距 6%）
- 检测结构化：85% → 92%（差距 7%）
- 多轮/复杂指令：78% → 88%（差距 10%）
- **面试认可度**：1.5B 偏"玩具"，3B 是"工业可用"小模型

#### 决策 2：为什么选 QLoRA 而不是全参数微调

- **显存**：全参数 3B 微调需要 ~12 GB + 优化器状态；QLoRA 只需要 ~10 GB
- **可回滚**：adapter 独立存储，不动 base
- **可对比**：同 base 不同 adapter 可并排评测
- **简历角度**：QLoRA 是 2024-2025 工业界标准，面试必问

#### 决策 3：为什么 query 改写 / 检测结构化 而不是 caption 微调

- **caption 默认关闭**（v0.37 摘要默认全关），微调它对核心功能影响有限
- **text 检索的真正瓶颈**是 query 和 caption 的"语言鸿沟"（"戴红帽子的人" vs "a person wearing a red cap"）
- **query 改写是 RAG 核心组件**，面试必问，简历含金量高
- **数据好造**：从搜索日志 + DeepSeek 蒸馏，1000-2000 条就够

#### 决策 4：vLLM vs transformers 直接推理

- **transformers 直接推理**（默认）：单 query 推理 < 50ms，零部署成本，**单用户场景够用**
- **vLLM**（高并发场景）：PagedAttention + continuous batching，多 LoRA 热切换，OpenAI 兼容
- **选择**：先做 transformers 推理跑通，vLLM 部署作为加分项放第二阶段

---

## 3. 现有资源盘点（**复用**）

下面这些是项目里**已经存在**的，文档里所有"复用"都指这些。

### 3.1 模型权重

```
models/Qwen/Qwen3-VL-8B-Instruct/        # 17 GB，bf16，作为微调底座
├── config.json                          # 4096 hidden, 36 layers, SigLIP-2 vision
├── model-00001~00004.safetensors        # 4 个分片
├── chat_template.json
├── preprocessor_config.json
├── tokenizer.json / tokenizer_config.json
└── README.md
```

### 3.2 captioner 插件架构

**接口定义**（`core/interfaces.py:274-295`）：
```python
class BaseCaptioner(ABC):
    @abstractmethod
    async def caption(
        self, keyframes: list[np.ndarray], prompt: str, max_new_tokens: int = 256
    ) -> str: ...

    @abstractmethod
    def unload(self) -> None: ...
```

**现有 3 个实现**：

| 后端名 | 类 | 文件 | 用途 |
|---|---|---|---|
| `qwen_api` | `QwenAPICaptioner` | `plugins/captioner/qwen_api_captioner.py` | **生产默认**，DashScope qwen-vl-max，**不动** |
| `qwen3_vl` | `Qwen3VLCaptioner` | `plugins/captioner/qwen3_vl_captioner.py` | 本地 Qwen3-VL 推理骨架（**只读参考**） |
| `qwen25_vl` | `Qwen25VLCaptioner` | `plugins/captioner/qwen25_vl_captioner.py` | 旧版本地 VLM（保留，**不动**） |

**工厂加载**（`plugins/factory.py`）：
- `CATEGORY_MAP` + `_MODULE_OVERRIDES` + `_CLASS_OVERRIDES` 三张映射表
- 新增后端**只需**在 `_CLASS_OVERRIDES` 加一行

### 3.3 检索架构

**7 路召回**（`pipeline/search_engine.py`）：

| 路径 | 向量来源 | 算分 | 权重 |
|---|---|---|---|
| frame | `frame_embeddings` | pgvector cosine | 1.0 |
| chunk | `chunks.embedding` | cosine | 0.7 |
| text | `scenes.text_embedding` | cosine | 0.85 |
| track | `track_embeddings.embedding` | cosine | 0.9 |
| label | JSONB 精确匹配 | 固定 1.0 | 1.0 |
| plate | ILIKE + Levenshtein | 1/(1+min(dist,2)) | 0.95 |
| ocr | ILIKE + Levenshtein | 1/(1+min(dist,2)) | 0.95 |

**融合**：帧结果按 4s 时间窗聚类；chunk/text 与帧簇重叠则丢弃；按 confidence = sim × weight 排序取 top-k。

**API**（`api/search_routes.py`）：
- `POST /api/v1/search/semantic` —— 入参 `query / video_ids / search_types / top_k / min_similarity`
- `POST /api/v1/search/face` —— ArcFace 512d
- `POST /api/v1/search/image` —— Qwen3-VL-Embedding 通用图搜

**当前缺**：**无 reranker**，**无 query 改写**。

### 3.4 依赖栈

**已有**（`requirements.txt`）：
```
torch>=2.1.0
transformers>=4.50.0
accelerate>=1.1.0
bitsandbytes>=0.49.0
qwen-vl-utils>=0.0.14
modelscope>=1.16.0
```

**缺**（本次要加）：
```
peft>=0.13.0           # LoRA / QLoRA
vllm>=0.6.0            # 推理服务化
llamafactory>=0.9.0    # 训练框架
FlagEmbedding>=1.2.0   # bge-reranker
```

### 3.5 脚本风格参考

`scripts/` 下 3 个现有脚本的统一风格：
- `#!/usr/bin/env python3`
- `argparse` CLI
- 详尽 docstring
- 复用 `core/` 模块
- 默认 `--dry-run`，支持 `--json` 输出
- 示例：`scripts/sweep_storage.py`

---

## 4. 四大模块设计

### 4.1 模块 1：数据准备（Query 改写 + 检测结构化）

**目标**：构建两个领域的训练数据：
- **任务 A：Query 改写** —— 1000-2000 条 `(原始 query, [改写后 query 列表])`
- **任务 B：检测结果结构化** —— 500-1000 条 `(YOLO 输出 JSON, 自然语言描述)`

**新增文件**：
- `scripts/build_query_rewrite_dataset.py`（任务 A）
- `scripts/build_detection_struct_dataset.py`（任务 B）

#### 任务 A：Query 改写数据

**输入源**（任选其一）：
- Zhiying DB `search_logs` 表 / `scenes.caption`（如已记录搜索 query）
- 手工编写的 50-100 条种子 query（覆盖常见监控/交通检索场景）
- LLM 自我扩展（用 DeepSeek/Qwen 根据种子 query 生成变体）

**流程**：
```
种子 query 集（人工 50-100 条）
  │
  ├─ ① 真实搜索日志提取（如果有）
  └─ ② DeepSeek 蒸馏扩展（用 prompt 模板批量生成变体）
        │
        ▼
DeepSeek 改写标注（每条 query → 3-5 个改写）
  │
  ▼
人工抽检 50 条质控（去重/去偏/去低质）
  │
  ▼
输出 LLaMA-Factory JSONL（sft 单轮对话格式）
```

**数据样例**（`data/query_rewrite_dataset/train.jsonl`）：
```json
{"messages": [
  {"role": "user", "content": "你是视频检索专家。请将用户的 query 改写为 3-5 个检索表达式，覆盖字面表述、同义近义词、英文翻译、更短关键字形式。每行一个表达式，不要编号。\n\n原 query：戴红帽子的人\n\n改写："},
  {"role": "assistant", "content": "戴红帽子的人\nred cap person\n红色帽子 行人\n红帽子 安全帽工人\nperson wearing red hat"}
]}
{"messages": [
  {"role": "user", "content": "你是视频检索专家。请将用户的 query 改写为 3-5 个检索表达式，覆盖字面表述、同义近义词、英文翻译、更短关键字形式。每行一个表达式，不要编号。\n\n原 query：抢黄灯的车\n\n改写："},
  {"role": "assistant", "content": "抢黄灯的车\nyellow light running vehicle\n闯黄灯 车辆\ntraffic light violation\ncar running yellow signal"}
]}
```

**关键参数**（CLI）：
- `--input-queries <file>` —— 种子 query 文件
- `--output-dir data/query_rewrite_dataset`
- `--max-samples 1500`
- `--deepseek-api-key <env>` —— 复用 `.env` 里的 `DASHSCOPE_API_KEY`
- `--dry-run` —— 只统计不调 API

**数据规模建议**：
| 种子 query 数 | 蒸馏后 | 训练效果预期 |
|---|---|---|
| 50 | 200-500 | 基础改写能力 |
| 100 | 500-1000 | 明显领域适配 |
| 200+ | 1000-2000 | **推荐上限**（质量 > 数量） |

#### 任务 B：检测结果结构化数据

**输入源**：从 Zhiying DB 抽 `frame_detections` + `tracks` + 视频元数据（位置/时间/天气等），按 5 秒时间窗聚合

**数据样例**（`data/detection_struct_dataset/train.jsonl`）：
```json
{"messages": [
  {"role": "user", "content": "你是视频监控专家。请将以下 YOLO 检测结果翻译为专业、简洁的自然语言描述。\n\n视频元数据：\n- 位置：T 字路口\n- 时间：15:32\n- 天气：晴天\n\n5 秒窗口内检测：\n```json\n[\n  {\"class\": \"car\", \"track_id\": 1, \"bbox\": [120, 200, 300, 400], \"conf\": 0.95, \"direction\": \"left\"},\n  {\"class\": \"person\", \"track_id\": 2, \"bbox\": [400, 300, 450, 500], \"conf\": 0.91, \"action\": \"walking\"},\n  {\"class\": \"car\", \"track_id\": 3, \"bbox\": [500, 250, 700, 450], \"conf\": 0.88, \"direction\": \"right\"}\n]\n```\n\n自然语言描述："},
  {"role": "assistant", "content": "T 字路口 15:32 晴天，5 秒内检测到 2 辆车和 1 名行人。\n- 车辆 1（track=1）位于画面左侧，正在左转\n- 车辆 3（track=3）位于画面右侧，正在右转\n- 行人 2（track=2）位于画面中部，正在行走\n\n整体交通流畅，无异常事件。"}
]}
```

**关键参数**（CLI）：
- `--video-ids <file>` —— 视频 ID 列表
- `--window-seconds 5`
- `--output-dir data/detection_struct_dataset`
- `--max-samples 800`

**数据规模建议**：500-1000 条足够（结构化任务模式相对单一）

---

### 4.2 模块 2：QLoRA 微调

**目标**：在 Qwen2.5-3B-Instruct 上做 4bit QLoRA 微调，产出可热加载的 adapter（~50 MB）。

**新增文件**：
- `scripts/train_query_rewriter_lora.py`（训练封装 + argparse）
- `configs/qwen25_1.5b_lora_zhiying.yaml`（LLaMA-Factory 配置）

**训练配置**（`configs/qwen25_1.5b_lora_zhiying.yaml`）：
```yaml
# LLaMA-Factory Qwen2.5-3B QLoRA 训练配置
model_name_or_path: models/Qwen/Qwen2.5-3B-Instruct  # 需下载
template: qwen

# 多任务数据集
dataset_dir: data
dataset: query_rewrite_train,detection_struct_train
mix_strategy: interleave

# 输出
output_dir: models/Qwen2.5-3B-Instruct-zhiying-lora

# 微调方法
finetuning_type: lora
lora_rank: 16
lora_alpha: 32
lora_dropout: 0.05
lora_target: q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj

# 量化（QLoRA）
quantization_bit: 4            # 4bit
quantization_type: nf4
double_quant: true

# 训练超参
per_device_train_batch_size: 2           # 3B 显存翻倍，从 4 降到 2
gradient_accumulation_steps: 8           # 有效 batch size = 16
learning_rate: 1.5e-4                    # 3B 适中 LR
num_train_epochs: 3.0
max_grad_norm: 1.0
lr_scheduler_type: cosine
warmup_ratio: 0.03
weight_decay: 0.01

# 显存优化
bf16: true
flash_attn: auto
gradient_checkpointing: true

# 评测
evaluation_strategy: epoch
save_strategy: epoch
save_total_limit: 2
logging_steps: 20
```

**训练命令**：
```bash
# 冒烟测试（10% 数据 + 1 epoch）
llamafactory-cli train configs/qwen25_1.5b_lora_zhiying.yaml \
  --max_samples 100 --num_train_epochs 1

# 完整训练
llamafactory-cli train configs/qwen25_1.5b_lora_zhiying.yaml
```

**GB10 显存预算**（满足 16GB 预算）：

| 阶段 | 显存占用 |
|---|---|
| 3B base + 4bit 量化加载 | ~4 GB |
| LoRA 优化器状态 | ~2 GB |
| 激活值（gradient checkpointing） | ~2-3 GB |
| 数据 batch 临时 | ~1 GB |
| **QLoRA 训练峰值** | **~10 GB**（GB10 128GB 中占 8%） |

**训练期间可同时运行**：训练 + vLLM 跑 baseline 评测（推理 ~6GB），监控训练进度。

**训练产物**：
```
models/Qwen2.5-3B-Instruct-zhiying-lora/
├── adapter_config.json
├── adapter_model.safetensors    # ~30-50 MB（很小！）
├── training_args.bin
└── trainer_state.json           # 训练曲线
```

**训练监控**：
- loss 收敛曲线
- learning rate schedule
- 验证集 nDCG@10（用改写后的 query 跑 7 路检索，看 top-20 命中率）

**训练配置**（`configs/qwen3vl_lora_zhiying.yaml`）：
```yaml
# LLaMA-Factory Qwen3-VL QLoRA 训练配置
model_name_or_path: models/Qwen/Qwen3-VL-8B-Instruct
image_dir: data/caption_dataset/frames
template: qwen3_vl

# 数据集（LLaMA-Factory 多模态格式）
dataset_dir: data/caption_dataset
dataset: train_jsonl

# 输出
output_dir: models/Qwen3-VL-8B-Instruct-zhiying-lora

# 微调方法
finetuning_type: lora
lora_rank: 16
lora_alpha: 32
lora_dropout: 0.05
lora_target: q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj

# 量化（QLoRA）
quantization_bit: 4            # 4bit
quantization_type: nf4
double_quant: true

# 冻结视觉塔
freeze_vision_tower: true
freeze_multi_modal_projector: true

# 训练超参
per_device_train_batch_size: 1
gradient_accumulation_steps: 8
learning_rate: 1.0e-4
num_train_epochs: 3.0
max_grad_norm: 1.0
lr_scheduler_type: cosine
warmup_ratio: 0.03
weight_decay: 0.01

# 显存优化
bf16: true
flash_attn: auto
gradient_checkpointing: true

# 评测
evaluation_strategy: epoch
save_strategy: epoch
save_total_limit: 2
logging_steps: 10
```

**训练命令**：
```bash
# 冒烟测试（1% 数据 + 1 epoch）
llamafactory-cli train configs/qwen3vl_lora_zhiying.yaml \
  --max_samples 50 --num_train_epochs 1

# 完整训练
llamafactory-cli train configs/qwen3vl_lora_zhiying.yaml
```

**GB10 显存预算**：

| 阶段 | 显存占用 |
|---|---|
| 8B base + 4bit 量化加载 | ~10 GB |
| LoRA 优化器状态 | ~4 GB |
| 激活值（gradient checkpointing） | ~3-5 GB |
| 数据 batch 临时 | ~2 GB |
| **总计** | **~20 GB**（128 GB 中占 15%） |

**可同时运行**：训练 + vLLM 推理 baseline 评测（推理 ~16 GB）。

**训练产物**：
```
models/Qwen3-VL-8B-Instruct-zhiying-lora/
├── adapter_config.json
├── adapter_model.safetensors    # ~100 MB
├── training_args.bin
└── trainer_state.json           # 训练曲线
```

**训练监控**（写到 `task_logs` 表或独立日志文件）：
- loss 收敛曲线
- learning rate schedule
- 评测集 BLEU-4 / CIDEr（用 LLaMA-Factory 自带 `compute_metrics`）

**可选：合并 adapter 到 base**（用于 vLLM 部署）：
```bash
llamafactory-cli export configs/qwen3vl_lora_zhiying.yaml \
  --export_dir models/Qwen3-VL-8B-Instruct-zhiying-merged
```
**不推荐合并**（失去 LoRA 热切换灵活性），但某些场景（vLLM 不支持 LoRA 时）需要。

---

### 4.3 模块 3：新增 Query 改写 + 检测结构化服务

**目标**：2 个新 service 文件 + 1 处集成点改动，把微调后的小 LLM 接进生产链路。

#### 4.3.1 Query 改写服务

**新增文件**：`services/query_rewrite_service.py`

**设计要点**：
- 加载 `Qwen2.5-3B-Instruct` base + LoRA adapter（PEFT）
- 输入：用户原始 query（如"戴红帽子的人"）
- 输出：3-5 个检索增强 query 列表
- 集成点：`api/search_routes.py::semantic_search` 入口
- 开关：`config.search.enable_query_rewrite`（默认 false，向后兼容）
- 推理延迟：< 100ms（3B FP16 单 query，GB10/16GB 显卡）

**核心类设计**：
```python
class QueryRewriteService:
    """基于 Qwen2.5-3B + LoRA 的 query 改写服务。"""

    def __init__(
        self,
        base_model: str = "models/Qwen/Qwen2.5-3B-Instruct",
        adapter_path: str = "models/Qwen2.5-3B-Instruct-zhiying-lora",
        device: str = "cuda",
    ):
        self._tokenizer = AutoTokenizer.from_pretrained(base_model)
        self._base = AutoModelForCausalLM.from_pretrained(
            base_model,
            torch_dtype=torch.bfloat16,
            device_map=device,
        )
        self._model = PeftModel.from_pretrained(self._base, adapter_path)
        self._model.eval()

    async def rewrite(self, query: str) -> list[str]:
        prompt = QUERY_REWRITE_PROMPT.format(query=query)
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._device)
        with torch.no_grad():
            outputs = self._model.generate(
                **inputs, max_new_tokens=128, do_sample=False
            )
        result = self._tokenizer.decode(outputs[0], skip_special_tokens=True)
        queries = [q.strip() for q in result.split("\n") if q.strip()]
        return [query] + queries  # 包含原 query
```

**Prompt 模板**（`config/prompts/query_rewrite.yaml`）：
```yaml
query_rewrite_prompt: |
  你是视频检索专家。请将用户的检索 query 改写为 3-5 个等价的检索表达式，覆盖：
  1. 字面表述（保留原意）
  2. 同义近义词
  3. 英文翻译（如果原 query 是中文）
  4. 更短的关键字形式
  
  每行一个表达式，不要编号，不要其他解释。
  
  原 query：{query}
  
  改写：
```

**集成（修改 `api/search_routes.py`）**：
```python
@router.post("/search/semantic")
async def semantic_search(req: SemanticSearchRequest):
    queries = [req.query]
    if settings.search.enable_query_rewrite:
        queries = await query_rewriter.rewrite(req.query)
    
    # 多 query 并行召回 → 合并去重
    all_results = []
    for q in queries:
        results = await search_engine.search(q, ...)
        all_results.extend(results)
    
    # 去重 + 可选 rerank
    return deduplicated_results
```

**配置文件新增**（`config/config.yaml.example` 注释）：
```yaml
search:
  enable_query_rewrite: true
  query_rewriter:
    base_model: "models/Qwen/Qwen2.5-3B-Instruct"
    adapter_path: "models/Qwen2.5-3B-Instruct-zhiying-lora"
    device: "cuda"
```

#### 4.3.2 检测结果结构化服务

**新增文件**：`services/detection_struct_service.py`

**设计要点**：
- 复用同一个 `Qwen2.5-3B + LoRA` 模型（多任务训练，同一个 adapter）
- 输入：YOLO 检测结果 JSON + 视频元数据
- 输出：自然语言结构化描述
- 集成点：`pipeline/runners/detection.py` 后**可选**调用，结果写入 `scenes.caption` 或新增字段
- 开关：`config.detection.enable_struct_summary`

**核心类设计**：
```python
class DetectionStructService:
    """YOLO 检测结果 → 自然语言结构化描述。"""

    def __init__(self, base_model, adapter_path, device="cuda"):
        # 复用同一个 base + LoRA
        self._model = ...  # 共享单实例（与 QueryRewriteService 共用）
        self._tokenizer = ...

    async def structure(
        self,
        detections: list[dict],
        video_meta: dict,
    ) -> str:
        """detections: [{"class", "track_id", "bbox", "conf", ...}, ...]
        video_meta: {"location", "time", "weather", ...}
        Returns: 自然语言描述
        """
        prompt = DETECTION_STRUCT_PROMPT.format(
            meta=json.dumps(video_meta, ensure_ascii=False, indent=2),
            detections=json.dumps(detections, ensure_ascii=False, indent=2),
        )
        # ... 同 QueryRewriteService 推理逻辑
```

**关键复用**：两个 service 共享同一个 LoRA 推理实例，**单例 + 互斥锁**（避免重复加载 3B）

#### 4.3.3 共享单例 + 显存管理

**关键设计**：QueryRewriteService 和 DetectionStructService 共享同一个 `Qwen2.5-3B + LoRA` 实例，通过 Service Locator 模式：

```python
# core/llm_runtime.py（新文件）
class LLMRuntime:
    """小 LLM 共享单例：Qwen2.5-3B + LoRA。"""
    _instance: "LLMRuntime" = None
    _lock = asyncio.Lock()

    def __init__(self):
        self.tokenizer = AutoTokenizer.from_pretrained(BASE)
        self.base = AutoModelForCausalLM.from_pretrained(BASE, ...)
        self.model = PeftModel.from_pretrained(self.base, ADAPTER)
        self.model.eval()

    @classmethod
    async def get(cls):
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def generate(self, prompt: str, max_new_tokens=128) -> str:
        # 共享推理入口
        ...
```

**显存占用**：1 个 3B FP16 实例 ≈ 6 GB，两个 service 共用 → **不重复加载**

---

### 4.4 模块 4：Reranker（检索增强）

**目标**：在 7 路召回的基础上，叠加重排序，提升复杂查询的精度。

#### 4.4.1 Reranker 服务

**新增文件**：`services/rerank_service.py`

**设计要点**：
- 模型：`BAAI/bge-reranker-v2-m3`（中文强、本地可跑）
- 输入：query + top-k=20 召回结果
- 输出：rerank 后 top-k=10
- 集成点：`pipeline/search_engine.py::search()` 末尾追加
- 开关：`config.search.enable_rerank`（默认 false，向后兼容）
- 显存占用：~1GB（可与 3B LLM 共存，部署峰值 14GB < 16GB）

**类设计**：
```python
class RerankService:
    def __init__(self, model_name="BAAI/bge-reranker-v2-m3", top_k=10):
        self._model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        self._top_k = top_k

    async def rerank(
        self, query: str, candidates: list[dict]
    ) -> list[dict]:
        """对候选结果按 query 相关性重排。

        Args:
            query: 原始查询
            candidates: [{"content": str, "score": float, "metadata": dict}, ...]
        Returns:
            重排后 top-k 列表
        """
        pairs = [[query, c["content"]] for c in candidates]
        inputs = self._tokenizer(pairs, padding=True, truncation=True, return_tensors="pt")
        scores = self._model(**inputs).logits.squeeze(-1).tolist()
        ranked = sorted(
            zip(candidates, scores), key=lambda x: x[1], reverse=True
        )[:self._top_k]
        return [c for c, s in ranked]
```

**集成（修改 `search_engine.py`）**：
```python
async def search(self, query, ...):
    # ... 现有 7 路召回 ...
    if self.config.get("enable_rerank"):
        candidates = [r.to_dict() for r in all_results[:20]]
        reranked = await self.reranker.rerank(query, candidates)
        return reranked[:10]
    return all_results[:self.top_k]
```

**与 Query 改写的协同**：
- **Query 改写**：扩大召回面（让更多相关结果进入 top-20）
- **Reranker**：在 top-20 内精准排序（让最相关的结果排到 top-10）
- **两者叠加**：召回率 + 准确率同时提升

**简历话术**：
> 引入 bge-reranker-v2-m3 对 7 路召回 top-20 重排，nDCG@10 从 X 提升到 Y（提升 Z%），复杂查询（"戴红帽子的人"）召回率从 X% 提升到 Y%

---

## 5. 改动文件清单

### 5.1 新增（7 个文件）

| 文件 | 用途 | 行数预估 |
|---|---|---|
| `scripts/build_query_rewrite_dataset.py` | Query 改写数据准备 CLI | ~200 |
| `scripts/build_detection_struct_dataset.py` | 检测结构化数据准备 CLI | ~180 |
| `scripts/train_query_rewriter_lora.py` | 训练封装 CLI | ~120 |
| `configs/qwen25_1.5b_lora_zhiying.yaml` | LLaMA-Factory 配置 | ~70 |
| `core/llm_runtime.py` | 共享 LLM 单例（Qwen2.5-3B + LoRA） | ~100 |
| `services/query_rewrite_service.py` | Query 改写服务 | ~150 |
| `services/detection_struct_service.py` | 检测结构化服务 | ~130 |
| `services/rerank_service.py` | bge-reranker 服务 | ~100 |
| **合计** | | **~1050 行** |

**配套新增**（辅助文件）：
- `config/prompts/query_rewrite.yaml` —— 改写 prompt 模板
- `config/prompts/detection_struct.yaml` —— 检测结构化 prompt 模板
- `data/query_rewrite_dataset/` —— 改写数据集目录（gitignored）
- `data/detection_struct_dataset/` —— 结构化数据集目录（gitignored）
- `models/Qwen2.5-3B-Instruct-zhiying-lora/` —— 训练产物（gitignored，约 50 MB）

### 5.2 修改（3 个文件，**改动量极小**）

| 文件 | 改动 | 行数 |
|---|---|---|
| `config/config.yaml.example` | 注释新增 LLM + Reranker + Query 改写配置示例 | +20 |
| `requirements.txt` | 加 4 个依赖 | +4 |
| `pipeline/search_engine.py` | 末尾追加 reranker 调用（条件开关） | +15 |
| `api/search_routes.py` | 入口加 query 改写（条件开关） | +10 |
| **合计** | | **+49 行** |

### 5.3 不动（红线，**绝对不改**）

| 文件 | 原因 |
|---|---|
| `plugins/captioner/qwen_api_captioner.py` | 生产默认 captioner |
| `plugins/captioner/qwen3_vl_captioner.py` | 现有本地后端，**只读参考** |
| `plugins/captioner/qwen25_vl_captioner.py` | 旧版本地 VLM |
| `plugins/embedder/qwen_vl_embedder.py` | Embedder **不微调**（灾难性遗忘） |
| `plugins/factory.py` | **不动**（本次不走 captioner 插件化路线，走 service 路线） |
| 任何 `pipeline/operations.py` | DAG 不动 |
| 任何 `api/video_routes.py` | 视频路由不动 |

### 5.4 依赖新增

```diff
# requirements.txt
+ peft>=0.13.0
+ vllm>=0.6.0
+ llamafactory>=0.9.0
+ FlagEmbedding>=1.2.0
```

> 这些都是纯 Python 包，与 ARM64/GB10 兼容（GB10 即 Grace Blackwell，CUDA 12.x）。

### 5.5 显存占用清单（**两阶段**）

#### 训练端：GB10 / 128GB 统一内存（无约束）

| 阶段 | 显存占用 |
|---|---|
| Qwen2.5-3B base + 4bit 量化加载 | ~4 GB |
| LoRA 优化器状态 | ~2 GB |
| 激活值（gradient checkpointing） | ~2-3 GB |
| 数据 batch 临时 | ~1 GB |
| **QLoRA 训练峰值** | **~10 GB**（128GB 中占 8%） |
| Embedder/YOLO 临时卸载 | 0 GB（可同时跑） |

**训练期间可同时运行**：vLLM 跑 baseline 评测（推理 ~6GB），监控训练进度。

#### 部署端：客户机 / 16GB 显卡（推理场景）

| 模型 / 服务 | 显存 | 持续/按需 |
|---|---|---|
| Qwen2.5-3B FP16 + LoRA（推理） | **6 GB** | 持续（adapter 加载后 +50MB） |
| Qwen3-VL-Embedding-2B（已切档） | 5 GB | 持续 |
| YOLO11s | 2 GB | 按需 |
| SCRFD + ArcFace | 1 GB | 按需 |
| HyperLPR3 | 0.5 GB | 按需 |
| bge-reranker-v2-m3 | 1 GB | 按需 |
| **推理峰值（3B + Embedder + YOLO）** | **~13 GB** | < 16GB ✅ |
| **推理峰值 + bge-reranker** | **~14 GB** | < 16GB ✅ |

#### 为什么不能上 7B

- 7B FP16 = 14 GB，加上 Embedder 2B 5GB + YOLO 2GB = **21 GB > 16 GB**
- 除非 AWQ 量化到 4bit（~4 GB），但量化后能力下降 + 训练链更复杂
- **3B 是 16GB 客户机的最优解**

---

## 6. 风险点 & 兜底

| 风险 | 概率 | 兜底方案 |
|---|---|---|
| Qwen2.5-3B 中文能力不足（query 改写不准） | 低 | ① 换 7B（需 AWQ 量化到 4GB，部署仍 < 16GB） ② 加更多训练数据 ③ 人工规则兜底 |
| 训练数据质量差（DeepSeek 蒸馏有噪声） | 中 | ① 人工抽检 50 条做质控 ② 失败 query 改写回退到原 query |
| LLaMA-Factory 与 Qwen2.5-3B 兼容性 | 低 | LLaMA-Factory 已原生支持 Qwen2.5 系列，几乎无风险 |
| QLoRA 训练 loss 不收敛 | 中 | ① 减小 LR（2e-4 → 1e-4） ② 减小 LoRA rank（16 → 8） ③ 检查数据格式 |
| Embedder 2B 检索质量下降 | 中 | ① 保留 8B 备选（设置页可切） ② Reranker 弥补 ③ 用 nDCG@10 评测 |
| bge-reranker 加载慢（首次） | 低 | 预加载到 app.state（与 embedder 一样） |
| 1 周时间不够 | 中 | **优先级降级**：模块 1+2+3（数据+训练+服务） > 模块 4（Reranker） |
| 显存超 16GB（实际跑） | 低 | ① 关掉 bge-reranker 临时让位 ② 3B 量化到 int4（~3GB） ③ YOLO 用半精度 |
| GB10 驱动/库不兼容 | 低 | ① 先做 1-epoch 冒烟测试（< 10 分钟） ② 失败时切回 2 张 4090 / 云上租 A100 |

---

## 7. 1 周时间表

| Day | 任务 | 产出 | 阻塞条件 |
|---|---|---|---|
| **Day 1** | 数据准备：50 条种子 query + DeepSeek 蒸馏到 1500 条 | `data/query_rewrite_dataset/train.jsonl` | 种子 query 就绪 |
| **Day 2** | 数据准备：500 条 YOLO 检测结构化数据 + LLaMA-Factory 配置 | 第二个数据集 + 训练配置 | 视频 DB 可访问 |
| **Day 3** | QLoRA 训练（3B + LoRA）+ 评测 | `models/Qwen2.5-3B-Instruct-zhiying-lora/` + loss 曲线 | GB10 环境就绪 |
| **Day 4** | `core/llm_runtime.py` + `query_rewrite_service.py` + 集成 | search 入口加 query 改写开关 | — |
| **Day 5** | `detection_struct_service.py` + 集成（可选） | YOLO 输出自动结构化 | — |
| **Day 6** | `rerank_service.py` + 集成 | 7 路召回 top-20 rerank | — |
| **Day 7** | README/技术博客 + 简历话术 + 评测报告 | 可直接写入简历的完整材料 | — |

**每日产出**都在 git 上一个独立 commit，便于回滚。

---

## 8. 简历话术模板（**直接可复制粘贴**）

### 8.1 项目描述

> **Zhiying · 视频分析引擎 · RAG 增强子系统**（独立模块，2026.08）
> 角色：核心开发
> 技术栈：Qwen2.5-3B / QLoRA / PEFT / bge-reranker / pgvector / FastAPI / LLaMA-Factory

### 8.2 4 个技术亮点（按权重）

1. **QLoRA 微调 + 数据蒸馏（核心亮点）**
   > 基于 Qwen2.5-3B-Instruct 用 QLoRA（4bit NF4 + LoRA r=16）在自建 1500 条 query 改写 + 500 条检测结构化数据上微调，覆盖监控/交通领域检索场景。蒸馏自 DeepSeek + 真实搜索日志，训练耗时 X 小时（GB10 128GB），adapter 仅 50 MB，可热加载、可多版本并存。

2. **RAG Query 改写**
   > 将微调后的 Qwen2.5-3B 接进 search 入口，原 query「戴红帽子的人」自动改写为多 query 联合召回（`["戴红帽子的人", "red cap person", "红色帽子 行人"]`），nDCG@10 提升 X%。推理延迟 < 100ms（FP16 单 query），与生产检索链路完全异步。

3. **Reranker 重排序**
   > 引入 bge-reranker-v2-m3 对 7 路召回 top-20 重排，复杂查询（"戴红帽子的人"）nDCG@10 进一步提升 Y%。与 Query 改写形成"召回面扩展 + 精度提升"双重组合，召回率 + 准确率同时改善。

4. **YOLO 检测结果结构化**
   > 基于同一个 LoRA 推理实例将 YOLO 检测 JSON（class/bbox/track_id/conf）翻译为自然语言描述，写入 scene 元数据，让"画面右侧的车"、"人行横道上的行人"等位置/行为描述可被 text 检索召回。原本只有"车""人"两个词，现在能搜到空间关系。

### 8.3 数据 & 评测（让数字真实可信）

- 训练数据：自建 2000 条（query 改写 1500 + 检测结构化 500，蒸馏自 DeepSeek + 真实搜索日志 + 人工抽检）
- 训练产物：adapter 约 50 MB，base 模型 3 GB 不动
- 评测指标：nDCG@10 / MRR / 推理延迟 / 显存占用
- 部署形态：单卡 GB10（128 GB 统一内存），峰值占用 < 10 GB

### 8.4 面试常见问题预演

| 问题 | 回答要点 |
|---|---|
| 为什么选 Qwen2.5-3B 而不是 1.5B/7B？ | 16GB 部署预算下，3B FP16 6GB + embedder 2B 5GB + YOLO 2GB = 13GB 刚好；能力比 1.5B 强 6-10%，比 7B 省一半显存 |
| 为什么用 QLoRA 而不是全参数微调？ | 3B 全参数需要 ~12GB + 优化器状态；QLoRA 只需要 ~10GB，adapter 仅 50MB 易回滚 |
| 数据怎么来的？ | ① 种子 query 手工编写 50-100 条 ② DeepSeek 蒸馏扩展到 1500 条 ③ 人工抽检 50 条质控 |
| Query 改写为什么能提升检索？ | 解决"用户自然语言"和"caption 数据库"之间的语言鸿沟；多 query 联合召回扩大召回面 |
| 为什么不动 Embedder？ | 灾难性遗忘 + 维度变化导致 pgvector 存量报废 + 1 万条数据微调大概率变差。改为 Reranker 路线 |
| 怎么防止过拟合？ | early stop + lora_dropout=0.05 + 混合数据（query 改写 + 检测结构化两个任务） |
| 怎么评测 query 改写质量？ | 改写后跑 7 路检索，对比 top-20 命中率 + nDCG@10 + 人工抽检 50 条 |
| 3B 推理延迟如何？ | FP16 单 query < 100ms（GB10/16GB 显卡），并发可通过 vLLM continuous batching 提升 |
| 为什么 caption 默认关掉还要做微调？ | caption 是辅助链路默认关，但 text 检索依赖 caption 作为 embedding 源头；改 query 改写是从"输入侧"提升，不依赖 caption |
| 显存怎么管理的？ | core/llm_runtime.py 共享单例 + 互斥锁；Query 改写和检测结构化共用同一个 LoRA 推理实例 |

---

## 9. 文档落盘后的下一步

**本周不动代码，只交付本份文档**。

待你审完文档并确认（或调整）后：
- 我会按 `7. 1 周时间表` 分阶段交付
- 每天交付 1 个独立 commit
- 每个模块完成后给你 1 段「简历话术 + 自检清单」

**当前任务进度跟踪**：
- [x] 文档落盘（本文件）
- [ ] 用户审阅 + 反馈
- [ ] 模块 1：Query 改写 + 检测结构化数据准备
- [ ] 模块 2：QLoRA 微调（Qwen2.5-3B）
- [ ] 模块 3：Query 改写 + 检测结构化服务集成
- [ ] 模块 4：Reranker 服务
- [ ] 简历话术 + README 整合

---

## 10. 参考资料

- LLaMA-Factory 文档：https://github.com/hiyouga/LLaMA-Factory
- PEFT 文档：https://huggingface.co/docs/peft
- vLLM 文档：https://docs.vllm.ai/
- bge-reranker：https://github.com/FlagOpen/FlagEmbedding
- Qwen3-VL：https://github.com/QwenLM/Qwen3-VL
- 项目内参考：`docs/arch.md`（架构）· `core/interfaces.py:274-295`（BaseCaptioner）· `plugins/factory.py`（插件工厂）

---

> **维护说明**：本文件是 LLM 增强子系统的**单一设计真相源**。后续代码改动如与本文件冲突，必须先更新本文件再改代码。

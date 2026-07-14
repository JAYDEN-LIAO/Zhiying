# Cerno 参数层设计

> Version: 1.1 | 关联: CLAUDE.md, docs/arch.md

## 一、概述

参数层设计目标：用户上传视频后，通过**四级参数配置**控制 Pipeline 工作流。上级参数支配下级参数的默认值和可选性，最终产出动态的进度条阶段节点。

### 核心规则

1. **上级支配下级**：L1 选场景 → L2/L3 设默认值（用户可手动覆盖）；L2 某模块关闭 → 依赖它的下级参数强制关闭并置灰
2. **自动变自定义**：用户修改任何 L2/L3 的预设值 → L1 自动切换为「自定义」
3. **自定义持久化**：自定义参数自动保存（localStorage），用户刷新页面后恢复上次配置
4. **至少一个功能**：L3 的搜索索引和智能摘要至少开启一个，否则阻止提交
5. **至少一个感知源**：L2 的视觉分析和音频转录至少开启一个，否则阻止提交（Pipeline 无数据可处理）

---

## 二、参数层级总览

```
L1: 场景类型（1 选 1）
     │
     │  设置默认值（用户可手动覆盖）
     ├──→ L2: 感知模块（5 个开关）
     │        │
     │        │  强制关闭 + 置灰下级
     │        ├──→ L3: 功能开关（2 个）
     │        │        │
     │        │        │  置灰下级
     │        │        └──→ L4: 高级参数（5 个）
     │        │
     │        └──→ L4:部分高级参数
     │
     └──→ L3: 功能开关（设置默认值）
```

---

## 三、L1: 场景类型

| 值 | 中文名 | 适用场景 |
|---|---|---|
| `general` | 通用 | 未知内容类型，均衡开启全部模块 |
| `meeting` | 会议 | 以语音和对话为核心（含课堂、访谈、教程） |
| `surveillance` | 监控 | 固定机位，无音频轨道，纯视觉分析 |
| `text_recognition` | 文字识别 | 扫描视频中出现的文件、聊天截图、票据、PPT 等文字内容 |

### L1 → L2/L3 默认值映射

| 场景 | 视觉分析 | 音频转录 | 文字识别 | 画面描述 | 物体检测 | 搜索索引 | 智能摘要 |
|---|---|---|---|---|---|---|---|
| **通用** | ✅ | ✅ | ✅ | ✅ | 🔒灰 | ✅ | ✅ |
| **会议** | ✅ | ✅ | ✅ | ✅ | 🔒灰 | ✅ | ✅ |
| **监控** | ✅ | ❌ | ❌ | ✅ | 🔒灰 | ✅ | ❌ |
| **文字识别** | ✅ | ❌ | ✅ | ❌ | 🔒灰 | ✅ | ❌ |

> ✅ = 默认开启，可手动关闭 | ❌ = 默认关闭，可手动开启 | 🔒灰 = 插件未实现，始终置灰

### 各场景设计逻辑

- **通用**：全开兜底，适合未知内容
- **会议**：语音是核心信息载体，音频必开；OCR 辅助捕获白板/PPT 文字
- **监控**：监控视频通常无音频轨道，音频默认关；N 个场景的 caption 已足够，摘要默认关
- **文字识别**：核心是 OCR 从帧中提取文字；不需要 VLM 做画面描述（caption 默认关），不需要音频。**视觉分析必须保持 ON**——它是帧处理总开关，OCR 依赖帧抽取才能运行

---

## 四、L2: 感知模块

从画面和音频中提取原始信息的模块。

| 字段 | 中文名 | 说明 |
|---|---|---|
| `vision_enabled` | 视觉分析 | **帧处理总开关**。控制视频帧抽取及所有基于画面的处理。关闭后 OCR、caption 全部失效 |
| `audio_enabled` | 音频转录 | 提取音频轨道 → 语音转文字 |
| `ocr_enabled` | 文字识别 | 从抽取的帧画面中提取文字（PPT、字幕、聊天截图等） |
| `caption_enabled` | 画面描述 | VLM 对每个场景生成自然语言描述（搜索和摘要的原材料） |
| `detection_enabled` | 物体检测 | YOLO 目标检测。**插件未实现，始终置灰不可选** |

> **视觉分析 ≠ "看画面理解内容"**。它是一个总开关：管帧抽取、管所有画面相关下游模块。关闭后 OCR 和 caption 都无法运行。

---

## 五、L3: 功能开关

消费 L2 产出的数据，决定 Pipeline 最终产出什么。

| 字段 | 中文名 | 说明 |
|---|---|---|
| `search_index_enabled` | 搜索索引 | 建立向量索引（3-path 编码），支持语义搜索 |
| `summary_enabled` | 智能摘要 | 基于画面描述生成全局结构化摘要 |

**硬约束**：二者至少一个为 ON。两个都关 → 前端阻止并提示「搜索索引和智能摘要至少开启一个」。

---

## 六、L4: 高级参数

| 字段 | 中文名 | 类型 | 默认值 | 范围/选项 | 分区说明 |
|---|---|---|---|---|---|
| `language` | 识别语言 | 选项 | 自动 | 自动 / 中文 / English / 日本語 / 한국어 | — |
| `sample_fps` | 采样帧率 | 滑块 | 1.0 | 0.5 ~ 3.0 fps | ≤1.0 低精度快处理 / 1.5~2.0 推荐 / ≥2.5 高精度慢处理 |
| `segment_threshold` | 场景切换敏感度 | 滑块 | 0.5 | 0.2 ~ 0.8 | 0.2~0.3 极度敏感 / 0.4~0.6 推荐 / 0.7~0.8 仅检测明显切换 |
| `caption_with_context` | 记忆上下文 | 开关 | 开 | 开 / 关 | — |
| `summary_detail` | 摘要详细度 | 选项 | 标准 | 简要 / 标准 / 详细 | — |

### 各参数说明

- **识别语言**：传给 transcriber 的语言提示，`auto` 为自动检测。仅音频转录开启时生效
- **采样帧率**：传给 TransNetV2 分割器的抽帧频率。越高边界检测越精确，但计算量线性增长。上限 3.0 已足够覆盖绝大多数场景
- **场景切换敏感度**：TransNetV2 镜头切换判定阈值。越低越敏感（产生更多短场景），越高越保守（只检测明显切换）。低于 0.2 会产生大量碎片场景，高于 0.8 几乎检测不到切换，已从滑块范围排除
- **记忆上下文**：是否将前一场景的 caption 作为当前场景的描述上下文，提升跨场景连贯性。仅画面描述开启时生效
- **摘要详细度**：传给 LLM summarizer 的 prompt 模板选择。仅智能摘要开启时生效

---

## 七、完整支配关系矩阵

### 7.1 L1 → L2/L3（设置默认值）

选择场景类型时自动设置 L2/L3 默认值（详见第三章映射表）。用户可手动覆盖任何默认值，触发 7.5 自定义模式。

### 7.2 L2 模块间依赖

| 条件 | 影响 | 原因 |
|---|---|---|
| `vision_enabled = OFF` | `ocr_enabled` 强制 OFF + 置灰 | OCR 需要从视频帧中提取文字 |
| `vision_enabled = OFF` | `caption_enabled` 强制 OFF + 置灰 | 画面描述需要视频帧作为输入 |
| `caption_enabled = OFF` | `summary_enabled` 强制 OFF + 置灰 | 摘要依赖画面描述文本作为输入 |
| `vision_enabled = OFF` 且 `audio_enabled = OFF` | **阻止提交** | Pipeline 无任何数据源可处理 |

### 7.3 L2 → L4 高级参数

| 条件 | 影响 |
|---|---|
| `vision_enabled = OFF` | `sample_fps` 置灰（不进行帧处理，帧率无意义） |
| `audio_enabled = OFF` | `language` 置灰（不转录，语言选择无关） |
| `caption_enabled = OFF` | `caption_with_context` 置灰（无描述则无上下文） |

### 7.4 L3 → L4 高级参数

| 条件 | 影响 |
|---|---|
| `summary_enabled = OFF` | `summary_detail` 置灰（无摘要则无详细度） |

### 7.5 L3 自身约束

| 条件 | 影响 |
|---|---|
| `search_index_enabled = OFF` 且 `summary_enabled = OFF` | **阻止提交**，提示「搜索索引和智能摘要至少开启一个」 |

### 7.6 自定义模式触发

| 触发条件 | 结果 |
|---|---|
| 用户修改任何 L2/L3 的预设值 | L1 自动切换为「自定义」 |
| 用户重新选择 L1 场景类型 | L2/L3 恢复为该场景的默认值（覆盖手动修改） |

### 7.7 自定义参数持久化

- 「自定义」场景下的所有参数配置保存到 `localStorage`
- 用户刷新页面或下次进入时，L1 显示为「自定义」，L2/L3/L4 恢复上次配置
- 选择预设场景时覆盖自定义配置
- 仅持久化「自定义」模式参数；预设场景每次选择时从配置表加载默认值

---

## 八、非法参数组合检测

以下组合在前端实时检测并阻止提交（红色提示），后端同样校验。

| # | 非法组合 | 检测方式 | 提示文案 |
|---|---|---|---|
| 1 | vision=OFF 且 audio=OFF | 前端实时 + 后端校验 | 「视觉分析和音频转录至少开启一个，否则无可处理的数据」 |
| 2 | search_index=OFF 且 summary=OFF | 前端实时 + 后端校验 | 「搜索索引和智能摘要至少开启一个」 |
| 3 | vision=OFF 但 ocr=ON | 前端自动纠正（强制关 ocr 并置灰） | 无需提示，开关自动回弹 |
| 4 | vision=OFF 但 caption=ON | 前端自动纠正（强制关 caption 并置灰） | 无需提示，开关自动回弹 |
| 5 | caption=OFF 但 summary=ON | 前端自动纠正（强制关 summary 并置灰） | 无需提示，开关自动回弹 |
| 6 | sample_fps 超出 0.5~3.0 | 滑块边界限制 + 后端校验 | 后端: `sample_fps must be 0.5~3.0` |
| 7 | segment_threshold 超出 0.2~0.8 | 滑块边界限制 + 后端校验 | 后端: `segment_threshold must be 0.2~0.8` |

组合 #3~#5 不会出现提示——它们是**前端自动连锁关闭**，用户看到的只是下级开关自动弹回 OFF 并变灰。

---

## 九、合法边界场景验证

以下是用户可能自定义出的极端但合法的参数组合：

| 场景 | 参数组合 | 实际效果 | 是否合法 |
|---|---|---|---|
| 纯音频转录 | vision=OFF, audio=ON, ocr=OFF(强制), caption=OFF(强制), summary=OFF(强制), search_index=ON | 仅转录语音，全文检索 transcript | ✅ |
| 纯文档扫描 | vision=ON, audio=OFF, ocr=ON, caption=OFF, summary=OFF(强制), search_index=ON | 仅 OCR 提取文字，全文检索 OCR 文本 | ✅ |
| 仅要摘要 | vision=ON, audio=ON, ocr=ON, caption=ON, summary=ON, search_index=OFF | 全流程处理但不建搜索索引 | ✅ |
| 仅要搜索 | vision=ON, audio=OFF, ocr=OFF, caption=ON, summary=OFF(强制), search_index=ON | 画面描述后仅建搜索索引 | ✅ |
| 监控+音频 | vision=ON, audio=ON, ocr=OFF, caption=ON, summary=OFF, search_index=ON | 用户手动为监控视频开启了音频 | ✅ |
| 文字识别+描述 | vision=ON, audio=OFF, ocr=ON, caption=ON, summary=ON, search_index=ON | 用户手动开启了 caption 和 summary | ✅ |

---

## 十、PipelineBar 动态阶段节点

前端进度条根据 L2 + L3 的实际有效值动态渲染阶段节点。

### 阶段依赖关系

| 阶段 | 显示条件 | 排序 |
|---|---|---|
| 质检 | 始终显示 | 1 |
| 镜头分割 | 始终显示 | 2 |
| 关键帧抽取 | `vision_enabled = ON`（否则无帧可抽） | 3 |
| 音频转录 | `audio_enabled = ON` | 4 |
| 文本对齐 | `audio_enabled = ON` | 5 |
| 画面描述 | `caption_enabled = ON` | 6 |
| 建立索引 | `search_index_enabled = ON` | 7 |
| 智能摘要 | `summary_enabled = ON` | 8 |

### 各场景进度条示例

```
通用:       [质检] → [分割] → [关键帧] → [音频] → [对齐] → [描述] → [索引] → [摘要]
会议:       [质检] → [分割] → [关键帧] → [音频] → [对齐] → [描述] → [索引] → [摘要]
监控:       [质检] → [分割] → [关键帧] →                     [描述] → [索引]
文字识别:   [质检] → [分割] → [关键帧] →                               [索引]

仅搜索:     [质检] → [分割] → [关键帧] → [音频] → [对齐] → [描述] → [索引]
仅摘要:     [质检] → [分割] → [关键帧] → [音频] → [对齐] → [描述] →           → [摘要]
纯音频:     [质检] → [分割] →             [音频] → [对齐] →           [索引]
纯文档扫描: [质检] → [分割] → [关键帧] →                               [索引]
```

---

## 十一、参数总表

| 层级 | 可操作参数数 | 内容 |
|---|---|---|
| L1 场景类型 | 1 | 通用 / 会议 / 监控 / 文字识别 / 自定义（自动生成） |
| L2 感知模块 | 4 | 视觉分析、音频转录、文字识别、画面描述 |
| L2 感知模块（置灰） | 1 | 物体检测（YOLO 插件未实现） |
| L3 功能开关 | 2 | 搜索索引、智能摘要 |
| L4 高级参数 | 5 | 识别语言、采样帧率、场景切换敏感度、记忆上下文、摘要详细度 |
| **合计** | **12** | （+1 个置灰占位） |

---

## 十二、与后端 Pipeline 的衔接

### 参数传递流程

```
1. 前端上传视频 → POST /api/v1/videos/upload
   → 后端创建 Video 记录（status=pending，不启动 Pipeline）
   → 返回 video_id

2. 参数面板自动展开 → 用户配置参数 → 点击「参数启动」
   → PUT /api/v1/videos/{id}/params
   → Body: { content_type, audio_enabled, vision_enabled, ocr_enabled,
             caption_enabled, search_index_enabled, summary_enabled,
             language, sample_fps, segment_threshold,
             caption_with_context, summary_detail }

3. 后端校验参数合法性（含跨字段依赖校验）→ 更新 Video 记录 → 启动 Pipeline

4. Pipeline 各阶段检查对应开关：
   - _extract_keyframes() 检查 vision_enabled
   - _phase1 _run_audio_transcription() 检查 audio_enabled
   - _phase4 检查 caption_enabled
   - _phase5 检查 summary_enabled
   - _encode_frames() 检查 search_index_enabled
```

### 后端校验要点

```python
# 跨字段依赖校验
if not vision_enabled:
    assert ocr_enabled == False
    assert caption_enabled == False
if not caption_enabled:
    assert summary_enabled == False

# 至少一个感知源
assert vision_enabled or audio_enabled, "vision 和 audio 至少开启一个"

# 至少一个功能
assert search_index_enabled or summary_enabled, "搜索索引和摘要至少开启一个"

# 高级参数范围
assert 0.5 <= sample_fps <= 3.0
assert 0.2 <= segment_threshold <= 0.8
assert language in ("auto", "zh", "en", "ja", "ko")
```

---

## 十三、关联文件

| 文件 | 需修改内容 |
|---|---|
| `core/models.py` | ContentType 枚举新增 `text_recognition`；删除 PresetMode（合并到 L1） |
| `core/schemas.py` | 新增 `PipelineParams` 校验模型（含跨字段依赖校验） |
| `api/routes.py` | 新增 `PUT /api/v1/videos/{id}/params` 端点；修改 upload 端点（不自动启动 Pipeline） |
| `pipeline/engine.py` | `run()` 各阶段增加开关检查（vision_enabled、search_index_enabled） |
| `config/config.yaml` | 新增 `presets` 配置段（L1 场景类型→默认值映射） |
| `frontend/src/types/index.ts` | ContentType 新增 `text_recognition`；删除 PresetMode；新增 `PipelineParams` 类型 |
| `frontend/src/services/api.ts` | 新增 `updateParams()` 方法 |
| `frontend/src/Dashboard.tsx` | ParameterPanel 重写（四级联动 + 动态置灰 + 持久化 + 非法组合检测）；PipelineBar 动态阶段节点 |
| `frontend/src/mockData.ts` | 阶段定义改为动态计算函数 |
| `docs/settings.md` | 本文档 |

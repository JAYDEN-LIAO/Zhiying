# Video Source Analysis — 视频来源分析系统 (v0.17)

> 状态: 📋 设计完成 · 创建: 2026-07-28 · 修订: 2026-07-29

---

## 一、功能概述

为 Cerno 新增两层视频来源分析能力：

| 功能 | 触发条件 | 原理 | 时延 | 准确率 |
|------|---------|------|------|:------:|
| **来源分类**（手机/摄像机/录屏/监控） | 永远在线 | 元数据规则引擎 | <10ms | 高 |
| **监控品牌判断** | 来源=监控时 | 文件名/元数据/二进制签名 | <50ms | 中~高 |
| **AI 生成检测** | 永远在线（快检），可选深度检测 | AICheck CLI：元数据签名 + SEI 水印 + C2PA；deep 模式加 DWT-DCT 像素水印 | 快检 <100ms，深度 ~5s（3 帧 ffmpeg 抽帧） | 高（元数据信号）/ 中（像素水印） |

---

## 二、背景与动机

### 2.1 问题陈述

当前 Cerno 的元数据面板展示了视频的技术编码信息（编码、分辨率、码率、HDR 等），但缺少一个更高维度的问题答案：**"这个视频是谁拍的？用什么设备？是不是 AI 生成的？"**

具体场景：

- 用户上传了一批视频，想快速筛选出监控视频做车牌识别，手机视频不做
- 用户收到一个视频，想知道是否来自手机录屏（可能被二次编辑）
- 想知道视频是否 AI 生成（Sora/Kling/Runway 等）

### 2.2 AI 检测方法选择：为什么是 AICheck

#### 2.2.1 内容级检测（像素分析）的现状

截至 2026 年 7 月，**没有成熟的开源、内容级（像素分析）AI 视频检测预训练模型可用**。原因：

- AI 视频生成爆发是 2024-2025 年的事（Sora 2024.02, Kling 2024.06, Runway Gen-3 2024.06）
- 学术界的检测模型（ReStraV 2025, DeCoF 2025, EA-Swin 2026, G2VD 2026）都停留在论文阶段
- 这些项目要么没有预训练权重，要么只有训练框架没有推理工具
- 现有的"deepfake detection"模型（如 ResNext50+LSTM）训练数据 100% 是人脸替换（FaceForensics++/DFDC），对 Sora/Kling 等全场景生成完全无效

#### 2.2.2 AICheck：信号级检测的优势

[AICheck](https://github.com/MatrixA/aicheck) 是一个 Rust CLI 工具，通过分析文件元数据和隐形水印检测 AI 生成内容。不依赖深度学习模型。

**能检测什么：**

| 信号类型 | 置信度 | 覆盖的 AI 视频工具 |
|---------|:------:|------|
| **C2PA 来源证明**（加密签名） | HIGH | Sora (C2PA 签名), DALL-E, Adobe Firefly |
| **H.264 SEI 水印标记** | MEDIUM | Kling, Sora, Runway, Pika, Luma, Hailuo, Pixverse, Vidu, Genmo, Haiper |
| **MP4 ilst 原子元数据** | MEDIUM | 编码工具字段(©too) 中的 AI 工具名（如 "Google"→Veo, "Runway Gen-3"） |
| **AIGC 标签**（中国标准） | MEDIUM | Vidu, Wan（含 ContentProducer 企业 ID 映射） |
| **XMP/EXIF 元数据** | MEDIUM/LOW | `DigitalSourceType`, `AISystemUsed`, `CreatorTool` 等字段 |
| **文件名模式** | LOW | ElevenLabs 时间戳格式, Suno/SoundRaw 前缀, Midjourney/DALL-E |
| **像素级水印**（--deep） | LOW | DWT-DCT 频域水印（SeedAnce, LTX）, 可见角标水印 |

**局限：**
- 元数据被剥离 → 只剩 --deep 模式的像素水印（覆盖窄，仅部分工具）
- 社交平台上传时自动剥离元数据 → 建议分析原始文件
- 约 81% 的 AI 图片不携带可检测的来源标记（2025 年数据）
- 专有水印（SynthID, Stable Signature, VideoSeal）无法识别

**为什么选 AICheck：**
1. ✅ 唯一真实可用的工程化工具（有代码、有测试、能跑）
2. ✅ AGPL-3.0 许可证，本地部署自用完全合规
3. ✅ 纯 Rust 编译，零外部依赖，CLI 调用极简
4. ✅ 覆盖 62 种 AI 工具，含 Sora/Kling/Runway/Pika/Luma 等主流视频生成器
5. ✅ 快检模式无 GPU 需求，<100ms
6. ✅ deep 模式可通过 ffmpeg 抽帧做像素级水印分析（补充信号）

#### 2.2.3 两层检测架构

```
上传视频
  │
  ├──▶ 规则引擎（首次 GET /metadata 时懒执行，<10ms）
  │     ├── classify_video_source()      → 来源类型 + 置信度 + 证据链
  │     └── classify_surveillance_brand() → 品牌（如命中）+ 方法
  │
  └──▶ AICheck 快检（上传时同步执行，<100ms）
  │     └── aic check --json → AI 信号列表 + 综合判定
  │
  └──▶ AICheck 深度检测（可选 pipeline operation）
        └── aic check --deep --json → 快检信号 + 像素水印分析
```

---

## 三、方案设计

### 3.1 整体架构

```
上传时（同步，probe_and_save 中，<150ms 附加时延）:
  ├── ffprobe 提取容器/编码信息（已有，format_service.probe）
  └── aic check --json                 <100ms → ai_detect_result JSONB
       （仅需文件路径，无需 exiftool；无 GPU）

首次 GET /metadata 请求时（同步，首次提取 ~1-3s，后续缓存命中 <1ms）:
  ├── pymediainfo + exiftool 提取完整元数据（已有）
  ├── classify_video_source()           <10ms  → source_analysis JSONB
  │   （依赖 exiftool 输出的 Make/Model/GPS 等字段）
  └── classify_surveillance_brand()     <50ms  → source_analysis JSONB (仅监控)
       （依赖文件名 + exiftool maker notes）

pipeline 阶段（可选 operation）:
  └── ai_detect_deep:
       ├── depends_on=["segmentation"]  ← 视频管线就绪后执行
       ├── gate: ai_detect_enabled=True AND 快检未命中 HIGH 信号
       └── aic check --deep --json → 快检信号 + 像素水印
```

### 3.2 来源分类决策树

输入：exiftool 原始 JSON + pymediainfo 流数据 + 文件名 + 二进制文件头

```
优先级（高→低，命中即停）：

P1  有 Make/Model，且 Make 在已知相机品牌列表
     │                                     ──▶ camera
     │
     ├─ 有 Make/Model，且 Make 在已知手机品牌列表
     │  + HandlerVendorID=appl 等                     ──▶ phone
     │
     ├─ CompressorName/Encoder 含软件编码器关键词
     │  (Lavc / x264 / x265 / OBS / FFmpeg / Screen)  ──▶ screen_recording
     │  + Make/Model 缺失
     │
     ├─ 文件名匹配置监控命名模式
     │  (ch01_YYYYMMDD… / YYYY-MM-DD HH-MM-SS…)       ──▶ surveillance
     │
P2  有 Make/Model，Make 在已知手机品牌列表（次级匹配）
     │  + 旋转=90/270° + GPS 存在                     ──▶ phone
     │
     ├─ Make 在手机品牌列表（无旋转/GPS）              ──▶ phone (中置信度)
     │
     ├─ 分辨率匹配显示器标准尺寸（16:9/16:10）
     │  + 无相机元数据 + 无 GPS                        ──▶ screen_recording
     │
     ├─ 固定分辨率 + H.264 + 无 GPS + 无旋转
     │  + 音频缺失或低码率 AAC/PCM                     ──▶ surveillance (低置信度)
     │
P3  全部相机元数据缺失
     + 编码器 = 软件编码器                            ──▶ non_camera_source
     │                                                  (录屏/AI生成/重编码)
     │
P4  兜底                                              ──▶ unknown
```

**执行时机**：在 `api/video_routes.py` 的 `get_video_metadata_endpoint()` 中，首次元数据提取完成后同步执行。规则引擎依赖 exiftool 输出的设备元数据（Make/Model/GPS/旋转角等字段），这些数据在 `utils/metadata.py` 的 `get_video_metadata()` 中通过 pymediainfo + exiftool 提取。不涉及 GPU，<10ms 即可完成。结果写入 `videos.source_analysis` JSONB 字段，伴随 `metadata_json` 一同缓存，后续请求直接读 DB 返回。

**证据链**：每个判断附带 `evidence` 数组，列出用了哪些信号（例如 `["Make=Apple", "HandlerVendorID=appl", "GPS=present"]`），前端可展示。

### 3.3 监控品牌判断

多条独立证据链，按可靠度排序：

| 优先级 | 方法 | 原理 | 准确度 | 适用范围 |
|:------:|------|------|:------:|------|
| P1 | 文件名模式 | Hikvision: `ch\d+_\d{14}\.mp4` / `\d{14}\.mp4`；Dahua: `\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\.mp4` 等 NVR Web 导出格式 | 80% | 用户上传的 MP4 文件 |
| P2 | 厂商元数据 | exiftool 私有 maker notes 字段（HandlerVendorID, CompressorName, 自定义 atom） | 70% | 用户上传的 MP4 文件 |
| P3 | 二进制签名 | Dahua 私有格式 DHAV (0x44484156) 头 / dhav (0x64686176) 尾；Hikvision 自定义 HIKBTREE 结构 | 100%（命中时） | ⚠️ 仅对 DVR/NVR 原始磁盘镜像有效 |
| P4 | 编码特征 | 特定分辨率/GOP/SEI 消息模式（需进一步研究各品牌差异） | 60% | 用户上传的 MP4 文件 |

> ⚠️ **重要**：P3 二进制签名方法仅适用于从 DVR/NVR 硬盘原始镜像中提取的视频文件。用户通过 NVR Web 界面或 USB 导出的视频是标准 MP4 容器，**不包含** DHAV 或 HIKBTREE 签名。因此在实际使用中，P3 的命中率极低。P1（文件名）+ P2（元数据）是主力检测路径。

**二进制签名检测代码示例**（P3，仅原始磁盘镜像）：

```python
# Dahua DHAV signature — 仅对 DVR/NVR 原始磁盘镜像有效
with open(file_path, "rb") as f:
    header = f.read(4096)
    if b"DHAV" in header[:1024]:
        return "dahua"
    f.seek(-1024, os.SEEK_END)
    footer = f.read(1024)
    if b"dhav" in footer:
        return "dahua"
```

### 3.4 AI 生成检测（集成 AICheck）

#### 3.4.1 AICheck 快检模式（上传时同步执行，永远在线）

在 upload/reuse handler 的 `format_service.probe_and_save()` 之后同步调用 AICheck CLI。快检模式只读取 MP4 二进制文件，不需要 exiftool 或 GPU，<100ms 即可完成。结果直接写入 `videos.ai_detect_result` JSONB 字段。

```python
import subprocess, json
from pathlib import Path

def run_ai_check(file_path: str, deep: bool = False) -> dict:
    """Run AICheck on a video file. Returns parsed JSON result."""
    args = ["aic", "--json", "check", file_path]
    if deep:
        args.insert(2, "--deep")

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=30 if deep else 5,
    )
    if result.returncode not in (0, 1):  # 0=detected, 1=not detected, 2=error
        return {"error": result.stderr.strip(), "ai_generated": False, "signals": []}

    return json.loads(result.stdout)
```

**快检模式工作原理**（不抽帧，纯二进制分析）：

1. 读取 MP4 文件头部，解析 atom/box 树
2. 提取 ilst 元数据（©too 编码工具、©swr 软件）→ 匹配 AI 工具名
3. 扫描 mdat 前 1MB → 查找已知 SEI 水印二进制标记
4. 解析 AIGC 标签（中国标准 JSON）→ 提取 ContentProducer/ProduceID → 映射工具
5. 读取 C2PA 清单（如有）→ 最高置信度信号
6. 检查 XMP/EXIF 元数据 → AI 工具引用
7. 匹配文件名模式 → 已知 AI 工具命名规则

**不涉及**：帧提取、GPU、深度学习。

#### 3.4.2 AICheck 深度检测模式（可选 pipeline operation）

当用户开启 `ai_detect_enabled` 且需要更深度的分析时，作为 pipeline operation 运行：

```python
# pipeline/operations.py
Operation(
    name="ai_detect_deep",
    gate=lambda video, config: (
        video.ai_detect_enabled
    ),
    depends_on=["segmentation"],  # 视频管线就绪后执行，AICheck --deep 内部自用 ffmpeg 抽 3 帧
    label="AI生成深度检测",
    description="像素级水印分析（DWT-DCT + 可见水印）",
)
```

深度模式的工作原理：

1. AICheck 内部通过 ffmpeg 从视频 25%/50%/75% 位置各抽 1 帧（共 3 帧）
2. 对每帧运行 DWT-DCT 频域水印分析（通道噪声不对称性、跨通道比特一致性、小波能量模式）
3. 对每帧运行可见水印检测（四角亮度分析、文字行模式检测）
4. 任意 1 帧命中即判定为阳性
5. 结果与快检信号合并

> **Gate 实现注记**：`快检未命中 HIGH 置信度` 的判断逻辑为读取 `video.ai_detect_result` JSONB 字段，检查 `signals` 数组中是否存在 `confidence == "high"` 的信号。若快检已通过 C2PA 等 HIGH 置信度信号确认 AI 生成，则跳过深度检测（避免无意义的像素水印分析）。
>
> **设计决策**：`depends_on=["segmentation"]` 而非 `depends_on=["duration"]`。AICheck --deep 内部通过 ffmpeg 自行抽帧（仅 3 帧，分别在 25%/50%/75% 位置），不消耗 Cerno 的帧流队列。`segmentation` 作为依赖确保视频管线基础就绪即可，不会因 keyframes 未完成而延迟启动。如果将来要完全复用 Cerno 的帧流（避免 AICheck 二次 ffmpeg 抽帧），可以改为将 keyframes 的帧数据直接传给 AICheck 的图片分析 API（`aic check frame.png`），届时依赖改为 `["keyframes"]`。

#### 3.4.3 资源消耗

| 项目 | 快检模式 | 深度模式 |
|------|------|------|
| GPU | 不需要 | 不需要 |
| CPU | <100ms | ~5s（3 帧 ffmpeg + 像素分析） |
| 内存 | ~10MB (AICheck 进程) | ~50MB |
| 磁盘 | 无 | tmp 3 帧 PNG (~2MB, 临时) |

**无需额外 GPU 显存**。AICheck 不加载任何深度学习模型。

#### 3.4.4 与现有模型的 GPU 共存

```
Qwen3-VL-Embedding-8B    ~16 GB   (常驻，startup 预加载)
Qwen3-VL-8B-Instruct     ~16 GB   (按需，caption 用完释放)
YOLO11s                  ~0.2 GB  (按需，detection)
SCRFD + ArcFace R50      ~0.5 GB  (按需，face)
AICheck                   0  GB   (纯 CPU，不占 GPU)
─────────────────────────────────
峰值                      ~33 GB  (120 GB GPU 完全可行)
```

### 3.5 Pipeline 集成

```
上传时（同步, 在 video_routes.py upload/reuse handler 中）:
  ├── ffprobe probe_and_save (已有)
  └── aic check --json             → ai_detect_result（快检，写入 DB）

首次 GET /metadata（同步, 在 get_video_metadata_endpoint 中）:
  ├── get_video_metadata() (已有, pymediainfo + exiftool)
  ├── classify_video_source()      → source_analysis
  ├── classify_surveillance_brand() → source_analysis.surveillance_brand
  └── 缓存 source_analysis 到 DB（伴随 metadata_json）

pipeline 阶段（可选, 异步 operation）:
  └── ai_detect_deep:
       ├── gate: ai_detect_enabled AND 快检未命中 HIGH 置信度
       ├── depends_on=["segmentation"]
       └── aic check --deep --json → 更新 ai_detect_result
```

---

## 四、配置与开关

### 4.1 参数层级（遵循现有 4 级参数体系）

| 层级 | 字段 | 默认值 | 说明 |
|:----:|------|:------:|------|
| L2 感知模块 | `ai_detect_enabled` | `false` | AI 生成内容深度检测开关（快检永远在线） |

> **设计决策**：AI 生成检测的快检模式永远在线（上传时在 `probe_and_save()` 后同步执行），因为它是纯元数据/二进制信号分析，不涉及 GPU 或密集型计算。`ai_detect_enabled` 开关只控制是否需要额外的 --deep 深度检测（像素水印分析）。来源分类则是首次 GET /metadata 时懒执行，因为它依赖 exiftool 输出的设备元数据。

### 4.2 参数面板位置

在前端 ParameterPanel 的 "L2 · 感知模块" 区块中，作为**独立开关**（与 `detection_enabled` 同级，不是其子开关）：

```
感知模块
  ├── 物体检测 [开关]          ← detection_enabled
  │   ├── 人脸识别 [子开关]    ← face_enabled
  │   └── 车牌识别 [子开关]    ← plate_enabled
  ├── AI生成深度检测 [开关]    ← ai_detect_enabled（独立，不隶属于 detection）
  ├── 视觉理解 [开关]          ← vision_enabled
  ├── 音频转录 [开关]          ← audio_enabled
  └── ...
```

> **设计决策**：`ai_detect_enabled` 不是 detection 的子功能——AI 检测分析的是"视频是否被 AI 生成/篡改"，和物体检测在概念上完全无关。人脸识别和车牌识别确实是 detection 的子功能（依赖 YOLO 提供 person/vehicle crop），但 AI 检测是独立维度。

---

## 五、API 设计

### 5.1 元数据端点扩展

`GET /api/v1/videos/{id}/metadata` 响应新增字段：

```json
{
  "source_analysis": {
    "source_type": "phone",
    "source_label": "手机视频",
    "confidence": "high",
    "evidence": [
      "Make=Apple, Model=iPhone 15 Pro",
      "HandlerVendorID=appl",
      "GPS数据存在",
      "旋转角度=90°（竖拍）"
    ],
    "surveillance_brand": null,
    "surveillance_method": null
  },
  "ai_detect": {
    "enabled": false,
    "deep_analysis_used": false,
    "status": "completed",
    "score": 1.0,
    "verdict": "ai_generated",
    "signals": [
      {
        "source": "C2PA",
        "confidence": "high",
        "description": "C2PA: digitalSourceType = trainedAlgorithmicMedia (fully AI-generated)",
        "tool": "sora"
      },
      {
        "source": "MP4",
        "confidence": "medium",
        "description": "SEI watermark marker: kling-ai",
        "tool": "kling"
      }
    ],
    "software_info": [
      ["Encoder", "Lavf60.16.100 (FFmpeg)"]
    ]
  }
}
```

### 5.2 API 集成说明

`VideoMetadataResponse` 是严格的 Pydantic v2 模型，需要显式新增字段：

```python
# api/schemas.py — VideoMetadataResponse 新增两个字段
class VideoMetadataResponse(BaseModel):
    # ... 现有字段 (container, duration, file_size, device, timestamps 等) ...
    
    source_analysis: SourceAnalysis | None = Field(
        default=None, description="视频来源分析（首次提取后缓存）"
    )
    ai_detect: AIDetectResult | None = Field(
        default=None, description="AI 生成检测结果（上传时快检，首次返回）"
    )
```

metadata 端点的工作流已自然支持这一机制：

1. **快路径**（缓存命中）：`select(Video.file_path, Video.metadata_json)` → 需追加查询 `source_analysis` 和 `ai_detect_result` 列
2. **慢路径**（首次提取）：`extract_metadata()` 后，运行 `classify_video_source()`，将结果合并到 meta dict 或单独赋值 → 缓存到 DB
3. `ai_detect_result` 在上传时已写入，metadata 端点直接读取即可

### 5.3 Pydantic Schema 定义

```python
# api/schemas.py

from pydantic import BaseModel
from typing import Optional, Literal
from enum import Enum


class SourceType(str, Enum):
    PHONE = "phone"
    CAMERA = "camera"
    SCREEN_RECORDING = "screen_recording"
    SURVEILLANCE = "surveillance"
    NON_CAMERA_SOURCE = "non_camera_source"
    UNKNOWN = "unknown"


class SourceConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SourceAnalysis(BaseModel):
    """视频来源分析结果 — 规则引擎输出"""
    source_type: SourceType
    source_label: str  # 中文标签，如 "手机视频"
    confidence: SourceConfidence
    evidence: list[str]  # 判断依据列表
    surveillance_brand: Optional[str] = None  # 命中的监控品牌
    surveillance_method: Optional[str] = None  # 品牌判断方法，如 "filename_pattern"


class AIDetectSignal(BaseModel):
    """单个 AI 检测信号 — 来自 AICheck"""
    source: str        # C2PA / MP4 / XMP / EXIF / WATERMARK / FILE / SPEC
    confidence: str     # high / medium / low
    description: str    # 人类可读描述
    tool: Optional[str] = None  # 命中的 AI 工具名，如 "sora"


class AIDetectResult(BaseModel):
    """AI 生成检测结果 — AICheck 输出"""
    enabled: bool              # 当前视频是否启用了深度检测
    deep_analysis_used: bool = False  # 是否使用了 --deep 模式
    status: Literal["not_run", "completed", "error"]
    score: Optional[float] = None     # 综合置信度 0.0-1.0 (1.0 = AI 生成)
    verdict: Optional[Literal["ai_generated", "likely_ai", "no_signal", "error"]] = None
    signals: list[AIDetectSignal] = []  # 命中的信号列表
    software_info: list[tuple[str, str]] = []  # 非 AI 创作软件信息 (label, value)
    error_message: Optional[str] = None
```

### 5.4 来源类型枚举

| 值 | 标签 | 说明 |
|----|------|------|
| `phone` | 手机视频 | 智能手机拍摄（iPhone, Samsung, Xiaomi 等） |
| `camera` | 摄像机拍摄 | 专业相机/运动相机（Canon, Sony, GoPro, DJI 等） |
| `screen_recording` | 屏幕录制 | OBS/QuickTime/系统录屏 |
| `surveillance` | 监控视频 | 安防摄像头 |
| `non_camera_source` | 非相机来源 | 无法区分录屏/AI生成/重编码（低置信度） |
| `unknown` | 未知 | 信息不足，无法判断 |

### 5.5 监控品牌枚举

| 值 | 标签 |
|----|------|
| `hikvision` | 海康威视 |
| `dahua` | 大华 |
| `xiaomi` | 小米 |
| `tplink` | TP-Link |
| `ezviz` | 萤石 |
| `reolink` | Reolink |
| `uniview` | 宇视 |
| `generic_ip` | 通用网络摄像头 |
| `unknown` | 未知品牌 |

---

## 六、前端展示

### 6.1 MetadataPanel 新增区块

在现有"文件格式/视频流/音频流/设备信息/时间"之后，新增两个区块：

**来源分析区块**（永远展示）：

```
来源分析
来源类型      手机视频  ✓ 高置信度
判断依据      Make=Apple, Model=iPhone 15 Pro
              HandlerVendorID=appl
              GPS数据存在
              旋转角度=90°（竖拍）
监控品牌      —
```

**AI 生成检测区块**：

```
AI 生成检测                     [ 未开启深度检测 ]
// 快检命中时:
AI 生成检测
结果          ⚠ AI 生成         置信度: HIGH
信号源        C2PA (HIGH)       digitalSourceType = trainedAlgorithmicMedia → Sora
              MP4 (MEDIUM)      SEI watermark: kling-ai → Kling
// 快检未命中时:
AI 生成检测
结果          ✓ 未检测到 AI 信号
// 深度检测开启+运行中:
AI 生成检测                     [ 深度分析中... ]
// 无信号时:
AI 生成检测
结果          未检测到 AI 信号    快检完成, 深度检测已关闭
```

### 6.2 置信度视觉

| 置信度 | 颜色 | 图标 |
|:------:|------|:----:|
| `high` | 绿色 | ✓ |
| `medium` | 黄色 | ~ |
| `low` | 灰色 | ? |

---

## 七、文件清单

### 新建文件

| 文件 | 说明 |
|------|------|
| `utils/video_source.py` | 规则引擎：来源分类 + 监控品牌判断（纯 Python，无额外依赖） |
| `services/ai_detect_service.py` | AICheck 调用封装：快检 + 深度检测 subprocess 调用 + JSON 解析 |
| `pipeline/runners/ai_detect_deep.py` | AI 深度检测 runner（调用 `aic check --deep --json`，depends_on=["segmentation"]） |

### 修改文件

| 文件 | 变更 |
|------|------|
| `core/models.py` | Video 表 + `ai_detect_enabled` (Boolean, default=False), + `ai_detect_result` (JSONB, nullable), + `source_analysis` (JSONB, nullable) |
| `core/db.py` | `ALTER TABLE ADD COLUMN IF NOT EXISTS` 增量迁移 |
| `core/schemas.py` | `PipelineParams` + `ai_detect_enabled` |
| `api/schemas.py` | `VideoMetadataResponse` + `source_analysis: Optional[SourceAnalysis]` + `ai_detect: Optional[AIDetectResult]`；新增 `SourceAnalysis`, `AIDetectResult`, `AIDetectSignal` Pydantic 模型 |
| `api/video_routes.py` | upload/reuse handler 集成 AICheck 快检；metadata 端点集成来源分类 + 返回新字段 |
| `services/format_service.py` | `probe_and_save()` 中集成 AICheck 快检调用 |
| `pipeline/operations.py` | 新增 `ai_detect_deep` Operation（gate: `ai_detect_enabled` AND 快检无 HIGH 信号, depends_on: `["segmentation"]`） |
| `frontend/src/types/index.ts` | 新增 `SourceAnalysis`、`AIDetectResult`、`AIDetectSignal` 类型 |
| `frontend/src/components/MetadataPanel.tsx` | "来源分析" + "AI 生成检测"区块，处理 NULL/完成/失败三种状态 |
| `frontend/src/components/ParameterPanel.tsx` | `ai_detect_enabled` 独立 L2 开关（与 `detection_enabled` 同级） |

共 **3 新建 + 10 修改 = 13 个文件**。

### 新增依赖

| 依赖 | 说明 |
|------|------|
| AICheck CLI (`aic`) | 需预装在系统 PATH 中：`cargo install aicheck`，或下载预编译二进制 |

---

## 八、回填策略

### 8.1 数据库迁移

新增三个字段均为 nullable，已有视频的字段为 NULL。增量迁移在 `init_db()` 中执行：

```sql
ALTER TABLE videos ADD COLUMN IF NOT EXISTS ai_detect_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS ai_detect_result JSONB;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS source_analysis JSONB;
```

> **与 `metadata_json` 的关系**：`metadata_json` 列（已在 v0.17 中新增）缓存完整技术元数据（pymediainfo + exiftool 输出）。`source_analysis` 存储的是规则引擎基于这些元数据的**分类结论**，两者独立存储以便前端分别渲染"技术元数据"和"来源分析"两个区块，避免耦合。

### 8.2 已有视频分析

提供两种方式对已有视频重新分析来源和 AI 检测：

1. **手动触发**：在视频详情页 MetadataPanel 中，"来源分析"和"AI 检测"区块若为 NULL，显示"重新分析"按钮，触发单独的分析端点
2. **批量回填**：提供 CLI 脚本 `scripts/backfill_source_analysis.py`，遍历已有视频执行分析并更新 DB

### 8.3 前端兼容

MetadataPanel 需处理以下三种状态：
- **NULL**（迁移前的旧视频）：显示"待分析"，提供触发按钮
- **分析完成**：正常渲染结果
- **分析失败**：显示错误信息，提供重试按钮

---

## 九、测试计划

### 9.1 来源分类测试

| 测试用例 | 输入 | 期望输出 |
|---------|------|---------|
| iPhone 竖拍视频 | Make=Apple, Model=iPhone 15 Pro, GPS=有, 旋转=90° | `phone` confidence=high |
| Canon 相机视频 | Make=Canon, Model=EOS R5, 无 GPS | `camera` confidence=high |
| OBS 录屏 | Make 缺失, CompressorName=Lavc60, 1920×1080 | `screen_recording` confidence=medium |
| 海康 NVR 导出 | 文件名 ch01_20240615120000.mp4, H.264, 无 GPS | `surveillance` confidence=medium |
| AI 生成视频 | 全部相机元数据缺失, 编码器=软件编码器 | `non_camera_source` confidence=low |
| 无元数据文件 | 全部信号缺失 | `unknown` |

### 9.2 监控品牌测试

| 测试用例 | 输入 | 期望输出 |
|---------|------|---------|
| 海康 NVR Web 导出 | 文件名 ch01_20240615120000.mp4 | `hikvision` method=filename_pattern |
| 大华 DVR 导出 | 文件名 2024-06-15 12-00-00.mp4 | `dahua` method=filename_pattern |
| 小米摄像头 | 文件名包含 xiaomi / 元数据 model=xiaomi | `xiaomi` method=metadata |

### 9.3 AI 检测测试

| 测试用例 | 输入 | 期望输出 |
|---------|------|---------|
| Sora 生成视频 (C2PA) | ai_sora.mp4 | verdict=ai_generated, 含 C2PA HIGH 信号 |
| Kling 生成视频 (SEI) | ai_kling.mp4 | verdict=ai_generated, 含 SEI MEDIUM 信号 |
| Kling v3/Omni 变体 | ai_kling_v3.mp4, ai_kling_omni.mp4 | 正确检测 kling |
| Vidu 生成视频 (AIGC) | ai_vidu.mp4 | verdict=ai_generated, 含 AIGC MEDIUM 信号 |
| Wan 生成视频 (AIGC+ContentProducer) | ai_wan.mp4 | verdict=ai_generated, tool=wan |
| 真实拍摄视频 | real_video.mp4 | verdict=no_signal |
| 元数据被剥离的 AI 视频 | 剥除了所有元数据的 Kling 视频 | 快检=no_signal, 深度检测可能命中像素水印 |

### 9.4 集成测试

| 场景 | 验证点 |
|------|--------|
| 上传视频后 → GET /metadata | ai_detect_result 在上传时已写入（非空）；source_analysis 在首次 metadata 请求后写入（非空） |
| 参数面板开启 ai_detect_enabled | `ai_detect_deep` operation 出现在 pipeline operations 列表中 |
| Pipeline 运行 | ai_detect_deep 正确依赖 segmentation，在 segmentation 完成后执行 |
| 前端展示 | MetadataPanel 渲染来源分析 + AI 检测区块（三种状态） |
| 已有视频回填 | backfill 脚本正确更新存量视频 |

### 9.5 验收标准

| 指标 | 目标 |
|------|:---:|
| 来源分类准确率（手机/相机/录屏/监控） | >90% |
| 监控品牌命中率（海康/大华标准导出文件） | >80% |
| AI 检测假阳性率（真实视频误报为 AI） | <5% |
| AI 检测命中率（含元数据信号的 AI 视频） | >80% |
| upload 附加时延（AICheck 快检） | <200ms |
| 首次 metadata 请求附加时延（来源分类） | <10ms |
| AICheck 进程内存增量 | <50MB |

---

## 十、限制与已知问题

1. **监控品牌二进制签名仅对原始磁盘镜像有效**。标准 MP4/MOV 封装的监控视频（如通过 NVR 导出）没有 DHAV/HIKBTREE 签名，需退回到文件名/元数据方法。

2. **AICheck 依赖元数据信号**。约 81% 的 AI 图片和相当比例的 AI 视频不携带可检测的来源标记。元数据被剥离后，快检模式可能返回 `no_signal`。--deep 模式的像素水印覆盖范围有限（仅部分工具嵌入频域水印）。

3. **AICheck 不能区分"录屏"和"AI 生成"**。在元数据信号都缺失的情况下，两者都显示为 no_signal。需结合来源分类规则引擎的结果综合判断。

4. **专有水印无法识别**。SynthID（Google）、Stable Signature（Stability AI）、VideoSeal 等专有水印需要厂商私有密钥，AICheck 不支持。

5. **AICheck 深度检测有时间开销**。--deep 模式需要 ffmpeg 抽 3 帧 + 像素级 DWT-DCT 分析，约 3-5 秒。对于 1 小时视频这个开销不大（仅 3 帧），但对极短视频可能占比较高。

6. **元数据伪造**。ExifTool/Make/Model 等标签可被故意修改。来源分类规则引擎依赖元数据真实性，不适用于取证场景。

7. **AICheck 是 Rust CLI 工具**。需要通过 subprocess 调用，而不是 Python 原生 import。如果 AICheck 未安装或不在 PATH 中，AI 检测功能需要优雅降级（返回 status="error" 而非崩溃）。建议在 Cerno 启动时检查 `aic` 是否可用，并在设置页展示状态。

---

## 十一、参考资料

| 主题 | 来源 |
|------|------|
| AICheck CLI 工具 | [MatrixA/aicheck](https://github.com/MatrixA/aicheck) — Rust, AGPL-3.0, 62 AI 工具检测 |
| MP4 容器结构取证 | Gloe, Fischer & Kirchner, *Forensic Analysis of Video File Formats*, DFRWS 2014 |
| 元数据指纹聚类 | Xiang et al., *Forensic Analysis of Video Files Using Metadata*, CVPR 2021 |
| 编码器配置分析 (ECA) | [Magnet Forensics — Encoder Configuration Analysis](https://www.magnetforensics.com/blog/magnet-verifys-latest-breakthrough-encoder-configuration-analysis/) |
| Hikvision/Dahua 文件系统取证 | *Automated Forensic Recovery for Hikvision and Dahua DVR/NVR*, MDPI Information 2025 |
| ReStraV (NeurIPS 2025) | *ReStraV: Retrieval of Straight Video Trajectories* — frozen DINOv2 + 轨迹几何 → MLP |
| DeCoF (ICME 2025) | *Detecting AI-Generated Video via Frame Consistency* — CLIP ViT + temporal transformer |
| GenVidBench (AAAI 2026) | 6.78M 视频 benchmark, 11 生成器, 跨生成器泛化评测 |
| pymediainfo duration 单位 | [pymediainfo 官方 doctest](https://github.com/sbraz/pymediainfo/blob/main/pymediainfo/__init__.py) — `t.duration → 3000` = 3s |
| exiftool QuickTime 标签 | [ExifTool TagNames Docs](https://exiftool.org/TagNames/QuickTime.html) |

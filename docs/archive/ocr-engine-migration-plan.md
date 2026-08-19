# OCR 引擎定版施工 + 验收方案（RapidOCR + DirectML）

> 状态：待施工 · 目标：把 OCR 从「EasyOCR（临时验证）」换成「生产级中文 OCR」
> 结论：**RapidOCR（PP-OCRv3 ONNX）+ onnxruntime DirectML EP**
> 一句话：不用换 torch、不用 VLM、不用两段式。用已装的 RapidOCR 模型 + 前后处理，只把推理后端从「onnxruntime CUDA EP（本机 1114 起不来）」换成「DirectML EP（DirectX12，不依赖 CUDA，与 torch cu130 零冲突）」。

---

## 0. 为什么这条路成立（干活前先看懂，别又去试 CUDA EP）

- 复盘文档的死结是「onnxruntime GPU = CUDA EP」。但 Windows 上 onnxruntime 有 **DirectML EP**（`DmlExecutionProvider`），跑 DirectX 12，RTX 5070 直接用，**完全不碰 CUDA/cuDNN/cuBLAS** → 与 torch(cu130) 无任何冲突。
- **RapidOCR 1.2.3 已装好**，PP-OCRv3 的 det/rec/cls 三个 ONNX 模型**已随包落盘**（`site-packages/rapidocr_onnxruntime/models/`，共 ~13MB，零下载），前后处理（DBNet 检测 / SVTR 识别 / 角度分类）开箱即用。
- PP-OCRv3 中文精度第一梯队（复盘里 PaddleOCR 精度「最佳」，同一模型系）。速度：5070 上走 DirectML 预估 ~50–150ms/帧，远超 400ms 门槛。
- 不动 DAG / 表 / 检索 / 前端：只新增一个插件后端 + 换一个依赖包 + 改一处 config。复盘文档第三节那套骨架全部复用。

---

## 1. 现状盘点（已实测确认）

| 项 | 现状 | 处理 |
|---|---|---|
| `rapidocr-onnxruntime` 1.2.3 | ✅ 已装，模型已落盘 | 复用 |
| `onnxruntime` 99.0.0 + `onnxruntime-gpu` 1.20.0 | ⚠️ 同目录共装，互相污染；CUDA EP 1114 | **卸载，换 `onnxruntime-directml`** |
| `paddlepaddle`/`paddlepaddle-gpu`/`paddlex`/`paddleocr` | ❌ GPU/CPU 均死路 | **本次不动**（`plugins/plate/paddle_plate.py` 备用后端还 import paddleocr，卸载会破坏它；清理另行评估） |
| `easyocr` 1.7.2 | 当前验证性后端，精度弱 | 保留作回滚，定版后再评估清理 |
| torch 2.13.0+cu130 | ✅ 唯一可用 GPU 栈 | 完全不动 |

---

## 2. 施工步骤

### 步骤 1：依赖切换（替换 onnxruntime）

```bash
cd /d/zhiying
.venv/Scripts/python.exe -m pip uninstall -y onnxruntime onnxruntime-gpu
.venv/Scripts/python.exe -m pip install onnxruntime-directml==1.24.4
```

验证（必须过，否则停）：

```bash
.venv/Scripts/python.exe -c "import onnxruntime as ort; print(ort.__version__); print(ort.get_available_providers())"
```

预期输出含 `DmlExecutionProvider`（如 `['DmlExecutionProvider', 'CPUExecutionProvider']`）。

> 注意：`rapidocr-onnxruntime` 的 pip 依赖是 `onnxruntime>=1.7.0`，装的是 `onnxruntime-directml`（dist 名不同）。运行时 `import onnxruntime` 正常即可；若后续 `pip install` 因依赖名抱怨，加 `--no-deps` 或忽略——不影响本项目运行。

### 步骤 2：新增插件 `plugins/ocr/rapidocr.py`

新建文件，内容如下（DML 补丁只打 RapidOCR 自己的 `OrtInferSession`，不碰全局 `onnxruntime.InferenceSession` → insightface/hyperlpr 各自 EP 不受影响）：

```python
"""
plugins/ocr/rapidocr.py
═══════════════════════════════════════════════════════════
OCR 画面文字提取 — RapidOCR (PP-OCRv3 ONNX) + onnxruntime DirectML。

v0.34 定版选型：PaddleOCR GPU(DLL 死路)/EasyOCR(精度弱) 均不达生产级。
改用 RapidOCR 的 PP-OCRv3 det+rec+cls 前后处理（中文精度第一梯队），
推理后端换 DirectML EP（DirectX 12，不依赖 CUDA，与 torch cu130 零冲突）。
复用已装 rapidocr-onnxruntime 1.2.3（模型已随包落盘，零下载）。

同步推理通过 asyncio.to_thread 包裹，遵循核心异步约定。
"""

import asyncio
import logging

import numpy as np

from core.interfaces import BaseOCR

logger = logging.getLogger(__name__)


def _patch_rapidocr_dml() -> bool:
    """让 RapidOCR 的 ONNX 会话走 DirectML EP（替代硬编码的 CUDA/CPU 分支）。

    rapidocr_onnxruntime.utils.OrtInferSession.__init__ 只认识
    CUDAExecutionProvider / CPUExecutionProvider。本补丁在 DML 可用时，
    把该类会话创建改写为 DML 优先、CPU 回退。只打 RapidOCR 自己的
    OrtInferSession，不碰全局 InferenceSession → 不影响 insightface/hyperlpr。
    幂等：只打一次。
    """
    try:
        import onnxruntime as ort
    except ImportError:
        return False
    try:
        if "DmlExecutionProvider" not in ort.get_available_providers():
            return False
    except Exception:
        return False

    from rapidocr_onnxruntime import utils as rapid_utils
    from onnxruntime import (GraphOptimizationLevel, InferenceSession,
                             SessionOptions)

    _orig = rapid_utils.OrtInferSession.__init__
    if getattr(_orig, "_zhiying_dml", False):
        return True  # 已打补丁

    def _patched(self, config):
        sess_opt = SessionOptions()
        sess_opt.log_severity_level = 4
        sess_opt.enable_cpu_mem_arena = False
        sess_opt.graph_optimization_level = GraphOptimizationLevel.ORT_ENABLE_ALL
        self._verify_model(config["model_path"])
        dml_provider = ("DmlExecutionProvider", {})
        cpu_provider = ("CPUExecutionProvider",
                        {"arena_extend_strategy": "kSameAsRequested"})
        self.session = InferenceSession(config["model_path"],
                                        sess_options=sess_opt,
                                        providers=[dml_provider, cpu_provider])

    _patched._zhiying_dml = True
    rapid_utils.OrtInferSession.__init__ = _patched
    return True


class RapidOCRExtractor(BaseOCR):
    """RapidOCR 画面文字提取。

    参数从 config.yaml plugins.ocr.params 传入（可被系统设置页 pipeline.ocr
    运行时覆盖 sample_fps/conf_thresh/max_width/scale/lang）:
      - lang: 识别语言，仅 "ch"（RapidOCR 随包模型为中文 PP-OCRv3）
      - conf_thresh: text_score 文字行置信度门槛
      - use_angle_cls: 是否用方向分类器（默认 True）
    """

    def __init__(
        self,
        lang: str = "ch",
        conf_thresh: float = 0.5,
        use_angle_cls: bool = True,
        **kwargs,
    ) -> None:
        self._lang = lang
        self._conf_thresh = conf_thresh
        self._use_angle_cls = use_angle_cls
        self._ocr = None

    async def extract(self, frame: np.ndarray) -> list[dict]:
        if self._ocr is None:
            await asyncio.to_thread(self._load)
        return await asyncio.to_thread(self._sync_extract, frame)

    def _load(self) -> None:
        ok = _patch_rapidocr_dml()
        from rapidocr_onnxruntime import RapidOCR
        self._ocr = RapidOCR()
        logger.info(
            "[RapidOCR] loaded (lang=%s, dml=%s)", self._lang, ok,
        )

    def _sync_extract(self, frame: np.ndarray) -> list[dict]:
        if frame is None or frame.size == 0 or min(frame.shape[:2]) < 10:
            return []

        h, w = frame.shape[:2]
        # RapidOCR 1.x __call__ 返回 (result, elapse_list)；
        # result 每项 = [box(4点), text, score]。以 rapid_ocr_api.py 实际为准。
        result, _ = self._ocr(
            frame,
            use_det=True,
            use_cls=self._use_angle_cls,
            use_rec=True,
        )

        rows: list[dict] = []
        if not result:
            return rows
        for item in result:
            box, text, score = item[0], item[1], item[2]
            text = (text or "").strip()
            conf = float(score or 0.0)
            if not text or conf < self._conf_thresh:
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            rows.append({
                "text": text,
                "bbox": {
                    "x1": max(0.0, min(1.0, float(min(xs)) / w)),
                    "y1": max(0.0, min(1.0, float(min(ys)) / h)),
                    "x2": max(0.0, min(1.0, float(max(xs)) / w)),
                    "y2": max(0.0, min(1.0, float(max(ys)) / h)),
                },
                "confidence": conf,
            })
        return rows
```

> 施工时先 `grep -n "def __call__" .venv/Lib/site-packages/rapidocr_onnxruntime/rapid_ocr_api.py` 核对返回值结构；若 `__call__` 返回的是对象（OCRResult）而非 `(list, elapse)`，按实际字段改 `_sync_extract` 的取值方式（思路不变：`box/text/score` → 归一化 bbox）。

### 步骤 3：注册后端 `plugins/factory.py`

在 `_MODULE_OVERRIDES` 加一行（与 easyocr 并列）：

```python
    ("ocr", "easyocr"): "easyocr",
    ("ocr", "rapidocr"): "rapidocr",
```

在 `_CLASS_OVERRIDES` 加一行：

```python
    ("ocr", "easyocr"): "EasyOCRExtractor",
    ("ocr", "rapidocr"): "RapidOCRExtractor",
```

> 必须加 `_CLASS_OVERRIDES`：`IMPL_CLASS_MAP["ocr"]` 默认是 `PaddleOCRExtractor`，不加会在 `rapidocr.py` 里找错类。

### 步骤 4：切换 backend

- `config/config.yaml`（机器相关，gitignored）：

```yaml
  ocr:
    backend: "rapidocr"
    params:
      lang: "ch"
      conf_thresh: 0.5
      sample_fps: 1.0
      max_width: null
      scale: 1.0
```

- 同步更新模板 `config/config.yaml.example` 里 `ocr:` 段注释与默认值（backend 示例改为 `"rapidocr"`，说明走 DirectML、无需 paddle）。

### 步骤 5（可选，精度再上一档）：PP-OCRv3 → v4 模型

PP-OCRv3 已满足门槛则跳过。要更准：从 PaddleOCR 官方 release 下载 `ch_PP-OCRv4_det_infer.onnx` / `ch_PP-OCRv4_rec_infer.onnx`，覆盖到 `site-packages/rapidocr_onnxruntime/models/`（或复制到项目固定路径并在插件里显式传 `det_model_path`/`rec_model_path`）。走代理下载（GitHub 直连会超时）。

---

## 3. 验收方案

### 验收 A — 环境/EP（步骤 1 后立即做）
- `ort.get_available_providers()` 含 `DmlExecutionProvider`。
- 无 `WinError 1114`、无 CUDA 相关报错。

### 验收 B — 单帧单元（先于全链路）
用测试视频抽一帧，直接调插件：

```bash
cd /d/zhiying
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
import asyncio, time, numpy as np
from plugins.ocr.rapidocr import RapidOCRExtractor
from utils.video_util import stream_frames

ocr = RapidOCRExtractor()
async def m():
    frames = []
    async for f in stream_frames('C:/Users/PC/Desktop/test/ocr2.mp4', fps=1.0, use_nvdec=True):
        frames.append(f)
    await ocr.extract(frames[0])  # 预热
    t0 = time.perf_counter()
    n = 0
    for f in frames:
        r = await ocr.extract(f)
        n += 1
        print('--- frame', n, '---')
        for line in r:
            print(f'{line[\"confidence\"]:.2f} {line[\"text\"]}')
    dt = (time.perf_counter() - t0) / max(n, 1) * 1000
    print(f'AVG {dt:.1f} ms/frame')
asyncio.run(m())
"
```

通过标准：
- **速度**：`AVG ≤ 400 ms/frame`（预热后均值，含 det+rec+cls）。
- **精度**：对照复盘文档里 EasyOCR 的错误，本方案必须纠正——例如「黄紫妍」不得再出「黄綮妍」、「明天会不会有人请假过情人节啊」不得再错、「运维部管培生」不得再成「苣墙生」。关键人名/公司全称/原话需逐字正确。

### 验收 C — 全链路落库 + 搜索
对 `ocr2.mp4` 走完整管道（OCR 独立模式），确认：
- `ocr_detections` 表有干净记录、`video_id`/`timestamp_sec`/`text`/`bbox`/`confidence` 正确、FK 级联删除正常。
- 第 8 路 `ocr_text_search` 命中，`/videos/{id}/ocr/data` 返回画面文字清单，桌面端「文字」tab 显示正常。

### 验收 D — 回归（不破坏现有功能）
- `import torch` + `torch.cuda.is_available()` 仍 True，embedder(2b) 正常编码。
- 人脸（insightface）/ 车牌（hyperlpr）仍走各自 EP，正常出结果（不被 DML 补丁影响）。
- 其余 7 路搜索 / 图搜不受影响。
- `backend` 切回 `"easyocr"`（或 `null`）时行为与改前一致（回滚验证）。

### 验收 E — 长稳/并发
- 连续跑 ≥ 2 条视频，无显存 OOM、无 DML 首帧编译后性能衰减异常、事件循环无阻塞（OCR 全程 `to_thread`）。

---

## 4. 回滚

- 依赖回滚：`pip install onnxruntime-gpu==1.20.0`（或重装原两个包）。
- 代码回滚：`config.yaml` 把 `backend` 改回 `"easyocr"`；`rapidocr.py` 与 factory 两行留着不影响（未被引用即不加载）。
- 数据无需回滚：表结构未变。

---

## 5. 风险与注意事项

1. **DirectML 处于 sustained engineering**：官方新特性已转 WinML，但继续维护推理。PP-OCRv3 全 conv/attention、无 GridSample/DeformConv 等 DML 不支持算子，无碍。
2. **首帧 kernel 编译有一次性开销**：测速必须预热后取均值，别拿首帧判生死。
3. **RapidOCR 返回结构以源码为准**：本方案按 1.x `(result, elapse)` 假设，施工第 2 步先核对。
4. **不要顺手卸载 paddle**：`plugins/plate/paddle_plate.py` 备用后端仍 import paddleocr，卸载会破坏它（默认 plate=hyperlpr 不受影响，但保守起见本次不动）。
5. **本次涉及后端改动**：定版验收通过后，按 CLAUDE.md 走 `./bump` 发版（后端 + `frontend-shared/` 变更必须 bump；若只动 `frontend-desktop/` 则不需要）。
6. **依赖残留清理**（easyocr / paddle 全家桶）放到定版确认后再单独评估，不混进本次施工。

---

## 6. 交付物清单

> **定版偏差（2026-08-19 施工时）**：步骤 1 原定「卸载全局 onnxruntime/gpu，换 onnxruntime-directml」被否决——本机验证 hyperlpr 车牌（显式检查 CUDA EP）与 insightface 人脸（FaceAnalysis ctx_id=0）依赖全局 onnxruntime 的 CUDA EP，全局替换会静默降 CPU（验收 D 测不出）。且 onnxruntime 与 onnxruntime-directml 共用 `import onnxruntime` 名，进程内只有一份 sys.modules，无法进程内隔离。定版改为：**全局保留 onnxruntime-gpu（人脸/车牌 CUDA 不动）；onnxruntime-directml==1.24.4 装进独立 `vendor/ort_dml`，RapidOCR 走独立子进程（`plugins/ocr/rapidocr_worker.py`）预载 DML**。子进程隔离既满足 DML，又零影响人脸/车牌。

- [x] `plugins/ocr/rapidocr_worker.py`（新增，独立 DML 子进程 worker：vendor/ort_dml 前置 + RapidOCR + stdin/stdout pickle 单帧协议）
- [x] `plugins/ocr/rapidocr.py`（新增，BaseOCR 子进程桥接，runner 零改动）
- [x] `plugins/factory.py`（注册 `("ocr","rapidocr")`；**已移除 easyocr** 两行注册）
- [x] `config/config.yaml`（backend=rapidocr；机器相关，gitignored）
- [x] `config/config.yaml.example`（模板同步，含 vendor/ort_dml 依赖说明；**已移除 easyocr** 备注）
- [x] 依赖：`rapidocr-onnxruntime` **加入 `requirements.txt`**；onnxruntime-directml==1.24.4 → `vendor/ort_dml`（走代理 10.0.0.183:7897，`/vendor/` gitignored 不提交；全局 onnxruntime-gpu 未动）
- [x] **清理**：移除 `plugins/ocr/easyocr.py`（精度弱的验证性后端，OCR 已定版 rapidocr；回滚改 `backend: null` 禁用）。paddle 全家桶保留（`paddle_plate.py` 车牌备选依赖）
- [x] **安全**：OCR 子进程桥无命令/pickle 注入面（参数硬编码非用户可控、无 shell、pickle 仅走受信内部管道）；无新增安全漏洞。已知边界：DML 子进程不持 gpu_lock（跨进程拿不到）、worker `stderr` 丢弃致调试困难（非安全）
- [x] 验收：DML provider 存在（worker 内）；AVG **164–183 ms/frame**（≤400ms 达标）；商用纠错样本：**「黄紫妍」正确（非黄綮妍）、「明天会不会有人请假过情人节啊」逐字正确**；主进程 onnxruntime 1.20.0 CUDA/TensorRT/CPU providers 原样、torch cu130 cuda_available=True（人脸/车牌零影响）；`tests/test_ocr_search.py` 8 通过（含去重/顺序/固定文字/模糊合并）
- [ ] 验收 C 全链路落库 + 第 8 路检索 + 桌面前端「文字」tab（管道/检索/前端代码零改动，建议在你正常环境下跑一条视频全链路确认）
- [ ] （定版后）`./bump` 发版（后端 + `frontend-shared/` 变更；本次仅触后端 + 文档，需 bump）

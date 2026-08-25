"""
plugins/ocr/rapidocr.py
═══════════════════════════════════════════════════════════
OCR 画面文字提取 — RapidOCR (PP-OCRv3 ONNX) + onnxruntime DirectML EP。

v0.34 定版选型：PaddleOCR GPU(DLL 死路)/EasyOCR(精度弱) 均不达生产级。
改用 RapidOCR 的 PP-OCRv3 det+rec+cls（中文精度第一梯队），推理走 DirectML EP
（DirectX 12，不依赖 CUDA，与 torch cu130 零冲突）。

关键架构决策——子进程隔离：
  onnxruntime 与 onnxruntime-directml 共用同一个 `import onnxruntime` 导入名，
  Python 进程内只有一个 sys.modules['onnxruntime']，谁先导入谁独占。主进程的
  人脸(insightface)/车牌(hyperlpr) 依赖全局 onnxruntime 的 CUDA EP，必须保留
  onnxruntime-gpu。因此本插件把 RapidOCR 放进独立子进程（rapidocr_worker.py），
  worker 启动时把 vendor/ort_dml 前置进 sys.path，先于 site-packages import 到
  DML 版 onnxruntime —— 人脸/车牌 的 CUDA EP 完全不受影响。

基类接口 async extract(frame) → [{text,bbox,confidence}] 与 runner 零改动。
"""

import asyncio
import logging
import os
import pickle
import struct
import subprocess
import sys
from pathlib import Path

from core.interfaces import BaseOCR

logger = logging.getLogger(__name__)

# 封装模式（PyInstaller 字节码包）下 __file__ 指向 _internal/backend_pyc，
# 项目根经 backend_launcher 注入 ZHIYING_PROJECT_ROOT（源码模式为空 → __file__ 推导）。
_PACKAGED_ROOT = os.environ.get("ZHIYING_PROJECT_ROOT")
_PROJECT_ROOT = Path(_PACKAGED_ROOT) if _PACKAGED_ROOT else Path(__file__).resolve().parent.parent.parent
# build_backend_pyc 把 .py 源码删成 .pyc：子进程入口脚本需兼容两种形态（Python 可直接执行 legacy .pyc）。
_WORKER_SCRIPT = Path(__file__).resolve().parent / "rapidocr_worker.py"
if not _WORKER_SCRIPT.is_file():
    _pyc = _WORKER_SCRIPT.with_suffix(".pyc")
    if _pyc.is_file():
        _WORKER_SCRIPT = _pyc


class RapidOCRExtractor(BaseOCR):
    """RapidOCR 画面文字提取 — 经独立 DML 子进程桥接。

    参数从 config.yaml plugins.ocr.params 传入（可被系统设置页 pipeline.ocr
    运行时覆盖）:
      - lang: 识别语言，仅 "ch"（RapidOCR 随包模型为中文 PP-OCRv3）
      - conf_thresh: 文字行置信度门槛
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
        self._conf_thresh = float(conf_thresh or 0.5)
        self._use_angle_cls = bool(use_angle_cls)
        self._proc: subprocess.Popen | None = None

    async def extract(self, frame) -> list[dict]:
        """对单帧 OCR → [{text,bbox,confidence}]。worker 未起则先启动。"""
        if frame is None or frame.size == 0 or min(frame.shape[:2]) < 10:
            return []
        if self._proc is None:
            await asyncio.to_thread(self._start_worker)
        return await asyncio.to_thread(self._request, frame)

    # ── 内部 ──

    def _start_worker(self) -> None:
        """启动 DML 子进程 worker，读启动握手确认，失败则抛错走 runner 容错。"""
        proc = subprocess.Popen(
            [sys.executable, "-u", str(_WORKER_SCRIPT),
             "--conf-thresh", str(self._conf_thresh),
             "--use-angle-cls", "1" if self._use_angle_cls else "0"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            handshake = self._read_reply(proc)
        except Exception:
            proc.kill()
            raise
        self._proc = proc
        dml = handshake.get("dml") if isinstance(handshake, dict) else None
        logger.info(
            "[RapidOCR] worker started (pid=%s, lang=%s, dml=%s, vendor=%s)",
            proc.pid, self._lang, dml, _PROJECT_ROOT / "vendor" / "ort_dml",
        )

    def _request(self, frame) -> list[dict]:
        if self._proc is None or self._proc.poll() is not None:
            self._start_worker()
        try:
            self._write(self._proc, frame)
            reply = self._read_reply(self._proc)
        except (BrokenPipeError, EOFError, ConnectionResetError, ValueError):
            # worker 异常退出 → 重启一次再试，仍挂则抛错
            logger.warning("[RapidOCR] worker died, respawning")
            self._proc = None
            self._start_worker()
            self._write(self._proc, frame)
            reply = self._read_reply(self._proc)
        if isinstance(reply, dict) and "error" in reply:
            raise RuntimeError(reply["error"])
        return reply or []

    @staticmethod
    def _write(proc, obj) -> None:
        data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
        proc.stdin.write(struct.pack(">I", len(data)))
        proc.stdin.write(data)
        proc.stdin.flush()

    @staticmethod
    def _read_reply(proc):
        n = proc.stdout.read(4)
        if not n or len(n) < 4:
            raise EOFError("worker closed unexpectedly")
        (size,) = struct.unpack(">I", n)
        payload = proc.stdout.read(size)
        if payload is None or len(payload) < size:
            raise EOFError("worker closed mid-reply")
        return pickle.loads(payload)

    def __del__(self):
        try:
            if self._proc and self._proc.poll() is None:
                self._proc.stdin.close()
                self._proc.terminate()
        except Exception:
            pass

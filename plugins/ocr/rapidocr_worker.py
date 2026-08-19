"""
plugins/ocr/rapidocr_worker.py
═══════════════════════════════════════════════════════════
RapidOCR (PP-OCRv3 ONNX) 子进程 worker — 通过 onnxruntime DirectML EP 推理。

背景：onnxruntime 与 onnxruntime-directml 共用同一个 `import onnxruntime`
导入名，Python 进程内只有一个 sys.modules['onnxruntime']，谁先导入谁独占。
主进程的人脸(insightface)/车牌(hyperlpr)依赖 CUDA EP，必须保留全局
onnxruntime-gpu；故 OCR 单独放一个子进程，startup 时把独立 vendor 目录
(vendor/ort_dml) 前置进 sys.path，先于 site-packages import 到 DML 版。

本文件以独立进程运行（主进程 subprocess 拉起），不作为插件导入。
协议：stdin/stdout 长度前缀(4 字节大端) + pickle。
  请求  = pickle.dumps(frame_ndarray)
  响应  = pickle.dumps(rows)               # [{text,bbox{x1,y1,x2,y2},confidence}]
        or pickle.dumps({"error": str})    # 该帧失败
"""

import pickle
import struct
import sys


def _bootstrap() -> bool:
    """把 vendored DML onnxruntime 前置到 sys.path（须早于一切 onnxruntime import）。

    返回是否成功定位到 vendor 目录并准备就绪（DML 可用性由后续 ORT 探测决定）。
    """
    from pathlib import Path
    project_root = Path(__file__).resolve().parent.parent.parent
    ort_dml = project_root / "vendor" / "ort_dml"
    if not ort_dml.is_dir():
        return False
    sys.path.insert(0, str(ort_dml))
    return True


def _patch_rapidocr_dml() -> bool:
    """让 RapidOCR 的 ONNX 会话优先走 DirectML EP，CPU 兜底。

    rapidocr_onnxruntime.utils.OrtInferSession 只认识 CUDA/CPU EP；
    本补丁改写其 __init__，在 DML 可用时 DML 优先。只打 RapidOCR 自己的
    OrtInferSession，不碰全局 onnxruntime.InferenceSession —— 本进程本来就是
    DML 隔离岛，其它调用方（若有）也会落到 DML/CPU。幂等。DML 不可用返回 False，
    让 RapidOCR 自然回落 CPU。
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
        return True

    def _patched(self, config):
        sess_opt = SessionOptions()
        sess_opt.log_severity_level = 4
        sess_opt.enable_cpu_mem_arena = False
        sess_opt.graph_optimization_level = GraphOptimizationLevel.ORT_ENABLE_ALL
        self._verify_model(config["model_path"])
        self.session = InferenceSession(
            config["model_path"],
            sess_options=sess_opt,
            providers=[("DmlExecutionProvider", {}),
                       ("CPUExecutionProvider",
                        {"arena_extend_strategy": "kSameAsRequested"})],
        )

    _patched._zhiying_dml = True
    rapid_utils.OrtInferSession.__init__ = _patched
    return True


def main() -> int:
    _bootstrap()  # vendor/ort_dml 前置 → 本进程 import 到 DML onnxruntime

    import argparse
    import logging
    logging.getLogger("rapidocr_onnxruntime").setLevel(logging.ERROR)

    parser = argparse.ArgumentParser()
    parser.add_argument("--conf-thresh", type=float, default=0.5)
    parser.add_argument("--use-angle-cls", type=int, default=1)
    args = parser.parse_args()

    ok = _patch_rapidocr_dml()

    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    use_cls = bool(args.use_angle_cls)

    send = sys.stdout.buffer.write
    flush = sys.stdout.buffer.flush
    recv = sys.stdin.buffer.read


    def _read_exact(n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf


    def _reply(obj) -> None:
        data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
        send(struct.pack(">I", len(data)))
        send(data)
        flush()


    # 通知父进程启动完成（含 DML 是否命中），父进程在首帧前读一次
    _reply({"ready": True, "dml": ok})

    while True:
        hdr = _read_exact(4)
        if hdr is None:
            break  # 父进程关闭
        (n,) = struct.unpack(">I", hdr)
        payload = _read_exact(n)
        if payload is None:
            break
        try:
            frame = pickle.loads(payload)
            rows = _sync_extract(ocr, frame, args.conf_thresh, use_cls)
            _reply(rows)
        except Exception as e:  # 单帧失败回错误，父进程容错 & 计数器
            _reply({"error": str(e)})

    return 0


def _sync_extract(ocr, frame, conf_thresh: float, use_cls: bool) -> list[dict]:
    import numpy as np
    if frame is None or frame.size == 0 or min(frame.shape[:2]) < 10:
        return []
    h, w = frame.shape[:2]
    result, _ = ocr(
        frame,
        use_det=True,
        use_cls=use_cls,
        use_rec=True,
    )
    rows: list[dict] = []
    if not result:
        return rows
    for item in result:
        box, text, score = item[0], item[1], item[2]
        text = (text or "").strip()
        conf = float(score or 0.0)
        if not text or conf < conf_thresh:
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


if __name__ == "__main__":
    raise SystemExit(main())

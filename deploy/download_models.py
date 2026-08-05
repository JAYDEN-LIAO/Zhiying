"""Download and verify the models required for a Zhiying Windows deployment.

Components (each skips when already complete, retries on failure):
  embedding    Qwen3-VL-Embedding-8B  (ModelScope → models/Qwen/...)
  yolo         yolo26s.pt              (Ultralytics assets → models/)
  face         InsightFace buffalo_l    (auto-download → ~/.insightface/models/buffalo_l)
  plate        HyperLPR3 ONNX pack      (auto-download → ~/.hyperlpr3/<version>/onnx)
  segmenter    TransNetV2 weights       (bundled inside transnetv2-pytorch pip package)

Design goals:
  - Partial downloads are kept so a later run resumes them (embedding / yolo).
  - `--verify-only` does not download anything; exits 0 if all requested
    components are present, 2 otherwise.
  - Library-managed models (face / plate) are warmed up through their own
    download paths, so their cache layout is never re-implemented here.

This intentionally does NOT download the local visual caption model
(Qwen3-VL-8B-Instruct), any summarizer weights, or a speech transcription
model — the deployment uses the vlm_llm API summary mode, and the transcriber
is a config-disabled opt-in plugin that is not part of the deployable feature
set.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen


EMBEDDING_MODEL_ID = "Qwen/Qwen3-VL-Embedding-8B"
YOLO_URL = "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26s.pt"
# BoT-SORT with_reid 外观模型（ultralytics 8.4.115 的 "auto" 仍会运行时下载，改为本地预置）
REID_URL = "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n-cls.pt"

# HyperLPR3 模型版本目录（与 hyperlpr3.config.settings._MODEL_VERSION_ 对齐）
HYPERLPR_VERSION = "20230229"
HYPERLPR_ONNX = {
    "y5fu_320x_sim.onnx",
    "y5fu_640x_sim.onnx",
    "rpv3_mdict_160_r3.onnx",
    "litemodel_cls_96x_r1.onnx",
}


# ════════════════════════════════════════════════════════════════
# 校验函数 — 返回该组件是否已就绪
# ════════════════════════════════════════════════════════════════

def embedding_complete(path: Path) -> bool:
    config = path / "config.json"
    if not config.is_file():
        return False

    index_path = path / "model.safetensors.index.json"
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            required = set(index.get("weight_map", {}).values())
            return bool(required) and all((path / name).is_file() for name in required)
        except (OSError, json.JSONDecodeError, TypeError):
            return False

    return any(path.glob("*.safetensors")) or any(path.glob("*.bin"))


def yolo_complete(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 1_000_000
    except OSError:
        return False


def reid_complete(path: Path) -> bool:
    """ReID 外观模型 yolo26n-cls.pt（BoT-SORT with_reid 用，~5.5MB）。"""
    try:
        return path.is_file() and path.stat().st_size > 1_000_000
    except OSError:
        return False


def face_complete() -> bool:
    """InsightFace buffalo_l 已就绪（det_10g + w600k_r50 两个必需 onnx）。"""
    base = Path.home() / ".insightface" / "models" / "buffalo_l"
    return (base / "det_10g.onnx").is_file() and (base / "w600k_r50.onnx").is_file()


def plate_complete() -> bool:
    """HyperLPR3 ONNX 模型包已就绪。"""
    base = Path.home() / ".hyperlpr3" / HYPERLPR_VERSION / "onnx"
    return all((base / name).is_file() for name in HYPERLPR_ONNX)


def segmenter_complete() -> bool:
    """TransNetV2 权重随 pip 包分发，确认包与权重文件在位即可。"""
    try:
        import transnetv2_pytorch as _pkg
        import os as _os
        weight = _os.path.join(_os.path.dirname(_pkg.__file__), "transnetv2-pytorch-weights.pth")
        return _os.path.isfile(weight)
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════
# 下载实现
# ════════════════════════════════════════════════════════════════

def _retry(msg: str, retries: int, fn, *args, **kwargs):
    """带指数退避的重试包装。已保留部分文件供续传。"""
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            print(f"[download] {msg} (attempt {attempt}/{retries})")
            fn(*args, **kwargs)
            return
        except Exception as exc:
            last_error = exc
            print(f"[warn] {msg} failed: {exc}", file=sys.stderr)
            if attempt < retries:
                time.sleep(min(10 * attempt, 30))
    raise RuntimeError(f"{msg} failed after {retries} attempts") from last_error


def download_embedding(target: Path, model_id: str, retries: int) -> None:
    if embedding_complete(target):
        print(f"[skip] Embedding model already complete: {target}")
        return
    target.mkdir(parents=True, exist_ok=True)

    def _do():
        from modelscope import snapshot_download
        snapshot_download(model_id, repo_type="model", local_dir=str(target))
        if not embedding_complete(target):
            raise RuntimeError("download finished but model files are incomplete")

    _retry(f"{model_id}", retries, _do)
    print(f"[ok] Embedding model verified: {target}")


def download_yolo(url: str, target: Path, retries: int) -> None:
    if yolo_complete(target):
        print(f"[skip] YOLO model already complete: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)

    def _do():
        _download_file_resumable(url, target)

    _retry("YOLO yolo26s.pt", retries, _do)
    print(f"[ok] YOLO model verified: {target}")


def download_reid(url: str, target: Path, retries: int) -> None:
    if reid_complete(target):
        print(f"[skip] ReID model already complete: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)

    def _do():
        _download_file_resumable(url, target)

    _retry("ReID yolo26n-cls.pt", retries, _do)
    print(f"[ok] ReID model verified: {target}")


def _download_file_resumable(url: str, target: Path) -> None:
    """单文件断点续传下载（.part → 原子 rename）。"""
    partial = target.with_name(target.name + ".part")
    start = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "zhiying-windows-installer/1.0"}
    if start:
        headers["Range"] = f"bytes={start}-"

    with urlopen(Request(url, headers=headers), timeout=60) as response:
        status = getattr(response, "status", response.getcode())
        if start and status != 206:
            # Server ignored Range; restart safely instead of corrupting the file.
            start = 0
            partial.unlink(missing_ok=True)
        total = response.headers.get("Content-Length")
        total_bytes = (int(total) + start) if total else None
        mode = "ab" if start else "wb"
        downloaded = start
        last_report = -1
        with partial.open(mode) as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if total_bytes:
                    percent = int(downloaded * 100 / total_bytes)
                    if percent != last_report:
                        print(f"\r[progress] {target.name} {percent:3d}%", end="", flush=True)
                        last_report = percent
                else:
                    print(f"\r[progress] {target.name} {downloaded / 1024 / 1024:.1f} MiB", end="", flush=True)
        print()

    if not yolo_complete(partial):
        raise RuntimeError("download finished but YOLO file is incomplete")
    os.replace(partial, target)


def download_face(retries: int) -> None:
    """预热 InsightFace buffalo_l（CPU 加载，触发自带下载）。"""
    if face_complete():
        print("[skip] InsightFace buffalo_l already complete")
        return

    def _do():
        from insightface.app import FaceAnalysis
        app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"])
        app.prepare(ctx_id=-1)  # -1 = CPU，仅用于触发下载与加载验证
        del app
        if not face_complete():
            raise RuntimeError("download finished but buffalo_l files are incomplete")

    _retry("InsightFace buffalo_l", retries, _do)
    print("[ok] InsightFace buffalo_l verified")


def download_plate(retries: int) -> None:
    """预热 HyperLPR3：直接调用其 initialization() 下载并解压模型包。"""
    if plate_complete():
        print("[skip] HyperLPR3 models already complete")
        return

    def _do():
        from hyperlpr3.config.configuration import initialization
        initialization()
        if not plate_complete():
            raise RuntimeError("download finished but HyperLPR3 models are incomplete")

    _retry("HyperLPR3 ONNX pack", retries, _do)
    print("[ok] HyperLPR3 models verified")


# ════════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════════

def _resolve_components(choices: list[str]) -> set[str]:
    all_comp = {"embedding", "yolo", "reid", "face", "plate", "segmenter"}
    result: set[str] = set()
    for c in choices:
        if c == "all":
            result |= all_comp
        elif c in all_comp:
            result.add(c)
        else:
            raise SystemExit(f"unknown component: {c}")
    return result


def _verify_all(root: Path, components: set[str]) -> bool:
    checks = {
        "embedding": lambda: embedding_complete(root / "Qwen" / "Qwen3-VL-Embedding-8B"),
        "yolo": lambda: yolo_complete(root / "yolo26s.pt"),
        "reid": lambda: reid_complete(root / "yolo26n-cls.pt"),
        "face": face_complete,
        "plate": plate_complete,
        "segmenter": segmenter_complete,
    }
    labels = {
        "embedding": "embedding (Qwen3-VL-Embedding-8B)",
        "yolo": "yolo (yolo26s.pt)",
        "reid": "reid (yolo26n-cls.pt)",
        "face": "face (InsightFace buffalo_l)",
        "plate": "plate (HyperLPR3)",
        "segmenter": "segmenter (TransNetV2)",
    }
    ok = True
    for comp in ("embedding", "yolo", "reid", "face", "plate", "segmenter"):
        if comp not in components:
            continue
        result = checks[comp]()
        print(f"{labels[comp]}: {'OK' if result else 'MISSING/INCOMPLETE'}")
        ok = ok and result
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--component", action="append", default=[],
        choices=["all", "embedding", "yolo", "reid", "face", "plate", "segmenter"],
        help="要准备/校验的组件；可多次传，'all' 表示全部",
    )
    parser.add_argument("--model-root", type=Path, default=Path("models"))
    parser.add_argument("--embedding-id", default=EMBEDDING_MODEL_ID)
    parser.add_argument("--yolo-url", default=YOLO_URL)
    parser.add_argument("--reid-url", default=REID_URL)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    if args.retries < 1:
        parser.error("--retries must be at least 1")

    components = _resolve_components(args.component or ["all"])
    root = args.model_root.resolve()

    if args.verify_only:
        return 0 if _verify_all(root, components) else 2

    if "embedding" in components:
        download_embedding(root / "Qwen" / "Qwen3-VL-Embedding-8B", args.embedding_id, args.retries)
    if "yolo" in components:
        download_yolo(args.yolo_url, root / "yolo26s.pt", args.retries)
    if "reid" in components:
        download_reid(args.reid_url, root / "yolo26n-cls.pt", args.retries)
    if "face" in components:
        download_face(args.retries)
    if "plate" in components:
        download_plate(args.retries)
    if "segmenter" in components:
        # 权重随 pip 包分发，只校验，不下载
        if segmenter_complete():
            print("[ok] segmenter (TransNetV2) bundled with package")
        else:
            print("[error] segmenter (TransNetV2) weights missing — reinstall transnetv2-pytorch", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

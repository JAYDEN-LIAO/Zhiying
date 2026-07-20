"""Automated check: detection module imports + schema validation."""
import sys

print("=== 1. Import Chain ===")

from plugins.detector.yolo import YoloDetector
print("  ✓ YoloDetector")

from pipeline.runners.detection import DetectionRunner
print("  ✓ DetectionRunner")

from pipeline.operations import ALL_OPERATIONS
print("  ✓ ALL_OPERATIONS")

from core.models import FrameDetection, Track, Video
print("  ✓ FrameDetection + Track + Video")

from core.repository import (
    bulk_insert_frame_detections,
    bulk_insert_tracks,
)
print("  ✓ bulk_insert_*")

from api.detection_routes import router
print("  ✓ detection_routes router")

from api.router import router as main_router
print("  ✓ main router imports detection_router")

# Operation registration
det_op = [o for o in ALL_OPERATIONS if o.name == "detection"][0]
print(f"  ✓ detection op: depends_on={det_op.depends_on}, weight={det_op.progress_weight}")

# Gate: backend=None → False
v = Video()
cfg_null = {"plugins": {"detector": {"backend": None}}}
assert det_op.gate(v, cfg_null) is False
print("    gate(backend=None) → False ✓")

# Gate: backend=yolo, explicit detection_enabled=False → False
cfg_yolo = {"plugins": {"detector": {"backend": "yolo"}}}
v_off = Video()
v_off.detection_enabled = False
assert det_op.gate(v_off, cfg_yolo) is False
print("    gate(detection_enabled=False, backend=yolo) → False ✓")

# Gate: backend=yolo AND detection_enabled=True → True
v2 = Video()
v2.detection_enabled = True
assert det_op.gate(v2, cfg_yolo) is True
print("    gate(attr=True, backend=yolo) → True ✓")

# Detection route path
routes = [(r.methods, r.path) for r in router.routes]
print(f"  ✓ detection route: {routes}")

print()
print("=== 2. Schema Validation ===")
from core.schemas import PipelineParams, VideoCreate, VideoResponse, VideoListItem

assert PipelineParams().detection_enabled is False
print("  ✓ PipelineParams default=False")

vc = VideoCreate(file_path="/t", file_name="n", file_size=1)
assert vc.detection_enabled is False
print("  ✓ VideoCreate default=False")

# detection ON requires vision ON
try:
    PipelineParams(
        vision_enabled=False, caption_enabled=False, detection_enabled=True,
    )
    print("  ✗ Should have raised ValueError")
    sys.exit(1)
except ValueError as e:
    print(f"  ✓ vision OFF + detection ON → rejected")

# vision ON + detection ON → OK
p = PipelineParams(vision_enabled=True, detection_enabled=True)
assert p.detection_enabled is True
print("  ✓ vision ON + detection ON → accepted")

# detection OFF + vision ON → OK
p2 = PipelineParams(vision_enabled=True, detection_enabled=False)
assert p2.detection_enabled is False
print("  ✓ vision ON + detection OFF → accepted")

assert "detection_enabled" in VideoResponse.model_fields
print("  ✓ VideoResponse has detection_enabled")

assert "detection_enabled" in VideoListItem.model_fields
print("  ✓ VideoListItem has detection_enabled")

print()
print("=== 3. Config ===")
from core.config_loader import load_config

cfg = load_config()
det = cfg.get("plugins", {}).get("detector", {})
assert det.get("backend") == "yolo"
print(f"  ✓ detector.backend = {det.get('backend')}")
print(f"    model={det.get('model')}, conf={det.get('confidence_threshold')}")

print()
print("=== ALL CHECKS PASSED ===")

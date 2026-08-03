"""
pipeline/runners/base.py
═══════════════════════════════════════════════════════════
Runner 基础设施 — OperationRunner ABC + Operation 数据类 + PipelineContext。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.interfaces import VideoContext
from core.status_tracker import StatusTracker
from core.models import Video
from core.prompt_loader import PromptLoader


def effective_summary_mode(video, config) -> str:
    """解析视频实际生效的摘要模式。

    native_video 依赖本地 caption 模型（Qwen3-VL-8B 等）；
    当配置的 captioner 后端是 qwen_api（无本地模型）时，把 native_video
    强制视为 vlm_llm，避免部署机缺模型导致空图 API 调用或管道失败。

    有本地 caption 模型的开发机（captioner.backend != qwen_api）不受影响。
    """
    mode = getattr(video, "summary_mode", "native_video")
    if mode == "native_video":
        captioner_backend = (
            config.get("plugins", {}).get("captioner", {}).get("backend")
        )
        if captioner_backend == "qwen_api":
            return "vlm_llm"
    return mode


@dataclass
class PipelineContext:
    """所有 runner 执行所需的共享状态。

    替代原来散落在 engine.__init__ 和 phase 类构造函数中的碎片化注入。
    """

    video: Video
    ctx: VideoContext
    config: dict
    plugins: dict[str, object]
    tracker: StatusTracker
    db_session_factory: async_sessionmaker[AsyncSession]
    shared_embedder: object | None = None
    prompt_loader: PromptLoader | None = None
    embedder_lock: object | None = None  # asyncio.Lock — 防 embedder 并发竞争
    frame_queue: object | None = None    # asyncio.Queue — keyframes → frame_encode 流式通道
    search_frame_queue: object | None = None  # asyncio.Queue — detection → search_encode 共享流


class OperationRunner(ABC):
    """操作执行器的抽象基类。

    每个 runner 只做"执行"一件事：
    - 不关心编排（由 engine 的 DAG 负责）
    - 不关心门控（由 Operation.gate 负责）
    - 不关心其他 runner（通过 PipelineContext 读取上游产出）

    输入 PipelineContext，输出写入 ctx（VideoContext）或 DB。
    """

    @abstractmethod
    async def run(self, pctx: PipelineContext) -> None:
        """执行此操作的处理逻辑。"""
        ...


@dataclass
class Operation:
    """声明式操作定义 — 一个可编排的处理单元。

    engine 通过 ALL_OPERATIONS 发现系统能力，
    根据 gate 过滤 → 拓扑排序 → 逐批执行。
    """

    name: str                                          # 唯一标识，如 "segmentation"
    runner: OperationRunner                            # 执行逻辑实例
    depends_on: list[str] = field(default_factory=list) # 依赖的 operation name
    gate: Callable[[Video, dict], bool] = lambda v, cfg: True  # 门控条件
    required_plugins: list[str] = field(default_factory=list)  # 需要的插件类别
    progress_weight: float = 0.05                       # 进度占比权重（全局均匀分配时会重新计算）
    label: str = ""                                     # 前端展示名，如 "场景分割"
    description: str = ""                               # 前端展示描述，如 "镜头边界检测中"

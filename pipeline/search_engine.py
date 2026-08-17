"""
pipeline/search_engine.py
═══════════════════════════════════════════════════════════
统一搜索引擎 — 四路并行召回 + 按 scene 合并 + 精度升级。

召回路径:
  1. frame   — 1fps 帧级向量，精确定位到秒
  2. chunk   — 多帧原生编码，过程语义匹配
  3. text    — caption 文本语义向量
  4. label   — entities JSONB 精确匹配（未来 YOLO 激活）
"""

import asyncio
import logging

from sqlalchemy import literal_column, select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import Scene, FrameEmbedding, Chunk
from core.search import (
    frame_vector_search, chunk_vector_search,
    text_vector_search, track_vector_search,
    plate_text_search,
)

logger = logging.getLogger(__name__)

_PRECISION_ORDER = {"frame": 0, "chunk": 1, "text": 2, "label": 3, "track": 2, "plate": 4}
_CLUSTER_GAP = 4.0  # 帧聚类最大间隔（秒）
_PATH_WEIGHT = {"frame": 1.0, "chunk": 0.7, "text": 0.85, "label": 1.0, "track": 0.9, "plate": 0.95}


class SearchEngine:
    """四路并行召回 + 按 scene 合并 + 精度升级搜索。"""

    def __init__(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        embedder=None,
    ):
        self.db_session_factory = db_session_factory
        self.embedder = embedder

    async def search(
        self,
        query: str | None = None,
        image_vec: list[float] | None = None,
        video_ids: list[str] | None = None,
        search_types: list[str] | None = None,
        top_k: int = 20,
        min_similarity: float = 0.3,
    ) -> list[dict]:
        """四路并行召回 + 按 scene 合并 + 精度升级。

        Args:
            query:        文本查询（与 image_vec 二选一）。
            image_vec:    图像查询向量（与 query 二选一）。
            video_ids:    限定视频范围，None=全库。
            search_types: 启用哪些路径 ["frame","chunk","text","label"]。
            top_k:        最终返回条数。
            min_similarity: 最低相似度阈值。

        Returns:
            统一格式的搜索结果列表，按 similarity 降序。
        """
        if search_types is None:
            search_types = ["frame", "chunk", "text", "label", "track", "plate"]

        # 文本查询 → 向量编码（仅一次，三条路共享）
        vec = image_vec
        needs_vec = any(t in search_types for t in ("frame", "chunk", "text", "track"))
        if query and needs_vec and self.embedder:
            vec = await self.embedder.encode_text(query)

        # ── 多路并行召回 ──
        tasks = []
        if "frame" in search_types and vec is not None:
            tasks.append(self._frame_search(vec, video_ids, top_k * 2))
        if "chunk" in search_types and vec is not None:
            tasks.append(self._chunk_search(vec, video_ids, top_k * 2))
        if "text" in search_types and vec is not None:
            tasks.append(self._text_search(vec, video_ids, top_k * 2))
        if "label" in search_types and query:
            tasks.append(self._label_search(query, video_ids, top_k * 2))
        if "track" in search_types and vec is not None:
            tasks.append(self._track_search(vec, video_ids, top_k * 2))
        if "plate" in search_types and query:
            tasks.append(self._plate_search(query, video_ids, top_k * 2))

        if not tasks:
            return []

        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        ranked_lists = [r for r in results_list if not isinstance(r, Exception) and r]
        if not ranked_lists:
            return []

        # ── 按 scene 合并（帧路在内部用 min_similarity 过滤低分帧）──
        merged = self._merge_results(ranked_lists, min_similarity)

        # ── 补全 scene 信息 ──
        merged = await self._enrich_merged(merged)

        # ── 过滤 + Top-K ──
        filtered = [item for item in merged if item["similarity"] >= min_similarity]
        return filtered[:top_k]

    # ──────────────────────────────────────────────────────
    # 各路召回
    # ──────────────────────────────────────────────────────

    async def _frame_search(
        self,
        vec: list[float],
        video_ids: list[str] | None,
        limit: int,
    ) -> list[dict]:
        """帧级向量召回 — 逐帧编码，精确定位到秒。"""
        async with self.db_session_factory() as session:
            results = await frame_vector_search(
                session, vec, limit=limit, video_ids=video_ids,
            )
        return [self._frame_to_dict(f, sim) for f, sim in results]

    async def _chunk_search(
        self,
        vec: list[float],
        video_ids: list[str] | None,
        limit: int,
    ) -> list[dict]:
        """chunk 窗口召回 — 多帧原生编码，过程语义匹配。"""
        async with self.db_session_factory() as session:
            results = await chunk_vector_search(
                session, vec, limit=limit, video_ids=video_ids,
            )
        return [self._chunk_to_dict(c, sim) for c, sim in results]

    async def _text_search(
        self,
        vec: list[float],
        video_ids: list[str] | None,
        limit: int,
    ) -> list[dict]:
        """文本语义召回 — 文本 vs caption 向量的语义匹配。"""
        async with self.db_session_factory() as session:
            results = await text_vector_search(
                session, vec, limit=limit, video_ids=video_ids,
            )
        return [self._scene_to_dict(s, sim, "text") for s, sim in results]

    async def _track_search(
        self,
        vec: list[float],
        video_ids: list[str] | None,
        limit: int,
    ) -> list[dict]:
        """track 嵌入召回 — encode_text(query) vs crop 跨模态嵌入。"""
        async with self.db_session_factory() as session:
            results = await track_vector_search(
                session, vec, limit=limit, video_ids=video_ids,
            )
            # 批量取 track 生命周期
            track_keys = [(str(r.video_id), r.track_id) for r, _ in results]
            track_map = await _load_track_ranges(session, track_keys)
        return [self._track_to_dict(t, sim, track_map) for t, sim in results]

    @staticmethod
    def _track_to_dict(track_emb, sim: float, track_map: dict | None = None) -> dict:
        key = (str(track_emb.video_id), track_emb.track_id)
        trk = track_map.get(key) if track_map else None
        bbox = track_emb.bbox
        # 构造 track crop 缩略图 URL（利用已有 detection/thumbnail 端点）
        thumb = (
            f"/api/v1/videos/{track_emb.video_id}/detection/thumbnail"
            f"?timestamp={track_emb.timestamp_sec}"
            f"&x1={bbox['x1']}&y1={bbox['y1']}&x2={bbox['x2']}&y2={bbox['y2']}"
        ) if bbox else None
        return {
            "video_id": str(track_emb.video_id),
            "track_id": track_emb.track_id,
            "class_name": track_emb.class_name,
            "display_seq": track_emb.display_seq,
            "scene_index": 0,
            "precise_start": trk["first_seen"] if trk else track_emb.timestamp_sec,
            "precise_end": trk["last_seen"] if trk else None,
            "precision_level": "track",
            "similarity": float(sim),
            "source": "track",
            "bbox": bbox,
            "thumbnail_url": thumb,
        }

    async def _plate_search(
        self,
        query: str,
        video_ids: list[str] | None,
        limit: int,
    ) -> list[dict]:
        """车牌文本搜索 — ILIKE / trigram 相似度匹配，结果含车辆 track 时间段。"""
        async with self.db_session_factory() as session:
            results = await plate_text_search(
                session, query, limit=limit, video_ids=video_ids,
            )
            # 批量取 track 生命周期，车牌定位到车辆 track 的时间段而非单帧
            track_keys = [(str(r.video_id), r.track_id) for r, _ in results]
            track_map = await _load_track_ranges(session, track_keys)
        return [self._plate_to_dict(p, sim, track_map) for p, sim in results]

    @staticmethod
    def _plate_to_dict(plate, sim: float, track_map: dict | None = None) -> dict:
        bbox = plate.bbox
        thumb = (
            f"/api/v1/videos/{plate.video_id}/plate/thumbnail"
            f"?timestamp={plate.timestamp_sec}"
            f"&x1={bbox['x1']}&y1={bbox['y1']}&x2={bbox['x2']}&y2={bbox['y2']}"
        ) if bbox else None
        key = (str(plate.video_id), plate.track_id)
        trk = track_map.get(key) if track_map else None
        return {
            "video_id": str(plate.video_id),
            "track_id": plate.track_id,
            "class_name": plate.class_name,
            "scene_index": 0,
            "precise_start": trk["first_seen"] if trk else plate.timestamp_sec,
            "precise_end": trk["last_seen"] if trk else None,
            "precision_level": "plate",
            "similarity": float(sim),
            "source": "plate",
            "plate_text": plate.plate_text,
            "plate_type": plate.plate_type,
            "char_confidences": plate.char_confidences,
            "bbox": bbox,
            "thumbnail_url": thumb,
        }

    async def _label_search(
        self,
        query: str,
        video_ids: list[str] | None,
        limit: int,
    ) -> list[dict]:
        """JSONB 精确匹配 entities.label（未来 YOLO 激活）。"""
        async with self.db_session_factory() as session:
            stmt = (
                select(Scene)
                .where(Scene.entities.op("@>")(
                    literal_column(f"'[{{\"label\": \"{query}\"}}]'::jsonb")
                ))
                .limit(limit)
            )
            if video_ids is not None:
                stmt = stmt.where(Scene.video_id.in_(video_ids))
            result = await session.execute(stmt)
            scenes = list(result.scalars().all())

        return [self._scene_to_dict(s, 1.0, "label") for s in scenes]

    # ──────────────────────────────────────────────────────
    # 结果融合：帧聚类 + 多路去重
    # ──────────────────────────────────────────────────────

    @staticmethod
    def _merge_results(
        ranked_lists: list[list[dict]],
        min_similarity: float = 0.3,
    ) -> list[dict]:
        """帧结果按时间聚类 + chunk/text 结果去重叠。

        规则：
          1. 帧先筛低分（< min_similarity），再按时间聚类（间隔 ≤ CLUSTER_GAP）
          2. chunk/text 结果若与任一帧簇时间重叠，丢弃
          3. 非重叠的 chunk/text 保留
        """
        frames: list[dict] = []
        tracks: list[dict] = []
        plates: list[dict] = []
        others: list[dict] = []
        for ranked in ranked_lists:
            for item in ranked:
                if item.get("source") == "frame":
                    frames.append(item)
                elif item.get("source") == "track":
                    tracks.append(item)
                elif item.get("source") == "plate":
                    plates.append(item)
                else:
                    others.append(item)

        # ── 帧：先过滤低分，再按时间聚类 ──
        clusters: list[dict] = []
        frames = [f for f in frames if f.get("similarity", 0) >= min_similarity]
        if frames:
            frames.sort(key=lambda x: x.get("precise_start", 0))
            cur: dict | None = None
            for fr in frames:
                ts = fr.get("precise_start", 0)
                if cur is None:
                    cur = dict(fr)
                    cur["precise_end"] = ts
                    cur["match_paths"] = ["frame"]
                elif ts - cur["precise_end"] <= _CLUSTER_GAP:
                    cur["precise_end"] = ts
                    if fr.get("similarity", 0) > cur.get("similarity", 0):
                        cur["similarity"] = fr["similarity"]
                else:
                    clusters.append(cur)
                    cur = dict(fr)
                    cur["precise_end"] = ts
                    cur["match_paths"] = ["frame"]
            if cur is not None:
                clusters.append(cur)

        # ── 辅助：判断时间区间是否与某帧簇重叠 ──
        def _overlaps(start: float | None, end: float | None) -> bool:
            if start is None:
                return False
            e = end if end is not None else start
            for c in clusters:
                cs = c.get("precise_start", 0)
                ce = c.get("precise_end", cs)
                if not (e < cs or start > ce):
                    return True
            return False

        # ── Track 独立去重：每个 track 作为一个独立物体，(video_id, track_id) 唯一
        track_map: dict[tuple[str, int], dict] = {}
        for item in tracks:
            key = (item["video_id"], item.get("track_id", 0))
            if key not in track_map or item.get("similarity", 0) > track_map[key].get("similarity", 0):
                track_map[key] = dict(item)
                track_map[key]["match_paths"] = [item.get("source", "track")]

        # ── Plate 独立去重：每块车牌按所属 track 唯一（(video_id, track_id)），
        #    不再挤进 (video_id, scene_index) 的桶（scene_index 对 plate 无意义，会互相覆盖）──
        plate_map: dict[tuple[str, int], dict] = {}
        for item in plates:
            key = (item["video_id"], item.get("track_id", 0))
            if key not in plate_map or item.get("similarity", 0) > plate_map[key].get("similarity", 0):
                plate_map[key] = dict(item)
                plate_map[key]["match_paths"] = [item.get("source", "plate")]

        # ── 非帧结果：去重叠 + 按 scene 合并 ──
        other_map: dict[tuple[str, int], dict] = {}
        for item in others:
            if _overlaps(item.get("precise_start"), item.get("precise_end")):
                continue
            key = (item["video_id"], item["scene_index"])
            if key not in other_map:
                other_map[key] = dict(item)
                other_map[key]["match_paths"] = [item.get("source", "unknown")]
            else:
                ex = other_map[key]
                if item.get("similarity", 0) > ex.get("similarity", 0):
                    ex["similarity"] = item["similarity"]
                src = item.get("source", "unknown")
                if src not in ex.get("match_paths", []):
                    ex.setdefault("match_paths", []).append(src)

        merged = clusters + list(other_map.values()) + list(plate_map.values()) + list(track_map.values())
        # 通用置信度（v0.30）: 校准分数 = 相似度 × 路径权重，作为跨路径统一可排行的置信度。
        # frame 1.0 > text 0.85 > chunk 0.7，确保高精度结果优先；前端据此显示与排序一致的置信度。
        for item in merged:
            item["confidence"] = round(
                item.get("similarity", 0) * _PATH_WEIGHT.get(item.get("source", ""), 1.0), 3,
            )
        merged.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        return merged

    async def _enrich_merged(self, merged: list[dict]) -> list[dict]:
        """为合并后的结果补全 scene 级别信息。"""
        if not merged:
            return merged

        video_ids = list(set(m["video_id"] for m in merged))
        async with self.db_session_factory() as session:
            stmt = select(Scene).where(Scene.video_id.in_(video_ids))
            result = await session.execute(stmt)
            scenes_map = {
                (str(s.video_id), s.scene_index): s
                for s in result.scalars().all()
            }

        for item in merged:
            if item.get("source") == "track":
                continue  # track 自有独立元数据，无需 scene 信息
            key = (item["video_id"], item["scene_index"])
            s = scenes_map.get(key)
            if s:
                item["scene_id"] = s.id
                item["scene_range_start"] = s.start_sec
                item["scene_range_end"] = s.end_sec
                item["caption"] = s.caption
                item["ocr_text"] = s.ocr_text
                item["aligned_transcript"] = s.aligned_transcript

        return merged

    # ═══════════════════════════════════════════════════════════
    # 通用图搜专用路径
    # ═══════════════════════════════════════════════════════════

    async def search_image_only(
        self,
        vec: list[float],
        video_ids: list[str] | None = None,
        search_types: list[str] | None = None,
        top_k: int = 20,
        min_similarity: float = 0.3,
    ) -> list[dict]:
        """图搜专用搜索路径。

        和 search() 的关键区别：
          - 帧结果不做时间聚类，每帧独立返回（精确到秒）
          - 不补充 scene 信息（不调 _enrich_merged）
          - 仅支持 frame + track 两种搜索路径

        Args:
            vec:             来自 encode_image() 的 embedding_profile 维度向量。
            video_ids:       限定视频范围，None=全库。
            search_types:    启用路径 ["frame","track"]，默认全开。
            top_k:           最终返回条数。
            min_similarity:  最低相似度阈值。

        Returns:
            按 similarity 降序排列的结果列表。
        """
        if search_types is None:
            search_types = ["frame", "track"]

        tasks = []
        if "frame" in search_types:
            tasks.append(self._frame_search(vec, video_ids, top_k))
        if "track" in search_types:
            tasks.append(self._track_search(vec, video_ids, top_k))

        if not tasks:
            return []

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        # 帧结果原样保留（不聚类）
        # Track 结果按 (video_id, track_id) 去重，保留最高分
        track_map: dict[tuple[str, int], dict] = {}
        merged: list[dict] = []
        for r in results_list:
            if isinstance(r, Exception) or not r:
                continue
            for item in r:
                if item.get("source") == "track":
                    key = (item["video_id"], item.get("track_id", 0))
                    if key not in track_map or item.get("similarity", 0) > track_map[key].get("similarity", 0):
                        track_map[key] = dict(item)
                        track_map[key]["match_paths"] = [item.get("source", "track")]
                else:
                    merged.append(item)

        merged.extend(track_map.values())

        # 过滤低分 + 通用置信度排序 + Top-K（与 search() 的 confidence 口径一致）
        merged = [m for m in merged if m.get("similarity", 0) >= min_similarity]
        for item in merged:
            item["confidence"] = round(
                item.get("similarity", 0) * _PATH_WEIGHT.get(item.get("source", ""), 1.0), 3,
            )
        merged.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        return merged[:top_k]

    # ──────────────────────────────────────────────────────
    # 格式化
    # ──────────────────────────────────────────────────────

    @staticmethod
    def _frame_to_dict(frame: FrameEmbedding, sim: float) -> dict:
        return {
            "video_id": str(frame.video_id),
            "scene_index": frame.scene_index,
            "precise_start": frame.timestamp_sec,
            "precise_end": None,
            "precision_level": "frame",
            "similarity": float(sim),
            "source": "frame",
            "thumbnail_url": f"/api/v1/videos/{frame.video_id}/thumbnail/{frame.scene_index}",
        }

    @staticmethod
    def _chunk_to_dict(chunk: Chunk, sim: float) -> dict:
        return {
            "video_id": str(chunk.video_id),
            "scene_index": chunk.scene_index,
            "precise_start": chunk.start_sec,
            "precise_end": chunk.end_sec,
            "precision_level": "chunk",
            "similarity": float(sim),
            "source": "chunk",
            "thumbnail_url": f"/api/v1/videos/{chunk.video_id}/thumbnail/{chunk.scene_index}",
        }

    @staticmethod
    def _scene_to_dict(scene: Scene, similarity: float, source: str) -> dict:
        return {
            "scene_id": scene.id,
            "video_id": str(scene.video_id),
            "scene_index": scene.scene_index,
            "scene_range_start": scene.start_sec,
            "scene_range_end": scene.end_sec,
            "precise_start": scene.start_sec,
            "precise_end": scene.end_sec,
            "precision_level": source,
            "caption": scene.caption,
            "ocr_text": scene.ocr_text,
            "aligned_transcript": scene.aligned_transcript,
            "entities": scene.entities or [],
            "similarity": similarity,
            "source": source,
            "thumbnail_url": f"/api/v1/videos/{scene.video_id}/thumbnail/{scene.scene_index}",
        }


async def _load_track_ranges(
    session: AsyncSession,
    keys: list[tuple[str, int]],
) -> dict[tuple[str, int], dict]:
    """批量查询 track 生命周期 (first_seen, last_seen)。"""
    if not keys:
        return {}
    from sqlalchemy import or_
    from core.models import Track

    # 构造 (video_id, track_id) IN 条件
    conditions = [
        (Track.video_id == vid) & (Track.track_id == tid)
        for vid, tid in keys
    ]
    if not conditions:
        return {}

    stmt = select(Track).where(or_(*conditions))
    result = await session.execute(stmt)
    rows = result.scalars().all()

    return {
        (str(r.video_id), r.track_id): {
            "first_seen": r.first_seen, "last_seen": r.last_seen,
        }
        for r in rows
    }

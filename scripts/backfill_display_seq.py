#!/usr/bin/env python3
"""存量回填：为已有视频补 display_seq + track_embeddings 最佳帧 bbox/timestamp。

1. display_seq：每视频 → 按 class_name 分组 → (first_seen, track_id) 排序 → 每类 1..N
   （与 `track_encode._assign_display_seq` 规则一致，写 tracks/frame_detections/track_embeddings）
2. track_embeddings bbox/timestamp：取该 track 在 frame_detections 中置信度最高帧，
   供搜索「物体定位」结果缩略图裁剪。

仅写这两块；**track_id 不动**（保持全局唯一，face/plate/导出/选中态零影响）。
新视频（本修复上线后处理的）已由 persist 自动赋值，脚本只回填旧数据。

用法:
  python scripts/backfill_display_seq.py                 # dry-run 预览
  python scripts/backfill_display_seq.py --apply         # 实际写入
  python scripts/backfill_display_seq.py --video-id <uuid>  # 只处理指定视频
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from core.db import engine  # noqa: E402

_TABLES = ("tracks", "frame_detections", "track_embeddings")


async def _compute_seq(rows) -> dict[int, int]:
    """rows: [(track_id, class_name, first_seen)] → {track_id: display_seq}（类内 1..N）"""
    by_class: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for tid, cls, first in rows:
        by_class[cls].append((tid, first))
    seq: dict[int, int] = {}
    for cls, lst in by_class.items():
        lst.sort(key=lambda x: (x[1], x[0]))  # (first_seen, track_id) 决胜
        for i, (tid, _) in enumerate(lst, 1):
            seq[tid] = i
    return seq


async def backfill_video(conn, video_id, apply: bool) -> int:
    rows = (await conn.execute(text(
        "SELECT track_id, class_name, first_seen FROM tracks WHERE video_id = :vid"
    ), {"vid": video_id})).fetchall()
    if not rows:
        return 0
    seq = await _compute_seq(rows)
    if not apply:
        return len(seq)
    params = [{"s": s, "vid": video_id, "tid": tid} for tid, s in seq.items()]
    for table in _TABLES:
        await conn.execute(text(
            f"UPDATE {table} SET display_seq = :s WHERE video_id = :vid AND track_id = :tid"
        ), params)
    await _backfill_emb_bbox(conn, video_id)
    return len(seq)


async def _backfill_emb_bbox(conn, video_id) -> int:
    """给存量 track_embeddings 补最佳帧 bbox/timestamp（搜索缩略图用）。
    取该 track 在 frame_detections 里置信度最高的帧的 bbox + 时间戳。"""
    r = await conn.execute(text("""
        SELECT te.track_id, fd.bbox, fd.timestamp_sec
        FROM track_embeddings te
        JOIN LATERAL (
            SELECT fd.bbox, fd.timestamp_sec
            FROM frame_detections fd
            WHERE fd.video_id = te.video_id AND fd.track_id = te.track_id
            ORDER BY fd.confidence DESC LIMIT 1
        ) fd ON true
        WHERE te.video_id = :vid AND te.bbox IS NULL
    """), {"vid": video_id})
    n = 0
    for tid, bbox, ts in r.fetchall():
        await conn.execute(text(
            "UPDATE track_embeddings SET bbox = :b, timestamp_sec = :ts"
            " WHERE video_id = :vid AND track_id = :tid"
        ), {"b": bbox, "ts": ts, "vid": video_id, "tid": tid})
        n += 1
    if n:
        print(f"    └ track_embeddings bbox/ts: {n} 条已补")
    return n


async def main(apply: bool, only_video: str | None) -> None:
    async with engine.connect() as conn:
        async with conn.begin():
            if only_video:
                vids: list[tuple] = [(only_video,)]
            else:
                # 只挑 display_seq 仍为 NULL 的存量视频（已赋值的新视频跳过）
                r = await conn.execute(text(
                    "SELECT DISTINCT video_id FROM tracks WHERE display_seq IS NULL ORDER BY video_id"
                ))
                vids = r.fetchall()
            total = 0
            for (vid,) in vids:
                n = await backfill_video(conn, vid, apply)
                if n:
                    total += n
                    print(f"{'[OK ]' if apply else '[DRY]'} {vid}: {n} tracks")
            mode = "已写入" if apply else "dry-run（未写入，加 --apply 生效）"
            print(f"\n完成：{mode}，{len(vids)} 视频，{total} tracks")
    await engine.dispose()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="存量 display_seq 回填")
    p.add_argument("--apply", action="store_true", help="实际写入（默认 dry-run）")
    p.add_argument("--video-id", default=None, help="只处理指定视频 UUID")
    args = p.parse_args()
    asyncio.run(main(args.apply, args.video_id))

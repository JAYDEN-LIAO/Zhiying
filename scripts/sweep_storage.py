#!/usr/bin/env python3
"""
scripts/sweep_storage.py
═══════════════════════════════════════════════════════════
存储卫生清扫 CLI — 离线清理孤儿文件/目录/空组。

无需启动服务，只要 PostgreSQL 可达。复用 core.storage_manager.StorageManager
（与 API POST /maintenance/sweep 同一逻辑）。

用法:
    python scripts/sweep_storage.py                # dry-run，只报告可回收量
    python scripts/sweep_storage.py --apply        # 实际执行删除
    python scripts/sweep_storage.py --json         # 输出机器可读 JSON

安全说明:
  - 默认 dry-run，绝不删除任何文件
  - 判定基于 DB 引用（reuse 共享文件天然安全），缩略图/音频/chunk 目录
    按 videos 表 id 集合判定，PENDING/PROCESSING 视频天然受保护
  - video_dir 文件带 mtime 保护（<10min 新文件跳过，防上传竞态）
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# 保证从任意 CWD 运行都能导入项目模块
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.config_loader import load_config          # noqa: E402
from core.db import AsyncSessionLocal, engine        # noqa: E402
from core.storage_manager import StorageManager      # noqa: E402


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} GB"


def _print_human(report: dict) -> None:
    verb = "可回收（dry-run，未删除）" if report["dry_run"] else "已回收"
    print(f"\n存储清扫报告 — {verb}")
    print(f"{'类别':<24}{'数量':>8}  {'大小':>12}")
    print("-" * 50)
    for cat, info in report["categories"].items():
        print(f"{cat:<24}{info['count']:>8}  {_fmt_size(info['bytes']):>12}")
        for item in info.get("items", [])[:20]:
            print(f"    {item}")
        if len(info.get("items", [])) > 20:
            print(f"    ... 还有 {len(info['items']) - 20} 项")
    print("-" * 50)
    print(f"合计可释放: {_fmt_size(report['total_bytes_reclaimable'])}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Zhiying 存储卫生清扫")
    parser.add_argument(
        "--apply", action="store_true",
        help="实际执行删除（默认 dry-run 只报告）",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="输出机器可读 JSON",
    )
    args = parser.parse_args()

    config = load_config()
    manager = StorageManager(config)

    try:
        async with AsyncSessionLocal() as session:
            report = await manager.sweep(session, dry_run=not args.apply)
    finally:
        await engine.dispose()

    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, default=str, indent=2))
    else:
        _print_human(report)

    return 0


if __name__ == "__main__":
    t0 = time.time()
    exit_code = asyncio.run(main())
    # 完成提示走 stderr，避免污染 --json 模式的 stdout
    print(f"\n完成，耗时 {time.time() - t0:.1f}s", file=sys.stderr)
    sys.exit(exit_code)

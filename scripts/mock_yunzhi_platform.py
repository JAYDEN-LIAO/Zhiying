#!/usr/bin/env python3
"""本地 mock 云智平台回调服务器 — 验证 /internal/yunzhi/jobs 的回调契约。

监听 /progress /complete /fail，把收到的每次 POST 打 stdout（带时间戳），
同时追加到日志文件。用于本地全链路验证 A2 自动化任务（对照 extension-automation-demo）。

用法:
  python scripts/mock_yunzhi_platform.py --port 9000 --log /tmp/mock-yunzhi-callbacks.log
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG: Path | None = None


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"_raw": body}
        entry = {
            "t": time.strftime("%H:%M:%S"),
            "path": self.path,
            "x_yunzhi_job_token": self.headers.get("X-Yunzhi-Job-Token", ""),
            "body": parsed,
        }
        line = json.dumps(entry, ensure_ascii=False)
        print(line, flush=True)
        if LOG is not None:
            with LOG.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"UP"}')
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args) -> None:  # 静默访问日志
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock 云智平台回调服务器")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--log", default="/tmp/mock-yunzhi-callbacks.log")
    args = parser.parse_args()

    global LOG
    LOG = Path(args.log)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Mock 云智平台回调 http://{args.host}:{args.port}  log={args.log}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

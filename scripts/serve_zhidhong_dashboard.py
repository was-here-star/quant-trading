#!/usr/bin/env python3
"""指定红看板本地实时服务：浏览器每次刷新都会更新数据。

用法:
  .venv/bin/python scripts/serve_zhidhong_dashboard.py --open
  浏览器打开 http://127.0.0.1:18765/ 后，按刷新即可自动更新
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "bin" / "python"
if not PY.exists():
    PY = Path(sys.executable)

DESKTOP_HTML = Path.home() / "Desktop" / "指定红看板.html"
CACHE_HTML = ROOT / "data_cache" / "strategy1" / "strategy1_dashboard.html"

_lock = threading.Lock()
_last_refresh_ts = 0.0
_last_html = ""
_min_interval = 45.0


def _run_dashboard(*, force_network: bool) -> str:
    """生成最新看板 HTML。force 或超过间隔则拉网，否则仅重绘。"""
    global _last_refresh_ts, _last_html
    now = time.time()
    with _lock:
        use_cache_only = (
            (not force_network)
            and bool(_last_html)
            and (now - _last_refresh_ts) < _min_interval
        )
        cmd = [str(PY), str(ROOT / "scripts" / "strategy1.py"), "dashboard"]
        if use_cache_only:
            cmd.append("--no-refresh")

        print(f"[serve] running: {' '.join(cmd)}", flush=True)
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        if proc.stdout:
            sys.stdout.write(proc.stdout if proc.stdout.endswith("\n") else proc.stdout + "\n")
            sys.stdout.flush()
        if proc.returncode != 0:
            err = proc.stderr or proc.stdout or "dashboard failed"
            sys.stderr.write(err + ("\n" if not err.endswith("\n") else ""))
            return (
                "<html><body style='background:#0b1020;color:#e6e9f2;font-family:sans-serif;padding:24px'>"
                f"<h1>刷新失败</h1><pre>{err}</pre></body></html>"
            )

        html_path = DESKTOP_HTML if DESKTOP_HTML.exists() else CACHE_HTML
        html = html_path.read_text(encoding="utf-8")
        badge = (
            '<div style="position:fixed;right:16px;bottom:16px;z-index:9999;'
            "padding:8px 12px;border-radius:999px;font:12px/1.4 -apple-system,BlinkMacSystemFont,sans-serif;"
            "background:rgba(54,207,201,.18);color:#36cfc9;border:1px solid rgba(54,207,201,.35);"
            'backdrop-filter:blur(8px);">实时模式 · 刷新本页自动更新'
            '<a href="/?force=1" style="color:#7fb4ff;margin-left:8px;text-decoration:none;">强制拉网</a></div>'
        )
        if "</body>" in html:
            html = html.replace("</body>", badge + "\n</body>")
        if not use_cache_only:
            _last_refresh_ts = time.time()
        _last_html = html
        return html


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[serve] {self.address_string()} - {fmt % args}", flush=True)

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path in ("/ping", "/health"):
            payload = json.dumps({"ok": True, "ts": time.time()}).encode()
            self._send(200, payload, "application/json; charset=utf-8")
            return
        if parsed.path not in ("/", "/index.html", "/dashboard"):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        force = qs.get("force", ["0"])[0] in ("1", "true", "yes")
        # 冷启动必拉网；之后刷新按间隔；force=1 强制拉网
        first = _last_refresh_ts == 0
        html = _run_dashboard(force_network=force or first)
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")


def main() -> int:
    global _min_interval
    ap = argparse.ArgumentParser(description="指定红看板实时服务")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18765)
    ap.add_argument("--min-interval", type=float, default=45.0, help="拉网最短间隔秒")
    ap.add_argument("--open", action="store_true", help="启动后打开浏览器")
    args = ap.parse_args()
    _min_interval = float(args.min_interval)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"指定红看板实时服务: {url}", flush=True)
    print("浏览器刷新本页 = 自动更新；/?force=1 = 强制重新拉网", flush=True)
    if args.open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

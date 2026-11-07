"""管理器桌面外壳：内置 FastAPI 服务 + pywebview 窗口（失败时回退浏览器 App 模式）。"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "data" / "logs" / "manager.log"
PORTS = range(7311, 7341)


def hide_console() -> None:
    """控制台子系统的 exe 启动后立即隐藏控制台窗口。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:  # noqa: BLE001
        pass


def log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def pick_port() -> int:
    for port in PORTS:
        if port_free(port):
            return port
    return 7311


def start_server(port: int):
    import uvicorn

    from server.api import app

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="uvicorn")
    thread.start()
    return server


def wait_ready(url: str, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def open_edge(url: str) -> bool:
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for exe in candidates:
        if Path(exe).exists():
            subprocess.Popen(
                [exe, f"--app={url}", "--window-size=1480,940"],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            return True
    return False


def main() -> None:
    if "--no-background" in sys.argv:
        os.environ["ASTRBOT_MANAGER_NO_BACKGROUND"] = "1"
        log("已禁用后台任务（watchdog / auto-learn）")
    port = pick_port()
    url = f"http://127.0.0.1:{port}"
    log(f"启动服务：{url}")
    start_server(port)
    if not wait_ready(url + "/api/health"):
        log("服务启动超时")
        raise SystemExit(1)

    try:
        import webview

        window = webview.create_window(
            "牧鱼 · AstrBot 多机管理台",
            url,
            width=1480,
            height=940,
            min_size=(1120, 720),
            background_color="#070a10",
            text_select=True,
        )
        log("使用 pywebview 窗口")
        webview.start(debug=False)
        return
    except Exception as exc:  # noqa: BLE001
        log(f"pywebview 不可用：{exc}\n{traceback.format_exc()}")

    if open_edge(url):
        log("回退到 Edge App 模式")
        while True:
            time.sleep(3600)
    else:
        import webbrowser

        webbrowser.open(url)
        log("回退到默认浏览器")


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    hide_console()
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        log(traceback.format_exc())
        raise

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
import json
from pathlib import Path

if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "data" / "logs" / "manager.log"
PORTS = range(7311, 7341)
TITLE = "牧鱼 · AstrBot 多机管理台"
SERVER_LOG_MAX = 5 * 1024 * 1024


def redirect_stdio() -> None:
    """把 stdout/stderr 落到滚动文件，避免隐藏控制台写满后阻塞事件循环。"""
    log_dir = ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "server.log"
    try:
        if path.exists() and path.stat().st_size > SERVER_LOG_MAX:
            backup = log_dir / "server.1.log"
            backup.unlink(missing_ok=True)
            path.replace(backup)
    except OSError:
        pass
    stream = open(
        path, "a", encoding="utf-8", buffering=1, errors="replace"
    )
    sys.stdout = stream
    sys.stderr = stream


def runtime_data_dir() -> Path:
    """管理器运行态文件的固定位置；各插件按同一路径发现实际端口。"""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "AstrBot舰队管理器" / "data"


def write_runtime(port: int) -> Path:
    """写入当前管理器端口，供 daily_mood / human_mode / presence / inbox 发现。"""
    path = runtime_data_dir() / "manager_runtime.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "port": int(port),
        "url": f"http://127.0.0.1:{int(port)}",
        "pid": os.getpid(),
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)
    return path


def window_handle(window=None) -> int:
    """优先取 pywebview 窗体的顶层 HWND，取不到时按窗口标题查找。"""
    if sys.platform != "win32":
        return 0
    try:
        import ctypes

        user32 = ctypes.windll.user32
        native = getattr(window, "native", None) if window is not None else None
        if native is not None:
            handle = getattr(native, "Handle", None)
            value = int(handle.ToInt32()) if handle is not None else 0
            if value:
                root = int(user32.GetAncestor(value, 2) or value)  # GA_ROOT
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(root, buf, 256)
                if buf.value:
                    return root
            return 0
    except Exception:  # noqa: BLE001
        pass
    try:
        import ctypes

        return int(ctypes.windll.user32.FindWindowW(None, TITLE))
    except Exception:  # noqa: BLE001
        return 0


def enable_native_resize(window, timeout: float = 15.0) -> None:
    """无边框窗口会丢失系统缩放边框，这里通过 Win32 样式补回。"""
    if sys.platform != "win32":
        return
    deadline = time.time() + timeout
    hwnd = 0
    while time.time() < deadline:
        # 必须等 pywebview 真正生成窗体后再取句柄，避免误抓到旧窗口
        if getattr(window, "native", None) is not None:
            hwnd = window_handle(window)
            if hwnd:
                break
        time.sleep(0.1)
    if not hwnd:
        log("未找到窗口句柄，跳过缩放边框恢复")
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, -16)
        user32.SetWindowLongW(
            hwnd,
            -16,
            style | 0x00040000 | 0x00010000 | 0x00020000 | 0x00080000,  # THICKFRAME | MAXIMIZEBOX | MINIMIZEBOX | SYSMENU
        )
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)  # FRAMECHANGED | NOMOVE | NOSIZE | NOZORDER
        log(f"已恢复无边框窗口的缩放边框（句柄 {hwnd}）")
    except Exception as exc:  # noqa: BLE001
        log(f"恢复缩放边框失败：{exc}")


class WindowApi:
    """供前端自定义标题栏调用的窗口控制 API。"""

    def __init__(self) -> None:
        self._window = None

    def bind(self, window) -> None:
        self._window = window

    def minimize(self) -> bool:
        if self._window:
            self._window.minimize()
        return True

    def is_maximized(self) -> bool:
        hwnd = window_handle(self._window)
        if not hwnd:
            return False
        try:
            import ctypes

            return bool(ctypes.windll.user32.IsZoomed(hwnd))
        except Exception:  # noqa: BLE001
            return False

    def toggle_maximize(self) -> bool:
        if not self._window:
            return False
        hwnd = window_handle(self._window)
        if hwnd:
            try:
                import ctypes

                # SW_RESTORE = 9, SW_MAXIMIZE = 3
                ctypes.windll.user32.ShowWindow(hwnd, 9 if self.is_maximized() else 3)
                return self.is_maximized()
            except Exception:  # noqa: BLE001
                pass
        if self.is_maximized():
            self._window.restore()
        else:
            self._window.maximize()
        return self.is_maximized()

    def close(self) -> bool:
        if self._window:
            self._window.destroy()
        return True


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
    redirect_stdio()
    if "--no-background" in sys.argv:
        os.environ["ASTRBOT_MANAGER_NO_BACKGROUND"] = "1"
        log("已禁用后台任务（watchdog / auto-learn）")
    port = pick_port()
    url = f"http://127.0.0.1:{port}"
    log(f"启动服务：{url}")
    write_runtime(port)
    start_server(port)
    if not wait_ready(url + "/api/health"):
        log("服务启动超时")
        raise SystemExit(1)

    try:
        import webview

        api = WindowApi()
        window = webview.create_window(
            TITLE,
            url,
            width=1480,
            height=940,
            min_size=(1120, 720),
            background_color="#070a10",
            text_select=True,
            frameless=True,
            easy_drag=False,
            js_api=api,
        )
        api.bind(window)
        threading.Thread(target=enable_native_resize, args=(window,), daemon=True, name="window-frame").start()
        log("使用 pywebview 无边框窗口")
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

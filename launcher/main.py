from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.request import urlopen

# PyInstaller's windowed bootloader intentionally removes console streams.
# Uvicorn's logging setup still expects file-like objects during initialization.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import uvicorn

from app.main import create_app


def resource_path(*parts: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root.joinpath(*parts)


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until_ready(url: str, timeout: float = 20) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{url}/api/health", timeout=1) as response:
                if response.status == 200:
                    return True
        except OSError:
            time.sleep(0.1)
    return False


def main() -> int:
    import tkinter as tk

    port = available_port()
    url = f"http://127.0.0.1:{port}"
    application = create_app(static_dir=resource_path("frontend", "dist"))
    server = uvicorn.Server(
        uvicorn.Config(application, host="127.0.0.1", port=port, log_level="warning")
    )
    server_thread = threading.Thread(target=server.run, name="workbench-server", daemon=True)
    server_thread.start()

    root = tk.Tk()
    root.title("PairForge · 双图生图工作台")
    root.geometry("430x230")
    root.resizable(False, False)
    root.configure(bg="#f3efe4")
    tk.Label(
        root,
        text="PairForge",
        font=("Microsoft YaHei UI", 20, "bold"),
        bg="#f3efe4",
        fg="#18201f",
    ).pack(pady=(30, 4))
    status = tk.Label(
        root,
        text="正在启动本地工作台……",
        font=("Microsoft YaHei UI", 10),
        bg="#f3efe4",
        fg="#68706c",
    )
    status.pack(pady=(0, 18))
    actions = tk.Frame(root, bg="#f3efe4")
    actions.pack()

    def open_workbench() -> None:
        webbrowser.open(url)

    open_button = tk.Button(
        actions,
        text="打开工作台",
        command=open_workbench,
        state="disabled",
        font=("Microsoft YaHei UI", 11, "bold"),
        bg="#e0442e",
        fg="white",
        activebackground="#a82d20",
        activeforeground="white",
        relief="flat",
        padx=24,
        pady=9,
    )
    open_button.pack(side="left", padx=6)

    def close() -> None:
        server.should_exit = True
        root.after(100, root.destroy)

    tk.Button(
        actions,
        text="退出程序",
        command=close,
        font=("Microsoft YaHei UI", 10),
        bg="#18201f",
        fg="white",
        activebackground="#343c3a",
        activeforeground="white",
        relief="flat",
        padx=18,
        pady=10,
    ).pack(side="left", padx=6)
    tk.Label(
        root,
        text="数据保存在 EXE 同级 PairForge_Data；完成后请点击“退出程序”。",
        font=("Microsoft YaHei UI", 9),
        bg="#f3efe4",
        fg="#7c7568",
    ).pack(pady=22)

    def ready_check() -> None:
        ready = wait_until_ready(url)

        def update() -> None:
            if ready:
                status.configure(text=f"本地服务已就绪 · {url}", fg="#267354")
                open_button.configure(state="normal")
                if os.environ.get("WORKBENCH_NO_BROWSER") != "1":
                    open_workbench()
            else:
                status.configure(text="启动失败，请退出后重试。", fg="#bd382e")

        root.after(0, update)

    threading.Thread(target=ready_check, name="readiness-check", daemon=True).start()
    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()
    server.should_exit = True
    server_thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Install a staged release after the service has stopped.

The running program cannot overwrite the files it has open, so the update is
finished by this separate script. The service starts it just before it
stops; the script waits for the port to be free, replaces the program files
and starts the program again.

The learner's data folder is never touched: it is not part of the release
and it is not part of the replacement.
"""
from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .updater import install_staged, start_after_update


def port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    """True when nothing listens on the port any more."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        return probe.connect_ex((host, port)) != 0


def wait_for_port(port: int, timeout: float = 60.0) -> bool:
    """Wait until the old service released the port."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_is_free(port):
            return True
        time.sleep(0.5)
    return False


def _end_process(pid: int) -> None:
    """End a process that will not let go of the port.

    Windows has no SIGKILL, so the process tree is ended with taskkill.
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, check=False)
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError, AttributeError):
        pass


def ask_service_to_stop(port: int) -> None:
    """Ask the running service to close its database and stop."""
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/update/shutdown", method="POST",
            headers={"User-Agent": "toeic-practice-studio",
                     "Content-Type": "application/json"},
            data=b"{}")
        urllib.request.urlopen(request, timeout=10).read()
    except (urllib.error.URLError, OSError):
        # The service may already be gone; the port check below decides.
        pass


def stop_service(pid: int, port: int) -> None:
    """Ask the old service to stop, and insist if it does not.

    The service is asked over HTTP first so it can close its database
    cleanly. A process that does not let go of the port in time is ended,
    because the files cannot be replaced while it still holds them open.
    """
    if not pid or pid == os.getpid():
        return
    ask_service_to_stop(port)
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    if wait_for_port(port, timeout=20.0):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    if wait_for_port(port, timeout=20.0):
        return
    _end_process(pid)
    wait_for_port(port, timeout=20.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="便携版目录")
    parser.add_argument("--archive", required=True, help="已下载并校验的发行包")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--pid", type=int, default=0, help="要停止的服务进程号")
    parser.add_argument("--log", default="", help="进度文件路径")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    log = Path(args.log) if args.log else None

    def note(message: str) -> None:
        if log is None:
            return
        try:
            log.write_text(message, encoding="utf-8")
        except OSError:
            pass

    try:
        note("正在停止服务…")
        stop_service(args.pid, args.port)
        if not port_is_free(args.port):
            note("服务仍在运行，更新未执行。")
            return 1
        note("正在安装新版本…")
        install_staged(root, Path(args.archive))
        note("更新完成，正在重新启动…")
        start_after_update(root, args.port)
        note("已启动新版本。")
        return 0
    except Exception as error:  # noqa: BLE001 - reported to the learner
        note(f"更新失败：{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
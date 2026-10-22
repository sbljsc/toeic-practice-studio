"""Local launcher that opens the browser only after Uvicorn has started."""

import argparse
import os
import threading
import webbrowser
from pathlib import Path

import uvicorn

from . import runtime_state




class BrowserOpeningServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config, *, open_browser: bool) -> None:
        super().__init__(config)
        self.open_browser = open_browser

    async def startup(self, sockets=None) -> None:
        await super().startup(sockets)
        if self.started and self.open_browser:
            webbrowser.open(f"http://127.0.0.1:{self.config.port}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TOEIC Practice on the local machine.")
    parser.add_argument("--port", type=int, default=8765, help="local port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="skip opening a browser")
    arguments = parser.parse_args()
    if not 1 <= arguments.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    config = uvicorn.Config(
        "toeic_practice.main:app",
        host="127.0.0.1",
        port=arguments.port,
    )
    server = BrowserOpeningServer(config, open_browser=not arguments.no_browser)
    runtime_state.set_running(server, arguments.port)
    # The cleanup runs alongside the server: server.run() below only
    # returns once the program has stopped.
    _remove_leftovers_later()
    server.run()
    return 0 if server.started else 1


def _remove_leftovers_later() -> None:
    """Remove the folders an update moved aside, a moment after start.

    The helper is still holding the old runtime when the new program
    begins, so the leftovers are removed once it has had time to finish.
    """
    import threading
    import time

    def worker() -> None:
        from .updater import clean_aside_folders
        # The helper ends a moment after the program starts; until then it
        # still holds the old runtime open.
        for _ in range(60):
            time.sleep(1.0)
            try:
                if clean_aside_folders(Path.cwd()):
                    return
            except Exception:  # noqa: BLE001 - leftovers are harmless
                return

    threading.Thread(target=worker, daemon=True).start()


def request_stop() -> bool:
    """Ask the running server to shut down.

    Uvicorn stops when its ``should_exit`` flag is set, which closes the
    socket and lets the program files be replaced.
    """
    server = runtime_state.RUNNING_SERVER
    if server is None:
        return False
    server.should_exit = True
    return True


if __name__ == "__main__":
    raise SystemExit(main())

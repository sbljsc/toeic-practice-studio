"""Local launcher that opens the browser only after Uvicorn has started."""

import argparse
import os
import threading
import webbrowser

import uvicorn

# The running server, so a request can ask it to stop.
RUNNING_SERVER = None
# The port it listens on, so an update can wait for the right one.
RUNNING_PORT = 0


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
    global RUNNING_SERVER, RUNNING_PORT
    server = BrowserOpeningServer(config, open_browser=not arguments.no_browser)
    RUNNING_SERVER = server
    RUNNING_PORT = arguments.port
    server.run()
    return 0 if server.started else 1


def request_stop() -> bool:
    """Ask the running server to shut down.

    Uvicorn stops when its ``should_exit`` flag is set, which closes the
    socket and lets the program files be replaced.
    """
    server = RUNNING_SERVER
    if server is None:
        return False
    server.should_exit = True
    return True


if __name__ == "__main__":
    raise SystemExit(main())

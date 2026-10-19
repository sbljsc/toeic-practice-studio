"""Local launcher that opens the browser only after Uvicorn has started."""

import argparse
import webbrowser

import uvicorn


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
    server.run()
    return 0 if server.started else 1


if __name__ == "__main__":
    raise SystemExit(main())

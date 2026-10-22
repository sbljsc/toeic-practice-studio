"""State that the running program shares with itself.

The launcher is started as ``python -m toeic_practice.launcher``, so the
code runs as ``__main__`` while the API imports it as
``toeic_practice.launcher``. Those are two different module objects, so
anything one of them records cannot be read by the other. This module is
the single place both of them look.
"""
from __future__ import annotations

# The server that is running, so a request can ask it to stop.
RUNNING_SERVER = None
# The port it listens on, so an update can wait for the right one.
RUNNING_PORT = 0


def set_running(server, port: int) -> None:
    """Record the server and the port it listens on."""
    global RUNNING_SERVER, RUNNING_PORT
    RUNNING_SERVER = server
    RUNNING_PORT = port


def running_port(default: int = 8765) -> int:
    """The port the program listens on."""
    return RUNNING_PORT or default
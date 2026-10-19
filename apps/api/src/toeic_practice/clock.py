"""Injectable clock primitives.

Deadline math uses `monotonic` (sleep/suspend proof); wall time is used only
for display timestamps and persisted checkpoints so a restart can re-anchor.
"""

import time
import uuid

PROCESS_ID = uuid.uuid4().hex
# Evidence only; recovery never trusts a monotonic anchor from another owner.
BOOT_ID = str(round((time.time() - time.monotonic()) / 10))


class Clock:
    """Default wall+monotonic clock used by the real server."""

    identity = PROCESS_ID
    boot_identity = BOOT_ID

    def monotonic(self) -> float:
        return time.monotonic()

    def wall(self) -> float:
        return time.time()


class ManualClock:
    """Deterministic test clock; tests advance it explicitly, never the OS."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.identity = uuid.uuid4().hex
        self.boot_identity = "manual-boot"
        self.now = start
        self.wall_now = 1_760_000_000.0

    def monotonic(self) -> float:
        return self.now

    def wall(self) -> float:
        return self.wall_now

    def advance(self, seconds: float) -> None:
        assert seconds >= 0
        self.now += seconds
        self.wall_now += seconds


def now_iso(clock) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(clock.wall(), tz=timezone.utc).isoformat()

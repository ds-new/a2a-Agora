"""Process-wide clock (epoch seconds). Simulations swap in a virtual clock."""

from __future__ import annotations

import time


class Clock:
    def now(self) -> float:
        return time.time()


class VirtualClock(Clock):
    def __init__(self, start: float = 1_790_000_000.0):
        self.t = start

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


_clock: Clock = Clock()


def now() -> float:
    return _clock.now()


def set_clock(clock: Clock) -> None:
    global _clock
    _clock = clock


def get_clock() -> Clock:
    return _clock

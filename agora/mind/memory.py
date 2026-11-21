"""Episodic memory of an agent's decisions and their outcomes."""

from __future__ import annotations

from collections import defaultdict, deque

from .. import clock


def _counter() -> defaultdict:
    return defaultdict(float)


class Memory:
    def __init__(self, maxlen: int = 400):
        self.events: deque = deque(maxlen=maxlen)
        self.producers: dict[str, defaultdict] = defaultdict(_counter)   # proposed/accepted/positive/negative/bought_ok/refunded
        self.friends: dict[str, defaultdict] = defaultdict(_counter)     # recommended/accepted/positive
        self.categories: dict[str, defaultdict] = defaultdict(_counter)  # shown/positive
        self.decided: set[str] = set()   # offers already shown or turned down (not re-shown)
        self.bought: set[str] = set()    # offers already bought (never bought twice)
        self.unsafe: set[str] = set()    # offers turned down as unsafe/blocked/untrusted (never reconsidered)

    def record(self, kind: str, **data) -> None:
        self.events.append({"t": clock.now(), "kind": kind, **data})

    def trust(self, did: str) -> float:
        """Posterior mean that dealing with this producer turns out well (Beta(1,1) prior)."""
        c = self.producers.get(did)
        if not c:
            return 0.5
        good = c["positive"] + 2 * c["bought_ok"]
        bad = c["negative"] + 3 * c["refunded"]
        return (1 + good) / (2 + good + bad)

    def precision(self, did: str) -> float:
        """Share of this producer's proposals that were worth letting through."""
        c = self.producers.get(did)
        if not c:
            return 0.5
        return (1 + c["accepted"]) / (2 + c["proposed"])

    def friend_precision(self, did: str) -> float:
        c = self.friends.get(did)
        if not c:
            return 0.5
        return (1 + c["positive"]) / (2 + c["recommended"])

    def summary(self, n: int = 8) -> list[str]:
        out = []
        for e in list(self.events)[-n:]:
            what = {k: v for k, v in e.items() if k not in ("t", "kind")}
            out.append(f"{e['kind']}: " + ", ".join(f"{k}={v}" for k, v in what.items()))
        return out

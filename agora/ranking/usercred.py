"""UserCred v2-style reputation (cf. ``user-cred-v2/UserCredV2App.scala``).

PageRank over a weighted directed graph, with a teleport vector that blends
uniform mass and "engagement" mass (engagement_teleport_beta = 0.5 and
max_iterations = 50 are the UserCredV2Config defaults). In Agora the edges come
from verifiable evidence (escrow settlements, endorsements, reviews, follows)
and teleport mass sits on agents that have actually spent money through a
trusted escrow, which makes Sybil rings expensive: fake identities earn no
teleport mass without real settled payments.
"""

from __future__ import annotations

import math
from collections import defaultdict


def pagerank(edges: list[tuple[str, str, float]], teleport_mass: dict[str, float], *, beta: float = 0.5,
             alpha: float = 0.15, max_iter: int = 50, tol: float = 1e-10) -> dict[str, float]:
    nodes = sorted({s for s, _, _ in edges} | {d for _, d, _ in edges} | set(teleport_mass))
    if not nodes:
        return {}
    n = len(nodes)
    total_mass = sum(max(0.0, m) for m in teleport_mass.values())
    teleport = {v: (1 - beta) / n + (beta * max(0.0, teleport_mass.get(v, 0.0)) / total_mass if total_mass else beta / n)
                for v in nodes}
    out_w: dict[str, float] = defaultdict(float)
    adj: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for s, d, w in edges:
        if w > 0 and s != d:
            adj[s].append((d, w))
            out_w[s] += w
    rank = dict(teleport)
    for _ in range(max_iter):
        dangling = sum(rank[v] for v in nodes if out_w[v] == 0)
        nxt = {v: alpha * teleport[v] + (1 - alpha) * dangling * teleport[v] for v in nodes}
        for s, nbrs in adj.items():
            share = (1 - alpha) * rank[s] / out_w[s]
            for d, w in nbrs:
                nxt[d] += share * w
        diff = sum(abs(nxt[v] - rank[v]) for v in nodes)
        rank = nxt
        if diff < tol:
            break
    return rank


def to_reputation(rank: dict[str, float]) -> dict[str, float]:
    """Log-scale min-max to [0, 1] (Tweepcred mapped PageRank mass through a log too)."""
    if not rank:
        return {}
    logs = {v: math.log(r) for v, r in rank.items() if r > 0}
    lo, hi = min(logs.values()), max(logs.values())
    span = (hi - lo) or 1.0
    return {v: (logs.get(v, lo) - lo) / span for v in rank}

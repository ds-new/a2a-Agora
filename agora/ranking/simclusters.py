"""SimClusters-lite (cf. ``simclusters/`` in x-algorithm).

KnownFor: producers are clustered by who engages with them. Producer-producer
similarity is the cosine of their consumer-engagement vectors; communities come
from Louvain on that graph (production SimClusters uses its own community
detection over the follow graph). InterestedIn: a consumer's engagement mass
mapped through KnownFor. Each agent computes this over the slice of the
engagement graph it has verified (settlements, endorsements, reviews, follows).
"""

from __future__ import annotations

import math
from collections import defaultdict

import networkx as nx


def known_for(engagements: dict[str, dict[str, float]], seed: int = 0, min_sim: float = 0.05) -> dict[str, int]:
    """engagements: consumer -> {producer: weight}. Returns producer -> cluster id."""
    by_producer: dict[str, dict[str, float]] = defaultdict(dict)
    for consumer, prods in engagements.items():
        for p, w in prods.items():
            by_producer[p][consumer] = w
    norms = {p: math.sqrt(sum(w * w for w in v.values())) for p, v in by_producer.items()}
    pair_dot: dict[tuple[str, str], float] = defaultdict(float)
    for prods in engagements.values():
        items = sorted(prods.items())
        for i, (p, wp) in enumerate(items):
            for q, wq in items[i + 1:]:
                pair_dot[(p, q)] += wp * wq
    g = nx.Graph()
    g.add_nodes_from(by_producer)
    for (p, q), dot in pair_dot.items():
        sim = dot / (norms[p] * norms[q] + 1e-12)
        if sim >= min_sim:
            g.add_edge(p, q, weight=sim)
    if g.number_of_edges() == 0:
        return {p: i for i, p in enumerate(sorted(g.nodes))}
    communities = nx.community.louvain_communities(g, weight="weight", seed=seed)
    return {p: cid for cid, members in enumerate(sorted(communities, key=lambda c: sorted(c)[0])) for p in members}


def interested_in(consumer_engagement: dict[str, float], kf: dict[str, int]) -> dict[int, float]:
    scores: dict[int, float] = defaultdict(float)
    for producer, w in consumer_engagement.items():
        if producer in kf:
            scores[kf[producer]] += w
    total = sum(scores.values()) or 1.0
    return {c: s / total for c, s in sorted(scores.items(), key=lambda kv: -kv[1])}

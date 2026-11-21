"""Port of ``vm-ranker/dpp.rs``: diversity reranking with a determinantal point process.

Kernel L_ij = q_i * q_j * cos(e_i, e_j) with quality q_i = exp(alpha * s_i / max s),
alpha = theta / (2 (1 - theta)). Greedy MAP inference with incremental Cholesky
updates (Chen, Zhang & Zhou, NeurIPS 2018), as in ``greedy_dpp``. theta = 0.5 is
the default used in dpp.rs tests; higher theta weights score over diversity.
"""

from __future__ import annotations

import math

import numpy as np

EPS = 1e-10


def dpp_order(scores: list[float], embeddings: np.ndarray, top_k: int, theta: float = 0.5) -> list[int]:
    n = len(scores)
    if n == 0:
        return []
    theta = min(max(theta, 0.0), 1.0 - 1e-6)
    alpha = theta / (2.0 * (1.0 - theta))
    s = np.asarray(scores, dtype=float)
    max_s = s.max() if s.max() > 0 else 1.0
    q = np.exp(alpha * s / max_s)
    e = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + EPS)
    L = (q[:, None] * q[None, :]) * (e @ e.T)
    k = min(top_k, n)
    cis = np.zeros((k, n))
    di2 = np.diag(L).copy()
    selected: list[int] = []
    j = int(np.argmax(di2))
    while len(selected) < k:
        selected.append(j)
        if len(selected) == k:
            break
        m = len(selected) - 1
        dj = math.sqrt(max(di2[j], EPS))
        eis = (L[j, :] - cis[:m, j] @ cis[:m, :]) / dj
        cis[m, :] = eis
        di2 -= eis ** 2
        di2[selected] = -np.inf
        j = int(np.argmax(di2))
        if di2[j] < EPS:  # remaining items are spanned by the selection: fall back to score order
            rest = [i for i in np.argsort(-s) if i not in selected]
            selected.extend(rest[: k - len(selected)])
            break
    return selected

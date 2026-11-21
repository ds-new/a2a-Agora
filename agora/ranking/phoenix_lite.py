"""Phoenix-lite: a small numpy model with the design decisions of X's Phoenix ranker.

From the x-algorithm README ("Key Design Decisions") and phoenix/xrex/models/:
  1. Multi-action prediction: one sigmoid head per action (plus a dwell-time
     regression head); the value model combines them in a separate step.
  2. Candidate isolation: a candidate attends to the viewer context (user
     token + action history) and to itself, never to other candidates
     (``attention_segment_ids``: context = 1, candidates = -1). Scores do not
     depend on batch composition, so they are cacheable and chunkable.
  3. Hash-based embeddings: each feature string is hashed by K functions into
     one shared table. No vocabulary; a brand-new offer is representable at once.
  4. The viewer's recent action sequence is the main input.

Production Phoenix is a Grok-architecture transformer trained in JAX on X's
logs. This is one attention layer and one head, trained online by each
consumer agent on its own impressions, so the training data never leaves the
agent. Forward and backward passes are written out by hand (no autodiff
dependency) and covered by a finite-difference gradient check in tests.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import numpy as np

from .value_model import BINARY_ACTIONS

PRIORS = {  # initial head biases = logit(prior), i.e. a calibrated cold start; negatives are rare events
    "click": 0.3, "dwell": 0.5, "favorite": 0.1, "reply": 0.03, "repost": 0.05, "share": 0.02,
    "follow_author": 0.03, "inquire": 0.05, "purchase": 0.03, "not_interested": 0.01, "mute_author": 0.002,
    "block_author": 0.001, "report": 0.001, "not_dwelled": 0.3, "return": 0.005,
}
N_BIN = len(BINARY_ACTIONS)


def _logit(p: float) -> float:
    return math.log(p / (1 - p))


class HashEmbedder:
    def __init__(self, table_size: int, n_hashes: int = 2):
        self.table_size = table_size
        self.n_hashes = n_hashes
        self._cache: dict[str, list[int]] = {}

    def __call__(self, token: str) -> list[int]:
        idx = self._cache.get(token)
        if idx is None:
            idx = [int.from_bytes(hashlib.blake2b(f"{k}|{token}".encode(), digest_size=8).digest(), "little")
                   % self.table_size for k in range(self.n_hashes)]
            if len(self._cache) < 500_000:
                self._cache[token] = idx
        return idx

    def rows(self, tokens: list[str]) -> list[int]:
        out: list[int] = []
        for t in tokens:
            out.extend(self(t))
        return out


@dataclass
class Example:
    user: list[str]
    history: list[list[str]]
    candidates: list[list[str]]
    labels: np.ndarray        # (C, N_BIN) in {0,1}
    dwell: np.ndarray         # (C,) seconds, NaN when unobserved


class PhoenixLite:
    PARAMS = ("E", "Wq", "Wk", "Wv", "Wo", "W1", "b1", "W2", "b2")

    def __init__(self, d: int = 24, hidden: int = 32, table_size: int = 4096, n_hashes: int = 2,
                 lr: float = 0.02, reg_weight: float = 0.1, seed: int = 0):
        rng = np.random.default_rng(seed)
        self.d, self.hidden = d, hidden
        self.embed = HashEmbedder(table_size, n_hashes)
        s = 1 / math.sqrt(d)
        self.p = {
            "E": rng.normal(0, 0.1, (table_size, d)),
            "Wq": rng.normal(0, s, (d, d)), "Wk": rng.normal(0, s, (d, d)),
            "Wv": rng.normal(0, s, (d, d)), "Wo": rng.normal(0, s, (d, d)),
            "W1": rng.normal(0, math.sqrt(2 / d), (d, hidden)), "b1": np.zeros(hidden),
            "W2": rng.normal(0, 0.05, (hidden, N_BIN + 1)),
            "b2": np.array([_logit(PRIORS[a]) for a in BINARY_ACTIONS] + [math.log1p(20.0)]),
        }
        self.lr, self.reg_weight = lr, reg_weight
        self._m = {k: np.zeros_like(v) for k, v in self.p.items()}
        self._v = {k: np.zeros_like(v) for k, v in self.p.items()}
        self._t = 0
        self.examples_seen = 0

    # ----------------------------------------------------------------- encoding
    def _embed_seq(self, seqs: list[list[str]]) -> tuple[np.ndarray, list[list[int]]]:
        rows = [self.embed.rows(toks) for toks in seqs]
        E = self.p["E"]
        X = np.stack([E[r].sum(0) if r else np.zeros(self.d) for r in rows]) if rows else np.zeros((0, self.d))
        return X, rows

    def item_vector(self, tokens: list[str]) -> np.ndarray:
        r = self.embed.rows(tokens)
        return self.p["E"][r].sum(0)

    # ------------------------------------------------------------------ forward
    def _forward(self, user: list[str], history: list[list[str]], candidates: list[list[str]]):
        p = self.p
        ctx_seqs = [user + ["seg:user"]] + [h + ["seg:hist"] for h in history]
        Xx, rows_x = self._embed_seq(ctx_seqs)
        Xc, rows_c = self._embed_seq([c + ["seg:cand"] for c in candidates])
        sc = 1 / math.sqrt(self.d)
        Qc = Xc @ p["Wq"]
        Kx, Vx = Xx @ p["Wk"], Xx @ p["Wv"]
        Kc, Vc = Xc @ p["Wk"], Xc @ p["Wv"]
        # candidate i attends to [context..., itself]  (candidate isolation)
        S = np.concatenate([Qc @ Kx.T, (Qc * Kc).sum(1, keepdims=True)], axis=1) * sc
        S -= S.max(1, keepdims=True)
        P = np.exp(S)
        P /= P.sum(1, keepdims=True)
        n = Xx.shape[0]
        O = P[:, :n] @ Vx + P[:, n:] * Vc
        H = Xc + O @ p["Wo"]
        Zp = H @ p["W1"] + p["b1"]
        Z = np.maximum(Zp, 0)
        Y = Z @ p["W2"] + p["b2"]
        cache = dict(Xx=Xx, Xc=Xc, rows_x=rows_x, rows_c=rows_c, Qc=Qc, Kx=Kx, Vx=Vx, Kc=Kc, Vc=Vc, P=P, O=O,
                     H=H, Zp=Zp, Z=Z, n=n, sc=sc)
        return Y, cache

    def predict(self, user: list[str], history: list[list[str]], candidates: list[list[str]]) -> list[dict]:
        if not candidates:
            return []
        Y, _ = self._forward(user, history, candidates)
        probs = 1 / (1 + np.exp(-Y[:, :N_BIN]))
        dwell = np.expm1(np.clip(Y[:, N_BIN], 0, 8))
        out = []
        for i in range(len(candidates)):
            d = {a: float(probs[i, j]) for j, a in enumerate(BINARY_ACTIONS)}
            d["dwell_time"] = float(dwell[i])
            out.append(d)
        return out

    # ----------------------------------------------------------------- backward
    def loss_and_grads(self, ex: Example) -> tuple[float, dict[str, np.ndarray]]:
        p = self.p
        Y, c = self._forward(ex.user, ex.history, ex.candidates)
        logits = Y[:, :N_BIN]
        lab = ex.labels.astype(float)
        bce = np.logaddexp(0, logits) - lab * logits
        loss = bce.mean()
        dY = np.zeros_like(Y)
        dY[:, :N_BIN] = (1 / (1 + np.exp(-logits)) - lab) / bce.size
        valid = ~np.isnan(ex.dwell)
        if valid.any():
            target = np.log1p(np.where(valid, ex.dwell, 0.0))
            err = np.where(valid, Y[:, N_BIN] - target, 0.0)
            nv = valid.sum()
            loss += self.reg_weight * 0.5 * (err ** 2).sum() / nv
            dY[:, N_BIN] = self.reg_weight * err / nv

        g: dict[str, np.ndarray] = {}
        g["W2"] = c["Z"].T @ dY
        g["b2"] = dY.sum(0)
        dZp = (dY @ p["W2"].T) * (c["Zp"] > 0)
        g["W1"] = c["H"].T @ dZp
        g["b1"] = dZp.sum(0)
        dH = dZp @ p["W1"].T
        g["Wo"] = c["O"].T @ dH
        dO = dH @ p["Wo"].T
        n, P, sc = c["n"], c["P"], c["sc"]
        dP = np.concatenate([dO @ c["Vx"].T, (dO * c["Vc"]).sum(1, keepdims=True)], axis=1)
        dVx = P[:, :n].T @ dO
        dVc = P[:, n:] * dO
        dS = P * (dP - (dP * P).sum(1, keepdims=True))
        dSx, dSs = dS[:, :n], dS[:, n:]
        dQc = (dSx @ c["Kx"] + dSs * c["Kc"]) * sc
        dKx = dSx.T @ c["Qc"] * sc
        dKc = dSs * c["Qc"] * sc
        Xx, Xc = c["Xx"], c["Xc"]
        g["Wq"] = Xc.T @ dQc
        g["Wk"] = Xx.T @ dKx + Xc.T @ dKc
        g["Wv"] = Xx.T @ dVx + Xc.T @ dVc
        dXc = dH + dQc @ p["Wq"].T + dKc @ p["Wk"].T + dVc @ p["Wv"].T
        dXx = dKx @ p["Wk"].T + dVx @ p["Wv"].T
        dE = np.zeros_like(p["E"])
        for X_grad, rows in ((dXx, c["rows_x"]), (dXc, c["rows_c"])):
            idx = [i for r in rows for i in r]
            if idx:
                rep = np.repeat(X_grad, [len(r) for r in rows], axis=0)
                np.add.at(dE, idx, rep)
        g["E"] = dE
        return float(loss), g

    def train(self, examples: list[Example], epochs: int = 1, batch_size: int = 8, seed: int = 0) -> float:
        if not examples:
            return float("nan")
        rng = np.random.default_rng(seed + self._t)
        losses = []
        for _ in range(epochs):
            order = rng.permutation(len(examples))
            for b in range(0, len(order), batch_size):
                batch = [examples[i] for i in order[b:b + batch_size]]
                acc = {k: np.zeros_like(v) for k, v in self.p.items()}
                for ex in batch:
                    loss, g = self.loss_and_grads(ex)
                    losses.append(loss)
                    for k in acc:
                        acc[k] += g[k] / len(batch)
                self._adam(acc)
        self.examples_seen += len(examples) * epochs
        return float(np.mean(losses))

    def _adam(self, grads: dict[str, np.ndarray], b1: float = 0.9, b2: float = 0.999, eps: float = 1e-8) -> None:
        self._t += 1
        for k, gk in grads.items():
            np.clip(gk, -5, 5, out=gk)
            self._m[k] = b1 * self._m[k] + (1 - b1) * gk
            self._v[k] = b2 * self._v[k] + (1 - b2) * gk * gk
            mh = self._m[k] / (1 - b1 ** self._t)
            vh = self._v[k] / (1 - b2 ** self._t)
            self.p[k] -= self.lr * mh / (np.sqrt(vh) + eps)

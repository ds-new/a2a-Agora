import numpy as np

from agora.ranking.phoenix_lite import N_BIN, Example, PhoenixLite


def _example(rng, n_hist=3, n_cand=4):
    user = ["user:u1", "region:SG"]
    hist = [[f"offer:h{i}", f"cat:c{i % 2}", f"act:{a}"] for i, a in enumerate(["click", "purchase", "favorite"][:n_hist])]
    cands = [[f"offer:x{i}", f"cat:c{i % 3}", "kind:physical"] for i in range(n_cand)]
    labels = (rng.random((n_cand, N_BIN)) < 0.3).astype(float)
    dwell = np.where(rng.random(n_cand) < 0.5, rng.random(n_cand) * 60, np.nan)
    return Example(user, hist, cands, labels, dwell)


def test_gradients_match_finite_differences():
    rng = np.random.default_rng(1)
    m = PhoenixLite(d=4, hidden=5, table_size=64, seed=3)
    ex = _example(rng)
    _, grads = m.loss_and_grads(ex)
    eps = 1e-6
    for name in m.PARAMS:
        P = m.p[name]
        flat_idx = rng.choice(P.size, size=min(12, P.size), replace=False)
        if name == "E":  # check rows that the example actually touches
            touched = sorted(set(i for t in ex.user + sum(ex.history, []) + sum(ex.candidates, []) for i in m.embed(t)))
            flat_idx = [r * P.shape[1] + c for r in touched[:4] for c in range(P.shape[1])]
        for fi in flat_idx:
            idx = np.unravel_index(fi, P.shape)
            old = P[idx]
            P[idx] = old + eps
            lp, _ = m.loss_and_grads(ex)
            P[idx] = old - eps
            lm, _ = m.loss_and_grads(ex)
            P[idx] = old
            num = (lp - lm) / (2 * eps)
            assert abs(num - grads[name][idx]) <= 1e-6 + 1e-4 * abs(num), (name, idx, num, grads[name][idx])


def test_candidate_isolation_scores_do_not_depend_on_batch():
    m = PhoenixLite(seed=0)
    user, hist = ["user:a"], [["offer:h1", "act:click"]]
    target = ["offer:t", "cat:coffee"]
    alone = m.predict(user, hist, [target])[0]
    batch = m.predict(user, hist, [["offer:o1"], target, ["offer:o2", "cat:books"]])[1]
    for k in alone:
        assert abs(alone[k] - batch[k]) < 1e-12


def test_learns_a_preference():
    m = PhoenixLite(seed=0, lr=0.03)
    exs = []
    for i in range(120):
        cands = [["cat:coffee", f"offer:c{i}"], ["cat:books", f"offer:b{i}"]]
        labels = np.zeros((2, N_BIN))
        labels[0, 0] = 1.0  # always clicks coffee, never books
        exs.append(Example(["user:a"], [["cat:coffee", "act:click"]], cands, labels, np.array([np.nan, np.nan])))
    m.train(exs, epochs=3)
    p = m.predict(["user:a"], [["cat:coffee", "act:click"]], [["cat:coffee", "offer:new1"], ["cat:books", "offer:new2"]])
    assert p[0]["click"] > 0.8 > 0.2 > p[1]["click"]

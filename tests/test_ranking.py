import asyncio

import numpy as np
import pytest

from agora.ranking.dpp import dpp_order
from agora.ranking.pipeline import Candidate, CandidatePipeline, Filter, Scorer, Source, TopKScoreSelector
from agora.ranking.simclusters import interested_in, known_for
from agora.ranking.usercred import pagerank, to_reputation
from agora.ranking.value_model import (
    ScoringInputs,
    ValueModelWeights,
    author_pool_counts,
    compute_value_scores,
    diversity_multiplier,
    offset_score,
    unoffset_score,
)


def test_offset_score_hand_computed():
    w = ValueModelWeights(weights={"favorite": 1.0, "report": -10.0})
    assert w.total_sum() == 11.0 and w.negative_sum() == 10.0
    assert offset_score(0.5 * 1 + 0.01 * -10, w) == pytest.approx(0.401)
    neg = 0.5 * 1 + 0.1 * -10  # -0.5
    assert offset_score(neg, w) == pytest.approx((neg + 10) / 11 * 0.001)
    for x in (-3.0, -0.2, 0.0, 0.7):
        assert unoffset_score(offset_score(x, w), w) == pytest.approx(x)


def test_author_diversity_and_oon():
    assert author_pool_counts(["a", "b", "a", "a"], [0.9, 0.8, 0.7, 0.95]) == [1, 0, 2, 0]
    assert diversity_multiplier(0.5, 0.25, 0) == 1.0 and diversity_multiplier(0.5, 0.25, 2) == pytest.approx(0.4375)
    w = ValueModelWeights(weights={"click": 1.0})
    cands = [ScoringInputs("a", {"click": 0.5}, True), ScoringInputs("a", {"click": 0.5}, True),
             ScoringInputs("b", {"click": 0.5}, False)]
    _, final = compute_value_scores(w, cands)
    base = 0.5 + 0.001
    assert sorted(final, reverse=True)[0] == pytest.approx(base)
    assert min(final[0], final[1]) == pytest.approx(base * 0.625)  # second post by author a: (1-.25)*.5+.25
    assert final[2] == pytest.approx(base * 0.75)                 # out-of-network discount


def test_dpp_prefers_diverse_items():
    emb = np.array([[1, 0], [0.99, 0.14], [0, 1]], dtype=float)
    order = dpp_order([1.0, 0.95, 0.6], emb, top_k=2, theta=0.5)
    assert order == [0, 2]  # near-duplicate of item 0 is skipped for the orthogonal one
    assert dpp_order([1.0, 0.9], np.array([[1.0, 0], [1.0, 0]]), top_k=2)[0] == 0


def test_usercred_resists_sybil_rings():
    edges = [("buyer1", "shop", 3.0), ("buyer2", "shop", 2.0), ("buyer1", "shop2", 1.0)]
    # a ring of fake identities endorsing each other, with no real spend
    edges += [("s1", "scam", 5.0), ("s2", "scam", 5.0), ("scam", "s1", 5.0), ("s1", "s2", 5.0), ("s2", "s1", 5.0)]
    rank = pagerank(edges, teleport_mass={"buyer1": 100.0, "buyer2": 80.0}, beta=0.9)
    rep = to_reputation(rank)
    assert rep["shop"] > rep["scam"]


def test_simclusters_finds_two_communities():
    eng = {f"c{i}": {"p_coffee1": 1.0, "p_coffee2": 1.0} for i in range(4)}
    eng.update({f"d{i}": {"p_book1": 1.0, "p_book2": 1.0} for i in range(4)})
    kf = known_for(eng)
    assert kf["p_coffee1"] == kf["p_coffee2"] != kf["p_book1"] == kf["p_book2"]
    ii = interested_in({"p_coffee1": 2.0, "p_book1": 1.0}, kf)
    assert list(ii)[0] == kf["p_coffee1"]


def test_pipeline_stage_order_and_failure_isolation():
    calls = []

    class Good(Source):
        name = "good"

        async def source(self, q):
            calls.append("source")
            return [Candidate(f"o{i}", "", {"producer": "p", "kind": "information"}, "good") for i in range(5)]

    class Broken(Source):
        name = "broken"

        async def source(self, q):
            raise RuntimeError("peer offline")

    class Odd(Filter):
        name = "odd"

        def keep(self, q, c):
            return int(c.offer_id[1:]) % 2 == 0

    class ByIndex(Scorer):
        name = "idx"

        async def score(self, q, cands):
            calls.append("score")
            for c in cands:
                c.score = int(c.offer_id[1:])

    pipe = CandidatePipeline("t", [], [Good(), Broken()], [], [Odd()], [ByIndex()], TopKScoreSelector(5),
                             [], [], [], result_size=2)
    res = asyncio.run(pipe.execute({}))
    assert [c.offer_id for c in res.selected] == ["o4", "o2"]
    assert calls == ["source", "score"] and len(res.filtered) == 2

"""The personal For You pipeline every consumer agent runs locally.

Mirrors home-mixer's PhoenixCandidatePipeline stage by stage:

  query hydration  : principal context, action sequence, reputation (UserCred), clusters (SimClusters)
  sources          : ThunderInbox (in-network push + reposts) | IntentResponses (C2M) |
                     PhoenixRetrieval (OON) | SimClusters (OON) | Popular (OON, gossiped)
  hydration        : core data, producer reputation/labels/stats, intent match, popularity
  filters          : DropDuplicates, CoreDataHydration, Age, Self, PreviouslySeen, MutedKeyword,
                     AuthorSocialgraph
  scoring          : PhoenixScorer (multi-action) -> RankingScorer (value model) -> DppRerank
  selection        : TopKScoreSelector
  post-selection   : VisibilityFiltering hydrator + VFFilter
  side effects     : record served items

The query carries a reference to the agent, whose state is the only data used.
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from ..crypto import jws_decode_unverified
from . import visibility
from .dpp import dpp_order
from .pipeline import (
    Candidate,
    CandidatePipeline,
    Filter,
    Hydrator,
    QueryHydrator,
    Scorer,
    SideEffect,
    Source,
    TopKScoreSelector,
)
from .retrieval import offer_text, retrieve, text_vector, user_vectors
from .simclusters import interested_in, known_for
from .usercred import pagerank, to_reputation
from .value_model import ScoringInputs, compute_value_scores

HISTORY_LEN = 24
SOURCE_PRIORITY = {"thunder": 0, "intent": 1, "phoenix_retrieval": 2, "simclusters": 3, "popular": 4}


def _b(x: float, base: float = 2.0, cap: int = 8) -> int:
    return min(cap, int(math.log(1 + max(0.0, x), base)))


def item_tokens(offer: dict) -> list[str]:
    return ([f"offer:{offer['offerId']}", f"producer:{offer['producer']}", f"cat:{offer['category']}",
             f"kind:{offer['kind']}", f"price_b:{_b(offer['price']['amount'])}"]
            + [f"tag:{t}" for t in offer.get("tags", [])[:4]])


def context_tokens(c: Candidate) -> list[str]:
    f = c.features
    return [f"src:{c.source}", f"inn:{int(c.in_network)}", f"rep_b:{int(f.get('reputation', 0) * 5)}",
            f"pop_b:{_b(f.get('popularity', 0))}", f"match_b:{int(f.get('intent_match', 0) * 5)}",
            f"lab:{int(bool(f.get('labels')))}", f"endorsed:{int(bool(c.endorsers))}",
            f"kind_cat:{c.kind}:{c.offer['category']}"]


# --------------------------------------------------------------------------- #
# Graph views derived from verified objects (no central database)
# --------------------------------------------------------------------------- #


def reputation_scores(store, viewer: str, following: set[str]) -> dict[str, float]:
    """UserCred over verifiable evidence. A settled purchase is an edge buyer -> merchant whose weight is
    the money at stake scaled by how satisfied that verified buyer said they were: volume alone would
    reward whoever sells the most, not whoever serves buyers best."""
    rating_of: dict[str, int] = {}
    for _, r in store.reviews.values():  # reviews were fully verified on intake
        rating_of[jws_decode_unverified(r["settlement"])[1]["escrowId"]] = r["rating"]
    edges: list[tuple[str, str, float]] = []
    spend: dict[str, float] = defaultdict(float)
    for key, (_, s) in store.settlements.items():
        if store._trusted(s) and s["status"] == "released":
            rating = rating_of.get(s["escrowId"])
            satisfaction = 0.5 if rating is None else ((rating - 1) / 4) ** 2
            edges.append((s["buyer"], s["merchant"], math.log1p(s["amount"]) * (0.1 + 0.9 * satisfaction)))
            spend[s["buyer"]] += s["amount"]
    for _, e in store.endorsements.values():
        producer = store.offers.get(e["offerId"], (None, {}))[1].get("producer")
        if producer:
            edges.append((e["endorser"], producer, 0.3))
    edges += [(viewer, f, 0.2) for f in following]
    for did in store.offers_by_producer:
        edges.append((did, did, 0.0))  # make every known producer a node
    rep = to_reputation(pagerank(edges, {b: math.sqrt(v) for b, v in spend.items()}))
    for did in list(rep):
        stats = store.merchant_stats(did)
        rep[did] *= (1 - stats["refund_rate"]) ** 2
    return rep


def engagement_graph(store) -> dict[str, dict[str, float]]:
    eng: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for _, s in store.settlements.values():
        if store._trusted(s) and s["status"] == "released":
            eng[s["buyer"]][s["merchant"]] += 2.0
    for _, e in store.endorsements.values():
        producer = store.offers.get(e["offerId"], (None, {}))[1].get("producer")
        if producer:
            eng[e["endorser"]][producer] += 1.0
    return eng


# --------------------------------------------------------------------------- #
# Query hydrators
# --------------------------------------------------------------------------- #


class UserContextHydrator(QueryHydrator):
    name = "UserContextHydrator"

    async def hydrate(self, q):
        a = q["agent"]
        hist = a.history[-HISTORY_LEN:]
        user_emb, user_txt = user_vectors(a.model, hist, [i["text"] for i in a.intents])
        return {"user_tokens": [f"user:{a.did}", f"region:{a.region}"],
                "history_tokens": [toks + [f"act:{act}"] for toks, act in hist],
                "user_emb": user_emb, "user_txt": user_txt, "following": set(a.following),
                "blocked": set(a.blocked), "region": a.region, "max_item_price": a.max_item_price,
                "seen": set(a.seen), "intent_vecs": [(i, text_vector(i["text"])) for i in a.intents]}


class ReputationHydrator(QueryHydrator):
    name = "UserCredHydrator"

    async def hydrate(self, q):
        return {"reputation": q["agent"].cached("reputation", lambda a: reputation_scores(a.store, a.did, a.following))}


class SimClustersHydrator(QueryHydrator):
    name = "SimClustersHydrator"

    async def hydrate(self, q):
        a = q["agent"]
        kf = a.cached("known_for", lambda ag: known_for(engagement_graph(ag.store)))
        mine: dict[str, float] = defaultdict(float)
        for toks, act in a.history:
            prod = next((t[9:] for t in toks if t.startswith("producer:")), None)
            if prod and act in ("purchase", "favorite", "repost", "follow_author", "click"):
                mine[prod] += 2.0 if act == "purchase" else 1.0
        for f in a.following:
            mine[f] += 1.0
        return {"known_for": kf, "interested_in": interested_in(mine, kf)}


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


def _from_store(a, oid: str, source: str, in_network: bool) -> Candidate | None:
    entry = a.store.offers.get(oid)
    if entry is None:
        return None
    return Candidate(oid, entry[0], entry[1], source, in_network=in_network)


class ThunderSource(Source):
    """In-network: offers pushed by followed producers and reposts by followed agents."""

    name = "ThunderSource"

    async def source(self, q):
        a, out = q["agent"], []
        for item in reversed(a.inbox[-300:]):
            if item.offer_id in q["seen"] or item.source == "intent":
                continue
            followed_leaf = item.endorsers and item.endorsers[-1] in q["following"]
            if item.offer["producer"] in q["following"] or followed_leaf:
                out.append(Candidate(item.offer_id, item.token, item.offer, "thunder", in_network=True,
                                     endorsers=list(item.endorsers), endorsement_token=item.endorsement_token))
        return out


class IntentResponseSource(Source):
    name = "IntentResponseSource"

    def enabled(self, q):
        return q["agent"].rank_mode != "chronological"

    async def source(self, q):
        a = q["agent"]
        return [Candidate(i.offer_id, i.token, i.offer, "intent") for i in a.inbox[-100:]
                if i.source == "intent" and i.offer_id not in q["seen"]]


def _oon_pool(q) -> list[tuple[str, dict]]:
    a = q["agent"]
    now = q["now"]
    return [(oid, p) for oid, (_, p) in a.store.offers.items()
            if p["producer"] not in q["following"] and p["producer"] != a.did and oid not in q["seen"]
            and p["expiresAt"] >= now]


class PhoenixRetrievalSource(Source):
    name = "PhoenixRetrievalSource"

    def __init__(self, k: int = 40):
        self.k = k

    def enabled(self, q):
        return q["agent"].rank_mode != "chronological"

    async def source(self, q):
        a = q["agent"]
        corpus = [(oid, item_tokens(p), a.text_vec(oid, p)) for oid, p in _oon_pool(q)]
        hits = retrieve(a.model, q["user_emb"], q["user_txt"], corpus, self.k)
        return [c for oid, _ in hits if (c := _from_store(a, oid, "phoenix_retrieval", False))]


class SimClustersSource(Source):
    name = "SimClustersSource"

    def __init__(self, k: int = 20):
        self.k = k

    def enabled(self, q):
        return q["agent"].rank_mode != "chronological" and bool(q.get("interested_in"))

    async def source(self, q):
        a, kf = q["agent"], q["known_for"]
        top = list(q["interested_in"])[:2]
        pool = [(oid, p) for oid, p in _oon_pool(q) if kf.get(p["producer"]) in top]
        pool.sort(key=lambda x: x[1]["createdAt"], reverse=True)
        return [c for oid, _ in pool[: self.k] if (c := _from_store(a, oid, "simclusters", False))]


class PopularSource(Source):
    name = "PopularSource"

    def __init__(self, k: int = 15):
        self.k = k

    def enabled(self, q):
        return q["agent"].rank_mode != "chronological"

    async def source(self, q):
        a = q["agent"]
        scored = []
        for oid, p in _oon_pool(q):
            pop = a.store.offer_popularity(oid)
            scored.append((3 * pop["purchases"] + pop["endorsements"], oid))
        scored.sort(reverse=True)
        return [c for s, oid in scored[: self.k] if s > 0 and (c := _from_store(a, oid, "popular", False))]


# --------------------------------------------------------------------------- #
# Hydrators
# --------------------------------------------------------------------------- #


class CoreDataHydrator(Hydrator):
    name = "CoreDataHydrator"

    async def hydrate(self, q, cands):
        a = q["agent"]
        for c in cands:
            c.features["item_tokens"] = item_tokens(c.offer)
            c.features["text_vec"] = a.text_vec(c.offer_id, c.offer)
            c.features["valid"] = bool(c.offer.get("offerId") == c.offer_id)
            c.features["age_h"] = (q["now"] - c.offer["createdAt"]) / 3600


class ProducerHydrator(Hydrator):
    name = "ProducerHydrator"

    async def hydrate(self, q, cands):
        a, rep = q["agent"], q.get("reputation", {})
        stats_cache: dict[str, dict] = {}
        for c in cands:
            st = stats_cache.get(c.producer) or stats_cache.setdefault(c.producer, a.store.merchant_stats(c.producer))
            c.features["reputation"] = rep.get(c.producer, 0.0)
            c.features["refund_rate"] = st["refund_rate"]
            c.features["settled"] = st["sales"] + st["refunds"]
            c.features["labels"] = (a.store.labels_for(c.producer, a.labelers, q["now"])
                                    + a.store.labels_for(c.offer_id, a.labelers, q["now"]))


class MatchHydrator(Hydrator):
    name = "IntentMatchHydrator"

    async def hydrate(self, q, cands):
        a = q["agent"]
        for c in cands:
            best = 0.0
            tv = a.text_vec(c.offer_id, c.offer)  # hydrators are independent: don't rely on CoreDataHydrator
            for intent, vec in q["intent_vecs"]:
                sim = float(vec @ tv)
                if intent["category"] == c.offer["category"]:
                    sim += 0.3
                if c.offer["price"]["amount"] > intent["maxPrice"]:
                    sim -= 0.2
                best = max(best, sim)
            c.features["intent_match"] = max(0.0, min(1.0, best))


class PopularityHydrator(Hydrator):
    name = "PopularityHydrator"

    async def hydrate(self, q, cands):
        store = q["agent"].store
        for c in cands:
            pop = store.offer_popularity(c.offer_id)
            c.features["popularity"] = 3 * pop["purchases"] + pop["endorsements"]
            c.features["new_producer"] = (store.merchant_stats(c.producer)["sales"]
                                          + len(store.offers_by_producer.get(c.producer, [])) < 3)


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #


class DropDuplicatesFilter(Filter):
    name = "DropDuplicatesFilter"

    def filter(self, q, cands):
        best: dict[str, Candidate] = {}
        for c in cands:
            cur = best.get(c.offer_id)
            if cur is None or SOURCE_PRIORITY[c.source] < SOURCE_PRIORITY[cur.source] or (
                    c.source == cur.source and len(c.endorsers) > len(cur.endorsers)):
                best[c.offer_id] = c
        kept = list(best.values())
        removed = [c for c in cands if best.get(c.offer_id) is not c]
        return kept, removed


class CoreDataHydrationFilter(Filter):
    name = "CoreDataHydrationFilter"

    def keep(self, q, c):
        return c.features.get("valid", False)


class AgeFilter(Filter):
    name = "AgeFilter"

    def keep(self, q, c):
        return c.offer["expiresAt"] >= q["now"]


class SelfOfferFilter(Filter):
    name = "SelfTweetFilter"

    def keep(self, q, c):
        return c.producer != q["agent"].did


class PreviouslySeenFilter(Filter):
    name = "PreviouslySeenPostsFilter"

    def keep(self, q, c):
        return c.offer_id not in q["seen"]


class MutedKeywordFilter(Filter):
    name = "MutedKeywordFilter"

    def keep(self, q, c):
        text = (c.offer["title"] + " " + c.offer["description"]).lower()
        return not any(k in text for k in q["agent"].muted_keywords)


class AuthorSocialgraphFilter(Filter):
    name = "AuthorSocialgraphFilter"

    def keep(self, q, c):
        return c.producer not in q["blocked"]


# --------------------------------------------------------------------------- #
# Scorers
# --------------------------------------------------------------------------- #


class PhoenixScorer(Scorer):
    name = "PhoenixScorer"

    def enabled(self, q):
        return q["agent"].rank_mode != "chronological"

    async def score(self, q, cands):
        if not cands:
            return
        model = q["agent"].model
        preds = model.predict(q["user_tokens"], q["history_tokens"],
                              [c.features["item_tokens"] + context_tokens(c) for c in cands])
        for c, p in zip(cands, preds):
            c.phoenix_scores = p


class RankingScorer(Scorer):
    """Value model + author diversity + OON discount + new-producer exploration bonus."""

    name = "RankingScorer"

    async def score(self, q, cands):
        a = q["agent"]
        if a.rank_mode == "chronological":
            for c in cands:
                c.score = c.weighted_score = c.offer["createdAt"]
            return
        w = a.weights
        inputs = [ScoringInputs(c.producer, c.phoenix_scores, c.in_network, is_repost=bool(c.endorsers),
                                exploration_bonus=w.new_producer_bonus if c.features.get("new_producer") else 0.0)
                  for c in cands]
        weighted, final = compute_value_scores(w, inputs)
        for c, ws, fs in zip(cands, weighted, final):
            c.weighted_score, c.score = ws, fs


class DppRerankScorer(Scorer):
    """VMRanker: reorder the head of the ranking for diversity (vm-ranker/dpp.rs)."""

    name = "VMRanker"

    def __init__(self, top_k: int, theta: float = 0.7):
        self.top_k, self.theta = top_k, theta

    def enabled(self, q):
        return q["agent"].rank_mode != "chronological"

    async def score(self, q, cands):
        if len(cands) < 3:
            return
        model = q["agent"].model
        head = sorted(cands, key=lambda c: c.score, reverse=True)[: 3 * self.top_k]
        emb = np.stack([np.concatenate([model.item_vector(c.features["item_tokens"]), c.features["text_vec"]])
                        for c in head])
        order = dpp_order([c.score for c in head], emb, self.top_k, self.theta)
        top = max(c.score for c in cands)
        for rank, idx in enumerate(order):
            head[idx].features["value_score"] = head[idx].score
            head[idx].score = top + (len(order) - rank)


# --------------------------------------------------------------------------- #
# Post-selection visibility and side effects
# --------------------------------------------------------------------------- #


class VisibilityHydrator(Hydrator):
    name = "VFCandidateHydrator"

    async def hydrate(self, q, cands):
        rules = q["agent"].visibility_rules
        for c in cands:
            c.visibility, why = visibility.evaluate(q, c, rules)
            if why:
                c.reasons.append(f"vf:{why}")


class VFFilter(Filter):
    name = "VFFilter"

    def keep(self, q, c):
        return c.visibility != visibility.DROP


class RecordServed(SideEffect):
    name = "RecordServedSideEffect"

    async def run(self, q, selected, non_selected):
        q["agent"].served.update(c.offer_id for c in selected)


def build_for_you_pipeline(result_size: int = 10) -> CandidatePipeline:
    return CandidatePipeline(
        name="AgoraForYou",
        query_hydrators=[UserContextHydrator(), ReputationHydrator(), SimClustersHydrator()],
        sources=[ThunderSource(), IntentResponseSource(), PhoenixRetrievalSource(), SimClustersSource(), PopularSource()],
        hydrators=[CoreDataHydrator(), ProducerHydrator(), MatchHydrator(), PopularityHydrator()],
        filters=[DropDuplicatesFilter(), CoreDataHydrationFilter(), AgeFilter(), SelfOfferFilter(),
                 PreviouslySeenFilter(), MutedKeywordFilter(), AuthorSocialgraphFilter()],
        scorers=[PhoenixScorer(), RankingScorer(), DppRerankScorer(top_k=result_size)],
        selector=TopKScoreSelector(result_size * 2),
        post_selection_hydrators=[VisibilityHydrator()],
        post_selection_filters=[VFFilter()],
        side_effects=[RecordServed()],
        result_size=result_size,
    )



__all__ = ["build_for_you_pipeline", "item_tokens", "context_tokens", "reputation_scores", "engagement_graph",
           "offer_text"]

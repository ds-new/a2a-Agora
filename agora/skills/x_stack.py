"""X's recommendation stack (ported from xai-org/x-algorithm) as optional agent skills.

In v0.1 the For You pipeline *was* the consumer agent. Here it is a toolbox the
agent's brain may or may not use, on candidates the agent itself gathered:

  x_rank        Phoenix-lite multi-action prediction -> value model (user-owned weights)
                -> author diversity / OON discount -> DPP diversity rerank
  x_retrieve    Phoenix two-tower-lite retrieval over the agent's local store of verified offers
  x_safety      visibility filtering (labels from subscribed labelers, X-style rules)
  x_reputation  UserCred PageRank over verifiable settlements, endorsements and follows
  x_audience    SimClusters look-alikes, for producers deciding whom to approach
  x_for_you     the complete pipeline, if the agent just wants a ready-made feed
"""

from __future__ import annotations

from .. import clock
from ..mind.skills import Skill
from ..ranking import visibility
from ..ranking.for_you import (
    CoreDataHydrator,
    DropDuplicatesFilter,
    MatchHydrator,
    PhoenixScorer,
    PopularityHydrator,
    ProducerHydrator,
    RankingScorer,
    ReputationHydrator,
    UserContextHydrator,
    build_for_you_pipeline,
    engagement_graph,
    item_tokens,
    reputation_scores,
)
from ..ranking.for_you import DppRerankScorer
from ..ranking.pipeline import Candidate, CandidatePipeline, Source, TopKScoreSelector
from ..ranking.retrieval import retrieve, user_vectors
from ..ranking.simclusters import interested_in, known_for

ORIGIN = "x-algorithm"


class _AgentSupplied(Source):
    """The candidates come from the agent (proposals, friends, its own searches), not from X's sources."""

    name = "AgentSuppliedCandidates"

    def __init__(self, items: list[Candidate]):
        self.items = items

    async def source(self, q):
        return list(self.items)  # same objects: hydrated features stay on the agent's items


def _query(agent) -> dict:
    return {"agent": agent, "now": clock.now()}


async def hydrate(agent, items: list[Candidate]) -> None:
    """Fill the features X's models read (also used to log training examples consistently)."""
    q = _query(agent)
    for h in (UserContextHydrator(), ReputationHydrator()):
        q.update(await h.hydrate(q))
    for h in (CoreDataHydrator(), ProducerHydrator(), MatchHydrator(), PopularityHydrator()):
        await h.hydrate(q, items)


async def x_rank(agent, items: list[Candidate], k: int | None = None) -> dict[str, dict]:
    if not items:
        return {}
    pipe = CandidatePipeline(
        name="XRankSkill", query_hydrators=[UserContextHydrator(), ReputationHydrator()],
        sources=[_AgentSupplied(items)],
        hydrators=[CoreDataHydrator(), ProducerHydrator(), MatchHydrator(), PopularityHydrator()],
        filters=[DropDuplicatesFilter()], scorers=[PhoenixScorer(), RankingScorer(), DppRerankScorer(top_k=k or len(items))],
        selector=TopKScoreSelector(len(items)), post_selection_hydrators=[], post_selection_filters=[],
        side_effects=[], result_size=len(items))
    res = await pipe.execute(_query(agent))
    n = len(res.selected)
    out = {}
    for i, c in enumerate(res.selected):
        out[c.offer_id] = {"score": 1.0 - i / max(1, n - 1) if n > 1 else 1.0, "rank": i,
                           "p": {a: round(c.phoenix_scores.get(a, 0.0), 3)
                                 for a in ("click", "favorite", "purchase", "not_interested", "report")}}
    return out


async def x_retrieve(agent, need=None, k: int = 20) -> list[Candidate]:
    now = clock.now()
    pool = [(oid, tok, p) for oid, (tok, p) in agent.store.offers.items()
            if oid not in agent.memory.bought and oid not in agent.memory.unsafe and p["producer"] not in agent.blocked and p["producer"] != agent.did
            and p["expiresAt"] >= now and (need is None or (p["category"] == need.category and p["kind"] == need.kind))]
    if not pool:
        return []
    texts = [need.text] if need is not None else [n.text for n in agent.profile.open_needs()]
    user_emb, user_txt = user_vectors(agent.model, agent.history[-24:], texts)
    hits = retrieve(agent.model, user_emb, user_txt, [(oid, item_tokens(p), agent.text_vec(oid, p)) for oid, _, p in pool], k)
    by_id = {oid: (tok, p) for oid, tok, p in pool}
    return [Candidate(oid, by_id[oid][0], by_id[oid][1], "x_retrieve") for oid, _ in hits]


async def x_safety(agent, items: list[Candidate]) -> dict[str, tuple[str, str | None]]:
    q = _query(agent)
    q.update({"blocked": set(agent.blocked), "region": agent.profile.region, "max_item_price": agent.max_item_price,
              "reputation": agent.cached("reputation", lambda a: reputation_scores(a.store, a.did, a.following))})
    await ProducerHydrator().hydrate(q, items)
    return {c.offer_id: visibility.evaluate(q, c, agent.visibility_rules) for c in items}


async def x_reputation(agent, dids: list[str] | None = None) -> dict[str, float]:
    rep = agent.cached("reputation", lambda a: reputation_scores(a.store, a.did, a.following))
    return rep if dids is None else {d: rep.get(d, 0.0) for d in dids}


async def x_audience(agent, category: str | None = None) -> dict[str, float]:
    """Consumers whose verified engagement puts them in this producer's SimClusters community."""
    eng = agent.cached("engagement", lambda a: engagement_graph(a.store))
    kf = agent.cached("known_for", lambda a: known_for(eng))
    mine = kf.get(agent.did)
    if mine is None:
        return {}
    out = {}
    for consumer, prods in eng.items():
        affinity = interested_in(prods, kf).get(mine, 0.0)
        if affinity > 0:
            out[consumer] = round(affinity, 3)
    return out


async def x_for_you(agent, k: int = 10) -> list[Candidate]:
    res = await build_for_you_pipeline(k).execute(_query(agent))
    return res.selected


def consumer_x_skills() -> list[Skill]:
    return [
        Skill("x_rank", "Rank candidate items for the principal with X's Phoenix multi-action model, the value "
              "model (weights owned by the principal), author diversity and DPP. Returns per-item score in [0,1], "
              "rank and predicted action probabilities.", {"items": "candidate item ids", "k": "head size"},
              x_rank, ORIGIN),
        Skill("x_retrieve", "Search the agent's local store of verified offers with Phoenix-style two-tower "
              "retrieval, optionally for one need.", {"need": "need id or null", "k": "max results"},
              x_retrieve, ORIGIN),
        Skill("x_safety", "Visibility verdicts (ALLOW, NOTICE, INTERSTITIAL, DROP) from labels of the labelers "
              "the principal subscribes to and X-style rules.", {"items": "candidate item ids"}, x_safety, ORIGIN),
        Skill("x_reputation", "UserCred-style PageRank reputation in [0,1] of producers, from verified "
              "settlements, endorsements and follows.", {"dids": "producer DIDs"}, x_reputation, ORIGIN),
        Skill("x_for_you", "Run X's complete For You pipeline over everything the agent knows.",
              {"k": "feed size"}, x_for_you, ORIGIN),
    ]


def producer_x_skills() -> list[Skill]:
    return [Skill("x_audience", "SimClusters look-alike audience: consumers whose verified purchases and "
                  "endorsements place them in this producer's community, with affinity scores.",
                  {"category": "optional category"}, x_audience, ORIGIN)]

"""Basic market skills every agent has (no X components involved).

Consumer side:  match_needs, trust, labels_check, search_local, ask_peers, query_producers
Producer side:  demand_scan
"""

from __future__ import annotations

from .. import clock
from ..mind.skills import Skill
from ..protocol.records import sign_instruction
from ..protocol.schema import endorsement_chain, verify_offer
from ..ranking.pipeline import Candidate
from ..ranking.retrieval import text_vector

# ------------------------------------------------------------------ consumer


def need_fit(agent, item: Candidate, need) -> float:
    o = item.offer
    if o["kind"] != need.kind or o["category"] != need.category:
        return 0.0
    sim = float(agent.text_vec(item.offer_id, o) @ text_vector(need.text))
    fit = 0.6 + 0.4 * min(1.0, 2 * sim)
    price = o["price"]["amount"]
    if price > need.max_price * 1.15:   # out of reach even after negotiating
        fit *= 0.4
    elif price > need.max_price:        # may come down in negotiation
        fit *= 0.85
    return round(fit, 3)


async def match_needs(agent, items: list[Candidate]) -> dict[str, tuple]:
    needs = agent.profile.open_needs()
    out = {}
    for it in items:
        out[it.offer_id] = max(((n, need_fit(agent, it, n)) for n in needs), key=lambda x: x[1], default=(None, 0.0))
    return out


async def trust(agent, items: list[Candidate]) -> dict[str, float]:
    """First-hand experience + verified settlement stats (+ UserCred if the agent has the X skill) + labels."""
    dids = sorted({it.producer for it in items})
    rep = await agent.skills.call(agent, "x_reputation", dids=dids) if agent.skills.has("x_reputation") else {}
    now = clock.now()
    out = {}
    for d in dids:
        st = agent.store.merchant_stats(d)
        verified = (1 + st["sales"]) / (2 + st["sales"] + 3 * st["refunds"])
        t = 0.5 * agent.memory.trust(d) + 0.5 * verified
        if d in rep:
            t = 0.6 * t + 0.4 * (0.3 + 0.7 * rep[d])
        for lab in agent.store.labels_for(d, agent.labelers, now):
            if lab["label"] in ("fraud", "scam-risk", "hash-mismatch"):
                t *= 1 - 0.8 * lab["severity"]
        out[d] = round(t, 3)
    return out


async def labels_check(agent, items: list[Candidate]) -> dict[str, tuple[str, str | None]]:
    now = clock.now()
    out = {}
    for it in items:
        labs = agent.store.labels_for(it.producer, agent.labelers, now) + agent.store.labels_for(it.offer_id, agent.labelers, now)
        sev = max((lab["severity"] for lab in labs if lab["label"] in ("fraud", "hash-mismatch", "scam-risk")), default=0.0)
        out[it.offer_id] = ("DROP", "label") if sev >= 0.5 else ("INTERSTITIAL", "label") if sev >= 0.3 else ("ALLOW", None)
    return out


async def search_local(agent, need=None, k: int = 10, explore: bool = False) -> list[Candidate]:
    """Search verified offers already known: for a need, for the principal's interests, or (explore=True)
    in categories the principal never mentioned and the agent has barely tried."""
    now = clock.now()
    want = text_vector(need.text) if need is not None else None
    scored = []
    for oid, (tok, p) in agent.store.offers.items():
        if oid in agent.memory.bought or oid in agent.memory.unsafe or p["producer"] in agent.blocked or p["expiresAt"] < now:
            continue
        cat = p["category"]
        if need is not None:
            if cat != need.category or p["kind"] != need.kind:
                continue
            s = float(agent.text_vec(oid, p) @ want)
        elif explore:
            if (oid in agent.memory.decided or cat in agent.profile.dislikes or cat in agent.profile.stated_likes
                    or agent.memory.categories[cat]["shown"] >= 2):
                continue
            s = -agent.memory.categories[cat]["shown"] + 0.1 * agent.rng.random()
        else:
            s = agent.profile.like(cat)
            if s < 0.3:
                continue
        scored.append((s + 1e-9 * p["createdAt"], oid, tok, p))
    scored.sort(reverse=True)
    return [Candidate(oid, tok, p, "search") for _, oid, tok, p in scored[:k]]


def _items_from_reply(entries: list[dict], source: str, sender: str, in_network: bool) -> list[Candidate]:
    out = []
    for e in entries[:6]:
        try:
            if e.get("endorsement"):
                ch = endorsement_chain(e["endorsement"])
                out.append(Candidate(ch["offer"]["offerId"], ch["offerToken"], ch["offer"], source, in_network=in_network,
                                     endorsers=ch["endorsers"], endorsement_token=e["endorsement"], meta={"from": sender}))
            else:
                offer = verify_offer(e["offer"])
                out.append(Candidate(offer["offerId"], e["offer"], offer, source, in_network=in_network,
                                     meta={"from": sender, "pitch": e.get("pitch", "")}))
        except Exception:  # noqa: BLE001  unverifiable entries are ignored
            continue
    return out


def signed_query(agent, target: str, need, **extra) -> dict:
    """An agora.query whose asker is proven by signature and bound to one recipient (friends answer only friends)."""
    return {"type": "agora.query", "query": sign_instruction(agent.key, {"type": "agora.query", "target": target,
                                                                          "need": need.brief(), **extra})}


async def ask_peers(agent, need, limit: int = 3) -> list[Candidate]:
    """Ask friends' agents whether they know something that satisfies this need."""
    friends = sorted(agent.friends.items(), key=lambda kv: -agent.memory.friend_precision(kv[0]))[:limit]
    out: list[Candidate] = []
    for did, url in friends:
        try:
            res = await agent.send(url, signed_query(agent, did, need))
            out += _items_from_reply((agent.status_data(res, "agora.query.reply") or {}).get("items", []), "friend",
                                     did, True)
        except Exception:  # noqa: BLE001
            agent.metrics.inc("query_fail")
    await agent.ingest([c.endorsement_token or c.token for c in out])  # keep what we were told, verified
    return out


async def query_producers(agent, need, limit: int = 4) -> list[Candidate]:
    """Ask producers known (from verified offers) to make this kind of thing."""
    latest: dict[str, tuple[float, str]] = {}
    for _, p in agent.store.offers.values():
        if p["category"] == need.category and p["kind"] == need.kind and p["producer"] not in agent.blocked:
            if p["createdAt"] > latest.get(p["producer"], (0, ""))[0]:
                latest[p["producer"]] = (p["createdAt"], p["producerUrl"])
    targets = sorted(latest.items(), key=lambda kv: -agent.memory.trust(kv[0]))[:limit]
    out: list[Candidate] = []
    for did, (_, url) in targets:
        try:
            res = await agent.send(url, signed_query(agent, did, need, region=agent.profile.region))
            out += _items_from_reply((agent.status_data(res, "agora.query.reply") or {}).get("items", []),
                                     "producer-query", did, False)
        except Exception:  # noqa: BLE001
            agent.metrics.inc("query_fail")
    await agent.ingest([c.token for c in out])
    return out


def consumer_base_skills() -> list[Skill]:
    return [
        Skill("match_needs", "For each candidate, the open need it best satisfies and a fit score in [0,1].",
              {"items": "candidate item ids"}, match_needs),
        Skill("trust", "Trust in each candidate's producer: own experience, verified settlements, labels "
              "(plus UserCred when x_reputation is available).", {"items": "candidate item ids"}, trust),
        Skill("labels_check", "Verdict from labels published by the labelers the principal subscribes to.",
              {"items": "candidate item ids"}, labels_check),
        Skill("search_local", "Search verified offers the agent already knows (from gossip) for a need, for the "
              "principal's interests, or with explore=true in categories the principal never mentioned.",
              {"need": "need id or null", "k": "max results", "explore": "bool"}, search_local),
        Skill("ask_peers", "Ask friends' agents over A2A what they know that satisfies a need.",
              {"need": "need id"}, ask_peers),
        Skill("query_producers", "Ask producers that make this category over A2A for matching offers.",
              {"need": "need id"}, query_producers),
    ]


# ------------------------------------------------------------------ producer


async def demand_scan(agent) -> dict[str, dict]:
    """What the network says it wants, per category this producer can make."""
    now = clock.now()
    out: dict[str, dict] = {c: {"audience": {}, "intents": []} for c in agent.capabilities}
    cards = {p["agent"]: p for p in agent.store.cards(now)}
    cards.update({d: p for d, p in agent.subscriber_cards.items() if p["expiresAt"] >= now})
    for did, card in cards.items():
        if did in agent.blocked_by:
            continue
        for cat, w in card["categories"].items():
            cap = agent.capabilities.get(cat)
            if cap and cap["kind"] in card["kinds"] and cat not in card["avoid"]:
                out[cat]["audience"][did] = {"url": card["agentUrl"], "weight": w, "priceMax": card["priceMax"].get(cat),
                                             "maxPerDay": card["maxPerDay"], "region": card.get("region"),
                                             "source": "subscriber" if did in agent.subscribers else "card"}
    for _, it in agent.store.intents.values():
        cap = agent.capabilities.get(it["category"])
        if (cap and it["expiresAt"] >= now and cap["kind"] == it["kind"] and it["intentId"] not in agent.answered_intents
                and it["consumer"] not in agent.blocked_by):
            out[it["category"]]["intents"].append(it)
            out[it["category"]]["audience"][it["consumer"]] = {
                "url": it["consumerUrl"], "weight": 1.0, "priceMax": it["maxPrice"], "maxPerDay": 1,
                "region": it.get("region"), "source": "intent", "intentId": it["intentId"]}
    for cat, d in out.items():
        fb = agent.feedback_stats[cat]
        d["accept_rate"] = round((fb["accept"] + 1) / (fb["n"] + 3), 3)
        d["too_expensive"] = round(fb["too-expensive"] / max(1.0, fb["n"]), 3)
        d["n_feedback"] = int(fb["n"])
    agent.last_demand = out
    return out


def producer_base_skills() -> list[Skill]:
    return [Skill("demand_scan", "Aggregate interest cards, open intents and feedback into demand per category.",
                  {}, demand_scan)]


__all__ = ["consumer_base_skills", "producer_base_skills", "need_fit", "demand_scan"]

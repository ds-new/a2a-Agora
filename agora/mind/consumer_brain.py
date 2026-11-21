"""Rule brain of a consumer agent: deliberate, explainable, no LLM required.

Each tick it
  1. goes looking for what open needs require (local search -> producers -> friends -> broadcast intent),
  2. rejects what must not reach the principal (blocked, unsafe, disliked, unshippable, untrusted),
  3. buys the best fit for each need,
  4. picks what the principal will see within their attention budget, keeping one
     slot to explore categories the principal never mentioned,
  5. manages relationships (subscribe to producers that keep delivering, block those that waste attention).

X's ranking stack is optional: if the agent has the ``x_rank`` skill it is used to
order what competes for scarce attention and to pick the exploration item; if
not, the agent orders by its own utility. Eligibility always comes from the
principal's profile, never from engagement predictions.
"""

from __future__ import annotations

from ..protocol.schema import PHYSICAL
from ..skills.market import need_fit
from .brain import Decision

EXPLAIN = {
    "blocked": "producer is blocked", "unsafe": "flagged by a subscribed labeler / safety rules",
    "disliked-category": "the principal said they don't want this category", "not-shippable": "does not ship to the principal",
    "low-trust": "producer has a bad verified record", "off-topic": "does not match what the principal likes",
    "too-expensive": "above the principal's price ceiling", "attention-budget": "relevant, but attention for this tick is used up",
    "duplicate": "already decided",
}
SOURCE_RANK = {"friend": 0, "intent": 1, "subscribed": 2, "producer-query": 3, "cold": 4, "x_retrieve": 5, "search": 6}


class ConsumerRuleBrain:
    def __init__(self, accept_threshold: float = 0.22, need_fit_min: float = 0.55, x_blend: float = 0.5,
                 explore_slots: int = 1, explore_rate: float = 0.35, explore_max_shows: int = 2,
                 block_after: int = 6, block_precision: float = 0.2):
        self.accept_threshold, self.need_fit_min, self.x_blend = accept_threshold, need_fit_min, x_blend
        self.explore_slots, self.explore_rate, self.explore_max_shows = explore_slots, explore_rate, explore_max_shows
        self.block_after, self.block_precision = block_after, block_precision

    # ------------------------------------------------------------------ main
    async def decide(self, agent, obs: dict) -> list[Decision]:
        prof, skills = agent.profile, agent.skills
        exclude = obs.get("exclude", set())
        items = self._dedupe([it for it in obs["items"] if it.offer_id not in exclude])
        needs = [n for n in prof.open_needs(obs["now"]) if n.need_id not in exclude]
        decisions: list[Decision] = []

        # 1) go and get what open needs require
        for need in needs:
            if any(need_fit(agent, it, need) >= self.need_fit_min for it in items):
                continue
            tools = ["x_retrieve" if skills.has("x_retrieve") else "search_local", "query_producers"]
            if need.attempts >= 1:
                tools.append("ask_peers")
            found = []
            for tool in tools:
                got = await skills.call(agent, tool, need=need)
                found += got
                if any(need_fit(agent, g, need) >= self.need_fit_min for g in got):
                    break
            known = {it.offer_id for it in items}
            fresh = [g for g in found if g.offer_id not in agent.memory.bought and g.offer_id not in agent.memory.unsafe
                     and g.offer_id not in known]
            items = self._dedupe(items + fresh)
            obs["items"].extend(fresh)
            if (not any(need_fit(agent, g, need) >= self.need_fit_min for g in fresh) and need.attempts >= 1
                    and need.intent_token is None):
                decisions.append(Decision("intent", need.need_id, reason="search, producers and friends had nothing "
                                          "suitable; broadcasting a signed intent so producers can come to us"))
            need.attempts += 1

        if items:
            decisions += await self._decide_items(agent, items, needs, obs)
        return decisions + self._relationships(agent)

    async def _decide_items(self, agent, items, needs, obs) -> list[Decision]:
        prof, skills = agent.profile, agent.skills
        decisions: list[Decision] = []
        safety = await skills.call(agent, "x_safety" if skills.has("x_safety") else "labels_check", items=items)
        trust = await skills.call(agent, "trust", items=items)
        fits = await skills.call(agent, "match_needs", items=items)

        # 2) hard rejections (items seen before and found again for a need are dropped silently)
        ok = []
        for it in items:
            verdict = safety.get(it.offer_id, ("ALLOW", None))[0]
            it.visibility = verdict  # the principal sees warnings the agent decided to show anyway
            if verdict == "INTERSTITIAL":
                trust[it.producer] = trust.get(it.producer, 0.5) * 0.5
            why = self._hard_reject(agent, it, verdict, trust)
            if why:
                if it.offer_id not in agent.memory.decided:
                    decisions.append(Decision("reject", it.offer_id, {"reasons": [why]}, reason=EXPLAIN[why]))
            else:
                ok.append(it)

        # 3) needs: buy the best fit for each
        taken: set[str] = set()
        for need in needs:
            cands = [it for it in ok if it.offer_id not in taken and fits[it.offer_id][0] is need
                     and fits[it.offer_id][1] >= self.need_fit_min]
            if not cands:
                continue
            best = max(cands, key=lambda it: fits[it.offer_id][1] * (0.5 + 0.5 * trust.get(it.producer, 0.5))
                       - 0.15 * it.offer["price"]["amount"] / max(1.0, need.max_price))
            price = best.offer["price"]["amount"]
            if price <= 0:  # free information: show it; reading it meets the need
                if best.offer_id not in agent.memory.decided:
                    decisions.append(Decision("accept", best.offer_id, {"need": need.need_id},
                                              reason=f"free and matches need '{need.text}' (fit {fits[best.offer_id][1]:.2f})"))
                    taken.add(best.offer_id)
                continue
            decisions.append(Decision("buy", best.offer_id, {"need": need.need_id, "reservation": need.max_price},
                                      reason=f"best match for need '{need.text}': fit {fits[best.offer_id][1]:.2f}, "
                                             f"trust {trust.get(best.producer, 0.5):.2f}, list {price} vs limit {need.max_price}"))
            taken.add(best.offer_id)

        # 4) curation within the attention budget (only for things not decided before)
        rest = [it for it in ok if it.offer_id not in taken and it.offer_id not in agent.memory.decided]
        util = {it.offer_id: self._utility(agent, it, trust) for it in rest}
        eligible = [it for it in rest if util[it.offer_id] >= self.accept_threshold]
        explore_pool = [it for it in rest if util[it.offer_id] < self.accept_threshold
                        and agent.memory.categories[it.offer["category"]]["shown"] < self.explore_max_shows
                        and it.offer["price"]["amount"] <= prof.price_ceiling(it.kind, it.offer["category"])]
        slots = prof.attention_per_tick
        exploring = prof.explore and agent.rng.random() < self.explore_rate  # epsilon-style: not every tick
        if not exploring:
            explore_pool = []
        if exploring and not explore_pool and self.explore_slots:
            # nothing unfamiliar arrived: go and find one thing from a category the principal never mentioned
            probe = await skills.call(agent, "search_local", explore=True, k=12)
            probe = [p for p in probe if p.offer_id not in {it.offer_id for it in items}]
            if probe:
                verdicts = await skills.call(agent, "x_safety" if skills.has("x_safety") else "labels_check", items=probe)
                probe = [p for p in probe if verdicts.get(p.offer_id, ("ALLOW", None))[0] == "ALLOW"]
                obs["items"].extend(probe)
                explore_pool = probe
                for p in probe:
                    util[p.offer_id] = self._utility(agent, p, trust)
        explore = min(self.explore_slots, len(explore_pool), slots)
        xs: dict = {}
        if skills.has("x_rank") and (len(eligible) > slots - explore or explore_pool):
            xs = await skills.call(agent, "x_rank", items=eligible + explore_pool)
            obs["used_x_rank"] = True

        def order_key(it):
            u = util[it.offer_id]
            if xs:
                return (1 - self.x_blend) * u + self.x_blend * xs.get(it.offer_id, {}).get("score", 0.0)
            return u

        eligible.sort(key=order_key, reverse=True)
        accepted: set[str] = set()
        for it in eligible:
            if len(accepted) < slots - explore:
                accepted.add(it.offer_id)
                decisions.append(Decision("accept", it.offer_id, reason=self._accept_reason(agent, it, util, xs)))
        if explore:
            pick_from = sorted(explore_pool, key=lambda it: (xs.get(it.offer_id, {}).get("score", 0.0) if xs
                                                              else util[it.offer_id]), reverse=True)
            for it in pick_from[:explore]:
                accepted.add(it.offer_id)
                decisions.append(Decision("accept", it.offer_id, {"explore": True},
                                          reason=f"exploring '{it.offer['category']}', which the principal never rated"
                                                 + (" (picked by x_rank)" if xs else "")))
        for it in rest:
            if it.offer_id in accepted or it.source == "search":
                continue
            price_cap = prof.price_ceiling(it.kind, it.offer["category"])
            if it.offer["price"]["amount"] > price_cap:
                why = "too-expensive"
            elif util[it.offer_id] < self.accept_threshold:
                why = "off-topic"
            else:
                why = "attention-budget"
            decisions.append(Decision("reject", it.offer_id, {"reasons": [why]}, reason=EXPLAIN[why]))
        return decisions

    # ------------------------------------------------------------------ parts
    @staticmethod
    def _dedupe(items):
        best = {}
        for it in items:
            cur = best.get(it.offer_id)
            if cur is None or SOURCE_RANK.get(it.source, 9) < SOURCE_RANK.get(cur.source, 9):
                best[it.offer_id] = it
        return list(best.values())

    @staticmethod
    def _hard_reject(agent, it, verdict: str, trust: dict) -> str | None:
        prof = agent.profile
        if it.producer in agent.blocked:
            return "blocked"
        if verdict == "DROP":
            return "unsafe"
        if it.offer["category"] in prof.dislikes:
            return "disliked-category"
        if it.kind == PHYSICAL and prof.region not in it.offer["shipping"]["regions"]:
            return "not-shippable"
        if trust.get(it.producer, 0.5) < prof.min_trust:
            return "low-trust"
        return None

    @staticmethod
    def _utility(agent, it, trust: dict) -> float:
        prof = agent.profile
        cat = it.offer["category"]
        ceiling = prof.price_ceiling(it.kind, cat)
        over = max(0.0, it.offer["price"]["amount"] / ceiling - 1.0) if ceiling > 0 else 0.0
        social = 0.08 * agent.memory.friend_precision(it.meta.get("from", "")) if it.source == "friend" else 0.0
        return prof.like(cat) * (0.55 + 0.45 * trust.get(it.producer, 0.5)) - 0.6 * over + social

    @staticmethod
    def _accept_reason(agent, it, util, xs) -> str:
        cat = it.offer["category"]
        base = f"principal's interest in '{cat}' is {agent.profile.like(cat):.2f}; utility {util[it.offer_id]:.2f}"
        if it.source == "friend":
            base += "; recommended by a friend"
        if xs:
            base += f"; x_rank position {xs.get(it.offer_id, {}).get('rank', '-')}"
        return base

    def _relationships(self, agent) -> list[Decision]:
        out = []
        mem = agent.memory
        for did, c in list(mem.producers.items()):
            if did in agent.blocked:
                continue
            if c["proposed"] >= self.block_after and mem.precision(did) < self.block_precision:
                out.append(Decision("block", did, reason=f"only {mem.precision(did):.0%} of {int(c['proposed'])} "
                                                         "proposals were worth the principal's attention"))
            elif (did not in agent.subscriptions and did in agent.producer_urls
                  and c["positive"] + 2 * c["bought_ok"] >= 3 and mem.trust(did) >= 0.65):
                out.append(Decision("subscribe", did, reason=f"delivered well {int(c['positive'] + c['bought_ok'])} "
                                                             f"times (trust {mem.trust(did):.2f})"))
        if agent.card_stale():
            out.append(Decision("share_card", None, reason="learned interests drifted from the last interest card"))
        return out

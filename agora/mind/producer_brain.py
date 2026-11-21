"""Rule brains of producer agents.

ProducerRuleBrain decides from demand, not from a broadcast list:
  phase "produce": which category to make next (Thompson sampling over observed
                   acceptance, weighted by how many agents declared interest and
                   how many open intents exist) and how to reprice from feedback;
  phase "target":  which consumer agents to approach with each live offer,
                   sampling P(accept) per (consumer, category) from a Beta posterior
                   seeded by the weight on their interest card and updated by their
                   signed accept/reject feedback. SimClusters (x_audience) can add
                   look-alike signal if the agent has that skill.

SpamBrain is the adversary used in the simulation: it sends every offer to every
agent it can reach and ignores feedback.
"""

from __future__ import annotations

import random

from ..protocol.schema import INFORMATION, PHYSICAL
from .brain import Decision


class ProducerRuleBrain:
    def __init__(self, send_budget: int = 20, min_p: float = 0.15, seed: int = 0, learn: bool = True):
        self.send_budget, self.min_p, self.learn = send_budget, min_p, learn  # learn=False: ablation, cards only
        self.rng = random.Random(seed)

    async def decide(self, agent, obs: dict) -> list[Decision]:
        if obs.get("phase") == "target":
            return await self._target(agent, obs.get("offers", []))
        return await self._produce(agent)

    async def _produce(self, agent) -> list[Decision]:
        demand = await agent.skills.call(agent, "demand_scan")
        out: list[Decision] = []
        for cat, d in demand.items():
            if not self.learn:
                break
            if d["n_feedback"] >= 4 and d["too_expensive"] > 0.3:
                out.append(Decision("reprice", cat, {"factor": 0.92},
                                    reason=f"{d['too_expensive']:.0%} of feedback on {cat} said too expensive"))
            elif d["n_feedback"] >= 4 and d["accept_rate"] > 0.6:
                out.append(Decision("reprice", cat, {"factor": 1.03}, reason=f"{d['accept_rate']:.0%} acceptance on {cat}"))
        scores, unreached = {}, {}
        live = agent.active_offer_tokens()
        for cat, d in demand.items():
            fb = agent.feedback_stats[cat] if self.learn else {"accept": 0, "n": 0}
            p = self.rng.betavariate(1 + fb["accept"], 2 + fb["n"] - fb["accept"])
            # interested agents that none of our live offers in this category has reached yet
            ids = [o["offerId"] for _, o in live if o["category"] == cat]
            unreached[cat] = [did for did in d["audience"] if not any((did, oid) in agent.proposed for oid in ids)]
            reach = sum(d["audience"][did]["weight"] for did in unreached[cat]) + 0.2 * len(d["audience"])
            margin = max(0.3, agent.price_for(cat) - agent.capabilities[cat]["unit_cost"])
            scores[cat] = (reach * p + 2.0 * len(d["intents"])) * margin
        if scores:
            best = max(scores, key=scores.get)
            d = demand[best]
            info = agent.capabilities[best]["kind"] == INFORMATION
            # media publish on a cadence; shops add a product line when their live ones have reached everyone
            make = scores[best] > 0 and (info or agent.active_count(best) < 2 or bool(d["intents"])
                                         or (not unreached[best] and self.rng.random() < 0.5))
            if make:
                paid = info and (bool(d["intents"]) or self.rng.random() < 0.35)
                out.append(Decision("produce", best, {"paid": paid},
                                    reason=f"{len(d['audience'])} agents interested in {best}, "
                                           f"{len(unreached[best])} not reached yet, {len(d['intents'])} open intents, "
                                           f"acceptance so far {d['accept_rate']:.0%}"))
        return out

    async def _target(self, agent, offers: list[tuple[str, dict]]) -> list[Decision]:
        demand = agent.last_demand or await agent.skills.call(agent, "demand_scan")
        boost = await agent.skills.call(agent, "x_audience") if agent.skills.has("x_audience") else {}
        scored = []
        for _, offer in offers:
            cat = offer["category"]
            for did, a in demand.get(cat, {}).get("audience", {}).items():
                if (did, offer["offerId"]) in agent.proposed or agent.sent_today(did) >= a["maxPerDay"]:
                    continue
                if offer["kind"] == PHYSICAL and a.get("region") and a["region"] not in offer["shipping"]["regions"]:
                    continue
                st = agent.consumer_stats[(did, cat)] if self.learn else {"accept": 0, "reject": 0}
                w = float(a["weight"])
                p = self.rng.betavariate(1 + 2 * w + st["accept"], 1 + 2 * (1 - w) + st["reject"])
                if a.get("priceMax") and offer["price"]["amount"] > 1.1 * a["priceMax"]:
                    p *= 0.3
                if a["source"] == "intent":
                    p += 0.5
                p += 0.2 * boost.get(did, 0.0)
                scored.append((p, did, a, offer))
        scored.sort(key=lambda x: -x[0])
        out, this_tick = [], set()
        for p, did, a, offer in scored:
            if len(out) >= self.send_budget or p < self.min_p:
                break
            if did in this_tick:
                continue
            this_tick.add(did)
            out.append(Decision("propose", offer["offerId"], {"to": did, "url": a["url"], "intentId": a.get("intentId")},
                                reason=f"est. P(accept) {p:.2f} (card weight {a['weight']}, source {a['source']})"))
        return out


class SpamBrain:
    """Adversary: makes something every tick and sends it to everyone it can reach."""

    def __init__(self, send_budget: int = 60, seed: int = 0):
        self.send_budget = send_budget
        self.rng = random.Random(seed)

    async def decide(self, agent, obs: dict) -> list[Decision]:
        if obs.get("phase") != "target":
            await agent.skills.call(agent, "demand_scan")
            cat = self.rng.choice(sorted(agent.capabilities))
            return [Decision("produce", cat, {"paid": agent.capabilities[cat]["kind"] == INFORMATION}, reason="volume")]
        targets = {}
        for d in (agent.last_demand or {}).values():
            for did, a in d["audience"].items():
                targets[did] = a["url"]
        for peer in agent.peers.values():
            if "consumer" in peer.roles:
                targets.setdefault(peer.did, peer.rpc_url)
        out = []
        for _, offer in offers_newest(obs.get("offers", [])):
            for did, url in targets.items():
                if len(out) >= self.send_budget:
                    return out
                if (did, offer["offerId"]) not in agent.proposed:
                    out.append(Decision("propose", offer["offerId"], {"to": did, "url": url}, reason="blast"))
        return out


def offers_newest(offers):
    return sorted(offers, key=lambda x: -x[1]["createdAt"])

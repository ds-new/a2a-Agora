"""A synthetic economy for the agent network, with ground truth kept outside the agents.

Each principal has hidden tastes; they *tell* their agent only part of it (four
likes, two dislikes, price ceilings) and react to what the agent shows them. Each
producer has hidden quality. Agents see only signed objects, A2A messages and
their own principal's reactions.

Consumers are split: half register X's ranking stack as skills (x_rank,
x_retrieve, x_safety, x_reputation), half decide with base skills only, so the
contribution of the X skills can be measured inside the same network. Two bad
actors take part: a counterfeit seller that spams everyone it can reach, and a
paid-information seller that delivers something other than what it committed to.
"""

from __future__ import annotations

import asyncio
import math
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass

from .. import clock
from ..agents.base import AgoraAgent, Peer
from ..agents.consumer import ConsumerAgent, Reaction, make_consumer_brain
from ..agents.infra import BankAgent, EscrowAgent, LabelerAgent, LogisticsAgent
from ..agents.merchant import Listing, MerchantAgent, make_producer_brain
from ..crypto import KeyPair
from ..mind.producer_brain import SpamBrain
from ..mind.profile import PRIOR, UserProfile
from ..net import HttpServerGroup, MemoryNetwork, free_port
from ..protocol.schema import INFORMATION, PHYSICAL
from ..ranking.for_you import reputation_scores
from ..ranking.visibility import INTERSTITIAL, NOTICE

try:
    import httpx  # type: ignore
except ImportError:  # pragma: no cover
    import httpx2 as httpx  # type: ignore

PHYSICAL_CATS = {
    "coffee": (28, ["single-origin beans", "espresso blend", "pour-over kit", "cold brew concentrate"],
               ["arabica", "roast", "espresso", "pourover"]),
    "books": (22, ["sci-fi novel", "history of computing", "economics primer", "poetry collection"],
              ["paperback", "fiction", "nonfiction", "hardcover"]),
    "electronics": (90, ["wireless earbuds", "mechanical keyboard", "usb-c hub", "portable ssd"],
                    ["usb-c", "bluetooth", "wireless", "gadget"]),
    "outdoor": (60, ["trail running shoes", "ultralight tent", "headlamp", "water filter"],
                ["hiking", "camping", "trail", "gear"]),
    "apparel": (45, ["merino t-shirt", "rain jacket", "wool socks", "running shorts"],
                ["merino", "waterproof", "fit", "cotton"]),
    "home": (35, ["ceramic mug set", "linen sheets", "desk lamp", "cast iron pan"],
             ["kitchen", "decor", "ceramic", "bedroom"]),
}
INFO_CATS = {
    "ai": (["notes on LLM inference costs", "RL fine-tuning tricks", "agent protocol deep dive", "GPU market weekly"],
           ["llm", "gpu", "agents", "rl"]),
    "markets": (["rates outlook", "earnings preview", "FX weekly", "commodities note"],
                ["rates", "equities", "fx", "macro"]),
    "science": (["fusion progress recap", "CRISPR explainer", "exoplanet roundup", "battery chemistry"],
                ["physics", "biology", "space", "research"]),
    "sports": (["match analysis", "transfer rumours", "training science", "league preview"],
               ["football", "nba", "running", "tennis"]),
    "cooking": (["weeknight noodle recipes", "sourdough troubleshooting", "knife skills guide", "spice blending"],
                ["recipe", "baking", "noodles", "spices"]),
    "travel": (["Kyoto on a budget", "rail pass hacks", "Patagonia trek log", "night train guide"],
               ["japan", "rail", "trekking", "budget"]),
}
ALL_CATS = list(PHYSICAL_CATS) + list(INFO_CATS)
PHYS_PRODUCERS = [("beanery", ["coffee"]), ("pagehouse", ["books"]), ("voltmart", ["electronics"]),
                  ("ridgeline", ["outdoor", "apparel"]), ("loomworks", ["apparel"]), ("hearth", ["home", "coffee"])]
INFO_PRODUCERS = [("inference-weekly", ["ai"]), ("macro-desk", ["markets"]), ("lab-notes", ["science", "ai"]),
                  ("pitchside", ["sports"]), ("wok-and-whisk", ["cooking", "travel"])]
SCAM_SELLER = ("brandz-outlet", ["electronics", "apparel"])
SCAM_INFO = ("alpha-leaks", ["markets", "ai"])


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


@dataclass
class SimConfig:
    consumers: int = 24
    physical_producers: int = 6
    info_producers: int = 5
    rounds: int = 12
    round_hours: float = 4.0
    transport: str = "http"       # "http" (one uvicorn server per agent) or "memory"
    seed: int = 7
    scammers: bool = True
    x_fraction: float = 0.5       # share of consumer agents that register X's ranking stack as skills
    friends: int = 3
    concurrency: int = 8
    starting_balance: float = 500.0
    llm: bool = False             # wrap rule brains in LLMBrain (needs AGORA_LLM_BASE_URL)
    producer_learning: bool = True  # False: producers target from interest cards only, ignoring feedback


class Principal:
    """A synthetic person: hidden tastes, what they choose to tell their agent, and how they react."""

    def __init__(self, world: "World", name: str, rng: random.Random):
        self.world, self.rng, self.name = world, rng, name
        self.key = KeyPair.from_seed(f"principal:{name}")
        self.affinity = {c: rng.betavariate(0.6, 2.4) for c in ALL_CATS}
        self.favorites = rng.sample(list(PHYSICAL_CATS), 2) + rng.sample(list(INFO_CATS), 2)
        for c in self.favorites:
            self.affinity[c] = rng.uniform(0.65, 1.0)
        self.wtp = rng.uniform(0.85, 1.25)
        self.info_budget = rng.uniform(3.0, 9.0)
        self.cheated_by: set[str] = set()

    # ------------------------------------------------------------ what they say
    def stated_profile(self, rng: random.Random) -> UserProfile:
        rest = sorted((c for c in ALL_CATS if c not in self.favorites), key=lambda c: self.affinity[c])
        prof = UserProfile(
            likes={c: 0.8 for c in self.favorites}, dislikes=set(rest[:2]), stated_likes=set(self.favorites),
            price_max={c: round(PHYSICAL_CATS[c][0] * self.wtp * 1.1, 2) for c in self.favorites if c in PHYSICAL_CATS},
            info_price_max=round(self.info_budget, 2), attention_per_tick=rng.randint(4, 7),
            disclosure=rng.choices(["public", "subscribers", "private"], weights=[0.5, 0.35, 0.15])[0],
            region=rng.choice(["SG", "US"]))
        return prof

    def stated_baseline(self, cat: str) -> float:
        rest = sorted((c for c in ALL_CATS if c not in self.favorites), key=lambda c: self.affinity[c])
        return 0.8 if cat in self.favorites else 0.0 if cat in rest[:2] else PRIOR

    # ------------------------------------------------------------ ground truth
    def relevance(self, offer: dict) -> float:
        lst = self.world.truth.get(offer["offerId"])
        q = (lst.quality if lst.honest else 0.0) if lst else 0.3
        return self.affinity[offer["category"]] * q

    def valuation(self, offer: dict) -> float:
        lst = self.world.truth.get(offer["offerId"])
        if lst is None:
            return 0.0
        a, q = self.affinity[offer["category"]], (lst.quality if lst.honest else 0.0)
        if offer["kind"] == PHYSICAL:
            return PHYSICAL_CATS[offer["category"]][0] * self.wtp * (0.85 + 0.4 * a) * (0.6 + 0.4 * q)
        return self.info_budget * (0.6 + 0.6 * a) * (0.4 + 0.6 * q)

    # ------------------------------------------------------------ reactions
    def react(self, offer: dict, visibility: str) -> Reaction:
        rng, r = self.rng, Reaction()
        lst = self.world.truth.get(offer["offerId"])
        if lst is None:
            return r
        a = self.affinity[offer["category"]]
        q_true = lst.quality if lst.honest else 0.05
        q_seen = lst.quality if lst.honest else 0.8  # scams are dressed up to look good
        if offer["producer"] in self.cheated_by:
            r.actions |= {"report", "block_author", "not_dwelled"}
            return r
        penalty = 1.2 if visibility == INTERSTITIAL else 0.3 if visibility == NOTICE else 0.0
        if rng.random() >= sigmoid(4.2 * a + 1.2 * (q_seen - 0.5) - 2.4 - penalty + rng.gauss(0, 0.3)):
            r.actions.add("not_dwelled")
            if rng.random() < 0.15 * sigmoid(-5 * a + 0.5):
                r.actions.add("not_interested")
                if rng.random() < 0.1:
                    r.actions.add("mute_author")
            return r
        r.actions |= {"click", "dwell"}
        if offer["kind"] == INFORMATION:
            r.dwell_time = max(3.0, 15 + 150 * a * q_true + rng.gauss(0, 10))
            if r.dwell_time < 12:
                r.actions.discard("dwell")
        for act, z in (("favorite", 4 * a + 2 * (q_true - 0.5) - 3.2), ("reply", 3 * a - 4.8),
                       ("follow_author", 3.5 * a + 2.5 * (q_true - 0.5) - 4.0),
                       ("repost", (4 * a + 2.5 * (q_true - 0.5) - 4.0) if offer["kind"] == INFORMATION
                        else (3 * a + 2 * (q_true - 0.5) - 4.6)),
                       ("share", 3 * a + 2 * (q_true - 0.5) - 5.0)):
            if rng.random() < sigmoid(z):
                r.actions.add(act)
        price = offer["price"]["amount"]
        if offer["kind"] == PHYSICAL:
            ref = PHYSICAL_CATS[offer["category"]][0]
            r.reservation = round(ref * self.wtp * (0.85 + 0.4 * a), 2)
            z = 5 * a + 1.5 * (q_seen - 0.5) - 2.5 * max(0.0, price / r.reservation - 1) - 3.3
            r.wants_buy = rng.random() < 0.4 * sigmoid(z)
        elif price > 0:
            r.reservation = self.info_budget
            r.wants_buy = price <= self.info_budget and rng.random() < 0.5 * sigmoid(5 * a + 2 * (q_seen - 0.5) - 3.0)
        return r

    def inspect(self, offer: dict) -> tuple[bool, int]:
        lst = self.world.truth[offer["offerId"]]
        if not lst.honest:
            self.cheated_by.add(offer["producer"])
            return False, 1
        return True, max(1, min(5, round(1 + 4 * lst.quality + self.rng.gauss(0, 0.5))))

    def on_refund(self, offer: dict) -> None:
        self.cheated_by.add(offer["producer"])

    def maybe_need(self) -> dict | None:
        if self.rng.random() > 0.25:
            return None
        cats = list(self.affinity)
        cat = self.rng.choices(cats, weights=[self.affinity[c] ** 2 for c in cats])[0]
        if cat in PHYSICAL_CATS:
            ref, items, _ = PHYSICAL_CATS[cat]
            return {"text": f"need {self.rng.choice(items)} ({cat})", "kind": PHYSICAL, "category": cat,
                    "max_price": round(ref * self.wtp * 1.1, 2)}
        items, _ = INFO_CATS[cat]
        return {"text": f"need a good read on {self.rng.choice(items)} ({cat})", "kind": INFORMATION,
                "category": cat, "max_price": round(self.info_budget, 2)}


class World:
    def __init__(self, cfg: SimConfig):
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.truth: dict[str, Listing] = {}
        self.vclock = clock.VirtualClock()
        self.agents: list[AgoraAgent] = []
        self.rounds: list[dict] = []
        self.principals: dict[str, Principal] = {}
        self.need_log: dict[str, dict] = {}
        self._sku = 0
        self._a2a_prev = 0.0

    # ------------------------------------------------------------------ setup
    def _port(self) -> int:
        if self.cfg.transport == "http":
            return free_port()
        self._next_port = getattr(self, "_next_port", 20000) + 1
        return self._next_port

    @staticmethod
    def _peer(a: AgoraAgent) -> Peer:
        return Peer(a.did, a.base_url, a.rpc_url, a.roles(), a.name)

    async def setup(self) -> None:
        clock.set_clock(self.vclock)
        cfg, rng = self.cfg, self.rng
        if cfg.transport == "memory":
            self.net = MemoryNetwork()
            self.http = self.net.client(timeout=60)
        else:
            self.servers = HttpServerGroup()
            self.http = httpx.AsyncClient(timeout=60, trust_env=False,
                                          limits=httpx.Limits(max_connections=200, max_keepalive_connections=100))
        kw = {"http": self.http}
        self.bank = BankAgent("bank", port=self._port(), **kw)
        self.logistics = LogisticsAgent("swiftship", port=self._port(), **kw)
        bank_peer, carrier_peer = self._peer(self.bank), self._peer(self.logistics)
        self.escrows = [EscrowAgent(n, port=self._port(), fee_bps=fee, bank=bank_peer, carriers={self.logistics.did}, **kw)
                        for n, fee in (("escrow-a", 50), ("escrow-b", 80))]
        trusted = {e.did for e in self.escrows}
        escrow_peers = [self._peer(e) for e in self.escrows]
        self.labelers = [LabelerAgent("labeler-strict", port=self._port(), min_refunds=2, refund_rate=0.3,
                                      trusted_escrows=trusted, **kw),
                         LabelerAgent("labeler-lenient", port=self._port(), min_refunds=4, refund_rate=0.5,
                                      trusted_escrows=trusted, **kw)]
        self.merchants: list[MerchantAgent] = []
        self.meta: dict[str, dict] = {}
        phys = PHYS_PRODUCERS[: cfg.physical_producers] + ([SCAM_SELLER] if cfg.scammers else [])
        info = INFO_PRODUCERS[: cfg.info_producers] + ([SCAM_INFO] if cfg.scammers else [])
        for i, (name, cats) in enumerate(phys + info):
            kind = PHYSICAL if (name, cats) in phys else INFORMATION
            honest = (name, cats) not in (SCAM_SELLER, SCAM_INFO)
            if kind == PHYSICAL:
                caps = {c: {"kind": PHYSICAL,
                            "unit_cost": round(PHYSICAL_CATS[c][0] * (0.55 if honest else 0.25), 2),
                            "base_price": round(PHYSICAL_CATS[c][0] * (rng.uniform(0.95, 1.2) if honest else 0.62), 2)}
                        for c in cats}
            else:
                caps = {c: {"kind": INFORMATION, "unit_cost": 0.0, "base_price": round(rng.uniform(2.5, 6.0), 2)}
                        for c in cats}
            brain = (SpamBrain(seed=i) if (name, cats) == SCAM_SELLER
                     else make_producer_brain(llm=cfg.llm, seed=i, learn=cfg.producer_learning))
            m = MerchantAgent(name, port=self._port(), escrows=escrow_peers, logistics=carrier_peer,
                              referral_bps=rng.choice([200, 300, 500]) if kind == PHYSICAL else rng.choice([1000, 1500]),
                              capabilities=caps, brain=brain, trusted_escrows=trusted, rng_seed=i, **kw)
            self.meta[m.did] = {"name": name, "kind": kind, "cats": cats, "honest": honest,
                                "quality": rng.uniform(0.55, 0.95) if honest else (0.05 if kind == PHYSICAL else 0.25),
                                "regions": ["SG", "US"] if not honest or rng.random() < 0.6 else [rng.choice(["SG", "US"])]}
            m.make_listing = self._factory(m)
            m.on_publish = self._register_truth
            self.merchants.append(m)
        self.consumers: list[ConsumerAgent] = []
        n_x = round(cfg.consumers * cfg.x_fraction)
        for i in range(cfg.consumers):
            name = f"c{i:02d}"
            p = Principal(self, name, random.Random(cfg.seed * 1000 + i))
            u = rng.random()
            labelers = ({self.labelers[0].did} if u < 0.6 else {self.labelers[1].did} if u < 0.8 else set())
            use_x = (i % 2 == 0) if n_x == cfg.consumers / 2 else i < n_x
            c = ConsumerAgent(name, principal=p, principal_key=p.key, profile=p.stated_profile(random.Random(i)),
                              bank=bank_peer, escrows=escrow_peers, logistics=carrier_peer, labelers=labelers,
                              brain=make_consumer_brain(llm=cfg.llm), use_x_skills=use_x,
                              budget=cfg.starting_balance * 0.8, max_item_price=150.0,
                              trusted_escrows=trusted, port=self._port(), rng_seed=i, **kw)
            self.bank.open_account(p.key.did, cfg.starting_balance)
            self.principals[c.did] = p
            self.consumers.append(c)
        self.agents = [self.bank, self.logistics, *self.escrows, *self.labelers, *self.merchants, *self.consumers]
        for a in self.agents:
            if cfg.transport == "memory":
                self.net.register(a.base_url, a.app)
            else:
                await self.servers.start(a.app, a.port)
        # no directory: everyone knows the service agents and three random agents; gossip does the rest
        service_urls = [a.base_url for a in (self.bank, self.logistics, *self.escrows, *self.labelers)]
        await self._gather([a.bootstrap(service_urls + [x.base_url for x in rng.sample(self.agents, 3)])
                            for a in self.agents])
        # friendships (mutual) between principals who know each other
        for c in self.consumers:
            for o in rng.sample([x for x in self.consumers if x is not c], cfg.friends):
                if o.did not in c.friends:
                    await c.befriend(o.did, o.rpc_url)
                    await o.befriend(c.did, c.rpc_url)
        await self._gather([c.share_card() for c in self.consumers])
        for m in self.merchants:  # every shop opens with something on the shelf
            for cat in self.meta[m.did]["cats"]:
                await m.publish(m.make_listing(cat, False, m.price_for(cat)))
        await self._gather([a.gossip_round(fanout=2) for a in self.agents])

    def _register_truth(self, offer_id: str, offer: dict, listing: Listing) -> None:
        self.truth[offer_id] = listing

    def _factory(self, m: MerchantAgent):
        def make(category: str, paid: bool, price: float) -> Listing:
            meta, rng = self.meta[m.did], self.rng
            self._sku += 1
            q = max(0.05, min(1.0, meta["quality"] + rng.gauss(0, 0.08))) if meta["honest"] else meta["quality"]
            if meta["kind"] == PHYSICAL:
                _, items, tags = PHYSICAL_CATS[category]
                item = rng.choice(items)
                return Listing(sku=f"sku{self._sku}", kind=PHYSICAL,
                               title=f"{'Premium ' if not meta['honest'] else ''}{item}",
                               description=f"{item} for {category} lovers, {' '.join(rng.sample(tags, 2))}",
                               category=category, tags=rng.sample(tags, 2), list_price=price,
                               cost=m.capabilities[category]["unit_cost"], inventory=rng.randint(15, 40),
                               ship_regions=meta["regions"], quality=q, honest=meta["honest"])
            items, tags = INFO_CATS[category]
            topic = rng.choice(items)
            body = f"{topic}: " + " ".join(rng.choice(tags) for _ in range(30))
            if paid:
                return Listing(sku=f"sku{self._sku}", kind=INFORMATION, title=f"[report] {topic}",
                               description=f"In-depth {category} report on {topic}", category=category,
                               tags=rng.sample(tags, 2), list_price=price, content=body,
                               teaser=f"{topic}: what everyone else is missing", quality=q,
                               honest=meta["honest"], bait_content="lorem ipsum " * 20)
            return Listing(sku=f"sku{self._sku}", kind=INFORMATION, title=topic, description=f"{category} note: {topic}",
                           category=category, tags=rng.sample(tags, 2), list_price=0.0, content=body,
                           quality=q, honest=True)
        return make

    async def _gather(self, coros, limit: int | None = None):
        sem = asyncio.Semaphore(limit or self.cfg.concurrency)

        async def run(c):
            async with sem:
                return await c

        return await asyncio.gather(*(run(c) for c in coros))

    # ------------------------------------------------------------------ rounds
    async def run_round(self, r: int) -> dict:
        for c in self.consumers:
            need = self.principals[c.did].maybe_need()
            if need:
                n = c.profile.add_need(**need)
                self.need_log[n.need_id] = {"consumer": c.did, "round": r, "created": n.created_at, "x": c.skills.has("x_rank"),
                                            "disclosure": c.profile.disclosure}
        fb_before = {m.did: (m.metrics.counters.get("feedback_accept", 0), m.metrics.counters.get("feedback_reject", 0),
                             m.metrics.counters.get("proposals", 0)) for m in self.merchants}
        prod = await self._gather([m.step() for m in self.merchants])
        await self._gather([a.gossip_round(fanout=2) for a in self.agents])
        reports = await self._gather([c.step() for c in self.consumers])
        new_labels = [lab for lb in self.labelers for lab in await lb.analyze()]
        losses = [c.train() for c in self.consumers]
        stats = self._round_stats(r, reports, prod, fb_before, losses, len(new_labels))
        self.rounds.append(stats)
        self.vclock.advance(self.cfg.round_hours * 3600)
        return stats

    def _round_stats(self, r, reports, prod, fb_before, losses, n_labels) -> dict:
        grp: dict[str, dict] = defaultdict(lambda: defaultdict(list))
        reasons: dict[str, Counter] = defaultdict(Counter)
        for c, rep in zip(self.consumers, reports):
            g = "x" if c.skills.has("x_rank") else "no_x"
            p = self.principals[c.did]
            for s in rep["shown"]:
                offer = s["offer"]
                lst = self.truth.get(s["offerId"])
                grp[g]["rel"].append(p.relevance(offer))
                grp[g]["pos"].append(1.0 if s["signal"] >= 0.8 else 0.0)
                grp[g]["scam"].append(0.0 if (lst is None or lst.honest) else 1.0)
                grp[g]["explore"].append(1.0 if s["explore"] else 0.0)
            for o in rep["purchases"]:
                if o["status"] == "completed":
                    offer = o["offer"]
                    grp[g]["surplus"].append(p.valuation(offer) - o["amount"])
                    grp[g]["spend"].append(o["amount"])
                    grp[g]["need_buys" if o.get("why") == "need" else "principal_buys"].append(1)
                grp[g]["deal_" + o["status"]].append(1)
            for nid in rep["needs_satisfied"]:
                if nid in self.need_log:
                    self.need_log[nid]["satisfied"] = clock.now()
            grp[g]["received"].append(rep["received"])
            reasons[g].update(rep["reasons"])
        out: dict = {"round": r, "groups": {}, "labels_issued": n_labels}
        for g, d in grp.items():
            out["groups"][g] = {
                "shown": len(d["rel"]), "mean_relevance": round(statistics.fmean(d["rel"]), 4) if d["rel"] else 0.0,
                "positive_rate": round(statistics.fmean(d["pos"]), 4) if d["pos"] else 0.0,
                "scam_share": round(statistics.fmean(d["scam"]), 4) if d["scam"] else 0.0,
                "explore_share": round(statistics.fmean(d["explore"]), 4) if d["explore"] else 0.0,
                "need_purchases": len(d["need_buys"]), "principal_purchases": len(d["principal_buys"]),
                "refunds": len(d["deal_refunded"]), "spend": round(sum(d["spend"]), 2),
                "surplus": round(sum(d["surplus"]), 2), "received": int(sum(d["received"])),
                "reject_reasons": dict(reasons[g])}
        honest = [m for m in self.merchants if self.meta[m.did]["honest"]]
        acc = rej = props = 0.0
        for m in honest:
            a0, r0, p0 = fb_before[m.did]
            acc += m.metrics.counters.get("feedback_accept", 0) - a0
            rej += m.metrics.counters.get("feedback_reject", 0) - r0
            props += m.metrics.counters.get("proposals", 0) - p0
        spam = [m for m in self.merchants if self.meta[m.did]["name"] == SCAM_SELLER[0]]
        out["honest_proposals"] = int(props)
        out["honest_acceptance"] = round(acc / (acc + rej), 4) if acc + rej else None
        out["spam_proposals"] = int(sum(m.metrics.counters.get("proposals", 0) - fb_before[m.did][2] for m in spam))
        total = sum(a.metrics.counters.get("a2a_sent", 0) for a in self.agents)
        out["a2a_messages"] = int(total - self._a2a_prev)
        self._a2a_prev = total
        trained = [x for x in losses if x is not None]
        out["x_train_loss"] = round(statistics.fmean(trained), 4) if trained else None
        out["produced"] = sum(p["produced"] for p in prod)
        return out

    # ------------------------------------------------------------------ report
    def report(self) -> dict:
        settlements: dict[str, dict] = {}
        for a in self.agents:  # union of every agent's verified view (reporting only)
            for k, (_, s) in a.store.settlements.items():
                settlements[k] = s
        released = [s for s in settlements.values() if s["status"] == "released"]
        refunded = [s for s in settlements.values() if s["status"] == "refunded"]
        gmv = sum(s["amount"] for s in released)
        bad = {d for d, m in self.meta.items() if not m["honest"]}
        groups: dict[str, dict] = {}
        for g in ("x", "no_x"):
            rs = [s["groups"][g] for s in self.rounds if g in s["groups"]]
            cons = [c for c in self.consumers if (c.skills.has("x_rank")) == (g == "x")]
            if not rs:
                continue
            shown = sum(x["shown"] for x in rs)
            needs = [n for n in self.need_log.values() if n["x"] == (g == "x") and n["round"] <= len(self.rounds) - 3]
            sat = [n for n in needs if "satisfied" in n]
            groups[g] = {
                "consumers": len(cons),
                "mean_relevance": round(sum(x["mean_relevance"] * x["shown"] for x in rs) / max(1, shown), 4),
                "positive_rate": round(sum(x["positive_rate"] * x["shown"] for x in rs) / max(1, shown), 4),
                "scam_share": round(sum(x["scam_share"] * x["shown"] for x in rs) / max(1, shown), 4),
                "shown_per_consumer_tick": round(shown / max(1, len(cons) * len(rs)), 2),
                "need_fulfilment": round(len(sat) / len(needs), 3) if needs else None,
                "hours_to_fulfil": round(statistics.median((n["satisfied"] - n["created"]) / 3600 for n in sat), 1) if sat else None,
                "purchases_per_consumer": round(sum(x["need_purchases"] + x["principal_purchases"] for x in rs) / len(cons), 2),
                "surplus_per_consumer": round(sum(x["surplus"] for x in rs) / len(cons), 2),
                "reject_reasons": dict(sum((Counter(x["reject_reasons"]) for x in rs), Counter())),
            }
        # does the agent learn what its principal likes beyond what they said?
        learned, stated, unstated = [], [], []
        for c in self.consumers:
            p = self.principals[c.did]
            truth = [p.affinity[k] for k in ALL_CATS]
            learned.append(spearman(truth, [c.profile.like(k) for k in ALL_CATS]))
            stated.append(spearman(truth, [p.stated_baseline(k) for k in ALL_CATS]))
            # among the categories the principal never mentioned, stated preferences carry no ordering at all
            hidden = [k for k in ALL_CATS if k not in p.favorites and k not in c.profile.dislikes]
            rho = spearman([p.affinity[k] for k in hidden], [c.profile.like(k) for k in hidden])
            if not math.isnan(rho):
                unstated.append(rho)
        by_disc: dict[str, dict] = {}
        for disc in ("public", "subscribers", "private"):
            needs = [n for n in self.need_log.values() if n["disclosure"] == disc and n["round"] <= len(self.rounds) - 3]
            cons = [c for c in self.consumers if c.profile.disclosure == disc]
            if cons:
                by_disc[disc] = {"consumers": len(cons),
                                 "need_fulfilment": round(sum("satisfied" in n for n in needs) / len(needs), 3) if needs else None,
                                 "proposals_received_per_consumer": round(
                                     sum(c.metrics.counters.get("proposals_received", 0) for c in cons) / len(cons), 1)}
        views = [reputation_scores(c.store, c.did, c.following) for c in self.consumers if c.skills.has("x_rank")]
        merchants = []
        for m in self.merchants:
            meta = self.meta[m.did]
            mine = [s for s in settlements.values() if s["merchant"] == m.did]
            acc, rej = m.metrics.counters.get("feedback_accept", 0), m.metrics.counters.get("feedback_reject", 0)
            reps = [v.get(m.did, 0.0) for v in views]
            merchants.append({
                "name": meta["name"], "kind": meta["kind"], "honest": meta["honest"], "true_quality": round(meta["quality"], 3),
                "proposals": int(m.metrics.counters.get("proposals", 0)),
                "acceptance": round(acc / (acc + rej), 3) if acc + rej else None,
                "blocked_by": len(m.blocked_by), "subscribers": len(m.subscribers),
                "sales": sum(1 for s in mine if s["status"] == "released"),
                "refunds": sum(1 for s in mine if s["status"] == "refunded"),
                "revenue": round(sum(sp["amount"] for s in mine if s["status"] == "released"
                                     for sp in s["splits"] if sp["role"] == "merchant"), 2),
                "reputation": round(statistics.fmean(reps), 3) if reps else 0.0,
                "labels": sorted({p["label"] for c in self.consumers for _, p in c.store.labels.values() if p["subject"] == m.did}),
                "made_to_order": int(m.metrics.counters.get("made_to_order", 0))})
        rq = [(x["reputation"], x["true_quality"] if x["honest"] else 0.0) for x in merchants]
        hon = [m for m in self.merchants if self.meta[m.did]["honest"]]
        h_acc = sum(m.metrics.counters.get("feedback_accept", 0) for m in hon)
        h_rej = sum(m.metrics.counters.get("feedback_reject", 0) for m in hon)
        examples = []
        for c in self.consumers[:4]:
            examples += [e for e in list(c.decision_log) if e["action"] in ("reject", "accept", "buy", "intent", "block")][-3:]
        return {
            "config": asdict(self.cfg), "agents": len(self.agents),
            "totals": {
                "gmv": round(gmv, 2), "deals_completed": len(released), "deals_refunded": len(refunded),
                "platform_fee": 0.0, "escrow_fees": round(sum(s["escrowFee"] for s in released), 2),
                "referral_payouts": round(sum(sp["amount"] for s in released for sp in s["splits"] if sp["role"] == "referrer"), 2),
                "paid_out_to_bad_actors": round(sum(sp["amount"] for s in released for sp in s["splits"] if sp["to"] in bad), 2),
                "money_conserved": abs(sum(self.bank.balances.values())
                                       - self.cfg.starting_balance * len(self.consumers)) < 1e-6,
                "offers_published": len(self.truth), "needs_created": len(self.need_log),
                "a2a_messages": int(sum(a.metrics.counters.get("a2a_sent", 0) for a in self.agents)),
                "intents": int(sum(c.metrics.counters.get("intents", 0) for c in self.consumers)),
                "forwards": int(sum(c.metrics.counters.get("forwards", 0) for c in self.consumers)),
                "blocks": int(sum(len(c.blocked) for c in self.consumers)),
                "subscriptions": int(sum(len(c.subscriptions) for c in self.consumers)),
                "honest_proposals": int(sum(m.metrics.counters.get("proposals", 0) for m in hon)),
                "honest_acceptance": round(h_acc / (h_acc + h_rej), 4) if h_acc + h_rej else None,
            },
            "groups": groups,
            "preference_learning": {"spearman_learned": round(statistics.fmean(learned), 3),
                                    "spearman_stated_only": round(statistics.fmean(stated), 3),
                                    "spearman_unstated_categories": round(statistics.fmean(unstated), 3) if unstated else None,
                                    "consumers_with_signal_on_unstated": len(unstated)},
            "by_disclosure": by_disc,
            "reputation_vs_quality_spearman": round(spearman([a for a, _ in rq], [b for _, b in rq]), 3),
            "merchants": merchants, "rounds": self.rounds, "decision_examples": examples[:12],
        }

    async def close(self) -> None:
        if self.cfg.transport == "http":
            await self.servers.stop()
        await self.http.aclose()
        clock.set_clock(clock.Clock())


def spearman(x: list[float], y: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r

    if len(x) < 3:
        return float("nan")
    rx, ry = ranks(x), ranks(y)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else float("nan")

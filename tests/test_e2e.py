"""End-to-end flows of the agent network over the in-memory transport (same A2A bytes as HTTP, no sockets)."""

import asyncio

import pytest

from agora import clock
from agora.agents.base import Peer
from agora.agents.consumer import ConsumerAgent, Reaction
from agora.agents.infra import BankAgent, EscrowAgent, LabelerAgent, LogisticsAgent
from agora.agents.merchant import Listing, MerchantAgent
from agora.crypto import KeyPair
from agora.mind.consumer_brain import ConsumerRuleBrain
from agora.mind.producer_brain import ProducerRuleBrain, SpamBrain
from agora.mind.profile import UserProfile
from agora.net import MemoryNetwork
from agora.protocol.records import sign_instruction
from agora.protocol.schema import INFORMATION, PHYSICAL, verify_offer
from agora.ranking.pipeline import Candidate
from agora.skills.market import signed_query


class Person:
    """Likes some categories (and reposts what it likes); never wants anything else."""

    def __init__(self, name, likes):
        self.key, self.likes = KeyPair.from_seed(f"principal:{name}"), set(likes)

    def react(self, offer, visibility):
        if offer["category"] in self.likes:
            return Reaction(actions={"click", "dwell", "favorite", "repost"}, dwell_time=90.0)
        return Reaction(actions={"not_dwelled"})

    def inspect(self, offer):
        return True, 5


def peer(a):
    return Peer(a.did, a.base_url, a.rpc_url, a.roles(), a.name)


def listing_factory(kind, honest=True):
    n = iter(range(10_000))

    def make(category, paid, price):
        i = next(n)
        if kind == PHYSICAL:
            return Listing(sku=f"{category}{i}", kind=PHYSICAL, title=f"{category} item {i}", description=f"good {category}",
                           category=category, tags=[category], list_price=price, cost=price * 0.55, inventory=20,
                           ship_regions=["SG"])
        return Listing(sku=f"{category}{i}", kind=INFORMATION, title=f"[report] {category} {i}",
                       description=f"{category} report", category=category, tags=[category],
                       list_price=price if paid else 0.0, content=f"real {category} analysis {i}", honest=honest,
                       bait_content="lorem ipsum")
    return make


async def build():
    clock.set_clock(clock.VirtualClock())
    net = MemoryNetwork()
    http = net.client()
    port = iter(range(31000, 31100))
    kw = {"http": http}
    bank = BankAgent("bank", port=next(port), **kw)
    carrier = LogisticsAgent("carrier", port=next(port), **kw)
    escrow = EscrowAgent("escrow", port=next(port), fee_bps=100, bank=peer(bank), carriers={carrier.did}, **kw)
    trusted = {escrow.did}
    labeler = LabelerAgent("labeler", port=next(port), min_refunds=1, refund_rate=0.3, trusted_escrows=trusted, **kw)

    def producer(name, caps, kind, brain, honest=True):
        m = MerchantAgent(name, port=next(port), escrows=[peer(escrow)], logistics=peer(carrier), referral_bps=500,
                          capabilities=caps, brain=brain, trusted_escrows=trusted, **kw)
        m.make_listing = listing_factory(kind, honest)
        return m

    shop = producer("shop", {"coffee": {"kind": PHYSICAL, "unit_cost": 15.0, "base_price": 30.0}}, PHYSICAL,
                    ProducerRuleBrain(seed=1))
    spam = producer("spam", {"electronics": {"kind": PHYSICAL, "unit_cost": 5.0, "base_price": 20.0}}, PHYSICAL,
                    SpamBrain(seed=2))
    bait = producer("bait", {"markets": {"kind": INFORMATION, "unit_cost": 0.0, "base_price": 5.0}}, INFORMATION,
                    ProducerRuleBrain(seed=3), honest=False)

    def consumer(name, likes, disclosure, **brain_kw):
        person = Person(name, likes)
        prof = UserProfile(likes={c: 0.8 for c in likes}, stated_likes=set(likes), dislikes={"sports"},
                           price_max={"coffee": 40.0}, info_price_max=8.0, disclosure=disclosure, region="SG",
                           attention_per_tick=4)
        return ConsumerAgent(name, principal=person, principal_key=person.key, profile=prof, bank=peer(bank),
                             escrows=[peer(escrow)], logistics=peer(carrier), labelers={labeler.did},
                             brain=ConsumerRuleBrain(explore_rate=0.0, **brain_kw), trusted_escrows=trusted,
                             port=next(port), **kw)

    alice = consumer("alice", ["coffee", "markets"], "public", block_after=2)
    bob = consumer("bob", ["books"], "private")
    carol = consumer("carol", ["coffee"], "public")
    agents = [bank, carrier, escrow, labeler, shop, spam, bait, alice, bob, carol]
    for a in agents:
        net.register(a.base_url, a.app)
    for a in agents:
        await a.bootstrap([x.base_url for x in agents if x is not a])
    for c in (alice, bob, carol):
        bank.open_account(c.principal_did, 300.0)
    return dict(bank=bank, escrow=escrow, labeler=labeler, shop=shop, spam=spam, bait=bait, alice=alice, bob=bob,
                carol=carol)


def run(coro_fn):
    async def wrapper():
        try:
            await coro_fn(await build())
        finally:
            clock.set_clock(clock.Clock())
    asyncio.run(wrapper())


def test_producer_targets_by_interest_card_and_learns_from_feedback():
    async def scenario(w):
        shop, spam, alice, bob = w["shop"], w["spam"], w["alice"], w["bob"]
        await shop.ingest([await alice.share_card()])   # alice's public card reaches the shop (as by gossip)
        assert await bob.share_card() is None            # bob is private: no card at all
        await shop.step()                                # decide what to make, then whom to approach
        assert [c.offer["category"] for c in alice.queue] == ["coffee"] and bob.queue == []
        await spam.step()                                # the spammer blasts everyone it can reach
        assert bob.queue == [] and bob.metrics.counters["rejected_on_arrival_unsolicited"] >= 1
        report = await alice.step()
        assert report["decisions"]["accept"] == 1 and report["reasons"]["off-topic"] == 1
        assert shop.feedback_stats["coffee"]["accept"] == 1               # signed feedback reached the producer
        assert spam.feedback_stats["electronics"]["off-topic"] == 1
        assert alice.profile.evidence["coffee"][1] == 1                   # and alice learned from the reaction
        for _ in range(3):  # precision = (1 + accepted) / (2 + proposed) must drop below 0.2: 4 misses
            clock.get_clock().advance(86400)
            await spam.step()
            await alice.step()
        assert spam.did in alice.blocked                                  # ... and gets blocked by alice's agent
        clock.get_clock().advance(86400)
        await spam.step()
        assert alice.did in spam.blocked_by                               # it is told so, with a signed reason
    run(scenario)


def test_need_driven_purchase_and_bait_and_switch_refund():
    async def scenario(w):
        bank, escrow, shop, bait, alice, labeler = (w[k] for k in ("bank", "escrow", "shop", "bait", "alice", "labeler"))
        total = sum(bank.balances.values())
        await alice.ingest([await shop.publish(shop.make_listing("coffee", False, 30.0))])  # known from gossip
        need = alice.profile.add_need(text="need coffee beans", kind=PHYSICAL, category="coffee", max_price=40.0)
        report = await alice.step()
        (deal,) = [p for p in report["purchases"] if p["why"] == "need"]
        assert deal["status"] == "completed" and need.status == "satisfied"
        assert bank.balances[shop.did] > 0 and bank.balances[escrow.did] > 0

        await alice.ingest([await bait.publish(bait.make_listing("markets", True, 5.0))])
        info_need = alice.profile.add_need(text="need a markets report", kind=INFORMATION, category="markets", max_price=8.0)
        report = await alice.step()
        (deal,) = [p for p in report["purchases"] if p["why"] == "need"]
        assert deal["status"] == "refunded" and info_need.status == "open"   # hash mismatch proven, money back
        assert bank.balances[bait.did] == 0
        await labeler.ingest(alice.store.recent_tokens("settlement", 50))
        await alice.ingest(await labeler.analyze())
        await bait.ingest([await alice.share_card()])
        await bait.step()                                                    # bait proposes again ...
        report = await alice.step()
        assert report["reasons"]["unsafe"] >= 1                              # ... and is kept out
        assert sum(bank.balances.values()) == pytest.approx(total)           # money is conserved
    run(scenario)


def test_friend_forwarding_carries_referral_to_the_friend():
    async def scenario(w):
        bank, shop, alice, carol = w["bank"], w["shop"], w["alice"], w["carol"]
        assert await alice.befriend(carol.did, carol.rpc_url) and await carol.befriend(alice.did, alice.rpc_url)
        await carol.share_card()                     # carol's card goes to her friends, alice included
        await shop.ingest([await alice.share_card()])
        await shop.step()
        report = await alice.step()                  # alice's principal likes and reposts the coffee
        assert report["forwards"] == 1 and [c.source for c in carol.queue] == ["friend"]
        carol.profile.add_need(text="need coffee", kind=PHYSICAL, category="coffee", max_price=40.0)
        report = await carol.step()
        (deal,) = [p for p in report["purchases"] if p["why"] == "need"]
        assert deal["status"] == "completed" and deal["referrers"] == 1
        assert bank.balances[alice.did] > 0          # alice's agent earned the referral share
    run(scenario)


def test_mandate_budget_is_enforced_by_the_bank_even_if_the_agent_misbehaves():
    async def scenario(w):
        bank, shop, alice = w["bank"], w["shop"], w["alice"]
        shop.capabilities["coffee"]["base_price"] = 140.0
        tok = await shop.publish(shop.make_listing("coffee", False, 140.0))
        offer = shop.offer_of_sku[shop.sku_of_offer[next(iter(shop.sku_of_offer))]][1]
        alice.max_item_price = 1000
        bank.open_account(alice.principal_did, 5000.0)
        statuses, amounts = [], []
        for _ in range(4):
            o = await alice.buy(Candidate(offer["offerId"], tok, offer, "search"), reservation=200)
            statuses.append(o["status"])
            amounts.append(o.get("amount", 0))
        k = statuses.index("payment_refused")
        assert k >= 1 and statuses[:k] == ["completed"] * k
        assert sum(amounts[:k]) <= 400 < sum(amounts[:k]) + amounts[k]   # 400 = budget in the principal's mandate
    run(scenario)


def test_pushes_must_be_signed_by_the_sender_and_addressed_to_the_receiver():
    async def scenario(w):
        shop, spam, alice, carol = w["shop"], w["spam"], w["alice"], w["carol"]
        tok = await shop.publish(shop.make_listing("coffee", False, 30.0))
        oid = verify_offer(tok)["offerId"]

        def proposal(signer, target):
            return {"type": "agora.proposal", "offer": tok, "proposal": sign_instruction(
                signer.key, {"type": "agora.proposal", "target": target.did, "offerId": oid})}

        async def push(sender, to, data):
            return sender.status_data(await sender.send(to.rpc_url, data))

        # the spammer cannot spend the shop's quota at alice, or make alice's agent block the shop
        assert (await push(spam, alice, proposal(spam, alice)))["type"] == "agora.error"
        # a proposal the shop addressed to carol cannot be replayed to alice
        assert (await push(spam, alice, proposal(shop, carol)))["type"] == "agora.error"
        assert alice.queue == [] and alice.memory.producers[shop.did]["proposed"] == 0
        genuine = proposal(shop, alice)
        assert (await push(shop, alice, genuine))["queued"] is True
        assert (await push(spam, alice, genuine))["type"] == "agora.error"          # replay of the genuine one
        await alice.step()                                                       # alice's principal likes it

        # what alice liked is told only to agents that prove (by signature) they are her friends
        assert await alice.befriend(carol.did, carol.rpc_url) and await carol.befriend(alice.did, alice.rpc_url)
        need = carol.profile.add_need(text="need coffee", kind=PHYSICAL, category="coffee", max_price=40.0)
        asked = signed_query(carol, alice.did, need)
        assert len((await push(carol, alice, asked))["items"]) == 1
        assert (await push(spam, alice, signed_query(spam, alice.did, need)))["items"] == []   # not a friend
        assert (await push(spam, alice, asked))["type"] == "agora.error"         # replaying carol's signed query
        assert alice.metrics.counters["forged_or_replayed"] == 4
    run(scenario)

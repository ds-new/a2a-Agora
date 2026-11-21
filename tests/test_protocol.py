import pytest

from agora import clock
from agora.crypto import KeyPair, text_hash
from agora.protocol.mandates import (
    MandateError,
    checkout_mandate,
    open_checkout_mandate,
    open_payment_mandate,
    payment_mandate,
    verify_checkout_chain,
    verify_payment_chain,
)
from agora.protocol.negotiation import BuyerPolicy, SellerPolicy
from agora.protocol.records import make_review, make_settlement, verify_review
from agora.protocol.schema import (
    INFORMATION,
    PHYSICAL,
    ProtocolError,
    endorsement_chain,
    make_checkout,
    make_endorsement,
    make_offer,
    referral_splits,
    verify_offer,
)
from agora.protocol.store import ObjectStore

shop, alice, bob, carol, user, escrow = (KeyPair.from_seed(s) for s in
                                         ("shop", "alice", "bob", "carol", "user", "escrow"))


def physical_offer(**kw):
    args = dict(producer_url="http://shop/a2a", kind=PHYSICAL, title="Yirgacheffe beans 1kg",
                description="washed process", category="coffee", price=30.0, inventory=5,
                ship_regions=["SG"], referral_bps=500)
    args.update(kw)
    return make_offer(shop, **args)


def test_offer_kinds_and_tamper_detection():
    tok, p = physical_offer()
    assert p["kind"] == PHYSICAL and verify_offer(tok)["offerId"] == p["offerId"]
    itok, ip = make_offer(alice, producer_url="http://a/a2a", kind=INFORMATION, title="GPU market note",
                          description="weekly", category="ai", price=2.0, paid_content="secret analysis")
    assert ip["contentHash"] == text_hash("secret analysis") and "content" not in ip
    with pytest.raises(ProtocolError):
        make_offer(alice, producer_url="x", kind=INFORMATION, title="t", description="d", category="ai", price=1.0)
    h, _, s = tok.split(".")
    _, forged = physical_offer(price=1.0)
    with pytest.raises(Exception):
        verify_offer(f"{h}.{itok.split('.')[1]}.{s}")


def test_endorsement_chain_and_referral_splits():
    tok, offer = physical_offer()
    e1 = make_endorsement(alice, offer_token=tok, comment="great beans")
    e2 = make_endorsement(bob, offer_token=tok, parent=e1)
    e3 = make_endorsement(carol, offer_token=tok, parent=e2)
    chain = endorsement_chain(e3)
    assert chain["endorsers"] == [alice.did, bob.did, carol.did]
    splits = dict(referral_splits(100.0, offer, chain["endorsers"], buyer=user.did))
    # 5% pool; leaf (carol) gets 4/7, bob 2/7, alice 1/7
    assert splits[carol.did] == pytest.approx(2.86, abs=0.01) and splits[alice.did] == pytest.approx(0.71, abs=0.01)
    assert sum(splits.values()) == pytest.approx(5.0, abs=0.02)
    assert referral_splits(100.0, offer, [alice.did], buyer=alice.did) == []  # buyers never self-refer


def test_mandate_chain_happy_path_and_violations():
    tok, offer = physical_offer()
    agent = KeyPair.from_seed("agent")
    oc = open_checkout_mandate(user, agent.did, line_items=[{"kind": PHYSICAL, "category": "coffee", "maxQuantity": 2}])
    op = open_payment_mandate(user, agent.did, max_amount=80, budget=100)
    co = make_checkout(shop, buyer=agent.did, offer=offer, quantity=2, unit_price=28.0, escrow=escrow.did,
                       referral_chain=[], region="SG", round_idx=1)
    principal, checkout = verify_checkout_chain(oc, checkout_mandate(agent, co), merchant=shop.did)
    assert principal == user.did and checkout["total"]["amount"] == 56.0
    pm = payment_mandate(agent, transaction_id="tx1", payee=escrow.did, amount=56.0, currency="USD", holder=user.did)
    assert verify_payment_chain(op, pm, spent=0)[0] == user.did
    with pytest.raises(MandateError):  # budget is cumulative
        verify_payment_chain(op, pm, spent=50)
    rogue = KeyPair.from_seed("rogue")  # a key the user never delegated to
    with pytest.raises(MandateError):
        verify_checkout_chain(oc, checkout_mandate(rogue, co), merchant=shop.did)
    too_many = make_checkout(shop, buyer=agent.did, offer=offer, quantity=3, unit_price=10, escrow=escrow.did,
                             referral_chain=[], region="SG", round_idx=1)
    with pytest.raises(MandateError):
        verify_checkout_chain(oc, checkout_mandate(agent, too_many), merchant=shop.did)
    with pytest.raises(MandateError):  # amount_range
        verify_payment_chain(op, payment_mandate(agent, transaction_id="t", payee=escrow.did, amount=90,
                                                 currency="USD", holder=user.did))


def test_mandate_expiry():
    vc = clock.VirtualClock()
    clock.set_clock(vc)
    try:
        agent = KeyPair.from_seed("agent")
        op = open_payment_mandate(user, agent.did, max_amount=10, budget=10, ttl_s=60)
        pm = payment_mandate(agent, transaction_id="t", payee=escrow.did, amount=5, currency="USD", holder=user.did)
        vc.advance(120)
        with pytest.raises(MandateError):
            verify_payment_chain(op, pm)
    finally:
        clock.set_clock(clock.Clock())


def test_negotiation_converges_inside_zopa():
    seller, buyer = SellerPolicy(list_price=100, floor_price=70), BuyerPolicy(reservation=85)
    counter, price = None, None
    for r in range(0, 6):
        action, p = seller.respond(r, counter)
        if action == "accept":
            price = p
            break
        b_action, b_price = buyer.respond(r, p, list_price=100, final=(action == "final"))
        if b_action == "accept":
            price = p
            break
        if b_action == "walk":
            break
        counter = b_price
    assert price is not None and 70 <= price <= 85
    # no zone of agreement -> buyer walks
    seller, buyer = SellerPolicy(list_price=100, floor_price=90), BuyerPolicy(reservation=60)
    assert buyer.respond(4, seller.respond(4, 60)[1], list_price=100, final=True)[0] == "walk"


def test_reviews_require_a_real_settlement_and_store_counts():
    tok, offer = physical_offer()
    co = make_checkout(shop, buyer=user.did, offer=offer, quantity=1, unit_price=30, escrow=escrow.did,
                       referral_chain=[], region="SG", round_idx=0)
    st = make_settlement(escrow, escrow_id="e1", checkout_token=co, status="released", reason="delivered",
                         splits=[{"to": shop.did, "amount": 30.0, "role": "merchant"}], fee=0.0)
    rv = make_review(user, settlement_token=st, rating=5, text="fresh")
    assert verify_review(rv)["subject"] == shop.did
    with pytest.raises(ProtocolError):
        make_review(alice, settlement_token=st, rating=1)  # alice did not buy
    store = ObjectStore(trusted_escrows={escrow.did})
    assert store.add(rv) is not None and store.add(rv) is None
    assert store.merchant_stats(shop.did)["sales"] == 1 and store.merchant_stats(shop.did)["rating"] == 5
    untrusting = ObjectStore(trusted_escrows={KeyPair.from_seed("other-escrow").did})
    untrusting.add(st)
    assert untrusting.merchant_stats(shop.did)["sales"] == 0  # Sybil escrows do not count

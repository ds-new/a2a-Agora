import asyncio

import pytest

from agora import clock
from agora.crypto import KeyPair
from agora.mind.memory import Memory
from agora.mind.profile import PRIOR, UserProfile
from agora.mind.skills import Skill, SkillRegistry
from agora.protocol.schema import INFORMATION, PHYSICAL, verify_interest_card


def test_profile_from_principals_words_zh_and_en():
    p = UserProfile.from_text("我喜欢科幻小说和咖啡，不想看体育，需要一双70美元以内的越野跑鞋")
    assert {"books", "coffee"} <= p.stated_likes and "sports" in p.dislikes
    (need,) = p.needs
    assert (need.kind, need.category, need.max_price) == (PHYSICAL, "outdoor", 70.0)
    q = UserProfile.from_text("I love GPU and LLM news, but I don't want sports; looking for a macro rates report under 6")
    assert "ai" in q.stated_likes and "sports" in q.dislikes
    assert q.needs[0].kind == INFORMATION and q.needs[0].category == "markets" and q.needs[0].max_price == 6.0


def test_bayesian_learning_keeps_stated_tastes_and_finds_new_ones():
    p = UserProfile(likes={"coffee": 0.8}, stated_likes={"coffee"}, dislikes={"sports"})
    p.learn("coffee", 0.0)                     # one lukewarm reaction does not erase a stated taste
    assert p.like("coffee") == pytest.approx((3 * 0.8 + 0) / 4)
    for _ in range(3):
        p.learn("cooking", 1.0)                # an unstated interest shows up in reactions
    assert p.like("cooking") == pytest.approx((PRIOR + 3) / 4) and p.like("cooking") > 0.7
    p.learn("sports", 1.0)                     # stated dislikes are never overridden
    assert p.like("sports") == 0.0


def test_interest_card_disclosure_levels():
    key = KeyPair.from_seed("card")
    p = UserProfile(likes={"coffee": 0.83, "ai": 0.71, "books": 0.66, "travel": 0.52, "home": 0.4}, dislikes={"sports"})
    pub = verify_interest_card(p.interest_card(key, "http://me/a2a"))
    assert pub["disclosure"] == "public" and len(pub["categories"]) == 4 and pub["categories"]["coffee"] == 0.8
    p.disclosure = "subscribers"
    sub = verify_interest_card(p.interest_card(key, "http://me/a2a"))
    assert len(sub["categories"]) == 5 and sub["categories"]["coffee"] == 0.83 and sub["avoid"] == ["sports"]
    p.disclosure = "private"
    assert p.interest_card(key, "http://me/a2a") is None


def test_needs_expire():
    vc = clock.VirtualClock()
    clock.set_clock(vc)
    try:
        p = UserProfile()
        n = p.add_need(text="beans", kind=PHYSICAL, category="coffee", max_price=30, ttl_s=3600)
        assert p.open_needs() == [n]
        vc.advance(7200)
        assert p.open_needs() == [] and n.status == "expired"
    finally:
        clock.set_clock(clock.Clock())


def test_memory_trust_and_precision():
    m = Memory()
    assert m.trust("x") == 0.5
    m.producers["x"]["bought_ok"] += 2
    m.producers["y"]["refunded"] += 1
    assert m.trust("x") > 0.8 > 0.3 > m.trust("y")
    m.producers["z"]["proposed"] += 8
    m.producers["z"]["accepted"] += 1
    assert m.precision("z") == pytest.approx(0.2)


def test_skill_registry_counts_and_describes():
    async def double(agent, x):
        return 2 * x

    reg = SkillRegistry()
    reg.add(Skill("double", "doubles", {"x": "number"}, double, origin="local"))
    assert asyncio.run(reg.call(None, "double", x=21)) == 42
    assert reg.calls["double"] == 1 and reg.describe()[0]["name"] == "double"
    with pytest.raises(KeyError):
        asyncio.run(reg.call(None, "missing"))

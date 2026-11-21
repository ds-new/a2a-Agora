import asyncio

from agora.llm import parse_intent, parse_intent_rules


def test_rule_parser_handles_chinese_and_english():
    p = parse_intent_rules("帮我找300元以内的咖啡豆")
    assert (p["kind"], p["category"], p["max_price"]) == ("physical", "coffee", 300.0)
    p = parse_intent_rules("want a report on the GPU market under $5")
    assert (p["kind"], p["category"], p["max_price"]) == ("information", "ai", 5.0)


def test_falls_back_without_llm(monkeypatch):
    monkeypatch.delenv("AGORA_LLM_BASE_URL", raising=False)
    assert asyncio.run(parse_intent("trail tent below 80 dollars"))["category"] == "outdoor"


def test_falls_back_when_llm_unreachable(monkeypatch):
    monkeypatch.setenv("AGORA_LLM_BASE_URL", "http://127.0.0.1:9/v1")  # nothing listens on port 9
    assert asyncio.run(parse_intent("mechanical keyboard 120", timeout=1.0))["category"] == "electronics"

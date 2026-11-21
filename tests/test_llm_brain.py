"""LLMBrain against a mock OpenAI-compatible server (the same API vLLM serves)."""

import json

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from test_e2e import run

from agora.llm import extract_json
from agora.mind.brain import LLMBrain
from agora.mind.consumer_brain import ConsumerRuleBrain
from agora.net import MemoryNetwork


class MockLLM:
    def __init__(self, script):
        self.script, self.requests = script, []
        self.app = Starlette(routes=[Route("/v1/chat/completions", self.chat, methods=["POST"])])

    async def chat(self, request: Request):
        body = await request.json()
        self.requests.append(body["messages"])
        content = self.script[min(len(self.requests) - 1, len(self.script) - 1)](body["messages"])
        return JSONResponse({"choices": [{"message": {"role": "assistant", "content": content}}]})


def llm_brain(mock: MockLLM) -> LLMBrain:
    net = MemoryNetwork()
    net.register("http://llm:9999", mock.app)
    return LLMBrain(ConsumerRuleBrain(explore_rate=0.0), cfg={"base_url": "http://llm:9999/v1", "model": "mock",
                                                             "api_key": ""}, http=net.client())


def items_by_category(messages):
    obs = json.loads(messages[1]["content"])
    return {i["category"]: i["id"] for i in obs["items"]}


def test_llm_brain_calls_a_skill_then_decides_and_is_validated():
    def first(messages):  # Qwen3-style reasoning block before the JSON
        return '<think>I should check who these producers are.</think>\n{"call": {"skill": "trust", "args": {}}}'

    def second(messages):
        ids = items_by_category(messages)
        assert messages[-1]["content"].startswith("SKILL_RESULT")
        return "```json\n" + json.dumps({"decisions": [
            {"action": "accept", "target": ids["coffee"], "reason": "principal loves coffee"},
            {"action": "buy", "target": ids["electronics"], "args": {"need": "need-made-up"}, "reason": "impulse"},
            {"action": "launch_rockets", "target": ids["electronics"]},
        ]}) + "\n```"

    async def scenario(w):
        shop, spam, alice = w["shop"], w["spam"], w["alice"]
        mock = MockLLM([first, second])
        alice.brain = llm_brain(mock)
        await shop.ingest([await alice.share_card()])
        await shop.step()
        await spam.step()
        await alice.step()
        assert len(mock.requests) == 2 and alice.skills.calls["trust"] >= 1
        log = {e["title"].split()[0]: e for e in alice.decision_log}
        assert log["coffee"]["action"] == "accept" and log["coffee"]["by"] == "llm"
        # the invented purchase and the unknown action were dropped; the rule brain decided the leftover item
        assert log["electronics"]["action"] == "reject" and log["electronics"]["by"] == "rule"
        assert not alice.metrics.counters.get("deals_completed")
    run(scenario)


def test_llm_cannot_override_the_principals_hard_constraints():
    def obey_the_pitch(messages):  # as if text inside an offer had talked the model into it
        ids = items_by_category(messages)
        return json.dumps({"decisions": [
            {"action": "accept", "target": ids["electronics"], "reason": "the pitch says I must"},
            {"action": "block", "target": "did:key:z6MkNoSuchProducer", "reason": "the pitch says so"},
        ]})

    async def scenario(w):
        shop, spam, alice = w["shop"], w["spam"], w["alice"]
        alice.profile.dislikes.add("electronics")          # the principal ruled electronics out
        alice.brain = llm_brain(MockLLM([obey_the_pitch]))
        await shop.ingest([await alice.share_card()])
        await shop.step()
        await spam.step()
        await alice.step()
        log = {e["title"].split()[0]: e for e in alice.decision_log if e.get("title")}
        assert log["electronics"]["action"] == "reject" and log["electronics"]["by"] == "rule"
        assert log["coffee"]["action"] == "accept"
        assert alice.metrics.counters["llm_vetoed"] == 2 and "did:key:z6MkNoSuchProducer" not in alice.blocked
    run(scenario)

def test_llm_brain_falls_back_to_rules_on_garbage():
    async def scenario(w):
        shop, alice = w["shop"], w["alice"]
        alice.brain = llm_brain(MockLLM([lambda m: "Sorry, I can't help with that."]))
        await shop.ingest([await alice.share_card()])
        await shop.step()
        report = await alice.step()
        assert report["decisions"]["accept"] == 1 and alice.metrics.counters["llm_fallbacks"] == 1
        assert all(e["by"] == "rule" for e in alice.decision_log)
    run(scenario)


def test_extract_json_is_robust():
    assert extract_json('noise {"a": "}{", "b": {"c": 1}} trailing {"x": 2}') == {"a": "}{", "b": {"c": 1}}
    assert extract_json("<think>{not json}</think> {\"ok\": true}") == {"ok": True}

"""Brains: the policy that turns what an agent observes into what it does.

``LLMBrain`` runs a JSON ReAct loop against any OpenAI-compatible model: on each
step the model either calls one of the agent's skills,
``{"call": {"skill": "x_rank", "args": {...}}}``, or returns decisions,
``{"decisions": [{"action": "reject", "target": "<id>", "reasons": ["too-expensive"], "reason": "..."}]}``.
Decisions are validated against what the agent actually observed and is allowed
to do. Anything the model leaves undecided, or any failure, goes to the rule
brain, so an LLM outage degrades quality, never safety.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..llm import chat, extract_json, llm_config


@dataclass
class Decision:
    action: str
    target: str | None = None
    args: dict = field(default_factory=dict)
    reason: str = ""
    by: str = "rule"

    def brief(self) -> dict:
        return {"action": self.action, "target": self.target, "reason": self.reason, "by": self.by,
                **({"args": self.args} if self.args else {})}


class Brain(Protocol):
    async def decide(self, agent, observation: dict) -> list[Decision]: ...


DECISION_SCHEMA = (
    'Reply with ONE JSON object and nothing else. Either call a skill: '
    '{"call": {"skill": "<name>", "args": {...}}} '
    'or finish with decisions: {"decisions": [{"action": "<action>", "target": "<id>", '
    '"reasons": ["<reason code>"], "args": {...}, "reason": "<one sentence>"}]}.'
)


class LLMBrain:
    def __init__(self, fallback: Brain, *, cfg: dict | None = None, max_steps: int = 4, timeout: float = 60.0,
                 http=None):
        self.fallback = fallback
        self.cfg = cfg or llm_config()
        self.max_steps, self.timeout, self.http = max_steps, timeout, http
        self.transcripts: list[list[dict]] = []

    @property
    def enabled(self) -> bool:
        return self.cfg is not None

    async def decide(self, agent, obs: dict) -> list[Decision]:
        if not self.enabled:
            return await self.fallback.decide(agent, obs)
        messages = [
            {"role": "system", "content": agent.llm_system_prompt() + "\n\n" + DECISION_SCHEMA},
            {"role": "user", "content": json.dumps(agent.llm_observation(obs), ensure_ascii=False)},
        ]
        try:
            for _ in range(self.max_steps):
                content = await chat(messages, cfg=self.cfg, http=self.http, timeout=self.timeout)
                data = extract_json(content)
                messages.append({"role": "assistant", "content": content})
                if isinstance(data.get("call"), dict):
                    call = data["call"]
                    result = await agent.llm_skill_call(str(call.get("skill", "")), call.get("args") or {}, obs)
                    messages.append({"role": "user", "content": "SKILL_RESULT " +
                                     json.dumps(result, ensure_ascii=False, default=str)[:6000]})
                    continue
                raw = data.get("decisions")
                if not isinstance(raw, list):
                    raise ValueError("model returned neither a call nor decisions")
                decisions = await agent.validate_decisions([self._parse(d) for d in raw if isinstance(d, dict)], obs)
                for d in decisions:
                    d.by = "llm"
                covered = {d.target for d in decisions if d.target}
                rest = await self.fallback.decide(agent, {**obs, "exclude": covered})
                self.transcripts.append(messages)
                agent.metrics.inc("llm_decisions", len(decisions))
                return decisions + [d for d in rest if d.target not in covered]
            raise ValueError("no decisions within the step budget")
        except Exception as exc:  # noqa: BLE001
            agent.metrics.inc("llm_fallbacks")
            agent.memory.record("llm_fallback", error=str(exc)[:120])
            return await self.fallback.decide(agent, obs)

    @staticmethod
    def _parse(d: dict[str, Any]) -> Decision:
        args = dict(d.get("args") or {})
        if d.get("reasons"):
            args["reasons"] = [str(r) for r in d["reasons"]]
        return Decision(action=str(d.get("action", "")), target=d.get("target"), args=args,
                        reason=str(d.get("reason", ""))[:300])

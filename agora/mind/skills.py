"""Skills: the tools an agent may choose to use while deciding.

A skill is informational (it gathers or scores; it does not move money or send
offers). Side effects are Decisions the agent executes afterwards, which keeps
spending and messaging under the profile and the AP2 mandate.

Skills can be local Python functions, ports of X's ranking stack
(origin="x-algorithm"), or another agent's A2A capability (remote_skill): an
agent without a GPU can borrow a bigger ranking model from an agent that has one.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass
class Skill:
    name: str
    description: str
    params: dict[str, str]
    fn: Callable[..., Awaitable[Any]]
    origin: str = "local"   # "local" | "x-algorithm" | "remote:<url>"


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self.calls: Counter = Counter()

    def add(self, *skills: Skill) -> None:
        for s in skills:
            self._skills[s.name] = s

    def remove(self, name: str) -> None:
        self._skills.pop(name, None)

    def has(self, name: str) -> bool:
        return name in self._skills

    def names(self) -> list[str]:
        return sorted(self._skills)

    def describe(self) -> list[dict]:
        return [{"name": s.name, "description": s.description, "params": s.params, "origin": s.origin}
                for s in sorted(self._skills.values(), key=lambda s: s.name)]

    async def call(self, agent, name: str, **kwargs) -> Any:
        skill = self._skills.get(name)
        if skill is None:
            raise KeyError(f"agent has no skill {name!r}")
        self.calls[name] += 1
        return await skill.fn(agent, **kwargs)


def remote_skill(name: str, description: str, params: dict[str, str], rpc_url: str, msg_type: str,
                 result_type: str) -> Skill:
    """Expose another agent's A2A capability as a local skill (arguments must be JSON)."""

    async def fn(agent, **kwargs):
        res = await agent.send(rpc_url, {"type": msg_type, **kwargs})
        return agent.status_data(res, result_type)

    return Skill(name, description, params, fn, origin=f"remote:{rpc_url}")

"""The agent core: what makes each node of the network an agent rather than a pipeline.

Every agent has
  * a UserProfile   - what its principal likes, avoids and currently needs (stated and learned);
  * a Memory        - outcomes of past decisions, per producer, friend and category;
  * a SkillRegistry - tools it may call: its own, X's ranking stack, or other agents' A2A skills;
  * a Brain         - the policy that turns observations into decisions (an LLM, or rules).

Decisions are actions with reasons ("reject: too-expensive"), recorded so the
principal can always ask why something was let through or kept out.
"""

from .brain import Decision, LLMBrain
from .memory import Memory
from .profile import Need, UserProfile
from .skills import Skill, SkillRegistry, remote_skill

__all__ = ["Decision", "LLMBrain", "Memory", "Need", "UserProfile", "Skill", "SkillRegistry", "remote_skill"]

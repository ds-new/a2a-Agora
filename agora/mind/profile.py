"""What the principal wants: stated preferences, learned preferences, current needs.

The profile is the agent's mandate in the everyday sense: it is what the agent
uses to decide what to let through, what to go and get, and what to disclose.
Stated preferences come from the principal ("I like sci-fi and coffee, no
sports, need trail shoes under $70"); learned ones from how the principal
reacts to what the agent shows. Stated dislikes are never overridden by learning.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from .. import clock
from ..crypto import KeyPair
from ..protocol.schema import INFORMATION, PHYSICAL, make_interest_card

PRIOR = 0.15  # interest assumed in a category nobody has said anything about


@dataclass
class Need:
    text: str
    kind: str
    category: str
    max_price: float
    quantity: int = 1
    deadline: float | None = None
    need_id: str = field(default_factory=lambda: "need-" + uuid.uuid4().hex[:10])
    created_at: float = field(default_factory=clock.now)
    status: str = "open"            # open | satisfied | expired
    attempts: int = 0               # deliberation ticks spent looking
    intent_token: str | None = None
    satisfied_by: str | None = None

    def is_open(self, now: float | None = None) -> bool:
        now = clock.now() if now is None else now
        if self.status == "open" and self.deadline is not None and now > self.deadline:
            self.status = "expired"
        return self.status == "open"

    def brief(self) -> dict:
        return {"id": self.need_id, "text": self.text, "kind": self.kind, "category": self.category,
                "maxPrice": self.max_price, "attempts": self.attempts}


@dataclass
class UserProfile:
    likes: dict[str, float] = field(default_factory=dict)
    dislikes: set[str] = field(default_factory=set)
    stated_likes: set[str] = field(default_factory=set)
    price_max: dict[str, float] = field(default_factory=dict)
    default_price_max: float = 60.0
    info_price_max: float = 5.0
    attention_per_tick: int = 6          # items the principal is willing to look at per tick
    max_per_producer_per_day: int = 3    # rate limit announced in the interest card
    min_trust: float = 0.08
    disclosure: str = "public"           # public | subscribers | private
    forward_to_friends: bool = True
    explore: bool = True                 # may the agent occasionally show something outside stated interests?
    region: str | None = None
    kinds: tuple[str, ...] = (PHYSICAL, INFORMATION)
    needs: list[Need] = field(default_factory=list)
    evidence: dict[str, tuple[float, int]] = field(default_factory=dict)  # category -> (sum of signals, count)

    # ------------------------------------------------------------- preferences
    def like(self, category: str) -> float:
        if category in self.dislikes:
            return 0.0
        return self.likes.get(category, PRIOR)

    def learn(self, category: str, signal: float) -> None:
        """Bayesian average of engagement signals in [0, 1].

        What the principal said counts as 3 observations at 0.8; a category they
        never mentioned starts as 1 observation at PRIOR, so a few reactions can
        reveal an interest they did not state, and a few lukewarm ones do not
        erase one they did."""
        if category in self.dislikes:
            return
        s, n = self.evidence.get(category, (0.0, 0))
        s, n = s + max(0.0, min(1.0, signal)), n + 1
        self.evidence[category] = (s, n)
        stated = category in self.stated_likes
        w0, base = (3.0, 0.8) if stated else (1.0, PRIOR)
        self.likes[category] = round((w0 * base + s) / (w0 + n), 4)

    def price_ceiling(self, kind: str, category: str) -> float:
        if kind == INFORMATION:
            return self.info_price_max
        return self.price_max.get(category, self.default_price_max)

    # ------------------------------------------------------------------- needs
    def add_need(self, *, text: str, kind: str, category: str, max_price: float, quantity: int = 1,
                 ttl_s: float | None = 48 * 3600) -> Need:
        need = Need(text=text, kind=kind, category=category, max_price=round(float(max_price), 2), quantity=quantity,
                    deadline=None if ttl_s is None else clock.now() + ttl_s)
        self.needs.append(need)
        return need

    def open_needs(self, now: float | None = None) -> list[Need]:
        return [n for n in self.needs if n.is_open(now)]

    # ----------------------------------------------------------- interest card
    def card_categories(self) -> dict[str, float]:
        ranked = sorted(((c, w) for c, w in self.likes.items() if c not in self.dislikes and w >= 0.3),
                        key=lambda x: -x[1])
        if self.disclosure == "public":  # coarse: top 4, weights rounded to 0.1
            return {c: round(w, 1) for c, w in ranked[:4]}
        return {c: round(w, 2) for c, w in ranked[:8]}

    def interest_card(self, key: KeyPair, agent_url: str) -> str | None:
        if self.disclosure == "private":
            return None
        cats = self.card_categories()
        return make_interest_card(key, agent_url=agent_url, kinds=list(self.kinds), categories=cats,
                                  avoid=sorted(self.dislikes),
                                  price_max={c: self.price_ceiling(PHYSICAL, c) for c in cats},
                                  max_per_day=self.max_per_producer_per_day, region=self.region,
                                  disclosure=self.disclosure)

    # ------------------------------------------------------------ from words
    @classmethod
    def from_text(cls, text: str, keywords: dict[str, list[str]] | None = None, **kw) -> "UserProfile":
        """Rule-based reading of a principal's own words; see llm.profile_from_text for the LLM path."""
        from ..llm import DEFAULT_KEYWORDS, INFO_CATEGORIES  # noqa: PLC0415

        kwds = keywords or DEFAULT_KEYWORDS
        prof = cls(**kw)
        for clause in re.split(r"[，,。.;；!！?？\n]|但是|不过|\bbut\b|\band\b|以及|还有", text):
            low = clause.lower().strip()
            if not low:
                continue
            cats = [c for c, words in kwds.items() if any(w.lower() in low for w in words)]
            if not cats:
                continue
            negative = any(w in low for w in ("不喜欢", "不想", "不要", "讨厌", "别给", "不看", "dislike", "don't",
                                               "do not", "hate", "avoid", "not interested", "no more"))
            need = any(w in low for w in ("需要", "想买", "要买", "找", "need", "looking for", "want to buy", "buy"))
            prices = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)", low)]
            for c in cats:
                if negative:
                    prof.dislikes.add(c)
                    prof.likes.pop(c, None)
                elif need:
                    kind = INFORMATION if c in INFO_CATEGORIES else PHYSICAL
                    prof.add_need(text=clause.strip(), kind=kind, category=c,
                                  max_price=max(prices) if prices else prof.price_ceiling(kind, c))
                else:
                    prof.likes[c] = 0.8
                    prof.stated_likes.add(c)
                    if prices:
                        prof.price_max[c] = max(prices)
        return prof

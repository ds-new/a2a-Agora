"""Visibility filtering (cf. ``visibility-filtering/rules/registry.rs``).

Ranking decides order; visibility decides whether an item may be shown at all.
Verdicts: ALLOW, NOTICE, INTERSTITIAL, DROP. Rules run in order and the first
DROP ends evaluation. Some rules apply only to out-of-network recommendations
and can only drop (spam caught at high recall), so the same offer stays
visible to someone who follows its producer, as in X.

The difference from X: labels come from labeler agents the *viewer* subscribes
to (composable moderation), and the viewer owns the rule list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..protocol.schema import PHYSICAL
from .pipeline import Candidate

ALLOW, NOTICE, INTERSTITIAL, DROP = "ALLOW", "NOTICE", "INTERSTITIAL", "DROP"
_RANK = {ALLOW: 0, NOTICE: 1, INTERSTITIAL: 2, DROP: 3}


@dataclass
class Rule:
    name: str
    check: Callable[[dict, Candidate], str | None]
    oon_only: bool = False


def _labels(c: Candidate) -> list[dict]:
    return c.features.get("labels", [])


def _max_sev(c: Candidate, names: set[str]) -> float:
    return max((lab["severity"] for lab in _labels(c) if lab["label"] in names), default=0.0)


def default_rules() -> list[Rule]:
    return [
        Rule("AuthorBlockedOrMuted", lambda q, c: DROP if c.producer in q["blocked"] else None),
        Rule("Expired", lambda q, c: DROP if c.offer["expiresAt"] < q["now"] else None),
        Rule("FraudLabel", lambda q, c: DROP if _max_sev(c, {"fraud", "hash-mismatch"}) >= 0.5 else None),
        Rule("ScamRiskLabel", lambda q, c: (DROP if (s := _max_sev(c, {"scam-risk"})) >= 0.7
                                            else INTERSTITIAL if s >= 0.3 else None)),
        Rule("NotShippable", lambda q, c: DROP if c.kind == PHYSICAL and q["region"] not in
             c.offer["shipping"]["regions"] else None),
        Rule("OverMandateNotice", lambda q, c: NOTICE if c.offer["price"]["amount"] > q["max_item_price"] else None),
        # out-of-network only, drop-only
        Rule("HighRefundRateOON", lambda q, c: DROP if c.features.get("refund_rate", 0) > 0.3
             and c.features.get("settled", 0) >= 3 else None, oon_only=True),
        Rule("LabeledLowCredOON", lambda q, c: DROP if c.features.get("reputation", 1.0) < 0.15
             and _labels(c) else None, oon_only=True),
    ]


def evaluate(query: dict, c: Candidate, rules: list[Rule]) -> tuple[str, str | None]:
    verdict, why = ALLOW, None
    for rule in rules:
        if rule.oon_only and c.in_network:
            continue
        v = rule.check(query, c)
        if v is None:
            continue
        if v == DROP:
            return DROP, rule.name
        if _RANK[v] > _RANK[verdict]:
            verdict, why = v, rule.name
    return verdict, why

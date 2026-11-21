"""Port of ``xai-value-model/`` (scoring.rs, weights.rs) with a commerce action space.

    Final Score = sum_i weight_i * P(action_i)   (+ weight_dwell_time * E[dwell seconds])

then ``offset_score`` (negative scores squeezed below NEGATIVE_SCORES_OFFSET),
author diversity decay, out-of-network discount and a new-producer exploration
bonus, exactly as ``compute_value_scores_with_adjustment`` does.

Weights for actions X also has are X's production defaults from
home-mixer/params/param.rs. Commerce actions (inquire, purchase, return) are
ours. Diversity/OON defaults are the 2023 twitter/the-algorithm values
(AuthorDiversityDecayFactor 0.5, AuthorDiversityFloor 0.25,
OutOfNetworkScaleFactorParam 0.75) because the 2026 code reads them from config.

The weights belong to the principal: a user who wants fewer impulse buys or
less doom-scrolling edits them, nobody else does.
"""

from __future__ import annotations

from dataclasses import dataclass, field

NEGATIVE_SCORES_OFFSET = 0.001  # weights.rs

BINARY_ACTIONS = [
    "click", "dwell", "favorite", "reply", "repost", "share", "follow_author",   # X heads
    "inquire", "purchase",                                                       # commerce (ours)
    "not_interested", "mute_author", "block_author", "report", "not_dwelled",    # X negatives
    "return",                                                                    # commerce negative (ours)
]
CONTINUOUS_ACTIONS = ["dwell_time"]
NEGATIVE_ACTIONS = {"not_interested", "mute_author", "block_author", "report", "not_dwelled", "return"}

X_DEFAULT_WEIGHTS = {  # home-mixer/params/param.rs @ 9081b33
    "click": 0.274, "dwell": 0.05, "favorite": 0.708, "reply": 5.0, "repost": 1.0, "share": 2.118,
    "follow_author": 4.0, "not_interested": -53.07, "mute_author": -58.8, "block_author": -31.2,
    "report": -234.0, "not_dwelled": -0.02,
}
COMMERCE_DEFAULT_WEIGHTS = {"inquire": 3.0, "purchase": 12.0, "return": -40.0}


def _default_weights() -> dict[str, float]:
    return {**X_DEFAULT_WEIGHTS, **COMMERCE_DEFAULT_WEIGHTS}


@dataclass
class ValueModelWeights:
    weights: dict[str, float] = field(default_factory=_default_weights)
    cont_dwell_time: float = 0.0075  # ContDwellTimeWeight
    enable_author_diversity: bool = True
    author_diversity_decay: float = 0.5
    author_diversity_floor: float = 0.25
    oon_weight: float = 0.75
    oon_rescore_in_network_reposts: bool = False  # oon_rescore_in_network_replies_retweets
    new_producer_bonus: float = 0.15
    new_producer_threshold: int = 3   # verified sales + endorsements below this count as "new"

    def positive_sum(self) -> float:
        return sum(w for a, w in self.weights.items() if a not in NEGATIVE_ACTIONS)

    def negative_sum(self) -> float:
        return -sum(w for a, w in self.weights.items() if a in NEGATIVE_ACTIONS)

    def total_sum(self) -> float:
        return self.positive_sum() + self.negative_sum()


def weighted_terms(w: ValueModelWeights, scores: dict[str, float]) -> dict[str, float]:
    terms = {a: scores.get(a, 0.0) * wt for a, wt in w.weights.items()}
    terms["dwell_time"] = scores.get("dwell_time", 0.0) * w.cont_dwell_time
    return terms


def compute_weighted_score(w: ValueModelWeights, scores: dict[str, float]) -> float:
    return sum(weighted_terms(w, scores).values())


def offset_score(combined: float, w: ValueModelWeights) -> float:
    total = w.total_sum()
    if total == 0.0:
        return max(combined, 0.0)
    if combined < 0.0:
        return (combined + w.negative_sum()) / total * NEGATIVE_SCORES_OFFSET
    return combined + NEGATIVE_SCORES_OFFSET


def unoffset_score(weighted: float, w: ValueModelWeights) -> float:
    total = w.total_sum()
    if total == 0.0:
        return weighted
    if weighted < NEGATIVE_SCORES_OFFSET:
        return weighted / NEGATIVE_SCORES_OFFSET * total - w.negative_sum()
    return weighted - NEGATIVE_SCORES_OFFSET


def diversity_multiplier(decay: float, floor: float, k: float) -> float:
    return (1.0 - floor) * decay ** k + floor


def author_pool_counts(author_ids: list[str], ordering_scores: list[float]) -> list[int]:
    """How many higher-scored candidates share each candidate's author."""
    order = sorted(range(len(author_ids)), key=lambda i: ordering_scores[i], reverse=True)
    seen: dict[str, int] = {}
    counts = [0] * len(author_ids)
    for i in order:
        counts[i] = seen.get(author_ids[i], 0)
        seen[author_ids[i]] = counts[i] + 1
    return counts


def add_exploration_bonus(weighted: float, bonus: float, w: ValueModelWeights) -> float:
    if bonus == 0.0:
        return weighted
    return offset_score(unoffset_score(weighted, w) + bonus, w)


@dataclass
class ScoringInputs:
    author_id: str
    scores: dict[str, float]
    in_network: bool
    is_repost: bool = False
    exploration_bonus: float = 0.0


def compute_value_scores(w: ValueModelWeights, cands: list[ScoringInputs]) -> tuple[list[float], list[float]]:
    """Returns (weighted, final) like ValueScores in scoring.rs."""
    weighted = [offset_score(compute_weighted_score(w, c.scores), w) for c in cands]
    base = [add_exploration_bonus(s, c.exploration_bonus, w) for s, c in zip(weighted, cands)]
    if w.enable_author_diversity:
        counts = author_pool_counts([c.author_id for c in cands], base)
        div = [diversity_multiplier(w.author_diversity_decay, w.author_diversity_floor, k) for k in counts]
    else:
        div = [1.0] * len(cands)
    final = []
    for s, d, c in zip(base, div, cands):
        oon = (not c.in_network) or (w.oon_rescore_in_network_reposts and c.is_repost)
        final.append(s * d * (w.oon_weight if oon else 1.0))
    return weighted, final

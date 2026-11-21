"""Python port of ``candidate-pipeline/`` (the framework ``home-mixer`` is built on).

Stage order follows ``CandidatePipeline::execute_stages`` in
candidate-pipeline/candidate_pipeline.rs:

  query hydrators (parallel) -> sources (parallel) -> hydrators (parallel)
  -> filters (in order) -> scorers (in order) -> selector
  -> post-selection hydrators -> post-selection filters -> truncate
  -> side effects

A failing source or hydrator is logged and skipped, as in the Rust version.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("agora.pipeline")


@dataclass
class Candidate:
    offer_id: str
    token: str
    offer: dict
    source: str
    in_network: bool = False
    endorsers: list[str] = field(default_factory=list)   # propagation chain (root -> leaf)
    endorsement_token: str | None = None
    features: dict[str, Any] = field(default_factory=dict)
    phoenix_scores: dict[str, float] = field(default_factory=dict)
    weighted_score: float = 0.0
    score: float = 0.0
    visibility: str = "ALLOW"
    reasons: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)  # agent-level context: sender, pitch, intent, need

    @property
    def producer(self) -> str:
        return self.offer["producer"]

    @property
    def kind(self) -> str:
        return self.offer["kind"]


class Stage:
    name = "stage"

    def enabled(self, query: dict) -> bool:
        return True


class QueryHydrator(Stage):
    async def hydrate(self, query: dict) -> dict:
        raise NotImplementedError


class Source(Stage):
    async def source(self, query: dict) -> list[Candidate]:
        raise NotImplementedError


class Hydrator(Stage):
    async def hydrate(self, query: dict, candidates: list[Candidate]) -> None:
        raise NotImplementedError


class Filter(Stage):
    def keep(self, query: dict, c: Candidate) -> bool:
        raise NotImplementedError

    def filter(self, query: dict, candidates: list[Candidate]) -> tuple[list[Candidate], list[Candidate]]:
        kept, removed = [], []
        for c in candidates:
            if self.keep(query, c):
                kept.append(c)
            else:
                c.reasons.append(f"filtered:{self.name}")
                removed.append(c)
        return kept, removed


class Scorer(Stage):
    async def score(self, query: dict, candidates: list[Candidate]) -> None:
        raise NotImplementedError


class Selector(Stage):
    def select(self, query: dict, candidates: list[Candidate]) -> tuple[list[Candidate], list[Candidate]]:
        raise NotImplementedError


class SideEffect(Stage):
    async def run(self, query: dict, selected: list[Candidate], non_selected: list[Candidate]) -> None:
        raise NotImplementedError


class TopKScoreSelector(Selector):
    """home-mixer/selectors/top_k_score_selector.rs: sort by final score, keep top K."""

    name = "TopKScoreSelector"

    def __init__(self, k: int):
        self.k = k

    def select(self, query, candidates):
        ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
        return ranked[: self.k], ranked[self.k:]


@dataclass
class PipelineResult:
    query: dict
    retrieved: list[Candidate]
    filtered: list[Candidate]
    selected: list[Candidate]
    trace: dict[str, Any]


@dataclass
class CandidatePipeline:
    name: str
    query_hydrators: list[QueryHydrator]
    sources: list[Source]
    hydrators: list[Hydrator]
    filters: list[Filter]
    scorers: list[Scorer]
    selector: Selector
    post_selection_hydrators: list[Hydrator]
    post_selection_filters: list[Filter]
    side_effects: list[SideEffect]
    result_size: int

    async def execute(self, query: dict) -> PipelineResult:
        trace: dict[str, Any] = {"pipeline": self.name, "stages": []}

        updates = await asyncio.gather(
            *(h.hydrate(query) for h in self.query_hydrators if h.enabled(query)), return_exceptions=True)
        for h, upd in zip([h for h in self.query_hydrators if h.enabled(query)], updates):
            if isinstance(upd, BaseException):
                log.warning("query hydrator %s failed: %s", h.name, upd)
            else:
                query.update(upd)

        srcs = [s for s in self.sources if s.enabled(query)]
        results = await asyncio.gather(*(s.source(query) for s in srcs), return_exceptions=True)
        candidates: list[Candidate] = []
        for s, res in zip(srcs, results):
            if isinstance(res, BaseException):
                log.warning("source %s failed: %s", s.name, res)
                continue
            trace["stages"].append(("source", s.name, len(res)))
            candidates.extend(res)

        await self._hydrate(self.hydrators, query, candidates)
        retrieved = list(candidates)

        filtered: list[Candidate] = []
        for f in self.filters:
            if f.enabled(query):
                candidates, removed = f.filter(query, candidates)
                filtered.extend(removed)
                trace["stages"].append(("filter", f.name, len(removed)))

        for sc in self.scorers:
            if sc.enabled(query):
                await sc.score(query, candidates)

        selected, non_selected = self.selector.select(query, candidates)
        await self._hydrate(self.post_selection_hydrators, query, selected)
        for f in self.post_selection_filters:
            if f.enabled(query):
                selected, removed = f.filter(query, selected)
                filtered.extend(removed)
                trace["stages"].append(("post_filter", f.name, len(removed)))
        non_selected.extend(selected[self.result_size:])
        selected = selected[: self.result_size]

        for se in self.side_effects:
            if se.enabled(query):
                try:
                    await se.run(query, selected, non_selected)
                except Exception as exc:  # noqa: BLE001
                    log.warning("side effect %s failed: %s", se.name, exc)
        trace["sizes"] = {"retrieved": len(retrieved), "filtered": len(filtered), "selected": len(selected)}
        return PipelineResult(query, retrieved, filtered, selected, trace)

    @staticmethod
    async def _hydrate(hydrators: list[Hydrator], query: dict, candidates: list[Candidate]) -> None:
        active = [h for h in hydrators if h.enabled(query)]
        results = await asyncio.gather(*(h.hydrate(query, candidates) for h in active), return_exceptions=True)
        for h, res in zip(active, results):
            if isinstance(res, BaseException):
                log.warning("hydrator %s failed: %s", h.name, res)

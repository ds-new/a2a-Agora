"""Bilateral price negotiation with time-dependent concession (Faratin et al., 1998).

The seller concedes from list price toward its floor; the buyer concedes from an
opening bid toward its reservation price; a deal exists only if the floor is at
most the reservation price. Both sides stop after ``max_rounds``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SellerPolicy:
    list_price: float
    floor_price: float
    max_rounds: int = 4
    beta: float = 1.0  # <1 concedes late (Boulware), >1 concedes early (Conceder)

    def target(self, r: int) -> float:
        frac = min(1.0, r / self.max_rounds) ** (1.0 / self.beta)
        return round(self.floor_price + (self.list_price - self.floor_price) * (1.0 - frac), 2)

    def respond(self, r: int, counter: float | None) -> tuple[str, float]:
        """Returns ("accept", price) | ("quote", price) | ("final", price)."""
        own = self.target(r)
        if counter is not None and counter >= own:
            return "accept", round(counter, 2)
        if r >= self.max_rounds:
            return "final", self.target(self.max_rounds)
        return "quote", own


@dataclass
class BuyerPolicy:
    reservation: float
    opening_ratio: float = 0.75
    max_rounds: int = 4

    def target(self, r: int, list_price: float) -> float:
        opening = min(self.reservation, list_price) * self.opening_ratio
        frac = min(1.0, r / self.max_rounds)
        return round(opening + (min(self.reservation, list_price) - opening) * frac, 2)

    def respond(self, r: int, quote: float, list_price: float, final: bool = False) -> tuple[str, float | None]:
        """Returns ("accept", price) | ("counter", price) | ("walk", None)."""
        if quote <= self.target(r, list_price) + 1e-9:
            return "accept", quote
        if final or r >= self.max_rounds:
            return ("accept", quote) if quote <= self.reservation + 1e-9 else ("walk", None)
        return "counter", self.target(r, list_price)

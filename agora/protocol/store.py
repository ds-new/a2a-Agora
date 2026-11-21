"""Each agent's local, verified view of the network's signed objects.

There is no shared database: agents learn objects from direct exchanges and
gossip, verify every signature on intake, and derive their own statistics
(popularity, sales, refund rates) from what they can verify.
"""

from __future__ import annotations

from collections import defaultdict

from ..crypto import SignatureError, jws_decode_unverified, text_hash
from .records import verify_label, verify_review, verify_settlement
from .schema import TYP, ProtocolError, endorsement_chain, verify_intent, verify_interest_card, verify_offer

_KIND_BY_TYP = {v: k for k, v in TYP.items()}
GOSSIP_KINDS = ("offer", "endorsement", "settlement", "review", "label", "intent", "interest")


class ObjectStore:
    def __init__(self, trusted_escrows: set[str] | None = None):
        self.trusted_escrows = set(trusted_escrows or ())
        self.offers: dict[str, tuple[str, dict]] = {}
        self.offers_by_producer: dict[str, list[str]] = defaultdict(list)
        self.endorsements: dict[str, tuple[str, dict]] = {}
        self.endorsements_by_offer: dict[str, list[str]] = defaultdict(list)
        self.settlements: dict[str, tuple[str, dict]] = {}
        self.reviews: dict[str, tuple[str, dict]] = {}
        self.reviews_by_subject: dict[str, list[str]] = defaultdict(list)
        self.labels: dict[str, tuple[str, dict]] = {}
        self.labels_by_subject: dict[str, list[str]] = defaultdict(list)
        self.intents: dict[str, tuple[str, dict]] = {}
        self.interest_by_id: dict[str, tuple[str, dict]] = {}
        self.interest_cards: dict[str, tuple[str, dict]] = {}  # agent DID -> its latest card
        self._log: dict[str, list[str]] = defaultdict(list)  # kind -> ids in arrival order
        self._seen_tokens: set[str] = set()
        self.version = 0

    # ------------------------------------------------------------------ intake
    def add(self, token: str) -> tuple[str, dict] | None:
        """Verify and insert; returns (kind, payload) if it was new, else None."""
        if not isinstance(token, str):
            return None
        h = text_hash(token)
        if h in self._seen_tokens:
            return None
        self._seen_tokens.add(h)
        try:
            header, _ = jws_decode_unverified(token)
            kind = _KIND_BY_TYP.get(header.get("typ", ""))
            if kind == "offer":
                p = verify_offer(token)
                key = p["offerId"]
                if key in self.offers:
                    return None
                self.offers[key] = (token, p)
                self.offers_by_producer[p["producer"]].append(key)
            elif kind == "endorsement":
                chain = endorsement_chain(token)
                _, ep = jws_decode_unverified(token)
                key = ep["endorsementId"]
                if key in self.endorsements:
                    return None
                p = {**ep, "endorsers": chain["endorsers"]}
                self.endorsements[key] = (token, p)
                self.endorsements_by_offer[p["offerId"]].append(key)
                self.add(chain["offerToken"])
            elif kind == "settlement":
                p = verify_settlement(token)
                key = f"{p['escrowId']}:{p['status']}"
                if key in self.settlements:
                    return None
                self.settlements[key] = (token, p)
            elif kind == "review":
                p = verify_review(token)
                key = p["reviewId"]
                if key in self.reviews:
                    return None
                self.reviews[key] = (token, p)
                self.reviews_by_subject[p["subject"]].append(key)
                self.add(p["settlement"])
            elif kind == "label":
                p = verify_label(token)
                key = p["labelId"]
                if key in self.labels:
                    return None
                self.labels[key] = (token, p)
                self.labels_by_subject[p["subject"]].append(key)
            elif kind == "interest":
                p = verify_interest_card(token)
                key = p["cardId"]
                cur = self.interest_cards.get(p["agent"])
                if key in self.interest_by_id or (cur and cur[1]["issuedAt"] >= p["issuedAt"]):
                    return None
                self.interest_by_id[key] = (token, p)
                self.interest_cards[p["agent"]] = (token, p)
            elif kind == "intent":
                p = verify_intent(token)
                key = p["intentId"]
                if key in self.intents:
                    return None
                self.intents[key] = (token, p)
            else:
                return None
        except (ProtocolError, SignatureError, KeyError, TypeError, ValueError):
            return None
        self._log[kind].append(key)
        self.version += 1
        return kind, p

    def add_many(self, tokens: list[str]) -> int:
        return sum(1 for t in tokens if self.add(t) is not None)

    def _table(self, kind: str) -> dict:
        return {"offer": self.offers, "endorsement": self.endorsements, "settlement": self.settlements,
                "review": self.reviews, "label": self.labels, "intent": self.intents,
                "interest": self.interest_by_id}[kind]

    def _shareable(self, kind: str, entry: tuple[str, dict]) -> bool:
        # an interest card travels further only if its owner chose "public" disclosure
        return kind != "interest" or entry[1].get("disclosure") == "public"

    def recent_tokens(self, kind: str, limit: int) -> list[str]:
        table = self._table(kind)
        return [table[k][0] for k in self._log[kind][-limit:] if self._shareable(kind, table[k])]

    def recent_tokens_range(self, kind: str, start: int, end: int) -> list[str]:
        table = self._table(kind)
        return [table[k][0] for k in self._log[kind][start:end] if self._shareable(kind, table[k])]

    def cards(self, now: float) -> list[dict]:
        """Latest unexpired interest card of every agent we know."""
        return [p for _, p in self.interest_cards.values() if p["expiresAt"] >= now]

    # ------------------------------------------------------------- derived stats
    def _trusted(self, p: dict) -> bool:
        return not self.trusted_escrows or p["escrow"] in self.trusted_escrows

    def settlements_for_merchant(self, did: str) -> list[dict]:
        return [p for _, p in self.settlements.values() if p["merchant"] == did and self._trusted(p)]

    def merchant_stats(self, did: str) -> dict:
        released = refunded = 0
        gmv = 0.0
        for p in self.settlements_for_merchant(did):
            if p["status"] == "released":
                released += 1
                gmv += p["amount"]
            elif p["status"] == "refunded":
                refunded += 1
        ratings = [self.reviews[k][1]["rating"] for k in self.reviews_by_subject.get(did, [])]
        return {"sales": released, "refunds": refunded, "gmv": round(gmv, 2),
                "refund_rate": refunded / max(1, released + refunded),
                "rating": sum(ratings) / len(ratings) if ratings else None, "n_ratings": len(ratings)}

    def offer_popularity(self, offer_id: str) -> dict:
        purchases = sum(1 for _, p in self.settlements.values()
                        if p["status"] == "released" and offer_id in p["offerIds"] and self._trusted(p))
        return {"endorsements": len(self.endorsements_by_offer.get(offer_id, [])), "purchases": purchases}

    def labels_for(self, subject: str, labelers: set[str] | None, now: float) -> list[dict]:
        out = []
        for k in self.labels_by_subject.get(subject, []):
            p = self.labels[k][1]
            if p["exp"] >= now and (labelers is None or p["labeler"] in labelers):
                out.append(p)
        return out


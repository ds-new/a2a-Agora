"""Signed protocol objects shared by every agent.

One Offer type covers both physical goods and information goods, so the same
propagation, ranking, negotiation, payment and reputation machinery serves
both. All objects are compact JWS tokens signed by the agent named inside
them; the ``*Id`` of an object is the content hash of its unsigned payload.

A2A carries these tokens in ``data`` parts:
``{"data": {"type": "agora.offer.push", "offer": "<jws>"}, "mediaType": "application/json"}``.
"""

from __future__ import annotations

import uuid
from typing import Any

from .. import clock
from ..crypto import KeyPair, content_id, jws_sign, jws_verify, text_hash

__all__ = [
    "EXT_MARKET", "EXT_MANDATES", "EXT_GOSSIP", "AGORA_EXTENSIONS", "PHYSICAL", "INFORMATION", "TYP",
    "ProtocolError", "make_offer", "verify_offer", "make_endorsement", "verify_endorsement",
    "endorsement_chain", "make_intent", "verify_intent", "make_checkout", "verify_checkout",
    "checkout_hash", "make_signed", "verify_signed", "referral_splits", "EXT_AGENTNET", "REASONS", "DISCLOSURE",
    "make_interest_card", "verify_interest_card", "make_feedback", "verify_feedback",
]

# A2A extension URIs declared in Agent Cards (URNs: this prototype owns no domain).
EXT_MARKET = "urn:agora:ext:market:v1"          # offers, intents, endorsements, negotiation, fulfilment
EXT_MANDATES = "urn:agora:ext:ap2-mandates:v0.2"  # AP2 v0.2 mandate chain, JWS profile
EXT_GOSSIP = "urn:agora:ext:gossip:v1"          # peer exchange of cards and signed objects
EXT_AGENTNET = "urn:agora:ext:agent-network:v1"  # interest cards, proposals, feedback, queries, recommendations
AGORA_EXTENSIONS = [EXT_MARKET, EXT_MANDATES, EXT_GOSSIP, EXT_AGENTNET]

# Why an agent turned something down (sent back to the producer so it can target better)
REASONS = ("need-match", "relevant", "off-topic", "disliked-category", "too-expensive", "low-trust", "unsafe",
           "attention-budget", "duplicate", "rate-limit", "blocked", "not-shippable", "unsolicited")
DISCLOSURE = ("public", "subscribers", "private")

PHYSICAL = "physical"
INFORMATION = "information"

TYP = {
    "offer": "agora.offer+jws",
    "endorsement": "agora.endorsement+jws",
    "intent": "agora.intent+jws",
    "checkout": "agora.checkout+jws",
    "settlement": "agora.settlement+jws",
    "review": "agora.review+jws",
    "label": "agora.label+jws",
    "delivery": "agora.delivery+jws",
    "payment_receipt": "agora.payment-receipt+jws",
    "content": "agora.content+jws",
    "mandate": "ap2.mandate+jws",
    "instruction": "agora.instruction+jws",  # signed commands: release, dispute, ship, return, transfer
    "interest": "agora.interest+jws",        # what an agent is willing to receive, at a disclosure level it picks
    "feedback": "agora.feedback+jws",        # accept/reject decision on a proposal, with reasons
}

MAX_ENDORSEMENT_DEPTH = 6


class ProtocolError(ValueError):
    pass


def _with_id(payload: dict, id_field: str) -> dict:
    payload = {k: v for k, v in payload.items() if k != id_field}
    return {**payload, id_field: content_id(payload)}


def _check_id(payload: dict, id_field: str) -> None:
    body = {k: v for k, v in payload.items() if k != id_field}
    if payload.get(id_field) != content_id(body):
        raise ProtocolError(f"{id_field} does not match content")


def make_signed(kind: str, payload: dict, key: KeyPair, id_field: str | None = None) -> str:
    if id_field:
        payload = _with_id(payload, id_field)
    return jws_sign(payload, key, typ=TYP[kind])


def verify_signed(kind: str, token: str, signer_field: str, id_field: str | None = None) -> dict:
    header, payload = jws_verify(token, expected_typ=TYP[kind])
    if payload.get(signer_field) != header["kid"]:
        raise ProtocolError(f"{kind}: {signer_field} is not the signer")
    if id_field:
        _check_id(payload, id_field)
    return payload


# --------------------------------------------------------------------------- #
# Offer: a unit of supply, physical or informational
# --------------------------------------------------------------------------- #


def make_offer(
    key: KeyPair,
    *,
    producer_url: str,
    kind: str,
    title: str,
    description: str,
    category: str,
    tags: list[str] | None = None,
    price: float = 0.0,
    currency: str = "USD",
    inventory: int | None = None,
    ship_regions: list[str] | None = None,
    ship_days: int | None = None,
    content: str | None = None,
    paid_content: str | None = None,
    teaser: str | None = None,
    license: str | None = None,
    referral_bps: int = 0,
    referral_depth: int = 3,
    reply_to: str | None = None,
    ttl_hours: float = 48.0,
    sku: str | None = None,
) -> tuple[str, dict]:
    if kind not in (PHYSICAL, INFORMATION):
        raise ProtocolError(f"unknown kind {kind!r}")
    if kind == PHYSICAL and (inventory is None or not ship_regions):
        raise ProtocolError("physical offers need inventory and ship_regions")
    if kind == INFORMATION and price > 0 and paid_content is None:
        raise ProtocolError("paid information needs paid_content to commit to its hash")
    t = clock.now()
    payload: dict[str, Any] = {
        "type": "agora.offer", "v": 1, "producer": key.did, "producerUrl": producer_url, "kind": kind,
        "title": title, "description": description, "category": category, "tags": list(tags or []),
        "price": {"amount": round(float(price), 2), "currency": currency},
        "referral": {"bps": int(referral_bps), "maxDepth": int(referral_depth)},
        "createdAt": t, "expiresAt": t + ttl_hours * 3600,
    }
    if sku:
        payload["sku"] = sku
    if kind == PHYSICAL:
        payload["inventory"] = int(inventory)  # type: ignore[arg-type]
        payload["shipping"] = {"regions": list(ship_regions or []), "days": int(ship_days or 3)}
    else:
        payload["license"] = license or "personal-use"
        if price > 0:
            payload["contentHash"] = text_hash(paid_content or "")
            payload["teaser"] = teaser or description[:140]
        else:
            payload["content"] = content if content is not None else description
    if reply_to:
        payload["replyTo"] = reply_to
    token = make_signed("offer", payload, key, "offerId")
    return token, verify_offer(token)


def verify_offer(token: str) -> dict:
    return verify_signed("offer", token, "producer", "offerId")


# --------------------------------------------------------------------------- #
# Endorsement: a repost. Chains of endorsements carry propagation provenance,
# which is what referral fees are paid on.
# --------------------------------------------------------------------------- #


def make_endorsement(key: KeyPair, *, offer_token: str, parent: str | None = None, comment: str | None = None) -> str:
    offer = verify_offer(offer_token)
    payload: dict[str, Any] = {
        "type": "agora.endorsement", "endorser": key.did, "offerId": offer["offerId"], "at": clock.now(),
        "offer": offer_token if parent is None else None, "parent": parent,
    }
    if comment:
        payload["comment"] = comment
    if parent is not None:
        chain = endorsement_chain(parent)
        if len(chain["endorsers"]) >= MAX_ENDORSEMENT_DEPTH:
            raise ProtocolError("endorsement chain too deep")
        if chain["offer"]["offerId"] != offer["offerId"]:
            raise ProtocolError("parent endorses a different offer")
    return make_signed("endorsement", payload, key, "endorsementId")


def verify_endorsement(token: str) -> dict:
    return verify_signed("endorsement", token, "endorser", "endorsementId")


def endorsement_chain(token: str) -> dict:
    """Verify a whole chain. Returns {"offer": payload, "offerToken", "endorsers": [root..leaf]}."""
    endorsers: list[str] = []
    cur: str | None = token
    depth = 0
    while cur is not None:
        depth += 1
        if depth > MAX_ENDORSEMENT_DEPTH + 1:
            raise ProtocolError("endorsement chain too deep")
        e = verify_endorsement(cur)
        endorsers.append(e["endorser"])
        if e["parent"] is None:
            offer_token = e["offer"]
            offer = verify_offer(offer_token)
            if offer["offerId"] != e["offerId"]:
                raise ProtocolError("endorsement root does not match offer")
            endorsers.reverse()
            return {"offer": offer, "offerToken": offer_token, "endorsers": endorsers}
        cur = e["parent"]
    raise ProtocolError("unreachable")


def referral_splits(amount: float, offer: dict, chain: list[str], buyer: str) -> list[tuple[str, float]]:
    """Referral pool = amount * bps; the endorser closest to the buyer gets the largest share.

    Weights halve per hop away from the buyer (1, 1/2, 1/4, ...), over at most
    ``maxDepth`` hops. The producer and the buyer never earn referral fees.
    """
    ref = offer.get("referral") or {}
    bps, depth = int(ref.get("bps", 0)), int(ref.get("maxDepth", 0))
    eligible = [d for d in chain if d not in (offer["producer"], buyer)]
    seen: set[str] = set()
    uniq = [d for d in reversed(eligible) if not (d in seen or seen.add(d))][:depth]  # leaf first
    if bps <= 0 or not uniq:
        return []
    pool = amount * bps / 10_000
    weights = [0.5 ** i for i in range(len(uniq))]
    total = sum(weights)
    return [(d, round(pool * w / total, 2)) for d, w in zip(uniq, weights)]


# --------------------------------------------------------------------------- #
# Intent: a consumer's need, broadcast to producers (C2M / reverse matching)
# --------------------------------------------------------------------------- #


def make_intent(key: KeyPair, *, consumer_url: str, text: str, kind: str, category: str, max_price: float,
                quantity: int = 1, region: str | None = None, ttl_hours: float = 24.0) -> str:
    t = clock.now()
    payload = {"type": "agora.intent", "consumer": key.did, "consumerUrl": consumer_url, "text": text,
               "kind": kind, "category": category, "maxPrice": round(float(max_price), 2), "quantity": quantity,
               "region": region, "createdAt": t, "expiresAt": t + ttl_hours * 3600}
    return make_signed("intent", payload, key, "intentId")


def verify_intent(token: str) -> dict:
    return verify_signed("intent", token, "consumer", "intentId")


# --------------------------------------------------------------------------- #
# Checkout: the merchant-signed quote (AP2 "Checkout JWT")
# --------------------------------------------------------------------------- #


def make_checkout(key: KeyPair, *, buyer: str, offer: dict, quantity: int, unit_price: float, escrow: str,
                  referral_chain: list[str], region: str | None, round_idx: int, ttl_s: float = 3600) -> str:
    t = clock.now()
    ship_fee = 0.0
    subtotal = round(unit_price * quantity, 2)
    payload = {
        "type": "agora.checkout", "checkoutId": str(uuid.uuid4()), "merchant": key.did, "buyer": buyer,
        "lineItems": [{"offerId": offer["offerId"], "title": offer["title"], "category": offer["category"],
                       "kind": offer["kind"], "quantity": quantity, "unitPrice": round(unit_price, 2)}],
        "shipping": ({"region": region, "days": offer["shipping"]["days"], "fee": ship_fee}
                     if offer["kind"] == PHYSICAL else None),
        "total": {"amount": round(subtotal + ship_fee, 2), "currency": offer["price"]["currency"]},
        "escrow": escrow, "referral": {"bps": offer["referral"]["bps"], "chain": list(referral_chain)},
        "contentHash": offer.get("contentHash"), "round": round_idx, "iat": t, "exp": t + ttl_s,
    }
    return make_signed("checkout", payload, key)


def verify_checkout(token: str, merchant: str | None = None) -> dict:
    p = verify_signed("checkout", token, "merchant")
    if merchant is not None and p["merchant"] != merchant:
        raise ProtocolError("checkout signed by a different merchant")
    if p["exp"] < clock.now():
        raise ProtocolError("checkout expired")
    return p


def checkout_hash(token: str) -> str:
    return text_hash(token)


# --------------------------------------------------------------------------- #
# Interest card: what an agent is willing to receive. The agent (not a platform)
# decides how much of its principal's taste to disclose, and to whom.
# --------------------------------------------------------------------------- #


def make_interest_card(key: KeyPair, *, agent_url: str, kinds: list[str], categories: dict[str, float],
                       avoid: list[str], price_max: dict[str, float], max_per_day: int, region: str | None,
                       disclosure: str = "public", ttl_hours: float = 72.0) -> str:
    if disclosure not in DISCLOSURE:
        raise ProtocolError(f"unknown disclosure {disclosure!r}")
    t = clock.now()
    payload = {"type": "agora.interest", "agent": key.did, "agentUrl": agent_url, "kinds": sorted(kinds),
               "categories": {c: round(float(w), 2) for c, w in sorted(categories.items())},
               "avoid": sorted(avoid), "priceMax": {c: round(float(p), 2) for c, p in sorted(price_max.items())},
               "maxPerDay": int(max_per_day), "region": region, "disclosure": disclosure,
               "issuedAt": t, "expiresAt": t + ttl_hours * 3600}
    return make_signed("interest", payload, key, "cardId")


def verify_interest_card(token: str) -> dict:
    return verify_signed("interest", token, "agent", "cardId")


# --------------------------------------------------------------------------- #
# Feedback: a receiving agent's decision on one proposal, signed so producers
# can trust it came from the agent they targeted.
# --------------------------------------------------------------------------- #


def make_feedback(key: KeyPair, *, to: str, offer_id: str, decision: str, reasons: list[str]) -> str:
    if decision not in ("accept", "reject", "purchased"):
        raise ProtocolError(f"unknown decision {decision!r}")
    bad = [r for r in reasons if r not in REASONS]
    if bad:
        raise ProtocolError(f"unknown reasons {bad}")
    return make_signed("feedback", {"type": "agora.feedback", "from": key.did, "to": to, "offerId": offer_id,
                                    "decision": decision, "reasons": list(reasons), "at": clock.now()}, key)


def verify_feedback(token: str, to: str | None = None) -> dict:
    p = verify_signed("feedback", token, "from")
    if to is not None and p["to"] != to:
        raise ProtocolError("feedback addressed to someone else")
    return p

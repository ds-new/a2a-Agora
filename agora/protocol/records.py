"""Records issued after a deal: payment receipts, deliveries, content deliveries,
settlements, reviews and moderation labels. Each is signed by the party that
attests to it, so any agent can verify the history without trusting a platform."""

from __future__ import annotations

import uuid

from .. import clock
from ..crypto import KeyPair, text_hash
from .schema import ProtocolError, make_signed, verify_checkout, verify_signed

# -------------------------------------------------------------- instructions


def sign_instruction(key: KeyPair, payload: dict) -> str:
    """A signed command (release, dispute, ship-order, return-order, transfer-order, follow).

    Economically meaningful requests are signed objects, so an agent can act on
    them without trusting the transport or holding sessions."""
    return make_signed("instruction", {**payload, "by": key.did, "at": clock.now(), "nonce": str(uuid.uuid4())}, key)


def verify_instruction(token: str, expected_type: str, max_age_s: float = 3600) -> dict:
    p = verify_signed("instruction", token, "by")
    if p.get("type") != expected_type:
        raise ProtocolError(f"expected {expected_type}, got {p.get('type')}")
    if clock.now() - p["at"] > max_age_s:
        raise ProtocolError("instruction too old")
    return p


# ------------------------------------------------------------------ payments


def make_payment_receipt(bank: KeyPair, *, transaction_id: str, payer: str, payee: str, amount: float,
                         currency: str, reference: str) -> str:
    return make_signed("payment_receipt", {
        "type": "agora.payment-receipt", "bank": bank.did, "transactionId": transaction_id, "payer": payer,
        "payee": payee, "amount": round(amount, 2), "currency": currency, "reference": reference,
        "at": clock.now()}, bank)


def verify_payment_receipt(token: str, bank: str | None = None) -> dict:
    p = verify_signed("payment_receipt", token, "bank")
    if bank is not None and p["bank"] != bank:
        raise ProtocolError("receipt from an unexpected bank")
    return p


# ---------------------------------------------------------------- deliveries


def make_delivery(carrier: KeyPair, *, checkout_hash: str, merchant: str, buyer: str, status: str,
                  region: str | None) -> str:
    return make_signed("delivery", {
        "type": "agora.delivery", "carrier": carrier.did, "shipmentId": str(uuid.uuid4()),
        "checkoutHash": checkout_hash, "merchant": merchant, "buyer": buyer, "status": status,
        "region": region, "at": clock.now()}, carrier)


def verify_delivery(token: str) -> dict:
    return verify_signed("delivery", token, "carrier")


def make_content(producer: KeyPair, *, offer_id: str, content: str, buyer: str) -> str:
    """Producer-signed delivery of paid information: non-repudiable evidence of what was sent."""
    return make_signed("content", {
        "type": "agora.content", "producer": producer.did, "offerId": offer_id, "buyer": buyer,
        "content": content, "contentHash": text_hash(content), "at": clock.now()}, producer)


def verify_content(token: str) -> dict:
    p = verify_signed("content", token, "producer")
    if p["contentHash"] != text_hash(p["content"]):
        raise ProtocolError("content hash field is inconsistent")
    return p


# --------------------------------------------------------------- settlements


def make_settlement(escrow: KeyPair, *, escrow_id: str, checkout_token: str, status: str, reason: str,
                    splits: list[dict], fee: float) -> str:
    co = verify_checkout(checkout_token) if status == "pending" else verify_checkout_signature(checkout_token)
    return make_signed("settlement", {
        "type": "agora.settlement", "escrow": escrow.did, "escrowId": escrow_id,
        "checkoutHash": text_hash(checkout_token), "checkout": checkout_token,
        "merchant": co["merchant"], "buyer": co["buyer"], "offerIds": [li["offerId"] for li in co["lineItems"]],
        "kind": co["lineItems"][0]["kind"], "category": co["lineItems"][0]["category"],
        "amount": co["total"]["amount"], "currency": co["total"]["currency"], "status": status,
        "reason": reason, "splits": splits, "escrowFee": round(fee, 2), "at": clock.now()}, escrow)


def verify_checkout_signature(token: str) -> dict:
    """Signature-only check: settlements and returns may happen after the quote expired."""
    return verify_signed("checkout", token, "merchant")


def verify_settlement(token: str) -> dict:
    p = verify_signed("settlement", token, "escrow")
    co = verify_checkout_signature(p["checkout"])
    if text_hash(p["checkout"]) != p["checkoutHash"] or co["merchant"] != p["merchant"] or co["buyer"] != p["buyer"]:
        raise ProtocolError("settlement does not match its checkout")
    return p


# ------------------------------------------------------------------- reviews


def make_review(buyer: KeyPair, *, settlement_token: str, rating: int, text: str = "") -> str:
    s = verify_settlement(settlement_token)
    if s["buyer"] != buyer.did:
        raise ProtocolError("only the buyer of a settled deal can review it")
    return make_signed("review", {
        "type": "agora.review", "reviewer": buyer.did, "subject": s["merchant"], "settlement": settlement_token,
        "offerIds": s["offerIds"], "rating": int(max(1, min(5, rating))), "text": text, "at": clock.now()},
        buyer, "reviewId")


def verify_review(token: str) -> dict:
    p = verify_signed("review", token, "reviewer", "reviewId")
    s = verify_settlement(p["settlement"])
    if s["buyer"] != p["reviewer"] or s["merchant"] != p["subject"]:
        raise ProtocolError("review is not backed by the reviewer's own settlement")
    return p


# -------------------------------------------------------------------- labels


def make_label(labeler: KeyPair, *, subject: str, subject_type: str, label: str, severity: float,
               evidence: list[str], ttl_hours: float = 24 * 30) -> str:
    t = clock.now()
    return make_signed("label", {
        "type": "agora.label", "labeler": labeler.did, "subject": subject, "subjectType": subject_type,
        "label": label, "severity": round(float(severity), 3), "evidence": evidence[:10], "at": t,
        "exp": t + ttl_hours * 3600}, labeler, "labelId")


def verify_label(token: str) -> dict:
    return verify_signed("label", token, "labeler", "labelId")

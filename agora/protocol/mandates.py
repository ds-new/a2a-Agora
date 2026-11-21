"""AP2 v0.2 mandate chain (JWS profile).

Follows github.com/google-agentic-commerce/AP2 @ e1ea56d, docs/ap2/specification.md:
  * Human-not-present ("autonomous") mode: the principal (human or business)
    signs *open* Checkout and Payment Mandates whose constraints describe what
    the agent may buy, binding the agent's key with a ``cnf`` claim (RFC 7800).
  * The agent then signs *closed* Checkout/Payment Mandates for one concrete
    checkout. Verifiers always receive closed mandates plus the open ones that
    authorize the agent key.
Profile differences from AP2 (documented in docs/PROTOCOL.md): compact JWS with
EdDSA and did:key instead of SD-JWT VCs, so there is no selective disclosure;
``cnf`` carries ``{"kid": <agent did>}``; ``payment.budget`` is enforced as a
cumulative spend limit by the credential provider rather than as single use.
The ``vct`` values and constraint type names are AP2's.
"""

from __future__ import annotations

import uuid

from .. import clock
from ..crypto import KeyPair, SignatureError, jws_sign, jws_verify, text_hash
from .schema import TYP, verify_checkout

VCT_OPEN_CHECKOUT = "mandate.checkout.open.1"
VCT_CHECKOUT = "mandate.checkout.1"
VCT_OPEN_PAYMENT = "mandate.payment.open.1"
VCT_PAYMENT = "mandate.payment.1"


class MandateError(ValueError):
    pass


def _sign(payload: dict, key: KeyPair) -> str:
    return jws_sign({**payload, "iss": key.did, "jti": str(uuid.uuid4())}, key, typ=TYP["mandate"])


def _verify(token: str, vct: str, expected_kid: str | None = None) -> dict:
    try:
        header, p = jws_verify(token, expected_kid=expected_kid, expected_typ=TYP["mandate"])
    except SignatureError as exc:
        raise MandateError(f"{vct}: {exc}") from exc
    if p.get("vct") != vct:
        raise MandateError(f"expected {vct}, got {p.get('vct')}")
    if p.get("iss") != header["kid"]:
        raise MandateError("iss is not the signer")
    if p.get("exp", 0) < clock.now():
        raise MandateError(f"{vct} expired")
    return p


# ------------------------------------------------------------- open mandates


def open_checkout_mandate(principal: KeyPair, agent_did: str, *, line_items: list[dict],
                          allowed_merchants: list[str] | None = None, ttl_s: float = 7 * 86400) -> str:
    """line_items: [{"kind": "physical", "category": "coffee", "maxQuantity": 2}, ...]"""
    t = clock.now()
    constraints: list[dict] = [{"type": "checkout.line_items", "items": line_items}]
    if allowed_merchants:
        constraints.append({"type": "checkout.allowed_merchants", "allowed": allowed_merchants})
    return _sign({"vct": VCT_OPEN_CHECKOUT, "constraints": constraints, "cnf": {"kid": agent_did},
                  "iat": t, "exp": t + ttl_s}, principal)


def open_payment_mandate(principal: KeyPair, agent_did: str, *, max_amount: float, budget: float,
                         currency: str = "USD", allowed_payees: list[str] | None = None,
                         ttl_s: float = 7 * 86400) -> str:
    t = clock.now()
    constraints: list[dict] = [
        {"type": "payment.amount_range", "min": 0, "max": round(max_amount, 2), "currency": currency},
        {"type": "payment.budget", "max": round(budget, 2), "currency": currency},
    ]
    if allowed_payees:
        constraints.append({"type": "payment.allowed_payees", "allowed": allowed_payees})
    return _sign({"vct": VCT_OPEN_PAYMENT, "constraints": constraints, "cnf": {"kid": agent_did},
                  "payment_instrument": {"type": "agora.account", "holder": principal.did},
                  "iat": t, "exp": t + ttl_s}, principal)


# ----------------------------------------------------------- closed mandates


def checkout_mandate(agent: KeyPair, checkout_token: str, ttl_s: float = 3600) -> str:
    t = clock.now()
    return _sign({"vct": VCT_CHECKOUT, "checkout_jwt": checkout_token, "checkout_hash": text_hash(checkout_token),
                  "iat": t, "exp": t + ttl_s}, agent)


def payment_mandate(agent: KeyPair, *, transaction_id: str, payee: str, amount: float, currency: str,
                    holder: str, ttl_s: float = 3600) -> str:
    t = clock.now()
    return _sign({"vct": VCT_PAYMENT, "transaction_id": transaction_id, "payee": {"did": payee},
                  "payment_amount": {"amount": round(amount, 2), "currency": currency},
                  "payment_instrument": {"type": "agora.account", "holder": holder},
                  "iat": t, "exp": t + ttl_s}, agent)


# --------------------------------------------------------------- verification


def _constraint(p: dict, ctype: str) -> dict | None:
    return next((c for c in p.get("constraints", []) if c.get("type") == ctype), None)


def verify_checkout_chain(open_token: str, closed_token: str, *, merchant: str) -> tuple[str, dict]:
    """Merchant-side check. Returns (principal DID, checkout payload)."""
    op = _verify(open_token, VCT_OPEN_CHECKOUT)
    agent_did = (op.get("cnf") or {}).get("kid")
    cp = _verify(closed_token, VCT_CHECKOUT, expected_kid=agent_did)
    if text_hash(cp["checkout_jwt"]) != cp["checkout_hash"]:
        raise MandateError("checkout_hash mismatch")
    checkout = verify_checkout(cp["checkout_jwt"], merchant=merchant)
    allowed = _constraint(op, "checkout.allowed_merchants")
    if allowed and merchant not in allowed["allowed"]:
        raise MandateError("merchant not allowed by the open checkout mandate")
    rules = (_constraint(op, "checkout.line_items") or {}).get("items", [])
    for li in checkout["lineItems"]:
        ok = any((r.get("kind") in (None, li["kind"])) and (r.get("category") in (None, li["category"]))
                 and li["quantity"] <= r.get("maxQuantity", 1) for r in rules)
        if not ok:
            raise MandateError(f"line item {li['title']!r} is outside the user's intent")
    return op["iss"], checkout


def verify_payment_chain(open_token: str, closed_token: str, *, spent: float = 0.0) -> tuple[str, dict]:
    """Credential-provider-side check. Returns (principal DID, closed payment payload)."""
    op = _verify(open_token, VCT_OPEN_PAYMENT)
    agent_did = (op.get("cnf") or {}).get("kid")
    pp = _verify(closed_token, VCT_PAYMENT, expected_kid=agent_did)
    amount = pp["payment_amount"]["amount"]
    rng = _constraint(op, "payment.amount_range")
    if rng and not (rng["min"] <= amount <= rng["max"]):
        raise MandateError(f"amount {amount} outside the allowed range")
    budget = _constraint(op, "payment.budget")
    if budget and spent + amount > budget["max"] + 1e-9:
        raise MandateError("budget exhausted")
    payees = _constraint(op, "payment.allowed_payees")
    if payees and pp["payee"]["did"] not in payees["allowed"]:
        raise MandateError("payee not allowed")
    if pp["payment_instrument"]["holder"] != op["payment_instrument"]["holder"] or op["payment_instrument"]["holder"] != op["iss"]:
        raise MandateError("payment instrument is not the principal's")
    return op["iss"], pp


def mandate_id(token: str) -> str:
    return text_hash(token)

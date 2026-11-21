"""Service agents that replace the platform's built-in functions:

* BankAgent      - AP2 Credential Provider + Merchant Payment Processor (a payment rail, not a marketplace)
* EscrowAgent    - holds funds until delivery is proven; pays merchant, referrers and its own fee
* LogisticsAgent - carrier that signs delivery / return receipts
* LabelerAgent   - independent moderation service that publishes signed labels

Each one is replaceable: consumers and merchants choose which escrows, carriers
and labelers they trust. The simulation runs one bank; real deployments would
use many banks or an on-chain rail behind the same AP2 mandate checks.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from ..a2a.card import skill
from ..protocol.mandates import MandateError, mandate_id, verify_payment_chain
from ..protocol.records import (
    make_delivery,
    make_label,
    make_payment_receipt,
    make_settlement,
    sign_instruction,
    verify_checkout_signature,
    verify_content,
    verify_delivery,
    verify_instruction,
    verify_payment_receipt,
)
from ..protocol.schema import ProtocolError, checkout_hash, referral_splits, verify_checkout
from .base import AgoraAgent, reply

# --------------------------------------------------------------------------- #
# Bank
# --------------------------------------------------------------------------- #


class BankAgent(AgoraAgent):
    role = "bank"
    description = "Holds accounts; executes AP2-authorized payments and signed transfer orders"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.balances: dict[str, float] = defaultdict(float)
        self.spent: dict[str, float] = defaultdict(float)  # per open payment mandate
        self._nonces: set[str] = set()
        self.handlers.update({"agora.pay": self.on_pay, "agora.transfer": self.on_transfer,
                              "agora.balance": self.on_balance})

    def card_skills(self):
        return super().card_skills() + [
            skill("agora.pay", "Pay under a mandate", "Verify an AP2 open+closed payment mandate chain and pay",
                  ["payments", "ap2"]),
            skill("agora.transfer", "Transfer", "Execute a transfer order signed by the account holder", ["payments"]),
        ]

    def open_account(self, did: str, amount: float) -> None:
        self.balances[did] += amount

    def _move(self, src: str, dst: str, amount: float) -> None:
        if self.balances[src] + 1e-9 < amount:
            raise ProtocolError("insufficient funds")
        self.balances[src] -= amount
        self.balances[dst] += amount

    async def on_pay(self, ctx, data, handle):
        op_token, pm_token = data["openPaymentMandate"], data["paymentMandate"]
        mid = mandate_id(op_token)
        principal, pm = verify_payment_chain(op_token, pm_token, spent=self.spent[mid])
        if pm["transaction_id"] != data.get("reference"):
            raise MandateError("payment reference does not match the mandate's transaction_id")
        amount, payee = pm["payment_amount"]["amount"], pm["payee"]["did"]
        self._move(principal, payee, amount)
        self.spent[mid] += amount
        self.metrics.inc("payments")
        self.metrics.inc("payment_volume", amount)
        receipt = make_payment_receipt(self.key, transaction_id=str(uuid.uuid4()), payer=principal, payee=payee,
                                       amount=amount, currency=pm["payment_amount"]["currency"],
                                       reference=pm["transaction_id"])
        return reply({"type": "agora.payment.receipt", "receipt": receipt})

    async def on_transfer(self, ctx, data, handle):
        receipts = []
        for order_token in data["orders"]:
            o = verify_instruction(order_token, "agora.transfer-order")
            if o["nonce"] in self._nonces:
                raise ProtocolError("replayed transfer order")
            self._nonces.add(o["nonce"])
            self._move(o["by"], o["to"], o["amount"])
            receipts.append(make_payment_receipt(self.key, transaction_id=str(uuid.uuid4()), payer=o["by"],
                                                 payee=o["to"], amount=o["amount"], currency=o["currency"],
                                                 reference=o["reference"]))
        return reply({"type": "agora.transfer.receipts", "receipts": receipts})

    async def on_balance(self, ctx, data, handle):
        """An account holder reads its own balance; the request is signed, so nobody can read someone else's."""
        did = verify_instruction(data["instruction"], "agora.balance")["by"]
        return reply({"type": "agora.balance", "did": did, "balance": round(self.balances.get(did, 0.0), 2)})


# --------------------------------------------------------------------------- #
# Escrow
# --------------------------------------------------------------------------- #


class EscrowAgent(AgoraAgent):
    role = "escrow"
    description = "Neutral escrow: releases funds on proof of delivery, refunds on proven fraud"

    def __init__(self, *a, fee_bps: int = 50, bank=None, carriers: set[str] | None = None, **kw):
        super().__init__(*a, **kw)
        self.fee_bps = fee_bps
        self.bank = bank  # Peer
        self.carriers = set(carriers or ())
        self.contracts: dict[str, dict] = {}
        self.handlers.update({"agora.escrow.open": self.on_open, "agora.escrow.fund": self.on_fund,
                              "agora.escrow.status": self.on_status, "agora.escrow.release": self.on_release,
                              "agora.escrow.dispute": self.on_dispute})

    def roles(self):
        return ["escrow"]

    def card_skills(self):
        return super().card_skills() + [
            skill("agora.escrow", "Escrow", "Open, fund, release or dispute an escrow for a signed checkout",
                  ["escrow", "payments", "trust"]),
        ]

    async def on_open(self, ctx, data, handle):
        co = verify_checkout(data["checkout"])
        if co["escrow"] != self.did:
            raise ProtocolError("checkout names a different escrow")
        eid = str(uuid.uuid4())
        self.contracts[eid] = {"checkout": data["checkout"], "co": co, "status": "open", "payer": None}
        return reply({"type": "agora.escrow.opened", "escrowId": eid, "payTo": self.did,
                      "amount": co["total"]["amount"], "currency": co["total"]["currency"]})

    async def on_fund(self, ctx, data, handle):
        c = self.contracts[data["escrowId"]]
        r = verify_payment_receipt(data["receipt"], bank=self.bank.did if self.bank else None)
        if (r["payee"] != self.did or r["reference"] != data["escrowId"]
                or abs(r["amount"] - c["co"]["total"]["amount"]) > 0.005 or c["status"] != "open"):
            raise ProtocolError("payment receipt does not fund this escrow")
        c.update(status="funded", payer=r["payer"])
        return reply({"type": "agora.escrow.funded", "escrowId": data["escrowId"]})

    async def on_status(self, ctx, data, handle):
        c = self.contracts.get(data["escrowId"])
        if c is None:
            return reply({"type": "agora.escrow.status", "status": "unknown"})
        return reply({"type": "agora.escrow.status", "escrowId": data["escrowId"], "status": c["status"],
                      "checkoutHash": checkout_hash(c["checkout"]), "amount": c["co"]["total"]["amount"]})

    async def _pay(self, orders: list[tuple[str, float, str]], reference: str) -> None:
        tokens = [sign_instruction(self.key, {"type": "agora.transfer-order", "to": to, "amount": round(amt, 2),
                                              "currency": "USD", "reference": f"{reference}:{role}"})
                  for to, amt, role in orders if amt > 0]
        if tokens:
            await self.send(self.bank.rpc_url, {"type": "agora.transfer", "orders": tokens})

    async def on_release(self, ctx, data, handle):
        instr = verify_instruction(data["instruction"], "agora.release")
        eid = instr["escrowId"]
        c = self.contracts[eid]
        co = c["co"]
        if instr["by"] != co["buyer"] or c["status"] != "funded":
            raise ProtocolError("only the buyer can release a funded escrow")
        amount = co["total"]["amount"]
        fee = round(amount * self.fee_bps / 10_000, 2)
        offer_stub = {"producer": co["merchant"], "referral": {"bps": co["referral"]["bps"], "maxDepth": 6}}
        refs = referral_splits(amount, offer_stub, co["referral"]["chain"], co["buyer"])
        merchant_amt = round(amount - fee - sum(a for _, a in refs), 2)
        splits = ([{"to": co["merchant"], "amount": merchant_amt, "role": "merchant"}]
                  + [{"to": d, "amount": a, "role": "referrer"} for d, a in refs])
        await self._pay([(s["to"], s["amount"], s["role"]) for s in splits], eid)
        c["status"] = "released"
        token = make_settlement(self.key, escrow_id=eid, checkout_token=c["checkout"], status="released",
                                reason=instr.get("reason", "buyer-confirmed"), splits=splits, fee=fee)
        await self.ingest([token])
        self.metrics.inc("released")
        self.metrics.inc("fees", fee)
        return reply({"type": "agora.settlement", "settlement": token})

    async def on_dispute(self, ctx, data, handle):
        instr = verify_instruction(data["instruction"], "agora.dispute")
        eid = instr["escrowId"]
        c = self.contracts[eid]
        co = c["co"]
        if instr["by"] != co["buyer"] or c["status"] != "funded":
            raise ProtocolError("only the buyer can dispute a funded escrow")
        reason = None
        ev = data.get("evidence", "")
        if co["lineItems"][0]["kind"] == "information":
            content = verify_content(ev)  # producer-signed: non-repudiable
            if (content["producer"] == co["merchant"] and content["buyer"] == co["buyer"]
                    and content["offerId"] == co["lineItems"][0]["offerId"]
                    and content["contentHash"] != co.get("contentHash")):
                reason = "hash-mismatch"
        else:
            d = verify_delivery(ev)
            if (d["status"] == "returned" and d["checkoutHash"] == checkout_hash(c["checkout"])
                    and (not self.carriers or d["carrier"] in self.carriers)):
                reason = "returned"
        if reason is None:
            return reply({"type": "agora.dispute.rejected", "escrowId": eid})
        await self._pay([(c["payer"], co["total"]["amount"], "refund")], eid)
        c["status"] = "refunded"
        token = make_settlement(self.key, escrow_id=eid, checkout_token=c["checkout"], status="refunded",
                                reason=reason, splits=[{"to": c["payer"], "amount": co["total"]["amount"],
                                                        "role": "refund"}], fee=0.0)
        await self.ingest([token])
        self.metrics.inc("refunded")
        return reply({"type": "agora.settlement", "settlement": token})


# --------------------------------------------------------------------------- #
# Logistics
# --------------------------------------------------------------------------- #


class LogisticsAgent(AgoraAgent):
    role = "logistics"
    description = "Carrier: ships orders and signs delivery and return receipts"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.handlers.update({"agora.ship": self.on_ship, "agora.return": self.on_return})

    def card_skills(self):
        return super().card_skills() + [skill("agora.ship", "Ship", "Ship an order and sign a delivery receipt",
                                         ["logistics"])]

    async def on_ship(self, ctx, data, handle):
        order = verify_instruction(data["order"], "agora.ship-order")
        co = verify_checkout(order["checkout"], merchant=order["by"])
        self.metrics.inc("shipments")
        token = make_delivery(self.key, checkout_hash=checkout_hash(order["checkout"]), merchant=co["merchant"],
                              buyer=co["buyer"], status="delivered", region=(co.get("shipping") or {}).get("region"))
        return reply({"type": "agora.delivery", "delivery": token})

    async def on_return(self, ctx, data, handle):
        order = verify_instruction(data["order"], "agora.return-order")
        co = verify_checkout_signature(order["checkout"])
        if order["by"] != co["buyer"]:
            raise ProtocolError("only the buyer can return an order")
        self.metrics.inc("returns")
        token = make_delivery(self.key, checkout_hash=checkout_hash(order["checkout"]), merchant=co["merchant"],
                              buyer=co["buyer"], status="returned", region=None)
        return reply({"type": "agora.delivery", "delivery": token})


# --------------------------------------------------------------------------- #
# Labeler
# --------------------------------------------------------------------------- #


class LabelerAgent(AgoraAgent):
    role = "labeler"
    description = "Independent moderation: publishes signed labels backed by verifiable evidence"

    def __init__(self, *a, min_refunds: int = 2, refund_rate: float = 0.3, **kw):
        super().__init__(*a, **kw)
        self.min_refunds, self.refund_rate = min_refunds, refund_rate
        self._issued: set[tuple[str, str]] = set()
        self.handlers.update({"agora.labels.query": self.on_query})

    def card_skills(self):
        return super().card_skills() + [skill("agora.labels", "Labels", "Signed moderation labels with evidence",
                                         ["moderation", "trust"])]

    async def analyze(self) -> list[str]:
        new: list[str] = []
        by_merchant: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        for token, s in self.store.settlements.values():
            by_merchant[s["merchant"]].append((token, s))
        for merchant, items in by_merchant.items():
            fraud = [t for t, s in items if s["status"] == "refunded" and s["reason"] == "hash-mismatch"]
            if fraud and (merchant, "fraud") not in self._issued:
                new.append(make_label(self.key, subject=merchant, subject_type="agent", label="fraud",
                                      severity=0.9, evidence=fraud))
                self._issued.add((merchant, "fraud"))
            refunds = [t for t, s in items if s["status"] == "refunded"]
            rate = len(refunds) / len(items)
            if len(refunds) >= self.min_refunds and rate >= self.refund_rate and (merchant, "scam-risk") not in self._issued:
                new.append(make_label(self.key, subject=merchant, subject_type="agent", label="scam-risk",
                                      severity=min(1.0, rate + 0.3), evidence=refunds))
                self._issued.add((merchant, "scam-risk"))
        await self.ingest(new)
        self.metrics.inc("labels", len(new))
        return new

    async def on_query(self, ctx, data, handle):
        labels = [self.store.labels[k][0] for k in self.store.labels_by_subject.get(data["subject"], [])]
        return reply({"type": "agora.labels", "labels": labels})


__all__ = ["BankAgent", "EscrowAgent", "LogisticsAgent", "LabelerAgent"]

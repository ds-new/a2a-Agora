"""Identity and signatures.

* Ed25519 key pairs with self-certifying ``did:key`` identifiers (no registry).
* RFC 8785 JSON Canonicalization Scheme (JCS), which the A2A v1.0 spec requires
  before signing an Agent Card.
* RFC 7515 JWS: compact tokens for signed protocol objects (offers, checkouts,
  mandates, receipts, labels) and the detached form used by A2A
  ``AgentCardSignature``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# --------------------------------------------------------------------------- #
# base64url / base58btc
# --------------------------------------------------------------------------- #


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58)}


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = []
    while n:
        n, r = divmod(n, 58)
        out.append(_B58[r])
    pad = len(data) - len(data.lstrip(b"\0"))
    return "1" * pad + "".join(reversed(out))


def b58decode(text: str) -> bytes:
    n = 0
    for c in text:
        n = n * 58 + _B58_INDEX[c]
    pad = len(text) - len(text.lstrip("1"))
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * pad + body


# --------------------------------------------------------------------------- #
# RFC 8785 canonical JSON
# --------------------------------------------------------------------------- #


def _es_number(x: float) -> str:
    """Serialize a float the way ECMAScript Number.prototype.toString does."""
    if not math.isfinite(x):
        raise ValueError("JCS does not allow NaN or Infinity")
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    r = repr(abs(x))  # shortest round-trip digits
    mant, _, exp = r.partition("e")
    e = int(exp) if exp else 0
    ip, _, fp = mant.partition(".")
    if fp == "0":
        fp = ""
    digits = (ip + fp).lstrip("0")
    exp10 = e - len(fp)
    trailing = len(digits) - len(digits.rstrip("0"))
    if trailing:
        digits = digits[:-trailing]
        exp10 += trailing
    k = len(digits)
    n = exp10 + k  # value = 0.d1..dk * 10**n
    if k <= n <= 21:
        out = digits + "0" * (n - k)
    elif 0 < n <= 21:
        out = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        out = "0." + "0" * (-n) + digits
    else:
        ee = n - 1
        out = digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + ("+" if ee > 0 else "-") + str(abs(ee))
    return sign + out


def _jcs(o: Any) -> str:
    if o is None:
        return "null"
    if o is True:
        return "true"
    if o is False:
        return "false"
    if isinstance(o, int):
        return str(o)
    if isinstance(o, float):
        return str(int(o)) if o.is_integer() and abs(o) < 1e21 else _es_number(o)
    if isinstance(o, str):
        return json.dumps(o, ensure_ascii=False)
    if isinstance(o, (list, tuple)):
        return "[" + ",".join(_jcs(v) for v in o) + "]"
    if isinstance(o, dict):
        items = sorted(o.items(), key=lambda kv: kv[0].encode("utf-16-be"))
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + _jcs(v) for k, v in items) + "}"
    raise TypeError(f"not JSON-serializable: {type(o).__name__}")


def canonical_json(obj: Any) -> bytes:
    """RFC 8785 canonical UTF-8 bytes of ``obj``."""
    return _jcs(obj).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_id(obj: Any) -> str:
    """Content address of a JSON value: ``sha256:<hex of JCS bytes>``."""
    return "sha256:" + sha256_hex(canonical_json(obj))


def text_hash(text: str) -> str:
    return "sha256:" + sha256_hex(text.encode("utf-8"))


# --------------------------------------------------------------------------- #
# Keys and did:key
# --------------------------------------------------------------------------- #

_ED25519_MULTICODEC = b"\xed\x01"


@dataclass
class KeyPair:
    private_key: Ed25519PrivateKey

    @classmethod
    def generate(cls) -> "KeyPair":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_seed(cls, seed: str | bytes) -> "KeyPair":
        """Deterministic key (for reproducible simulations only)."""
        raw = seed.encode() if isinstance(seed, str) else seed
        return cls(Ed25519PrivateKey.from_private_bytes(hashlib.sha256(raw).digest()))

    @property
    def public_bytes(self) -> bytes:
        return self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )

    @property
    def did(self) -> str:
        return "did:key:z" + b58encode(_ED25519_MULTICODEC + self.public_bytes)

    def sign(self, data: bytes) -> bytes:
        return self.private_key.sign(data)


def public_key_from_did(did: str) -> Ed25519PublicKey:
    if not did.startswith("did:key:z"):
        raise ValueError(f"unsupported DID method: {did[:16]}")
    raw = b58decode(did[len("did:key:z"):])
    if raw[:2] != _ED25519_MULTICODEC or len(raw) != 34:
        raise ValueError("did:key is not an Ed25519 key")
    return Ed25519PublicKey.from_public_bytes(raw[2:])


def verify_bytes(did: str, data: bytes, signature: bytes) -> bool:
    try:
        public_key_from_did(did).verify(signature, data)
        return True
    except (InvalidSignature, ValueError):
        return False


# --------------------------------------------------------------------------- #
# JWS (RFC 7515)
# --------------------------------------------------------------------------- #


class SignatureError(ValueError):
    pass


def jws_sign(payload: dict, key: KeyPair, typ: str = "JWT", extra_header: dict | None = None) -> str:
    """Compact JWS over the canonical JSON of ``payload``. ``kid`` is the signer's DID."""
    header = {"alg": "EdDSA", "kid": key.did, "typ": typ, **(extra_header or {})}
    signing_input = b64url(canonical_json(header)) + "." + b64url(canonical_json(payload))
    return signing_input + "." + b64url(key.sign(signing_input.encode("ascii")))


def jws_decode_unverified(token: str) -> tuple[dict, dict]:
    try:
        h, p, _ = token.split(".")
        return json.loads(b64url_decode(h)), json.loads(b64url_decode(p))
    except Exception as exc:  # noqa: BLE001
        raise SignatureError(f"malformed JWS: {exc}") from exc


def jws_verify(token: str, expected_kid: str | None = None, expected_typ: str | None = None) -> tuple[dict, dict]:
    """Verify a compact JWS whose ``kid`` is a did:key. Returns (header, payload)."""
    header, payload = jws_decode_unverified(token)
    if header.get("alg") != "EdDSA":
        raise SignatureError("only EdDSA is accepted")
    kid = header.get("kid", "")
    if expected_kid is not None and kid != expected_kid:
        raise SignatureError("signed by an unexpected key")
    if expected_typ is not None and header.get("typ") != expected_typ:
        raise SignatureError(f"unexpected typ {header.get('typ')!r}")
    h, p, s = token.split(".")
    if not verify_bytes(kid, f"{h}.{p}".encode("ascii"), b64url_decode(s)):
        raise SignatureError("bad signature")
    return header, payload


def detached_sign(payload: Any, key: KeyPair, header: dict | None = None) -> dict:
    """JWS with detached payload: returns {"protected", "signature"} (A2A AgentCardSignature)."""
    protected = b64url(canonical_json({"alg": "EdDSA", "kid": key.did, "typ": "JOSE", **(header or {})}))
    signing_input = protected + "." + b64url(canonical_json(payload))
    return {"protected": protected, "signature": b64url(key.sign(signing_input.encode("ascii")))}


def detached_verify(payload: Any, sig: dict) -> str:
    """Verify a detached JWS and return the signer's DID."""
    header = json.loads(b64url_decode(sig["protected"]))
    if header.get("alg") != "EdDSA":
        raise SignatureError("only EdDSA is accepted")
    kid = header.get("kid", "")
    signing_input = sig["protected"] + "." + b64url(canonical_json(payload))
    if not verify_bytes(kid, signing_input.encode("ascii"), b64url_decode(sig["signature"])):
        raise SignatureError("bad agent card signature")
    return kid

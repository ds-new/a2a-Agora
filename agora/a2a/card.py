"""Agent Card construction, JWS signing and verification (A2A v1.0 section 8.4).

The card is canonicalized with RFC 8785 with the ``signatures`` field removed,
then signed as a detached-payload JWS. Our signatures use EdDSA with the
agent's ``did:key`` as ``kid``, which makes the card self-certifying: anyone
can check that the endpoint speaks for that DID without a certificate
authority or a platform-run registry.
"""

from __future__ import annotations

from ..crypto import KeyPair, SignatureError, detached_sign, detached_verify
from .types import A2A_VERSION, JSONRPC_BINDING


def build_agent_card(
    *,
    name: str,
    description: str,
    url: str,
    version: str = "0.1.0",
    skills: list[dict] | None = None,
    extensions: list[dict] | None = None,
    streaming: bool = True,
    provider: dict | None = None,
    input_modes: tuple[str, ...] = ("application/json", "text/plain"),
    output_modes: tuple[str, ...] = ("application/json", "text/plain"),
) -> dict:
    card: dict = {
        "name": name,
        "description": description,
        "supportedInterfaces": [
            {"url": url, "protocolBinding": JSONRPC_BINDING, "protocolVersion": A2A_VERSION}
        ],
        "version": version,
        "capabilities": {
            "streaming": streaming,
            "pushNotifications": False,
            "extensions": list(extensions or []),
            "extendedAgentCard": False,
        },
        "defaultInputModes": list(input_modes),
        "defaultOutputModes": list(output_modes),
        "skills": list(skills or []),
    }
    if provider:
        card["provider"] = provider
    return card


def skill(skill_id: str, name: str, description: str, tags: list[str], examples: list[str] | None = None) -> dict:
    s = {"id": skill_id, "name": name, "description": description, "tags": tags}
    if examples:
        s["examples"] = examples
    return s


def sign_agent_card(card: dict, key: KeyPair) -> dict:
    unsigned = {k: v for k, v in card.items() if k != "signatures"}
    return {**unsigned, "signatures": [detached_sign(unsigned, key)]}


def verify_agent_card(card: dict, expected_did: str | None = None) -> str:
    """Return the DID that signed ``card``; raise SignatureError if none verifies."""
    unsigned = {k: v for k, v in card.items() if k != "signatures"}
    for sig in card.get("signatures") or []:
        try:
            did = detached_verify(unsigned, sig)
        except (SignatureError, KeyError, ValueError):
            continue
        if expected_did is None or did == expected_did:
            return did
    raise SignatureError("agent card has no valid signature")


def jsonrpc_url(card: dict) -> str:
    for iface in card.get("supportedInterfaces", []):
        if iface.get("protocolBinding") == JSONRPC_BINDING and iface.get("protocolVersion", "").startswith("1."):
            return iface["url"]
    raise ValueError("agent card has no A2A 1.x JSON-RPC interface")


def card_extension(card: dict, uri: str) -> dict | None:
    for ext in card.get("capabilities", {}).get("extensions", []):
        if ext.get("uri") == uri:
            return ext
    return None

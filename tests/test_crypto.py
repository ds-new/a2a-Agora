import pytest

from agora.crypto import (
    KeyPair,
    SignatureError,
    b58decode,
    b58encode,
    canonical_json,
    jws_sign,
    jws_verify,
    public_key_from_did,
)


def test_jcs_rfc8785_numbers():
    # RFC 8785 section 3.2.3 sample
    data = {"numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 0.000000000000000000000000001]}
    assert canonical_json(data) == b'{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27]}'
    assert canonical_json([1e21, 1e-7, 0.000001, -0.0, 5e-324, 1.7976931348623157e308]) == (
        b"[1e+21,1e-7,0.000001,0,5e-324,1.7976931348623157e+308]"
    )


def test_jcs_key_order_and_strings():
    assert canonical_json({"b": 1, "a": [True, None, "€\n"]}) == '{"a":[true,null,"€\\n"],"b":1}'.encode()
    # UTF-16 code unit ordering: U+E000 sorts after a surrogate pair (U+1F600)
    assert canonical_json({"": 1, "\U0001f600": 2}).startswith('{"\U0001f600"'.encode())


def test_base58_roundtrip():
    for raw in (b"", b"\0\0abc", bytes(range(40))):
        assert b58decode(b58encode(raw)) == raw


def test_did_key_and_jws():
    alice, mallory = KeyPair.from_seed("alice"), KeyPair.from_seed("mallory")
    assert alice.did.startswith("did:key:z6Mk")  # Ed25519 multicodec prefix
    public_key_from_did(alice.did)
    tok = jws_sign({"type": "agora.offer", "price": 9.5}, alice, typ="agora.offer+jws")
    header, payload = jws_verify(tok, expected_kid=alice.did, expected_typ="agora.offer+jws")
    assert payload["price"] == 9.5 and header["kid"] == alice.did
    with pytest.raises(SignatureError):
        jws_verify(tok, expected_kid=mallory.did)
    h, p, s = tok.split(".")
    forged = jws_sign({"type": "agora.offer", "price": 0.5}, mallory).split(".")[1]
    with pytest.raises(SignatureError):
        jws_verify(f"{h}.{forged}.{s}")

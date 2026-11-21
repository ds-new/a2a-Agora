"""Common machinery for every Agora agent.

An agent is an A2A v1.0 server plus client, with:
  * a did:key identity that also signs its Agent Card (self-certifying, no registry);
  * a local ObjectStore of verified signed objects;
  * a peer table filled by bootstrap URLs and gossip (no central directory);
  * dispatch of incoming A2A messages by the ``type`` of their first data part.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .. import __version__, clock
from ..a2a.card import build_agent_card, card_extension, sign_agent_card, skill, verify_agent_card
from ..a2a.client import A2AClient
from ..a2a.server import A2AServer, RequestContext, TaskHandle
from ..a2a.types import A2AError, Role, TaskState, data_part, find_data, make_message, text_part
from ..crypto import KeyPair, SignatureError
from ..protocol.schema import AGORA_EXTENSIONS, EXT_AGENTNET, EXT_GOSSIP, EXT_MANDATES, EXT_MARKET
from ..protocol.store import GOSSIP_KINDS, ObjectStore

log = logging.getLogger("agora.agent")
Handler = Callable[[RequestContext, dict, TaskHandle], Awaitable[dict | None]]


@dataclass
class Peer:
    did: str
    base_url: str
    rpc_url: str
    roles: list[str]
    name: str


@dataclass
class Metrics:
    counters: dict[str, float] = field(default_factory=dict)

    def inc(self, key: str, by: float = 1.0) -> None:
        self.counters[key] = self.counters.get(key, 0.0) + by


def reply(data: dict, text: str | None = None) -> dict:
    parts = [data_part(data)]
    if text:
        parts.append(text_part(text))
    return make_message(Role.AGENT, parts)


class AgoraAgent:
    role = "agent"
    description = "Agora agent"

    def __init__(self, name: str, *, port: int, host: str = "127.0.0.1", seed: str | None = None,
                 http=None, trusted_escrows: set[str] | None = None, rng_seed: int = 0):
        self.name = name
        self.key = KeyPair.from_seed(seed or f"agora:{name}")
        self.did = self.key.did
        self.base_url = f"http://{host}:{port}"
        self.rpc_url = self.base_url + "/a2a"
        self.port = port
        self.store = ObjectStore(trusted_escrows)
        self.peers: dict[str, Peer] = {}
        self.rng = random.Random(rng_seed)
        self.metrics = Metrics()
        self.client = A2AClient(http, extensions=AGORA_EXTENSIONS) if http is not None else A2AClient(
            extensions=AGORA_EXTENSIONS)
        self.handlers: dict[str, Handler] = {"agora.gossip": self.on_gossip, "agora.hello": self.on_hello}
        self._card = sign_agent_card(build_agent_card(
            name=f"{self.role}:{name}", description=self.description, url=self.rpc_url, version=__version__,
            provider={"organization": name, "url": self.base_url}, skills=self.card_skills(),
            extensions=[
                {"uri": EXT_MARKET, "description": "Agora market objects and negotiation", "required": False,
                 "params": {"did": self.did, "roles": self.roles()}},
                {"uri": EXT_MANDATES, "description": "AP2 v0.2 mandate chain (JWS profile)", "required": False},
                {"uri": EXT_GOSSIP, "description": "Peer exchange of cards and signed objects", "required": False},
                {"uri": EXT_AGENTNET, "description": "Interest cards, proposals, feedback, queries, recommendations",
                 "required": False},
            ]), self.key)
        self.server = A2AServer(lambda: self._card, self, supported_extensions=set(AGORA_EXTENSIONS))
        self._cache: dict[str, tuple[int, Any]] = {}
        self._sent_upto: dict[tuple[str, str], int] = {}
        self._seen_nonces: dict[str, float] = {}

    # ------------------------------------------------------------ card/skills
    def roles(self) -> list[str]:
        return [self.role]

    def card_skills(self) -> list[dict]:
        return [skill("agora.gossip", "Gossip", "Exchange peers and signed market objects", ["gossip", "p2p"])]

    @property
    def app(self):
        return self.server.app

    def cached(self, key: str, compute: Callable[["AgoraAgent"], Any]) -> Any:
        """Memoize a derived view until the object store changes."""
        hit = self._cache.get(key)
        if hit is not None and hit[0] == self.store.version:
            return hit[1]
        val = compute(self)
        self._cache[key] = (self.store.version, val)
        return val

    def fresh_nonce(self, nonce: str, max_age_s: float = 3600) -> bool:
        """Replay guard for signed requests: a nonce is accepted once while its request is young enough to verify."""
        now = clock.now()
        if len(self._seen_nonces) > 4096:
            self._seen_nonces = {n: t for n, t in self._seen_nonces.items() if now - t <= max_age_s}
        if nonce in self._seen_nonces:
            return False
        self._seen_nonces[nonce] = now
        return True

    # ------------------------------------------------------------ A2A server
    async def execute(self, ctx: RequestContext, handle: TaskHandle) -> dict | None:
        data = find_data(ctx.message)
        if data is None or "type" not in data:
            return reply({"type": "agora.error", "error": "expected a data part with a 'type'"},
                         f"{self.name} speaks the Agora extension; send a data part.")
        handler = self.handlers.get(data["type"])
        if handler is None:
            if ctx.task is not None:
                await handle.reject(reply({"type": "agora.error", "error": f"unsupported {data['type']}"}))
                return None
            return reply({"type": "agora.error", "error": f"unsupported type {data['type']}"})
        try:
            return await handler(ctx, data, handle)
        except Exception as exc:  # noqa: BLE001  bad signatures, mandate violations, failing downstream agents
            self.metrics.inc("rejected_requests")
            log.debug("%s rejected %s: %s", self.name, data["type"], exc)
            if handle.task is not None and handle.task["status"]["state"] not in TaskState.TERMINAL:
                await handle.reject(reply({"type": "agora.error", "error": str(exc)}))
                return None
            return reply({"type": "agora.error", "error": str(exc)})

    async def cancel(self, task: dict) -> None:
        return None

    # ------------------------------------------------------------ A2A client
    async def send(self, rpc_url: str, data: dict, *, task_id: str | None = None, context_id: str | None = None,
                   text: str | None = None) -> dict:
        parts = [data_part(data)] + ([text_part(text)] if text else [])
        msg = make_message(Role.USER, parts, task_id=task_id, context_id=context_id)
        self.metrics.inc("a2a_sent")
        return await self.client.send_message(rpc_url, msg)

    @staticmethod
    def status_data(result: dict, type_: str | None = None) -> dict | None:
        if "message" in result:
            return find_data(result["message"], type_)
        return find_data(result["task"]["status"].get("message"), type_)

    async def discover(self, base_url: str) -> Peer | None:
        if any(p.base_url == base_url for p in self.peers.values()) or base_url == self.base_url:
            return None
        try:
            card = await self.client.fetch_card(base_url)
            did = verify_agent_card(card)
        except (A2AError, SignatureError, ValueError, OSError) as exc:
            log.debug("discover %s failed: %s", base_url, exc)
            return None
        except Exception as exc:  # noqa: BLE001  (network errors from the HTTP client)
            log.debug("discover %s failed: %s", base_url, exc)
            return None
        ext = card_extension(card, EXT_MARKET) or {}
        params = ext.get("params") or {}
        if params.get("did") != did:  # the card must be signed by the DID it claims
            return None
        peer = Peer(did, base_url, A2AClient.rpc_url_of(card), list(params.get("roles", [])), card["name"])
        self.peers[did] = peer
        return peer

    def peers_with_role(self, role: str) -> list[Peer]:
        return [p for p in self.peers.values() if role in p.roles]

    # ------------------------------------------------------------ gossip
    def gossip_payload(self, peer_did: str | None = None, per_kind: int = 40) -> dict:
        """Anti-entropy: send each peer only objects we have not sent it before (per-kind watermark)."""
        objs: list[str] = []
        for kind in GOSSIP_KINDS:
            log_ids = self.store._log[kind]
            key = (peer_did or "", kind)
            start = self._sent_upto.get(key, max(0, len(log_ids) - per_kind))
            end = min(len(log_ids), start + per_kind)
            objs.extend(self.store.recent_tokens_range(kind, start, end))  # may skip non-shareable entries
            self._sent_upto[key] = end  # advance past everything scanned, shared or not
        peers = [p.base_url for p in self.rng.sample(list(self.peers.values()), min(12, len(self.peers)))]
        return {"type": "agora.gossip", "from": self.did, "peers": peers + [self.base_url], "objects": objs}

    async def ingest(self, tokens: list[str]) -> int:
        new = 0
        for t in tokens:
            res = self.store.add(t)
            if res is not None:
                new += 1
                await self.on_new_object(*res)
        return new

    async def on_new_object(self, kind: str, payload: dict) -> None:
        """Hook for subclasses (e.g. producers react to new intents)."""

    async def learn_peers(self, base_urls: list[str], limit: int = 4) -> None:
        unknown = [u for u in base_urls if u != self.base_url and all(p.base_url != u for p in self.peers.values())]
        for u in unknown[:limit]:
            await self.discover(u)

    async def on_gossip(self, ctx, data, handle):
        await self.ingest(data.get("objects", []))
        await self.learn_peers(data.get("peers", []), limit=2)
        out = self.gossip_payload(data.get("from"))
        out["type"] = "agora.gossip.reply"
        return reply(out)

    async def on_hello(self, ctx, data, handle):
        await self.learn_peers([data.get("base", "")], limit=1)
        return reply({"type": "agora.hello.reply", "did": self.did})

    async def gossip_round(self, fanout: int = 2) -> None:
        if not self.peers:
            return
        for peer in self.rng.sample(list(self.peers.values()), min(fanout, len(self.peers))):
            try:
                res = await self.send(peer.rpc_url, self.gossip_payload(peer.did))
                d = self.status_data(res, "agora.gossip.reply") or {}
                await self.ingest(d.get("objects", []))
                await self.learn_peers(d.get("peers", []))
                self.metrics.inc("gossip_ok")
            except Exception as exc:  # noqa: BLE001
                self.metrics.inc("gossip_fail")
                log.debug("gossip with %s failed: %s", peer.name, exc)

    async def bootstrap(self, base_urls: list[str]) -> None:
        for u in base_urls:
            peer = await self.discover(u)
            if peer is not None:
                try:
                    await self.send(peer.rpc_url, {"type": "agora.hello", "base": self.base_url})
                except Exception:  # noqa: BLE001
                    pass

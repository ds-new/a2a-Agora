import asyncio

import pytest

from agora.a2a.card import build_agent_card, sign_agent_card, verify_agent_card
from agora.a2a.client import A2AClient
from agora.a2a.server import A2AServer
from agora.a2a.types import (
    A2AError,
    Role,
    TaskState,
    data_part,
    make_artifact,
    make_message,
    message_text,
    text_part,
)
from agora.crypto import KeyPair, SignatureError
from agora.net import HttpServerGroup, MemoryNetwork, free_port

EXT = "urn:agora:ext:test:v1"


class EchoExecutor:
    async def execute(self, ctx, handle):
        text = message_text(ctx.message)
        if ctx.is_continuation:
            await handle.complete(make_message(Role.AGENT, [text_part(f"thanks for {text}")]))
            return None
        if text == "hi":
            return make_message(Role.AGENT, [text_part("hello")])
        if text == "ask":
            await handle.require_input(make_message(Role.AGENT, [text_part("how many?")]))
            return None
        await handle.working()
        await asyncio.sleep(0.01)
        await handle.add_artifact(make_artifact([data_part({"type": "result", "echo": text})], name="echo"))
        await handle.complete()
        return None


def make_server(url, key, required=False):
    card = sign_agent_card(build_agent_card(
        name="echo", description="test agent", url=url + "/a2a",
        extensions=[{"uri": EXT, "description": "test", "required": required}]), key)
    return A2AServer(lambda: card, EchoExecutor(), supported_extensions={EXT},
                     required_extensions={EXT} if required else set())


def test_agent_card_signature_and_tamper():
    key = KeyPair.from_seed("echo")
    card = sign_agent_card(build_agent_card(name="a", description="b", url="http://x/a2a"), key)
    assert verify_agent_card(card) == key.did
    card["description"] = "evil"
    with pytest.raises(SignatureError):
        verify_agent_card(card)


async def _memory_client(required=False):
    net = MemoryNetwork()
    key = KeyPair.from_seed("echo")
    server = make_server("http://echo:9000", key, required)
    net.register("http://echo:9000", server.app)
    return A2AClient(net.client(), extensions=[EXT]), key


def test_message_task_lifecycle_memory():
    async def run():
        client, key = await _memory_client()
        card = await client.fetch_card("http://echo:9000", expected_did=key.did)
        url = A2AClient.rpc_url_of(card)

        r = await client.send_message(url, make_message(Role.USER, [text_part("hi")]))
        assert message_text(r["message"]) == "hello" and r["message"]["role"] == Role.AGENT

        r = await client.send_message(url, make_message(Role.USER, [text_part("work")]))
        task = r["task"]
        assert task["status"]["state"] == TaskState.COMPLETED
        assert task["artifacts"][0]["parts"][0]["data"]["echo"] == "work"

        r = await client.send_message(url, make_message(Role.USER, [text_part("ask")]))
        t = r["task"]
        assert t["status"]["state"] == TaskState.INPUT_REQUIRED
        r2 = await client.send_message(url, make_message(Role.USER, [text_part("3")], task_id=t["id"]))
        assert r2["task"]["status"]["state"] == TaskState.COMPLETED
        got = await client.get_task(url, t["id"], history_length=2)
        assert len(got["history"]) == 2 and message_text(got["history"][-1]) == "thanks for 3"
        assert (await client.list_tasks(url))["totalSize"] == 2

        with pytest.raises(A2AError) as e:
            await client.cancel_task(url, t["id"])
        assert e.value.code == -32002  # TaskNotCancelableError
        with pytest.raises(A2AError) as e:
            await client.get_task(url, "nope")
        assert e.value.code == -32001  # TaskNotFoundError
        with pytest.raises(A2AError) as e:
            await client.send_message(url, make_message(Role.USER, [text_part("x")], task_id=t["id"]))
        assert e.value.code == -32004  # terminal task cannot continue
        await client.aclose()

    asyncio.run(run())


def test_version_and_required_extension():
    async def run():
        client, _ = await _memory_client(required=True)
        url = "http://echo:9000/a2a"
        payload = '{"jsonrpc":"2.0","id":1,"method":"GetTask","params":{"id":"x"}}'
        r = await client.http.post(url, content=payload, headers={"Content-Type": "application/json"})
        assert r.json()["error"]["code"] == -32009  # no A2A-Version => 0.3 => unsupported
        with pytest.raises(A2AError) as e:
            await client.send_message(url, make_message(Role.USER, [text_part("hi")]), extensions=[])
        assert e.value.code == -32008  # ExtensionSupportRequiredError
        r = await client.send_message(url, make_message(Role.USER, [text_part("hi")]))
        assert "message" in r
        await client.aclose()

    asyncio.run(run())


def test_streaming_over_real_http():
    async def run():
        group = HttpServerGroup()
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        server = make_server(base, KeyPair.from_seed("echo"))
        await group.start(server.app, port)
        client = A2AClient(extensions=[EXT])
        try:
            card = await client.fetch_card(base)
            events = [e async for e in client.stream_message(A2AClient.rpc_url_of(card),
                                                              make_message(Role.USER, [text_part("stream me")]))]
            kinds = [next(iter(e)) for e in events]
            assert kinds == ["task", "statusUpdate", "artifactUpdate", "statusUpdate"]
            assert events[-1]["statusUpdate"]["status"]["state"] == TaskState.COMPLETED
        finally:
            await client.aclose()
            await group.stop()

    asyncio.run(run())

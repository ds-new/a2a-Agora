"""LLM access for agents (optional): any OpenAI-compatible endpoint, e.g. a vLLM server.

    export AGORA_LLM_BASE_URL=http://<host>:8000/v1
    export AGORA_LLM_MODEL=Qwen3-8B
    export AGORA_LLM_API_KEY=...        # if the server needs one

Used by LLMBrain (an agent's decision policy), by profile_from_text (turning a
principal's own words into a profile) and by parse_intent. Without these
variables every caller falls back to deterministic rules, so nothing depends on
an LLM being available.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

try:
    import httpx  # type: ignore
except ImportError:  # pragma: no cover
    import httpx2 as httpx  # type: ignore

DEFAULT_KEYWORDS = {
    "coffee": ["coffee", "beans", "espresso", "咖啡"], "books": ["book", "novel", "sci-fi", "科幻", "小说", "书"],
    "electronics": ["earbuds", "keyboard", "ssd", "usb", "耳机", "键盘", "电子"],
    "outdoor": ["tent", "hiking", "trail", "户外", "帐篷", "越野"], "apparel": ["shirt", "jacket", "socks", "衣", "外套"],
    "home": ["mug", "lamp", "pan", "sheets", "家居", "台灯"],
    "ai": ["llm", "gpu", "agent", "模型", "大模型", "算力", "人工智能"],
    "markets": ["rates", "fx", "earnings", "macro", "股", "汇率", "宏观", "金融"],
    "science": ["physics", "biology", "space", "科学", "物理"], "sports": ["football", "nba", "tennis", "sports", "体育", "足球"],
    "cooking": ["recipe", "noodle", "sourdough", "cooking", "菜谱", "做饭", "烹饪"],
    "travel": ["kyoto", "rail", "trek", "travel", "旅行", "旅游"],
}
INFO_CATEGORIES = {"ai", "markets", "science", "sports", "cooking", "travel"}
_PRICE = re.compile(r"(?:\$|¥|￥|usd\s*)?\s*(\d+(?:\.\d+)?)\s*(?:元|块|usd|dollars|\$)?", re.I)


def llm_config() -> dict | None:
    base = os.environ.get("AGORA_LLM_BASE_URL")
    if not base:
        return None
    return {"base_url": base.rstrip("/"), "model": os.environ.get("AGORA_LLM_MODEL", "default"),
            "api_key": os.environ.get("AGORA_LLM_API_KEY", "")}


def extract_json(text: str) -> Any:
    """Pull the first JSON object out of a model reply (tolerates <think> blocks and code fences)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("no JSON object in model output")


async def chat(messages: list[dict], *, cfg: dict | None = None, http=None, timeout: float = 60.0,
               temperature: float = 0.2) -> str:
    cfg = cfg or llm_config()
    if cfg is None:
        raise RuntimeError("no LLM configured")
    headers = {"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else {}
    body = {"model": cfg["model"], "temperature": temperature, "messages": messages}
    if http is not None:
        resp = await http.post(f"{cfg['base_url']}/chat/completions", json=body, headers=headers, timeout=timeout)
    else:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            resp = await client.post(f"{cfg['base_url']}/chat/completions", json=body, headers=headers)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"] or ""


# ------------------------------------------------------------------ intents


def parse_intent_rules(text: str, keywords: dict[str, list[str]] | None = None) -> dict:
    kw = keywords or DEFAULT_KEYWORDS
    low = text.lower()
    scores = {cat: sum(low.count(w.lower()) for w in words) for cat, words in kw.items()}
    category = max(scores, key=scores.get) if any(scores.values()) else "other"
    prices = [float(m.group(1)) for m in _PRICE.finditer(text) if m.group(1)]
    kind = "information" if category in INFO_CATEGORIES or any(w in low for w in ("report", "报告", "分析", "资讯")) \
        else "physical"
    return {"text": text, "kind": kind, "category": category, "max_price": max(prices) if prices else 50.0}


async def parse_intent(text: str, categories: list[str] | None = None, timeout: float = 20.0) -> dict:
    """LLM-backed parsing with a strict JSON contract; falls back to rules on any failure."""
    cfg = llm_config()
    if cfg is None:
        return parse_intent_rules(text)
    cats = categories or list(DEFAULT_KEYWORDS)
    prompt = ("Extract a purchase or reading intent. Reply with JSON only: "
              '{"kind": "physical"|"information", "category": one of ' + json.dumps(cats) +
              ', "max_price": number in USD}. Request: ' + text)
    try:
        data = extract_json(await chat([{"role": "user", "content": prompt}], cfg=cfg, timeout=timeout,
                                       temperature=0.0))
        if data.get("kind") in ("physical", "information") and data.get("category") in cats:
            return {"text": text, "kind": data["kind"], "category": data["category"],
                    "max_price": float(data.get("max_price") or 50.0)}
    except Exception:  # noqa: BLE001  any failure -> deterministic fallback
        pass
    return parse_intent_rules(text)


# ------------------------------------------------------------------ profiles


async def profile_from_text(text: str, categories: list[str] | None = None, timeout: float = 30.0, **kw):
    """The principal's own words -> UserProfile, via the LLM when configured, else rules."""
    from .mind.profile import UserProfile  # noqa: PLC0415

    cfg = llm_config()
    if cfg is None:
        return UserProfile.from_text(text, **kw)
    cats = categories or list(DEFAULT_KEYWORDS)
    prompt = ("Read what a user says about their tastes and needs. Reply with JSON only: "
              '{"likes": [categories], "dislikes": [categories], "price_max": {category: USD}, '
              '"needs": [{"text": str, "kind": "physical"|"information", "category": str, "max_price": number}]}. '
              f"Categories: {json.dumps(cats)}. Information categories: {json.dumps(sorted(INFO_CATEGORIES))}. "
              f"User: {text}")
    try:
        data = extract_json(await chat([{"role": "user", "content": prompt}], cfg=cfg, timeout=timeout,
                                       temperature=0.0))
        prof = UserProfile(**kw)
        for c in data.get("likes", []):
            if c in cats:
                prof.likes[c] = 0.8
                prof.stated_likes.add(c)
        prof.dislikes = {c for c in data.get("dislikes", []) if c in cats}
        prof.price_max = {c: float(p) for c, p in (data.get("price_max") or {}).items() if c in cats}
        for n in data.get("needs", []):
            if n.get("category") in cats and n.get("kind") in ("physical", "information"):
                prof.add_need(text=n.get("text", text), kind=n["kind"], category=n["category"],
                              max_price=float(n.get("max_price") or prof.price_ceiling(n["kind"], n["category"])))
        return prof
    except Exception:  # noqa: BLE001
        return UserProfile.from_text(text, **kw)

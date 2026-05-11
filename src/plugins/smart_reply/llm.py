from __future__ import annotations

import json
import random
from dataclasses import dataclass

import httpx
from nonebot import logger

from src.skills.arknights_calculator import CalcRequest
from .config import config
from .memory import MemoryTurn


@dataclass(slots=True)
class ReplyDecision:
    should_reply: bool
    replies: list[str]
    reason: str = ""


@dataclass(slots=True)
class WikiLookupDecision:
    should_lookup: bool
    query: str = ""
    reason: str = ""


def _json_from_text(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`").removeprefix("json").strip()
    return json.loads(content)


def _cn(text: str) -> str:
    return text.encode("utf-8").decode("unicode_escape")


def _format_history(history: list[MemoryTurn]) -> str:
    if not history:
        return "No recent history."
    return "\n".join(
        f"[{turn.time}] {turn.role}/{turn.name}: {turn.content}" for turn in history
    )


def _system_prompt() -> str:
    return f"""
{config.smart_reply_persona}

You are deciding whether to reply in a QQ chat.
The latest input may contain multiple consecutive messages from the same session.
Treat those messages as one context package, not as separate reply requests.

Decision rules:
1. First decide whether a reply is needed right now.
2. Reply in Chinese unless the user explicitly asks for another language.
3. If the latest context names PRTS, mentions you, asks a question, gives a task, or clearly expects a response, you should usually reply.
4. If the context is idle chatter, a closed conversation, repeated noise, or something you cannot help with, you may choose not to reply.
5. Default to exactly one reply message. Only use more than one message when the user explicitly asks for steps, a list, or multiple options.
6. Each reply must be brief and useful: no more than {config.smart_reply_max_reply_chars} Chinese characters when possible.
7. Avoid spam, long lectures, repeated greetings, and pretending to know things you do not know.
8. Output JSON only. No Markdown, no extra explanation.

JSON format:
{{
  "should_reply": true,
  "replies": ["message one", "message two"],
  "reason": "short internal reason"
}}
""".strip()


def _parse_decision(content: str) -> ReplyDecision:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content.removeprefix("json").strip()

    data = _json_from_text(content)
    replies = data.get("replies") or []
    clean_replies = []
    for reply in replies[: config.smart_reply_max_replies]:
        clean_reply = _trim_reply(str(reply).strip())
        if clean_reply:
            clean_replies.append(clean_reply)
    should_reply = bool(data.get("should_reply")) and bool(clean_replies)
    return ReplyDecision(
        should_reply=should_reply,
        replies=clean_replies,
        reason=str(data.get("reason", ""))[:200],
    )


def _trim_reply(reply: str) -> str:
    reply = " ".join(reply.split())
    max_chars = config.smart_reply_max_reply_chars
    if len(reply) <= max_chars:
        return reply

    for mark in (_cn("\\u3002"), _cn("\\uff01"), _cn("\\uff1f"), ".", "!", "?"):
        index = reply.find(mark)
        if 0 < index + 1 <= max_chars:
            return reply[: index + 1]
    return reply[:max_chars].rstrip() + "..."


async def decide_with_llm(
    session_name: str,
    sender_name: str,
    message: str,
    history: list[MemoryTurn],
    wiki_context: str | None = None,
    calc_context: str | None = None,
) -> ReplyDecision:
    if not config.smart_reply_api_key:
        return decide_with_fallback(message)

    payload = {
        "model": config.smart_reply_model,
        "temperature": config.smart_reply_temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": (
                    f"Session: {session_name}\n"
                    f"Latest sender: {sender_name}\n"
                    f"Recent memory:\n{_format_history(history)}\n\n"
                    f"Latest context package:\n{message}\n\n"
                    f"Wiki context:\n{wiki_context or 'No wiki context was used.'}\n\n"
                    f"Calculation context:\n{calc_context or 'No calculation was used.'}"
                ),
            },
        ],
    }

    headers = {
        "Authorization": f"Bearer {config.smart_reply_api_key}",
        "Content-Type": "application/json",
    }
    url = f"{config.smart_reply_api_base}/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=config.smart_reply_timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return _parse_decision(content)
    except Exception as exc:
        logger.warning(f"smart_reply LLM decision failed, fallback used: {exc!r}")
        return decide_with_fallback(message)


async def decide_wiki_lookup(
    session_name: str,
    sender_name: str,
    message: str,
    history: list[MemoryTurn],
) -> WikiLookupDecision:
    if not config.smart_reply_wiki_enabled:
        return WikiLookupDecision(False, reason="wiki disabled")
    if not config.smart_reply_api_key:
        return decide_wiki_lookup_fallback(message)

    payload = {
        "model": config.smart_reply_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You decide whether a QQ message needs Arknights wiki lookup. "
                    "Use lookup only for factual Arknights questions about operators, "
                    "skills, modules, enemies, stages, materials, events, mechanics, or lore names. "
                    "Do not lookup for greetings, roleplay, casual chat, or subjective conversation. "
                    "If lookup is needed, produce the shortest useful search query in Chinese when possible. "
                    "Output JSON only: "
                    '{"should_lookup": true, "query": "search terms", "reason": "short reason"}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Session: {session_name}\n"
                    f"Sender: {sender_name}\n"
                    f"Recent memory:\n{_format_history(history)}\n\n"
                    f"Latest context package:\n{message}"
                ),
            },
        ],
    }

    headers = {
        "Authorization": f"Bearer {config.smart_reply_api_key}",
        "Content-Type": "application/json",
    }
    url = f"{config.smart_reply_api_base}/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=config.smart_reply_timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            data = _json_from_text(content)
            query = str(data.get("query", "")).strip()
            should_lookup = bool(data.get("should_lookup")) and bool(query)
            return WikiLookupDecision(
                should_lookup=should_lookup,
                query=query[:80],
                reason=str(data.get("reason", ""))[:200],
            )
    except Exception as exc:
        logger.warning(f"smart_reply wiki lookup decision failed: {exc!r}")
        return decide_wiki_lookup_fallback(message)


async def extract_calc_request(
    session_name: str,
    sender_name: str,
    message: str,
    history: list[MemoryTurn],
    wiki_context: str | None = None,
) -> CalcRequest:
    if not config.smart_reply_calc_enabled:
        return CalcRequest(enabled=False, note="calculator disabled")
    if not config.smart_reply_api_key:
        return CalcRequest(enabled=False, note="no api key")

    payload = {
        "model": config.smart_reply_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You extract parameters for a simple Arknights damage/healing calculator. "
                    "Enable calculation only when the user asks for DPS, HPS, total damage, total healing, or average output. "
                    "If key numeric parameters are missing, set enabled=false and explain missing fields in note. "
                    "Supported kind values: physical_dps, physical_total, arts_dps, arts_total, true_dps, true_total, hps, heal_total. "
                    "Use multiplier as a decimal: 240% => 2.4. enemy_res is percent, e.g. 20 means 20% RES. "
                    "Use attack_interval in seconds. duration is skill duration in seconds. "
                    "Output JSON only with keys: enabled, kind, attack, multiplier, attack_interval, duration, hit_count, target_count, enemy_defense, enemy_res, heal_amount, heal_interval, note."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Session: {session_name}\n"
                    f"Sender: {sender_name}\n"
                    f"Recent memory:\n{_format_history(history)}\n\n"
                    f"Latest context package:\n{message}\n\n"
                    f"Wiki context:\n{wiki_context or 'No wiki context was used.'}"
                ),
            },
        ],
    }

    headers = {
        "Authorization": f"Bearer {config.smart_reply_api_key}",
        "Content-Type": "application/json",
    }
    url = f"{config.smart_reply_api_base}/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=config.smart_reply_timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = _json_from_text(response.json()["choices"][0]["message"]["content"])
            request = CalcRequest(
                enabled=bool(data.get("enabled")),
                kind=str(data.get("kind", "")),
                attack=_optional_float(data.get("attack")),
                multiplier=_float_or_default(data.get("multiplier"), 1.0),
                attack_interval=_optional_float(data.get("attack_interval")),
                duration=_optional_float(data.get("duration")),
                hit_count=max(1, int(data.get("hit_count") or 1)),
                target_count=max(1, int(data.get("target_count") or 1)),
                enemy_defense=_float_or_default(data.get("enemy_defense"), 0),
                enemy_res=_float_or_default(data.get("enemy_res"), 0),
                heal_amount=_optional_float(data.get("heal_amount")),
                heal_interval=_optional_float(data.get("heal_interval")),
                note=str(data.get("note", ""))[:200],
            )
            return _correct_calc_kind(request, message)
    except Exception as exc:
        logger.warning(f"smart_reply calc extraction failed: {exc!r}")
        return CalcRequest(enabled=False, note="calc extraction failed")


def _correct_calc_kind(request: CalcRequest, message: str) -> CalcRequest:
    text = message.lower()
    wants_total = any(term in text for term in ("total", _cn("\\u603b\\u4f24"), _cn("\\u603b\\u91cf")))
    if any(term in text for term in ("hps", _cn("\\u6cbb\\u7597"), _cn("\\u5976\\u91cf"), _cn("\\u56de\\u590d"))):
        request.kind = "heal_total" if wants_total else "hps"
    elif any(term in text for term in ("true damage", _cn("\\u771f\\u4f24"), _cn("\\u771f\\u5b9e\\u4f24\\u5bb3"))):
        request.kind = "true_total" if wants_total else "true_dps"
    elif any(term in text for term in ("arts", "res", _cn("\\u6cd5\\u4f24"), _cn("\\u6cd5\\u672f"), _cn("\\u6cd5\\u6297"))):
        request.kind = "arts_total" if wants_total or request.duration else "arts_dps"
    elif any(term in text for term in ("physical", "def", _cn("\\u7269\\u7406"), _cn("\\u9632\\u5fa1"))):
        request.kind = "physical_total" if wants_total or request.duration else "physical_dps"
    return request


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_default(value: object, default: float) -> float:
    parsed = _optional_float(value)
    return default if parsed is None else parsed


def decide_wiki_lookup_fallback(message: str) -> WikiLookupDecision:
    text = message.strip()
    arknights_markers = (
        _cn("\\u660e\\u65e5\\u65b9\\u821f"),
        _cn("\\u5e72\\u5458"),
        _cn("\\u6280\\u80fd"),
        _cn("\\u4e13\\u7cbe"),
        _cn("\\u6a21\\u7ec4"),
        _cn("\\u6750\\u6599"),
        _cn("\\u5173\\u5361"),
        _cn("\\u654c\\u4eba"),
        _cn("\\u6d3b\\u52a8"),
        _cn("\\u57fa\\u5efa"),
        _cn("\\u5929\\u8d4b"),
    )
    question_markers = ("?", _cn("\\uff1f"), _cn("\\u4ec0\\u4e48"), _cn("\\u600e\\u4e48"), _cn("\\u591a\\u5c11"))
    if any(marker in text for marker in arknights_markers) and any(
        marker in text for marker in question_markers
    ):
        return WikiLookupDecision(True, query=text[-80:], reason="fallback arknights question")
    return WikiLookupDecision(False, reason="fallback no wiki need")


def decide_with_fallback(message: str) -> ReplyDecision:
    text = message.strip()
    direct_markers = (
        "?",
        "PRTS",
        "prts",
        "@",
        _cn("\\u5417"),
        _cn("\\u4e48"),
        _cn("\\u5565"),
        _cn("\\u600e\\u4e48"),
        _cn("\\u4e3a\\u4ec0\\u4e48"),
        _cn("\\u8c01"),
        _cn("\\u5728\\u54ea"),
        _cn("\\u591a\\u5c11"),
    )
    if any(marker in text for marker in direct_markers):
        return ReplyDecision(True, [_fallback_answer(text)], "fallback direct context")

    if random.random() > config.smart_reply_reply_probability:
        return ReplyDecision(False, [], "fallback probability")

    if len(text) <= 2:
        return ReplyDecision(False, [], "fallback too short")

    short_replies = [
        _cn("\\u535a\\u58eb\\uff0cPRTS\\u5df2\\u8bb0\\u5f55\\u3002"),
        _cn("\\u6536\\u5230\\u3002\\u9700\\u8981\\u8fdb\\u4e00\\u6b65\\u6570\\u636e\\u65f6\\uff0c\\u8bf7\\u7ee7\\u7eed\\u8bf4\\u660e\\u3002"),
        _cn("\\u8be5\\u4fe1\\u606f\\u5df2\\u7eb3\\u5165\\u5f53\\u524d\\u4e0a\\u4e0b\\u6587\\u3002"),
        _cn("\\u535a\\u58eb\\uff0c\\u8bf7\\u7ee7\\u7eed\\u3002"),
    ]
    return ReplyDecision(True, [random.choice(short_replies)], "fallback casual")


def _fallback_answer(text: str) -> str:
    if _cn("\\u600e\\u4e48") in text or _cn("\\u5982\\u4f55") in text:
        return _cn("\\u535a\\u58eb\\uff0c\\u8bf7\\u63d0\\u4f9b\\u76ee\\u6807\\u4e0e\\u5f53\\u524d\\u53d7\\u963b\\u70b9\\uff0cPRTS\\u5c06\\u534f\\u52a9\\u62c6\\u89e3\\u6b65\\u9aa4\\u3002")
    if _cn("\\u4e3a\\u4ec0\\u4e48") in text:
        return _cn("\\u535a\\u58eb\\uff0c\\u5f53\\u524d\\u4fe1\\u606f\\u4e0d\\u8db3\\u4ee5\\u5f62\\u6210\\u53ef\\u9760\\u5224\\u65ad\\u3002\\u8bf7\\u8865\\u5145\\u4e0a\\u4e0b\\u6587\\u3002")
    return _cn("\\u535a\\u58eb\\uff0cPRTS\\u5df2\\u63a5\\u6536\\u3002\\u8bf7\\u7ee7\\u7eed\\u63d0\\u4f9b\\u5177\\u4f53\\u9700\\u6c42\\u3002")

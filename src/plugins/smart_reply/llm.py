from __future__ import annotations

import json
import random
from dataclasses import dataclass

import httpx
from nonebot import logger

from .config import config
from .memory import MemoryTurn


@dataclass(slots=True)
class ReplyDecision:
    should_reply: bool
    replies: list[str]
    reason: str = ""


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
5. If you reply, send at most {config.smart_reply_max_replies} short QQ-style messages.
6. Avoid spam, long lectures, and pretending to know things you do not know.
7. Output JSON only. No Markdown, no extra explanation.

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

    data = json.loads(content)
    replies = data.get("replies") or []
    clean_replies = [
        str(reply).strip()
        for reply in replies[: config.smart_reply_max_replies]
        if str(reply).strip()
    ]
    should_reply = bool(data.get("should_reply")) and bool(clean_replies)
    return ReplyDecision(
        should_reply=should_reply,
        replies=clean_replies,
        reason=str(data.get("reason", ""))[:200],
    )


async def decide_with_llm(
    session_name: str,
    sender_name: str,
    message: str,
    history: list[MemoryTurn],
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
            return _parse_decision(content)
    except Exception as exc:
        logger.warning(f"smart_reply LLM decision failed, fallback used: {exc!r}")
        return decide_with_fallback(message)


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

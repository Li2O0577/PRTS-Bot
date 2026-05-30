from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime

from nonebot import get_bot, logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, PrivateMessageEvent
from nonebot.params import EventMessage
from nonebot.plugin import PluginMetadata

from src.skills.arknights_calculator import calculate
from src.skills.arknights_wiki import search_wiki

from .config import SmartReplyConfig, config
from .llm import decide_with_llm, extract_calc_request
from .memory import memory


__plugin_meta__ = PluginMetadata(
    name="smart_reply",
    description="QQ smart reply with per-session memory and batched reply decisions.",
    usage="Configure NapCat OneBot V11 reverse WebSocket and the bot will listen automatically.",
    config=SmartReplyConfig,
)


@dataclass(slots=True)
class PendingMessage:
    sender_name: str
    text: str
    time: str


@dataclass(slots=True)
class PendingBatch:
    bot: Bot
    event: MessageEvent
    session_name: str
    latest_sender_name: str
    messages: list[PendingMessage] = field(default_factory=list)
    version: int = 0
    task: asyncio.Task | None = None


matcher = on_message(priority=99, block=False)
_pending_batches: dict[str, PendingBatch] = {}


def _plain_text(event: MessageEvent) -> str:
    return event.get_plaintext().strip()


def _session_id(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        return f"group:{event.group_id}"
    return f"private:{event.user_id}"


def _session_name(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        return f"QQ group {event.group_id}"
    return f"Private chat {event.user_id}"


def _sender_name(event: MessageEvent) -> str:
    sender = getattr(event, "sender", None)
    nickname = getattr(sender, "nickname", "") or getattr(sender, "card", "")
    return nickname or str(event.user_id)


def _is_at_me(event: MessageEvent, bot: Bot) -> bool:
    for segment in event.message:
        if segment.type == "at" and str(segment.data.get("qq")) == str(bot.self_id):
            return True
    return False


def _should_listen(event: MessageEvent, bot: Bot) -> bool:
    if not config.smart_reply_enabled:
        return False
    if isinstance(event, PrivateMessageEvent):
        return config.smart_reply_allowed_private
    if isinstance(event, GroupMessageEvent):
        if not config.smart_reply_allowed_group:
            return False
        return not config.smart_reply_require_mention_in_group or _is_at_me(event, bot)
    return False


def _format_pending_context(messages: list[PendingMessage]) -> str:
    return "\n".join(
        f"[{item.time}] {item.sender_name}: {item.text}" for item in messages
    )


async def _send_replies(bot: Bot, event: MessageEvent, replies: list[str]) -> None:
    for index, reply in enumerate(replies):
        if index == 0:
            typing_delay = min(len(reply) * 0.15 + random.uniform(1.5, 4.0), 12.0)
            await asyncio.sleep(typing_delay)
        else:
            await asyncio.sleep(1.2)
        await bot.send(event, reply)


def _add_to_pending_batch(
    bot: Bot,
    event: MessageEvent,
    session_id: str,
    session_name: str,
    sender_name: str,
    text: str,
) -> int:
    batch = _pending_batches.get(session_id)
    if batch is None:
        batch = PendingBatch(
            bot=bot,
            event=event,
            session_name=session_name,
            latest_sender_name=sender_name,
        )
        _pending_batches[session_id] = batch

    batch.bot = bot
    batch.event = event
    batch.session_name = session_name
    batch.latest_sender_name = sender_name
    batch.messages.append(
        PendingMessage(
            sender_name=sender_name,
            text=text,
            time=datetime.now().strftime("%H:%M:%S"),
        )
    )
    if len(batch.messages) > config.smart_reply_max_batch_messages:
        batch.messages = batch.messages[-config.smart_reply_max_batch_messages :]

    batch.version += 1
    if batch.task and not batch.task.done():
        batch.task.cancel()
    batch.task = asyncio.create_task(_flush_after_idle(session_id, batch.version))
    return batch.version


async def _flush_after_idle(session_id: str, version: int) -> None:
    try:
        await asyncio.sleep(config.smart_reply_batch_wait_seconds)
    except asyncio.CancelledError:
        return

    batch = _pending_batches.get(session_id)
    if batch is None or batch.version != version:
        return

    _pending_batches.pop(session_id, None)
    context = _format_pending_context(batch.messages)
    history = memory.get(session_id)
    wiki_context = None
    calc_context = None

    calc_request = await extract_calc_request(
        session_name=batch.session_name,
        sender_name=batch.latest_sender_name,
        message=context,
        history=history,
        wiki_context=None,
    )

    if calc_request.enabled:
        wiki_query = context.strip().split("\n")[-1] if context.strip() else context.strip()
        wiki_result = await search_wiki(wiki_query)
        if wiki_result is not None and wiki_result.pages:
            wiki_context = wiki_result.as_prompt_context()
            logger.info(
                f"smart_reply wiki lookup for calc: query={wiki_query[:80]!r}, "
                f"pages={len(wiki_result.pages)}"
            )
            calc_request = await extract_calc_request(
                session_name=batch.session_name,
                sender_name=batch.latest_sender_name,
                message=context,
                history=history,
                wiki_context=wiki_context,
            )

    calc_result = calculate(calc_request)
    if calc_result is not None:
        calc_context = (
            f"Calculator result: {calc_result.summary}\n"
            f"Formula details: {calc_result.details}\n"
            "Use this numeric result. Mention that it is a simplified estimate if assumptions are incomplete."
        )
        logger.info(f"smart_reply calculation used: {calc_result.summary}")
    elif calc_request.enabled:
        calc_context = (
            "Calculator could not run because required parameters were missing. "
            f"Missing/notes: {calc_request.note}"
        )

    decision = await decide_with_llm(
        session_name=batch.session_name,
        sender_name=batch.latest_sender_name,
        message=context,
        history=history,
        wiki_context=wiki_context,
        calc_context=calc_context,
    )

    if not decision.should_reply:
        logger.debug(f"smart_reply skipped batch: {decision.reason}")
        memory.save()
        return

    replies = decision.replies[: config.smart_reply_max_replies]
    try:
        await _send_replies(batch.bot, batch.event, replies)
    except Exception as exc:
        logger.warning(f"smart_reply send failed: {exc!r}")
        return

    for reply in replies:
        memory.append(session_id, "assistant", "bot", reply)
    memory.save()


@matcher.handle()
async def handle_smart_reply(
    bot: Bot,
    event: MessageEvent,
    message=EventMessage(),
) -> None:
    if not _should_listen(event, bot):
        return

    text = _plain_text(event)
    if not text:
        return

    session_id = _session_id(event)
    sender_name = _sender_name(event)
    memory.append(session_id, "user", sender_name, text)
    _add_to_pending_batch(
        bot=bot,
        event=event,
        session_id=session_id,
        session_name=_session_name(event),
        sender_name=sender_name,
        text=text,
    )


async def send_to_session(bot_id: str, session_id: str, text: str) -> None:
    bot = get_bot(bot_id)
    kind, raw_id = session_id.split(":", 1)
    if kind == "group":
        await bot.send_group_msg(group_id=int(raw_id), message=text)
    elif kind == "private":
        await bot.send_private_msg(user_id=int(raw_id), message=text)
    else:
        raise ValueError(f"unknown session id: {session_id}")

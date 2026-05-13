from __future__ import annotations

import re
import time
from pathlib import Path

from nonebot import on_regex
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment, PrivateMessageEvent
from nonebot.plugin import PluginMetadata

from src.skills.skland_account import (
    bind_account_by_scan_token,
    create_scan_id,
    format_roles,
    get_account_summary,
    get_token_by_scan_code,
    list_roles,
    poll_scan_code,
    refresh_roles,
    unbind_account,
)
from src.skills.skland_account.skill import SklandError


__plugin_meta__ = PluginMetadata(
    name="skland_account",
    description="Skland account binding and profile query commands.",
    usage="森空岛绑定 / 森空岛解绑 / 森空岛角色 / 森空岛信息 / 森空岛刷新",
)


bind_cmd = on_regex(r"^[\/!！]?森空岛绑定(?:\s+|$)", priority=10, block=True)
unbind_cmd = on_regex(r"^[\/!！]?森空岛解绑\s*$", priority=10, block=True)
roles_cmd = on_regex(r"^[\/!！]?森空岛角色\s*$", priority=10, block=True)
info_cmd = on_regex(r"^[\/!！]?森空岛信息\s*$", priority=10, block=True)
refresh_cmd = on_regex(r"^[\/!！]?森空岛刷新\s*$", priority=10, block=True)


def _ensure_private(event: MessageEvent) -> str | None:
    if not isinstance(event, PrivateMessageEvent):
        return "森空岛相关命令只允许在私聊中使用。"
    return None


@bind_cmd.handle()
async def handle_bind(event: MessageEvent) -> None:
    if message := _ensure_private(event):
        await bind_cmd.finish(message)

    plain_text = event.get_plaintext().strip()
    extra_text = re.sub(r"^[\/!！]?森空岛绑定", "", plain_text, count=1).strip()
    if extra_text:
        await bind_cmd.finish("当前只支持扫码绑定。请直接发送：森空岛绑定")

    try:
        import qrcode
    except ImportError:
        await bind_cmd.finish("缺少二维码依赖，请先执行一次 `pip install -e .`。")

    qr_dir = Path("data") / "skland_qr"
    _cleanup_qr_files(qr_dir)
    qr_dir.mkdir(parents=True, exist_ok=True)

    try:
        scan_id = await create_scan_id()
        scan_url = f"hypergryph://scan_login?scanId={scan_id}"
        qr_file = qr_dir / f"{event.user_id}_{int(time.time())}.png"
        qrcode.make(scan_url).save(qr_file)

        await bind_cmd.send(
            Message(
                [
                    MessageSegment.text("请使用森空岛 App 扫描下方二维码完成绑定，二维码约 100 秒内有效。"),
                    MessageSegment.image(file=qr_file.resolve().as_uri()),
                ]
            )
        )

        scan_code = await poll_scan_code(scan_id)
        if not scan_code:
            await bind_cmd.finish("二维码已超时，请重新发送“森空岛绑定”。")

        token = await get_token_by_scan_code(scan_code)
        result = await bind_account_by_scan_token(str(event.user_id), token)
        await bind_cmd.finish(
            f"{result.message}\n已同步角色数：{result.role_count}\n默认 UID：{result.default_uid or '未找到'}"
        )
    except SklandError as exc:
        await bind_cmd.finish(str(exc))
    finally:
        _cleanup_qr_files(qr_dir)


@unbind_cmd.handle()
async def handle_unbind(event: MessageEvent) -> None:
    if message := _ensure_private(event):
        await unbind_cmd.finish(message)

    if unbind_account(str(event.user_id)):
        await unbind_cmd.finish("森空岛绑定已清除。")
    await unbind_cmd.finish("你当前还没有绑定森空岛。")


@roles_cmd.handle()
async def handle_roles(event: MessageEvent) -> None:
    if message := _ensure_private(event):
        await roles_cmd.finish(message)

    try:
        await roles_cmd.finish(format_roles(list_roles(str(event.user_id))))
    except SklandError as exc:
        await roles_cmd.finish(str(exc))


@info_cmd.handle()
async def handle_info(event: MessageEvent) -> None:
    if message := _ensure_private(event):
        await info_cmd.finish(message)

    try:
        summary = await get_account_summary(str(event.user_id))
        await info_cmd.finish(summary.to_text())
    except SklandError as exc:
        await info_cmd.finish(str(exc))


@refresh_cmd.handle()
async def handle_refresh(event: MessageEvent) -> None:
    if message := _ensure_private(event):
        await refresh_cmd.finish(message)

    try:
        result = await refresh_roles(str(event.user_id))
        await refresh_cmd.finish(
            f"{result.message}\n当前角色数：{result.role_count}\n默认 UID：{result.default_uid or '未找到'}"
        )
    except SklandError as exc:
        await refresh_cmd.finish(str(exc))


def _cleanup_qr_files(qr_dir: Path) -> None:
    if not qr_dir.exists():
        return
    for file in qr_dir.glob("*.png"):
        file.unlink(missing_ok=True)

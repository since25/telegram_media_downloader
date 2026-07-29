"""Activated resource Bot commands, channel binding, search, and publishing."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import pyrogram
from loguru import logger
from pyrogram import enums, types
from pyrogram.handlers import (
    CallbackQueryHandler,
    ChatMemberUpdatedHandler,
    MessageHandler,
)

from module.channel_library_store import PackageFilter
from utils.format import format_byte


SEARCH_PAGE_SIZE = 5
SEARCH_SESSION_TTL = 30 * 60
SEARCH_SESSIONS_PER_USER = 5
BIND_INTENT_TTL = 10 * 60


def user_can_manage_channel(chat_member) -> bool:
    """Return whether a Telegram member can manage the target channel."""

    return bool(
        chat_member
        and chat_member.status
        in {
            enums.ChatMemberStatus.OWNER,
            enums.ChatMemberStatus.ADMINISTRATOR,
        }
    )


def bot_can_post_to_channel(chat_member) -> bool:
    """Return whether the resource Bot can publish channel posts."""

    if chat_member is None:
        return False
    if chat_member.status == enums.ChatMemberStatus.OWNER:
        return True
    if chat_member.status != enums.ChatMemberStatus.ADMINISTRATOR:
        return False
    privileges = getattr(chat_member, "privileges", None)
    return bool(privileges and privileges.can_post_messages)


def build_resource_bot_commands() -> list[types.BotCommand]:
    """Return the public command menu for the resource Bot."""

    return [
        types.BotCommand("start", "查看资源 Bot 使用方法"),
        types.BotCommand("activate", "使用激活密钥"),
        types.BotCommand("status", "查看激活、频道和任务状态"),
        types.BotCommand("bind", "开始绑定目标频道"),
        types.BotCommand("channel", "查看当前目标频道"),
        types.BotCommand("unbind", "解除当前目标频道"),
        types.BotCommand("search", "搜索资源包"),
        types.BotCommand("help", "查看使用方法"),
    ]


def build_resource_admin_bot_commands() -> list[types.BotCommand]:
    """Return management Bot commands for resource access administration."""

    return [
        types.BotCommand("create_resource_key", "创建一次性资源激活密钥"),
        types.BotCommand("revoke_resource_user", "撤销资源用户"),
    ]


@dataclass
class SearchSession:
    """One bounded, private search session."""

    token: str
    user_id: int
    query: str
    current_cursor: Optional[str]
    next_cursor: Optional[str]
    created_at: float
    packages: dict[int, dict] = field(default_factory=dict)
    action_jobs: dict[int, str] = field(default_factory=dict)
    buffered_packages: list[dict] = field(default_factory=list)


class ResourceAdminCommands:
    """Management Bot commands for issuing keys and revoking users."""

    def __init__(self, store) -> None:
        self.store = store

    def register(self, admin_client, allowed_user_ids) -> None:
        allowed = list(allowed_user_ids)
        admin_client.add_handler(
            MessageHandler(
                self.handle_create_key,
                filters=pyrogram.filters.command(["create_resource_key"])
                & pyrogram.filters.user(allowed),
            )
        )
        admin_client.add_handler(
            MessageHandler(
                self.handle_revoke_user,
                filters=pyrogram.filters.command(["revoke_resource_user"])
                & pyrogram.filters.user(allowed),
            )
        )

    async def handle_create_key(self, client, message) -> None:
        user_id = int(message.from_user.id)
        key = self.store.create_activation_key(user_id)
        logger.info(
            "Resource activation key created: prefix={} actor={}",
            key[:8],
            user_id,
        )
        await client.send_message(
            user_id,
            "一次性资源 Bot 激活密钥（仅显示本次）：\n" + key,
        )

    async def handle_revoke_user(self, client, message) -> None:
        user_id = int(message.from_user.id)
        parts = str(message.text or "").split()
        if len(parts) != 2:
            await client.send_message(
                user_id,
                "格式：/revoke_resource_user <telegram_user_id>",
            )
            return
        try:
            target_user_id = int(parts[1])
        except ValueError:
            await client.send_message(
                user_id,
                "Telegram user ID 必须是整数。",
            )
            return
        revoked = self.store.revoke_user(target_user_id)
        if revoked:
            await client.send_message(
                user_id, f"已撤销资源用户 {target_user_id}。"
            )
        else:
            await client.send_message(
                user_id, f"未找到资源用户 {target_user_id}。"
            )


class ResourceBotRole:
    """Activated-user Bot role managed by the main Bot lifecycle."""

    def __init__(
        self,
        app,
        main_client,
        store,
        channel_store,
        *,
        client_factory=pyrogram.Client,
        time_func: Callable[[], float] = time.time,
    ) -> None:
        self.app = app
        self.main_client = main_client
        self.store = store
        self.channel_store = channel_store
        self.client_factory = client_factory
        self.time_func = time_func
        self.bot = None
        self.bot_info = None
        self.delivery_service = None
        self.pending_bind_users: dict[int, float] = {}
        self.search_sessions: dict[str, SearchSession] = {}

    async def start(self) -> None:
        self.bot = self.client_factory(
            self.app.application_name + "_resource_bot",
            api_hash=self.app.api_hash,
            api_id=self.app.api_id,
            bot_token=self.app.resource_bot_token,
            workdir=self.app.session_file_path,
            proxy=self.app.proxy,
        )
        await self.bot.start()
        self.bot_info = await self.bot.get_me()
        await self.bot.set_bot_commands(build_resource_bot_commands())
        self._register_handlers()

    async def stop(self) -> None:
        if self.bot is not None:
            await self.bot.stop()
            self.bot = None
            self.bot_info = None

    def _register_handlers(self) -> None:
        command_handlers = {
            "start": self.handle_start,
            "help": self.handle_help,
            "activate": self.handle_activate,
            "status": self.handle_status,
            "bind": self.handle_bind,
            "channel": self.handle_channel,
            "unbind": self.handle_unbind,
            "search": self.handle_search,
        }
        for command, callback in command_handlers.items():
            self.bot.add_handler(
                MessageHandler(
                    callback,
                    filters=pyrogram.filters.command([command]),
                )
            )
        self.bot.add_handler(CallbackQueryHandler(self.handle_callback))
        self.bot.add_handler(
            ChatMemberUpdatedHandler(self.handle_chat_member_updated)
        )

    @staticmethod
    def _is_private(message) -> bool:
        return getattr(message.chat, "type", None) == enums.ChatType.PRIVATE

    async def _require_private(self, client, message) -> bool:
        if self._is_private(message):
            return True
        await client.send_message(
            int(message.from_user.id),
            "请在资源 Bot 私聊中使用此命令。",
        )
        return False

    async def _require_active(self, client, message) -> bool:
        if not await self._require_private(client, message):
            return False
        if self.store.is_user_active(int(message.from_user.id)):
            return True
        await client.send_message(
            int(message.from_user.id),
            "尚未激活，请使用 /activate <激活密钥>。",
        )
        return False

    async def handle_start(self, client, message) -> None:
        await self.handle_help(client, message)

    async def handle_help(self, client, message) -> None:
        if not await self._require_private(client, message):
            return
        await client.send_message(
            int(message.from_user.id),
            "资源 Bot 使用方法：\n"
            "1. /activate <激活密钥>\n"
            "2. /bind 后把本 Bot 添加为目标频道管理员并授予发帖权限\n"
            "3. /search <关键词> 搜索资源包\n"
            "4. 点击“一键发布”加入串行发布队列\n\n"
            "其他命令：/status /channel /unbind",
        )

    async def handle_activate(self, client, message) -> None:
        if not await self._require_private(client, message):
            return
        parts = str(message.text or "").split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip():
            await client.send_message(
                int(message.from_user.id),
                "格式：/activate <激活密钥>",
            )
            return
        activated = self.store.redeem_activation_key(
            parts[1].strip(), int(message.from_user.id)
        )
        if activated:
            await client.send_message(
                int(message.from_user.id),
                "激活成功。下一步可使用 /bind 绑定目标频道。",
            )
        else:
            await client.send_message(
                int(message.from_user.id),
                "激活密钥无效或已使用。",
            )

    async def handle_status(self, client, message) -> None:
        if not await self._require_private(client, message):
            return
        user_id = int(message.from_user.id)
        if not self.store.is_user_active(user_id):
            await client.send_message(user_id, "状态：未激活。")
            return
        binding = self.store.get_binding(user_id)
        lines = ["状态：已激活。"]
        if binding and binding["status"] == "active":
            lines.append(
                f"目标频道：{binding['title']}（{binding['chat_id']}）"
            )
        elif binding and binding["status"] == "permission_lost":
            lines.append("目标频道：权限已失效，请重新执行 /bind。")
        else:
            lines.append("目标频道：未绑定。")
        latest_job = self.store.get_latest_delivery_job(user_id)
        if latest_job is not None:
            lines.append(
                "最近任务："
                f"{latest_job['public_id']} / {latest_job['status']} / "
                f"{latest_job['uploaded_items']}/{latest_job['total_items']}"
            )
        await client.send_message(user_id, "\n".join(lines))

    async def handle_bind(self, client, message) -> None:
        if not await self._require_active(client, message):
            return
        user_id = int(message.from_user.id)
        self.pending_bind_users[user_id] = self.time_func()
        username = getattr(self.bot_info, "username", None)
        mention = f"@{username}" if username else "本资源 Bot"
        await client.send_message(
            user_id,
            f"请在 10 分钟内把 {mention} 添加到目标频道，"
            "设为管理员并授予“发布消息”权限。\n"
            "完成后 Telegram 的成员权限更新会自动完成绑定。",
        )

    async def handle_channel(self, client, message) -> None:
        if not await self._require_active(client, message):
            return
        user_id = int(message.from_user.id)
        binding = self.store.get_binding(user_id)
        if binding and binding["status"] == "active":
            await client.send_message(
                user_id,
                f"当前目标频道：{binding['title']}（{binding['chat_id']}）",
            )
            return
        if binding and binding["status"] == "permission_lost":
            await client.send_message(
                user_id,
                "原目标频道的发帖权限已失效，请重新使用 /bind。",
            )
            return
        await client.send_message(user_id, "当前没有绑定目标频道。")

    async def handle_unbind(self, client, message) -> None:
        if not await self._require_active(client, message):
            return
        user_id = int(message.from_user.id)
        self.pending_bind_users.pop(user_id, None)
        if self.store.unbind_channel(user_id):
            await client.send_message(user_id, "已解除目标频道绑定。")
        else:
            await client.send_message(user_id, "当前没有活动的频道绑定。")

    async def handle_chat_member_updated(self, client, update) -> None:
        chat = getattr(update, "chat", None)
        new_member = getattr(update, "new_chat_member", None)
        member_user = getattr(new_member, "user", None)
        if (
            chat is None
            or new_member is None
            or member_user is None
            or self.bot_info is None
            or int(member_user.id) != int(self.bot_info.id)
        ):
            return
        chat_id = int(chat.id)
        existing = self.store.get_binding_by_chat(chat_id)
        if not bot_can_post_to_channel(new_member):
            if existing is not None and existing["status"] != "unbound":
                self.store.mark_binding_permission_lost(chat_id)
                await self._safe_private_notice(
                    int(existing["telegram_user_id"]),
                    "目标频道的资源 Bot 发帖权限已失效，请重新绑定。",
                )
            return
        if existing is not None and existing["status"] != "unbound":
            self.store.mark_binding_verified(chat_id)
        actor = getattr(update, "from_user", None)
        if actor is None:
            return
        user_id = int(actor.id)
        created_at = self.pending_bind_users.get(user_id)
        if created_at is None:
            return
        if self.time_func() - created_at > BIND_INTENT_TTL:
            self.pending_bind_users.pop(user_id, None)
            await self._safe_private_notice(
                user_id, "绑定请求已过期，请重新使用 /bind。"
            )
            return
        if not self.store.is_user_active(user_id):
            self.pending_bind_users.pop(user_id, None)
            return
        try:
            actor_member = await client.get_chat_member(chat_id, user_id)
            bot_member = await client.get_chat_member(
                chat_id, int(self.bot_info.id)
            )
        except Exception as error:
            logger.warning(
                "Resource channel binding verification failed: {}",
                error.__class__.__name__,
            )
            await self._safe_private_notice(
                user_id, "无法验证频道权限，请确认权限后重试。"
            )
            return
        if not user_can_manage_channel(actor_member):
            await self._safe_private_notice(
                user_id, "只有频道创建者或管理员可以绑定该频道。"
            )
            return
        if not bot_can_post_to_channel(bot_member):
            await self._safe_private_notice(
                user_id, "资源 Bot 尚未获得频道管理员发帖权限。"
            )
            return
        try:
            binding = self.store.bind_channel(
                user_id,
                chat_id,
                getattr(chat, "title", None) or str(chat_id),
                getattr(chat, "username", None),
            )
        except ValueError as error:
            message = (
                "该频道已绑定给其他资源用户。"
                if str(error) == "channel_already_bound"
                else "频道绑定失败，请重新操作。"
            )
            await self._safe_private_notice(user_id, message)
            return
        self.pending_bind_users.pop(user_id, None)
        await self._safe_private_notice(
            user_id, f"频道绑定成功：{binding['title']}。"
        )

    async def _safe_private_notice(self, user_id: int, text: str) -> None:
        try:
            await self.bot.send_message(int(user_id), text)
        except Exception as error:
            logger.warning(
                "Resource Bot private notice failed: {}",
                error.__class__.__name__,
            )

    def make_search_session(
        self,
        *,
        user_id: int,
        query: str,
        created_at: Optional[float] = None,
    ) -> SearchSession:
        now = self.time_func() if created_at is None else float(created_at)
        session = SearchSession(
            token=secrets.token_urlsafe(8),
            user_id=int(user_id),
            query=str(query),
            current_cursor=None,
            next_cursor=None,
            created_at=now,
        )
        existing = sorted(
            (
                value
                for value in self.search_sessions.values()
                if value.user_id == int(user_id)
            ),
            key=lambda value: value.created_at,
        )
        while len(existing) >= SEARCH_SESSIONS_PER_USER:
            oldest = existing.pop(0)
            self.search_sessions.pop(oldest.token, None)
        self.search_sessions[session.token] = session
        return session

    async def handle_search(self, client, message) -> None:
        if not await self._require_active(client, message):
            return
        user_id = int(message.from_user.id)
        parts = str(message.text or "").split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip():
            await client.send_message(user_id, "格式：/search <关键词>")
            return
        if self.channel_store is None:
            await client.send_message(user_id, "资源搜索服务当前不可用。")
            return
        session = self.make_search_session(
            user_id=user_id, query=parts[1].strip()
        )
        packages = self._load_search_page(session, None)
        text, markup = self._render_search_page(session, packages)
        await client.send_message(user_id, text, reply_markup=markup)

    def _load_search_page(
        self, session: SearchSession, cursor: Optional[str]
    ) -> list[dict]:
        results = []
        while session.buffered_packages and len(results) < SEARCH_PAGE_SIZE:
            results.append(session.buffered_packages.pop(0))
        next_cursor = cursor
        while len(results) < SEARCH_PAGE_SIZE:
            if next_cursor is None and session.current_cursor is not None:
                break
            page = self.channel_store.list_packages_aggregate(
                [],
                PackageFilter(q=session.query),
                cursor=next_cursor,
                limit=SEARCH_PAGE_SIZE,
            )
            stable = [
                item
                for item in page.items
                if item.get("boundary_status") == "stable"
            ]
            needed = SEARCH_PAGE_SIZE - len(results)
            results.extend(stable[:needed])
            session.buffered_packages.extend(stable[needed:])
            session.current_cursor = next_cursor
            next_cursor = page.next_cursor
            if next_cursor is None:
                break
        session.next_cursor = next_cursor
        for package in results:
            session.packages[int(package["id"])] = dict(package)
        return results

    def _render_search_page(
        self, session: SearchSession, packages: list[dict]
    ) -> tuple[str, Optional[types.InlineKeyboardMarkup]]:
        if not packages:
            return f"未找到与“{session.query}”匹配的稳定资源包。", None
        lines = [f"🔎 搜索：{session.query}"]
        rows = []
        for package in packages:
            size_text = format_byte(int(package.get("known_total_size") or 0))
            if int(package.get("unknown_size_count") or 0):
                size_text += "+"
            published = str(package.get("published_at") or "未知")[:10]
            lines.extend(
                [
                    "",
                    f"📦 {package.get('title') or '未命名资源包'}",
                    f"来源：{package.get('channel_title') or package.get('chat_id')}",
                    f"日期：{published}",
                    f"媒体：{int(package.get('media_count') or 0)}",
                    f"大小：{size_text}",
                ]
            )
            rows.append(
                [
                    types.InlineKeyboardButton(
                        f"一键发布：{str(package.get('title') or package['id'])[:24]}",
                        callback_data=(
                            f"rp:{session.token}:{int(package['id'])}"
                        ),
                    )
                ]
            )
        if session.buffered_packages or session.next_cursor is not None:
            rows.append(
                [
                    types.InlineKeyboardButton(
                        "下一页",
                        callback_data=f"rs:{session.token}:next",
                    )
                ]
            )
        return "\n".join(lines), types.InlineKeyboardMarkup(rows)

    async def handle_callback(self, client, query) -> None:
        data = str(getattr(query, "data", "") or "")
        parts = data.split(":")
        if len(parts) < 3 or parts[0] not in {"rs", "rp"}:
            await query.answer("无效操作。")
            return
        session = self.search_sessions.get(parts[1])
        if session is None:
            await query.answer("搜索已过期，请重新搜索。")
            return
        user_id = int(query.from_user.id)
        if session.user_id != user_id:
            await query.answer("搜索会话不属于当前用户。")
            return
        if self.time_func() - session.created_at > SEARCH_SESSION_TTL:
            self.search_sessions.pop(session.token, None)
            await query.answer("搜索已过期，请重新搜索。")
            return
        if not self.store.is_user_active(user_id):
            await query.answer("激活状态已失效。")
            return
        if parts[0] == "rs":
            await self._handle_search_next(query, session)
            return
        await self._handle_publish(query, session, parts)

    async def _handle_search_next(self, query, session: SearchSession) -> None:
        if not session.buffered_packages and session.next_cursor is None:
            await query.answer("没有更多结果。")
            return
        packages = self._load_search_page(session, session.next_cursor)
        text, markup = self._render_search_page(session, packages)
        await query.message.edit_text(text, reply_markup=markup)
        await query.answer()

    async def _handle_publish(
        self, query, session: SearchSession, parts: list[str]
    ) -> None:
        if len(parts) != 3:
            await query.answer("无效发布操作。")
            return
        try:
            package_id = int(parts[2])
        except ValueError:
            await query.answer("无效发布操作。")
            return
        package = session.packages.get(package_id)
        if package is None:
            await query.answer("资源包不在当前搜索结果中。")
            return
        binding = self.store.get_binding(session.user_id)
        if binding is None or binding["status"] != "active":
            await query.answer("请先绑定目标频道。")
            return
        if package_id in session.action_jobs:
            await query.answer(
                f"发布任务已加入队列：{session.action_jobs[package_id]}"
            )
            return
        if not await self.verify_bot_post_permission(int(binding["chat_id"])):
            await query.answer("目标频道发帖权限已失效，请重新绑定。")
            return
        current = (
            self.channel_store.get_package(package_id)
            if self.channel_store is not None
            else None
        )
        if (
            current is None
            or current.get("boundary_status") != "stable"
            or int(current["index_revision"])
            != int(package["index_revision"])
        ):
            await query.answer("资源包已变化，请重新搜索。")
            return
        if self.delivery_service is None:
            await query.answer("资源发布服务当前不可用。")
            return
        action_key = (
            f"resource:{session.user_id}:{session.token}:{package_id}"
        )
        try:
            job, _created = await self.delivery_service.enqueue(
                idempotency_key=action_key,
                user_id=session.user_id,
                package_id=package_id,
                target_chat_id=int(binding["chat_id"]),
            )
        except ValueError as error:
            messages = {
                "package_changed": "资源包已变化，请重新搜索。",
                "package_not_found": "资源包不存在，请重新搜索。",
                "service_unavailable": "资源发布服务当前不可用。",
            }
            await query.answer(
                messages.get(str(error), "创建发布任务失败，请稍后重试。")
            )
            return
        public_id = str(job["public_id"])
        session.action_jobs[package_id] = public_id
        await query.answer(f"发布任务已加入队列：{public_id}")

    async def verify_bot_post_permission(self, chat_id: int) -> bool:
        try:
            bot_id = int(
                getattr(self.bot_info, "id", None)
                or getattr(self.bot.me, "id")
            )
            chat_member = await self.bot.get_chat_member(chat_id, bot_id)
        except Exception as error:
            logger.warning(
                "Resource Bot post permission verification failed: {}",
                error.__class__.__name__,
            )
            chat_member = None
        if bot_can_post_to_channel(chat_member):
            self.store.mark_binding_verified(chat_id)
            return True
        self.store.mark_binding_permission_lost(chat_id)
        return False

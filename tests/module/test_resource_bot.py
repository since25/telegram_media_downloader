"""Tests for activated resource Bot commands, binding, search, and publishing."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

from pyrogram import enums

from module.channel_library_store import QueryPage
from module.resource_bot import (
    ResourceAdminCommands,
    ResourceBotRole,
    bot_can_post_to_channel,
    user_can_manage_channel,
)
from module.resource_bot_store import ResourceBotStore


def run(coroutine):
    return asyncio.run(coroutine)


def member(status, *, can_post=None):
    privileges = (
        None
        if can_post is None
        else SimpleNamespace(can_post_messages=can_post)
    )
    return SimpleNamespace(status=status, privileges=privileges)


def test_channel_permission_helpers():
    assert user_can_manage_channel(member(enums.ChatMemberStatus.OWNER))
    assert user_can_manage_channel(
        member(enums.ChatMemberStatus.ADMINISTRATOR, can_post=False)
    )
    assert not user_can_manage_channel(member(enums.ChatMemberStatus.MEMBER))
    assert bot_can_post_to_channel(member(enums.ChatMemberStatus.OWNER))
    assert bot_can_post_to_channel(
        member(enums.ChatMemberStatus.ADMINISTRATOR, can_post=True)
    )
    assert not bot_can_post_to_channel(
        member(enums.ChatMemberStatus.ADMINISTRATOR, can_post=False)
    )
    assert not bot_can_post_to_channel(
        member(enums.ChatMemberStatus.ADMINISTRATOR)
    )


class FakeBotClient:
    def __init__(self):
        self.sent_messages = []
        self.handlers = []
        self.members = {}
        self.me = SimpleNamespace(id=999, username="resource_bot")

    async def send_message(self, chat_id, text, **kwargs):
        sent = SimpleNamespace(chat_id=chat_id, text=text, **kwargs)
        self.sent_messages.append(sent)
        return sent

    async def get_chat_member(self, chat_id, user_id):
        return self.members[(int(chat_id), int(user_id))]

    def add_handler(self, handler):
        self.handlers.append(handler)


class FakeMessage:
    def __init__(self, user_id=200, text="", chat_type=enums.ChatType.PRIVATE):
        self.from_user = SimpleNamespace(id=user_id)
        self.chat = SimpleNamespace(id=user_id, type=chat_type)
        self.text = text
        self.id = 1


class FakeCallbackMessage:
    def __init__(self):
        self.edits = []

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))


class FakeCallback:
    def __init__(self, user_id, data):
        self.from_user = SimpleNamespace(id=user_id)
        self.data = data
        self.message = FakeCallbackMessage()
        self.answers = []

    async def answer(self, text="", **kwargs):
        self.answers.append(text)


class FakeChannelStore:
    def __init__(self, pages=None):
        self.pages = pages or {}
        self.calls = []
        self.packages = {}
        for page in self.pages.values():
            for package in page.items:
                self.packages[int(package["id"])] = dict(package)

    def list_packages_aggregate(
        self, library_ids, package_filter, cursor=None, limit=20
    ):
        self.calls.append((library_ids, package_filter, cursor, limit))
        return self.pages.get(cursor, QueryPage([], None))

    def get_package(self, package_id):
        package = self.packages.get(int(package_id))
        return dict(package) if package is not None else None


class FakeDeliveryService:
    def __init__(self):
        self.enqueue_calls = []

    async def enqueue(self, **kwargs):
        self.enqueue_calls.append(dict(kwargs))
        public_id = f"job-{len(self.enqueue_calls)}"
        return {
            "public_id": public_id,
            "status": "queued",
            "package_id": kwargs["package_id"],
        }, True


def make_package(
    package_id,
    title,
    *,
    status="stable",
    revision=3,
    channel_title="Source",
):
    return {
        "id": package_id,
        "title": title,
        "boundary_status": status,
        "index_revision": revision,
        "channel_title": channel_title,
        "published_at": "2026-07-29T10:00:00",
        "media_count": 2,
        "known_total_size": 1024,
        "unknown_size_count": 0,
    }


def make_store(tmp_path: Path, user_id=200):
    store = ResourceBotStore(tmp_path / "resource_bot.sqlite3")
    store.initialize()
    key = store.create_activation_key(1)
    assert store.redeem_activation_key(key, user_id)
    return store


def make_role(tmp_path, channel_store=None):
    store = make_store(tmp_path)
    bot = FakeBotClient()
    role = ResourceBotRole(
        SimpleNamespace(),
        SimpleNamespace(),
        store,
        channel_store,
        time_func=lambda: 2000,
    )
    role.bot = bot
    role.bot_info = bot.me
    role.delivery_service = FakeDeliveryService()
    return role


def test_admin_create_key_replies_privately_and_revoke_user(tmp_path):
    async def scenario():
        store = make_store(tmp_path)
        client = FakeBotClient()
        commands = ResourceAdminCommands(store)

        await commands.handle_create_key(
            client, FakeMessage(user_id=1, text="/create_resource_key")
        )
        key = client.sent_messages[-1].text.splitlines()[-1]
        assert client.sent_messages[-1].chat_id == 1
        assert store.redeem_activation_key(key, 201)

        await commands.handle_revoke_user(
            client,
            FakeMessage(user_id=1, text="/revoke_resource_user 201"),
        )
        assert not store.is_user_active(201)
        assert "已撤销" in client.sent_messages[-1].text

    run(scenario())


def test_activate_is_private_and_key_redeems_only_once(tmp_path):
    async def scenario():
        store = ResourceBotStore(tmp_path / "resource_bot.sqlite3")
        store.initialize()
        key = store.create_activation_key(1)
        bot = FakeBotClient()
        role = ResourceBotRole(
            SimpleNamespace(),
            SimpleNamespace(),
            store,
            None,
            time_func=lambda: 1000,
        )
        role.bot = bot
        role.bot_info = bot.me

        await role.handle_activate(
            bot,
            FakeMessage(
                user_id=200,
                text=f"/activate {key}",
                chat_type=enums.ChatType.GROUP,
            ),
        )
        assert not store.is_user_active(200)
        assert "私聊" in bot.sent_messages[-1].text

        await role.handle_activate(
            bot, FakeMessage(user_id=200, text=f"/activate {key}")
        )
        assert store.is_user_active(200)
        assert "激活成功" in bot.sent_messages[-1].text

        await role.handle_activate(
            bot, FakeMessage(user_id=201, text=f"/activate {key}")
        )
        assert not store.is_user_active(201)
        assert "无效或已使用" in bot.sent_messages[-1].text

    run(scenario())


def test_status_reports_activation_and_channel(tmp_path):
    async def scenario():
        role = make_role(tmp_path)
        role.store.bind_channel(200, -1001, "Target", "target")

        await role.handle_status(
            role.bot, FakeMessage(user_id=200, text="/status")
        )

        text = role.bot.sent_messages[-1].text
        assert "已激活" in text
        assert "Target" in text

    run(scenario())


def test_bind_event_requires_pending_admin_and_bot_post_permission(tmp_path):
    async def scenario():
        role = make_role(tmp_path)
        await role.handle_bind(role.bot, FakeMessage(text="/bind"))
        assert 200 in role.pending_bind_users

        role.bot.members[(-1001, 200)] = member(enums.ChatMemberStatus.MEMBER)
        role.bot.members[(-1001, 999)] = member(
            enums.ChatMemberStatus.ADMINISTRATOR, can_post=True
        )
        update = SimpleNamespace(
            from_user=SimpleNamespace(id=200),
            chat=SimpleNamespace(
                id=-1001,
                title="Target",
                username="target",
                type=enums.ChatType.CHANNEL,
            ),
            new_chat_member=SimpleNamespace(
                user=SimpleNamespace(id=999),
                status=enums.ChatMemberStatus.ADMINISTRATOR,
                privileges=SimpleNamespace(can_post_messages=True),
            ),
        )

        await role.handle_chat_member_updated(role.bot, update)
        assert role.store.get_binding(200) is None

        role.bot.members[(-1001, 200)] = member(
            enums.ChatMemberStatus.ADMINISTRATOR, can_post=True
        )
        await role.handle_chat_member_updated(role.bot, update)
        assert role.store.get_binding(200)["chat_id"] == -1001

    run(scenario())


def test_bot_permission_loss_marks_binding(tmp_path):
    async def scenario():
        role = make_role(tmp_path)
        role.store.bind_channel(200, -1001, "Target", "target")
        update = SimpleNamespace(
            from_user=SimpleNamespace(id=200),
            chat=SimpleNamespace(
                id=-1001,
                title="Target",
                username="target",
                type=enums.ChatType.CHANNEL,
            ),
            new_chat_member=SimpleNamespace(
                user=SimpleNamespace(id=999),
                status=enums.ChatMemberStatus.ADMINISTRATOR,
                privileges=SimpleNamespace(can_post_messages=False),
            ),
        )

        await role.handle_chat_member_updated(role.bot, update)

        assert role.store.get_binding(200)["status"] == "permission_lost"

    run(scenario())


def test_unbind_marks_binding_unbound(tmp_path):
    async def scenario():
        role = make_role(tmp_path)
        role.store.bind_channel(200, -1001, "Target", "target")

        await role.handle_unbind(
            role.bot, FakeMessage(user_id=200, text="/unbind")
        )

        assert role.store.get_binding(200)["status"] == "unbound"

    run(scenario())


def test_search_only_lists_stable_packages_and_builds_publish_buttons(tmp_path):
    async def scenario():
        store = FakeChannelStore(
            {
                None: QueryPage(
                    [
                        make_package(12, "Stable Course"),
                        make_package(11, "Draft Course", status="provisional"),
                    ],
                    None,
                )
            }
        )
        role = make_role(tmp_path, store)

        await role.handle_search(
            role.bot, FakeMessage(user_id=200, text="/search course")
        )

        sent = role.bot.sent_messages[-1]
        assert "Stable Course" in sent.text
        assert "Draft Course" not in sent.text
        assert "Source" in sent.text
        assert "2026-07-29" in sent.text
        assert "2" in sent.text
        assert "1.0KB" in sent.text
        buttons = sent.reply_markup.inline_keyboard
        assert any(button.callback_data.startswith("rp:") for row in buttons for button in row)
        assert store.calls[-1][3] >= 5

    run(scenario())


def test_search_page_size_is_five_stable_packages(tmp_path):
    async def scenario():
        packages = [make_package(value, f"Course {value}") for value in range(10, 4, -1)]
        store = FakeChannelStore({None: QueryPage(packages, "next")})
        role = make_role(tmp_path, store)

        await role.handle_search(
            role.bot, FakeMessage(user_id=200, text="/search course")
        )

        assert role.bot.sent_messages[-1].text.count("📦") == 5

    run(scenario())


def test_search_session_rejects_other_user_and_expiry(tmp_path):
    async def scenario():
        role = make_role(tmp_path, FakeChannelStore())
        session = role.make_search_session(user_id=200, query="course")

        other = FakeCallback(201, f"rs:{session.token}:next")
        await role.handle_callback(role.bot, other)
        assert other.answers[-1] == "搜索会话不属于当前用户。"

        session.created_at = 0
        expired = FakeCallback(200, f"rs:{session.token}:next")
        await role.handle_callback(role.bot, expired)
        assert expired.answers[-1] == "搜索已过期，请重新搜索。"

    run(scenario())


def test_publish_requires_active_binding(tmp_path):
    async def scenario():
        package = make_package(12, "Course")
        store = FakeChannelStore({None: QueryPage([package], None)})
        role = make_role(tmp_path, store)
        session = role.make_search_session(user_id=200, query="course")
        session.packages[12] = package
        query = FakeCallback(200, f"rp:{session.token}:12")

        await role.handle_callback(role.bot, query)

        assert query.answers[-1] == "请先绑定目标频道。"

    run(scenario())


def test_repeated_publish_callback_returns_same_job(tmp_path):
    async def scenario():
        package = make_package(12, "Course")
        store = FakeChannelStore({None: QueryPage([package], None)})
        role = make_role(tmp_path, store)
        role.store.bind_channel(200, -1001, "Target", "target")
        role.bot.members[(-1001, 999)] = member(
            enums.ChatMemberStatus.ADMINISTRATOR, can_post=True
        )
        session = role.make_search_session(user_id=200, query="course")
        session.packages[12] = package
        first = FakeCallback(200, f"rp:{session.token}:12")
        second = FakeCallback(200, f"rp:{session.token}:12")

        await role.handle_callback(role.bot, first)
        await role.handle_callback(role.bot, second)

        assert len(role.delivery_service.enqueue_calls) == 1
        assert first.answers[-1] == second.answers[-1]
        assert "job-1" in first.answers[-1]

    run(scenario())

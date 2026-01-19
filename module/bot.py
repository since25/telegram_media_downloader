"""Bot for media downloader"""

import asyncio
import os
from datetime import datetime
from typing import Callable, List, Union

import pyrogram
from loguru import logger
from pyrogram import types
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from ruamel import yaml

import utils
from module.app import (
    Application,
    ChatDownloadConfig,
    ForwardStatus,
    QueryHandler,
    QueryHandlerStr,
    TaskNode,
    TaskType,
    UploadStatus,
)
from module.filter import Filter
from module.get_chat_history_v2 import get_chat_history_v2
from module.language import Language, _t
from module.pyrogram_extension import (
    check_user_permission,
    parse_link,
    proc_cache_forward,
    report_bot_forward_status,
    report_bot_status,
    retry,
    set_meta_data,
    upload_telegram_chat_message,
)
from module.download_stat import add_active_task_node, remove_active_task_node
from utils.format import replace_date_time, validate_title
from utils.meta_data import MetaData

# pylint: disable = C0301, R0902


class DownloadBot:
    """Download bot"""

    def __init__(self):
        self.bot = None
        self.client = None
        self.add_download_task: Callable = None
        self.download_chat_task: Callable = None
        self.app = None
        self.listen_forward_chat: dict = {}
        self.config: dict = {}
        self._yaml = yaml.YAML()
        self.config_path = os.path.join(os.path.abspath("."), "bot.yaml")
        self.download_command: dict = {}
        self.filter = Filter()
        self.bot_info = None
        self.task_node: dict = {}
        self.is_running = True
        self.allowed_user_ids: List[Union[int, str]] = []

        meta = MetaData(datetime(2022, 8, 5, 14, 35, 12), 0, "", 0, 0, 0, "", 0)
        self.filter.set_meta_data(meta)

        self.download_filter: List[str] = []
        self.task_id: int = 0
        self.reply_task = None

    def gen_task_id(self) -> int:
        """Gen task id"""
        self.task_id += 1
        return self.task_id

    def add_task_node(self, node: TaskNode):
        """Add task node"""
        self.task_node[node.task_id] = node

    def remove_task_node(self, task_id: int):
        """Remove task node"""
        self.task_node.pop(task_id)

    def stop_task(self, task_id: str):
        """Stop task"""
        if task_id == "all":
            for value in self.task_node.values():
                value.stop_transmission()
        else:
            try:
                task = self.task_node.get(int(task_id))
                if task:
                    task.stop_transmission()
            except Exception:
                return

    async def update_reply_message(self):
        """Update reply message"""
        while self.is_running:
            for key, value in self.task_node.copy().items():
                if value.is_running:
                    await report_bot_status(self.bot, value)

            for key, value in self.task_node.copy().items():
                if value.is_running and value.is_finish():
                    self.remove_task_node(key)
            await asyncio.sleep(3)

    def assign_config(self, _config: dict):
        """assign config from str.

        Parameters
        ----------
        _config: dict
            application config dict

        Returns
        -------
        bool
        """

        self.download_filter = _config.get("download_filter", self.download_filter)

        return True

    def update_config(self):
        """Update config from str."""
        self.config["download_filter"] = self.download_filter

        with open("d", "w", encoding="utf-8") as yaml_file:
            self._yaml.dump(self.config, yaml_file)

    async def start(
        self,
        app: Application,
        client: pyrogram.Client,
        add_download_task: Callable,
        download_chat_task: Callable,
    ):
        """Start bot"""
        self.bot = pyrogram.Client(
            app.application_name + "_bot",
            api_hash=app.api_hash,
            api_id=app.api_id,
            bot_token=app.bot_token,
            workdir=app.session_file_path,
            proxy=app.proxy,
        )

        # 命令列表
        commands = [
            types.BotCommand("help", _t("Help")),
            types.BotCommand(
                "get_info", _t("Get group and user info from message link")
            ),
            types.BotCommand(
                "download",
                _t(
                    "To download the video, use the method to directly enter /download to view"
                ),
            ),
            types.BotCommand(
                "forward",
                _t("Forward video, use the method to directly enter /forward to view"),
            ),
            types.BotCommand(
                "listen_forward",
                _t(
                    "Listen forward, use the method to directly enter /listen_forward to view"
                ),
            ),
            types.BotCommand(
                "add_filter",
                _t(
                    "Add download filter, use the method to directly enter /add_filter to view"
                ),
            ),
            types.BotCommand("set_language", _t("Set language")),
            types.BotCommand("stop", _t("Stop bot download or forward")),
            types.BotCommand(
                "retry_failed",
                _t("Retry failed download tasks with chat_id|message_id pairs"),
            ),
        ]

        self.app = app
        self.client = client
        self.add_download_task = add_download_task
        self.download_chat_task = download_chat_task

        # load config
        if os.path.exists(self.config_path):
            with open(self.config_path, encoding="utf-8") as f:
                config = self._yaml.load(f.read())
                if config:
                    self.config = config
                    self.assign_config(self.config)

        await self.bot.start()

        self.bot_info = await self.bot.get_me()

        for allowed_user_id in self.app.allowed_user_ids:
            try:
                chat = await self.client.get_chat(allowed_user_id)
                self.allowed_user_ids.append(chat.id)
            except Exception as e:
                logger.warning(f"set allowed_user_ids error: {e}")

        admin = await self.client.get_me()
        self.allowed_user_ids.append(admin.id)

        await self.bot.set_bot_commands(commands)

        self.bot.add_handler(
            MessageHandler(
                download_from_bot,
                filters=pyrogram.filters.command(["download"])
                & pyrogram.filters.user(self.allowed_user_ids),
            )
        )
        self.bot.add_handler(
            MessageHandler(
                forward_messages,
                filters=pyrogram.filters.command(["forward"])
                & pyrogram.filters.user(self.allowed_user_ids),
            )
        )
        self.bot.add_handler(
            MessageHandler(
                download_forward_media,
                filters=pyrogram.filters.media
                & pyrogram.filters.user(self.allowed_user_ids),
            )
        )
        self.bot.add_handler(
            MessageHandler(
                download_from_link,
                filters=pyrogram.filters.regex(r"^https://t.me.*")
                & pyrogram.filters.user(self.allowed_user_ids),
            )
        )
        self.bot.add_handler(
            MessageHandler(
                set_listen_forward_msg,
                filters=pyrogram.filters.command(["listen_forward"])
                & pyrogram.filters.user(self.allowed_user_ids),
            )
        )
        self.bot.add_handler(
            MessageHandler(
                help_command,
                filters=pyrogram.filters.command(["help"])
                & pyrogram.filters.user(self.allowed_user_ids),
            )
        )
        self.bot.add_handler(
            MessageHandler(
                get_info,
                filters=pyrogram.filters.command(["get_info"])
                & pyrogram.filters.user(self.allowed_user_ids),
            )
        )
        self.bot.add_handler(
            MessageHandler(
                help_command,
                filters=pyrogram.filters.command(["start"])
                & pyrogram.filters.user(self.allowed_user_ids),
            )
        )
        self.bot.add_handler(
            MessageHandler(
                set_language,
                filters=pyrogram.filters.command(["set_language"])
                & pyrogram.filters.user(self.allowed_user_ids),
            )
        )
        self.bot.add_handler(
            MessageHandler(
                add_filter,
                filters=pyrogram.filters.command(["add_filter"])
                & pyrogram.filters.user(self.allowed_user_ids),
            )
        )

        self.bot.add_handler(
            MessageHandler(
                stop,
                filters=pyrogram.filters.command(["stop"])
                & pyrogram.filters.user(self.allowed_user_ids),
            )
        )
        
        # 添加重试失败任务的命令
        self.bot.add_handler(
            MessageHandler(
                retry_failed_tasks,
                filters=pyrogram.filters.command(["retry_failed"])
                & pyrogram.filters.user(self.allowed_user_ids),
            )
        )

        self.bot.add_handler(
            CallbackQueryHandler(
                on_query_handler, filters=pyrogram.filters.user(self.allowed_user_ids)
            )
        )

        self.client.add_handler(MessageHandler(listen_forward_msg))

        try:
            await send_help_str(self.bot, admin.id)
        except Exception:
            pass

        self.reply_task = _bot.app.loop.create_task(_bot.update_reply_message())

        self.bot.add_handler(
            MessageHandler(
                forward_to_comments,
                filters=pyrogram.filters.command(["forward_to_comments"])
                & pyrogram.filters.user(self.allowed_user_ids),
            )
        )


_bot = DownloadBot()


async def start_download_bot(
    app: Application,
    client: pyrogram.Client,
    add_download_task: Callable,
    download_chat_task: Callable,
):
    """Start download bot"""
    await _bot.start(app, client, add_download_task, download_chat_task)


async def stop_download_bot():
    """Stop download bot"""
    _bot.update_config()
    _bot.is_running = False
    if _bot.reply_task:
        _bot.reply_task.cancel()
    _bot.stop_task("all")
    if _bot.bot:
        await _bot.bot.stop()


async def send_help_str(client: pyrogram.Client, chat_id):
    """
    Sends a help string to the specified chat ID using the provided client.

    Parameters:
        client (pyrogram.Client): The Pyrogram client used to send the message.
        chat_id: The ID of the chat to which the message will be sent.

    Returns:
        str: The help string that was sent.

    Note:
        The help string includes information about the Telegram Media Downloader bot,
        its version, and the available commands.
    """

    update_keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Github",
                    url="https://github.com/tangyoha/telegram_media_downloader/releases",
                ),
                InlineKeyboardButton(
                    "Join us", url="https://t.me/TeegramMediaDownload"
                ),
            ]
        ]
    )
    latest_release_str = ""
    # try:
    #     latest_release = get_latest_release(_bot.app.proxy)

    #     latest_release_str = (
    #         f"{_t('New Version')}: [{latest_release['name']}]({latest_release['html_url']})\an"
    #         if latest_release
    #         else ""
    #     )
    # except Exception:
    #     latest_release_str = ""

    msg = (
        f"`\n🤖 {_t('Telegram Media Downloader')}\n"
        f"🌐 {_t('Version')}: {utils.__version__}`\n"
        f"{latest_release_str}\n"
        f"{_t('Available commands:')}\n"
        f"/help - {_t('Show available commands')}\n"
        f"/get_info - {_t('Get group and user info from message link')}\n"
        f"/download - {_t('Download messages')}\n"
        f"/forward - {_t('Forward messages')}\n"
        f"/listen_forward - {_t('Listen for forwarded messages')}\n"
        f"/forward_to_comments - {_t('Forward a specific media to a comment section')}\n"
        f"/set_language - {_t('Set language')}\n"
        f"/stop - {_t('Stop bot download or forward')}\n\n"
        f"{_t('**Note**: 1 means the start of the entire chat')},"
        f"{_t('0 means the end of the entire chat')}\n"
        f"`[` `]` {_t('means optional, not required')}\n"
    )

    await client.send_message(chat_id, msg, reply_markup=update_keyboard)


async def help_command(client: pyrogram.Client, message: pyrogram.types.Message):
    """
    Sends a message with the available commands and their usage.

    Parameters:
        client (pyrogram.Client): The client instance.
        message (pyrogram.types.Message): The message object.

    Returns:
        None
    """

    await send_help_str(client, message.chat.id)


async def set_language(client: pyrogram.Client, message: pyrogram.types.Message):
    """
    Set the language of the bot.

    Parameters:
        client (pyrogram.Client): The pyrogram client.
        message (pyrogram.types.Message): The message containing the command.

    Returns:
        None
    """

    if len(message.text.split()) != 2:
        await client.send_message(
            message.from_user.id,
            _t("Invalid command format. Please use /set_language en/ru/zh/ua"),
        )
        return

    language = message.text.split()[1]

    try:
        language = Language[language.upper()]
        _bot.app.set_language(language)
        await client.send_message(
            message.from_user.id, f"{_t('Language set to')} {language.name}"
        )
    except KeyError:
        await client.send_message(
            message.from_user.id,
            _t("Invalid command format. Please use /set_language en/ru/zh/ua"),
        )


async def get_info(client: pyrogram.Client, message: pyrogram.types.Message):
    """
    Async function that retrieves information from a group message link.
    """

    msg = _t("Invalid command format. Please use /get_info group_message_link")

    args = message.text.split()
    if len(args) != 2:
        await client.send_message(
            message.from_user.id,
            msg,
        )
        return

    chat_id, message_id, _ = await parse_link(_bot.client, args[1])

    entity = None
    if chat_id:
        entity = await _bot.client.get_chat(chat_id)

    if entity:
        if message_id:
            _message = await retry(_bot.client.get_messages, args=(chat_id, message_id))
            if _message:
                meta_data = MetaData()
                set_meta_data(meta_data, _message)
                msg = (
                    f"`\n"
                    f"{_t('Group/Channel')}\n"
                    f"├─ {_t('id')}: {entity.id}\n"
                    f"├─ {_t('first name')}: {entity.first_name}\n"
                    f"├─ {_t('last name')}: {entity.last_name}\n"
                    f"└─ {_t('name')}: {entity.username}\n"
                    f"{_t('Message')}\n"
                )

                for key, value in meta_data.data().items():
                    if key == "send_name":
                        msg += f"└─ {key}: {value or None}\n"
                    else:
                        msg += f"├─ {key}: {value or None}\n"

                msg += "`"
    await client.send_message(
        message.from_user.id,
        msg,
    )


async def add_filter(client: pyrogram.Client, message: pyrogram.types.Message):
    """
    Set the download filter of the bot.

    Parameters:
        client (pyrogram.Client): The pyrogram client.
        message (pyrogram.types.Message): The message containing the command.

    Returns:
        None
    """

    args = message.text.split(maxsplit=1)
    if len(args) != 2:
        await client.send_message(
            message.from_user.id,
            _t("Invalid command format. Please use /add_filter your filter"),
        )
        return

    filter_str = replace_date_time(args[1])
    res, err = _bot.filter.check_filter(filter_str)
    if res:
        _bot.app.down = args[1]
        await client.send_message(
            message.from_user.id, f"{_t('Add download filter')} : {args[1]}"
        )
    else:
        await client.send_message(
            message.from_user.id, f"{err}\n{_t('Check error, please add again!')}"
        )
    return


async def direct_download(
    download_bot: DownloadBot,
    chat_id: Union[str, int],
    message: pyrogram.types.Message,
    download_message: pyrogram.types.Message,
    client: pyrogram.Client = None,
):
    """Direct Download"""

    replay_message = "Direct download..."
    last_reply_message = await download_bot.bot.send_message(
        message.from_user.id, replay_message, reply_to_message_id=message.id
    )

    node = TaskNode(
        chat_id=chat_id,
        from_user_id=message.from_user.id,
        reply_message_id=last_reply_message.id,
        replay_message=replay_message,
        limit=1,
        bot=download_bot.bot,
        task_id=_bot.gen_task_id(),
    )

    node.client = client

    _bot.add_task_node(node)
    add_active_task_node(node)

    await _bot.add_download_task(
        download_message,
        node,
    )

    node.is_running = True


async def download_forward_media(
    client: pyrogram.Client, message: pyrogram.types.Message
):
    """
    Downloads the media from a forwarded message.

    Parameters:
        client (pyrogram.Client): The client instance.
        message (pyrogram.types.Message): The message object.

    Returns:
        None
    """

    if message.media and getattr(message, message.media.value):
        await direct_download(_bot, message.from_user.id, message, message, client)
        return

    await client.send_message(
        message.from_user.id,
        f"1. {_t('Direct download, directly forward the message to your robot')}\n\n",
        parse_mode=pyrogram.enums.ParseMode.HTML,
    )


async def download_from_link(client: pyrogram.Client, message: pyrogram.types.Message):
    """
    Downloads a single message from a Telegram link.

    Parameters:
        client (pyrogram.Client): The pyrogram client.
        message (pyrogram.types.Message): The message containing the Telegram link.

    Returns:
        None
    """

    if not message.text or not message.text.startswith("https://t.me"):
        return

    msg = (
        f"1. {_t('Directly download a single message')}\n"
        "<i>https://t.me/12000000/1</i>\n\n"
    )

    text = message.text.split()
    if len(text) != 1:
        await client.send_message(
            message.from_user.id, msg, parse_mode=pyrogram.enums.ParseMode.HTML
        )

    chat_id, message_id, _ = await parse_link(_bot.client, text[0])

    entity = None
    if chat_id:
        entity = await _bot.client.get_chat(chat_id)
    if entity:
        if message_id:
            download_message = await retry(
                _bot.client.get_messages, args=(chat_id, message_id)
            )
            if download_message:
                await direct_download(_bot, entity.id, message, download_message)
            else:
                client.send_message(
                    message.from_user.id,
                    f"{_t('From')} {entity.title} {_t('download')} {message_id} {_t('error')}!",
                    reply_to_message_id=message.id,
                )
        return

    await client.send_message(
        message.from_user.id, msg, parse_mode=pyrogram.enums.ParseMode.HTML
    )


# pylint: disable = R0912, R0915,R0914


async def retry_failed_tasks(client: pyrogram.Client, message: pyrogram.types.Message):
    """
    Retries the failed download tasks using the provided chat_id and message_id pairs.
    
    Usage: /retry_failed chat_id|message_id chat_id|message_id ...
    
    Example: /retry_failed -1234567890|1234 -1234567890|5678
    """
    msg = f"""
{_t('Parameter error, please enter according to the reference format')}:

{_t('Retry failed tasks with format')}
<i>/retry_failed chat_id|message_id chat_id|message_id ...</i>

{_t('Example')}:
<i>/retry_failed -1234567890|1234 -1234567890|5678</i>
"""

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await client.send_message(
            message.from_user.id, msg, parse_mode=pyrogram.enums.ParseMode.HTML
        )
        return

    try:
        # 解析所有的 chat_id|message_id 对
        task_pairs = args[1].split()
        tasks_to_retry = []
        
        for pair in task_pairs:
            if '|' not in pair:
                await client.send_message(
                    message.from_user.id, msg, parse_mode=pyrogram.enums.ParseMode.HTML
                )
                return
            chat_id_str, msg_id_str = pair.split('|')
            chat_id = int(chat_id_str)
            message_id = int(msg_id_str)
            tasks_to_retry.append((chat_id, message_id))
        
        # 创建一个新的 TaskNode 来处理这些失败的任务
        if tasks_to_retry:
            # 假设所有任务都来自同一个聊天
            first_chat_id, _ = tasks_to_retry[0]
            entity = await _bot.client.get_chat(first_chat_id)
            chat_title = entity.title if entity else "Unknown chat"
            
            reply_message = f"Retry failed tasks from {chat_title} ({len(tasks_to_retry)} tasks)"
            last_reply_message = await client.send_message(
                message.from_user.id, reply_message, reply_to_message_id=message.id
            )
            
            # 创建一个 TaskNode 用于重试
            node = TaskNode(
                chat_id=first_chat_id,
                from_user_id=message.from_user.id,
                reply_message_id=last_reply_message.id,
                replay_message=reply_message,
                bot=_bot.bot,
                task_id=_bot.gen_task_id(),
            )
            
            _bot.add_task_node(node)
            add_active_task_node(node)
            
            # 启动下载任务
            node.is_running = True
            
            # 为每个失败的任务创建一个下载任务
            for chat_id, msg_id in tasks_to_retry:
                try:
                    download_message = await retry(
                        _bot.client.get_messages, args=(chat_id, msg_id)
                    )
                    if download_message:
                        # 添加到下载任务队列
                        await _bot.add_download_task(download_message, node)
                    else:
                        logger.warning(f"Failed to get message {msg_id} from chat {chat_id}")
                except Exception as e:
                    logger.error(f"Error getting message {msg_id} from chat {chat_id}: {e}")
            
            # 设置任务完成条件
            node.total_task = len(tasks_to_retry)
            
            await client.edit_message_text(
                message.from_user.id,
                last_reply_message.id,
                f"{reply_message}\nTasks added to download queue!"
            )
            
    except Exception as e:
        logger.error(f"Error in retry_failed_tasks: {e}")
        await client.send_message(
            message.from_user.id,
            f"{_t('Error processing retry request')}: {e}",
            reply_to_message_id=message.id
        )


async def download_from_bot(client: pyrogram.Client, message: pyrogram.types.Message):
    """Download from bot"""

    msg = (
        f"{_t('Parameter error, please enter according to the reference format')}:\n\n"
        f"1. {_t('Download all messages of common group')}\n"
        "<i>/download https://t.me/fkdhlg 1 0</i>\n\n"
        f"{_t('The private group (channel) link is a random group message link')}\n\n"
        f"2. {_t('The download starts from the N message to the end of the M message')}. "
        f"{_t('When M is 0, it means the last message. The filter is optional')}\n"
        f"<i>/download https://t.me/12000000 N M [filter]</i>\n\n"
    )

    args = message.text.split(maxsplit=5)
    if not message.text or len(args) < 3:
        await client.send_message(
            message.from_user.id, msg, parse_mode=pyrogram.enums.ParseMode.HTML
        )
        return

    url = args[1]
    try:
        # 解析URL获取基础信息
        from utils.format import extract_info_from_link
        link_info = extract_info_from_link(url)
        
        # 检查是否是评论下载
        is_comment_range_download = "comment=" in url and len(args) >= 4
        if link_info.comment_id is not None or is_comment_range_download:
            # 评论下载模式
            start_comment_id = None
            end_comment_id = None
            download_filter = None
            is_single_comment = False
            
            # 解析标签参数（最后一个参数，如果存在且不是数字，则视为标签）
            file_name_tag = None
            if link_info.comment_id is not None:
                # 单条评论下载
                logger.info(f"单条评论下载: comment_id={link_info.comment_id}, post_id={link_info.post_id}")
                start_comment_id = link_info.comment_id
                end_comment_id = link_info.comment_id
                # args[2] 可能是 download_filter 或 file_name_tag
                if len(args) > 2:
                    # 如果 args[2] 不是纯数字，则视为标签
                    if not args[2].isdigit():
                        file_name_tag = args[2]
                    else:
                        download_filter = args[2]
                # args[3] 可能是标签
                if len(args) > 3 and not args[3].isdigit():
                    file_name_tag = args[3]
                is_single_comment = True
            elif is_comment_range_download:
                # 评论范围下载: /download https://t.me/xxx?comment= 724 744 [标签]
                logger.info(f"评论范围下载: args={args}")
                start_comment_id = int(args[2])
                end_comment_id = int(args[3])
                # args[4] 可能是 download_filter 或 file_name_tag
                if len(args) > 4:
                    # 如果 args[4] 不是纯数字，则视为标签
                    if not args[4].isdigit():
                        file_name_tag = args[4]
                    else:
                        download_filter = args[4]
                # args[5] 可能是标签
                if len(args) > 5 and not args[5].isdigit():
                    file_name_tag = args[5]
                is_single_comment = False
            
            # 处理评论下载逻辑
            try:
                # 获取基础消息
                base_message_id = link_info.post_id
                if not base_message_id:
                    # 如果URL中没有消息ID，尝试从URL路径中提取
                    if "/" in url and "?" in url:
                        path_part = url.split("?")[0]
                        parts = path_part.split("/")
                        if len(parts) >= 3:
                            base_message_id = int(parts[-1])
                
                logger.info(f"处理评论下载: base_message_id={base_message_id}, chat_id={link_info.group_id}")
                
                if not base_message_id:
                    await client.send_message(
                        message.from_user.id,
                        f"{_t('Invalid comment URL format, please include the base message ID')}",
                        reply_to_message_id=message.id
                    )
                    return
                
                chat_id, _, _ = await parse_link(_bot.client, url)
                logger.info(f"解析链接结果: chat_id={chat_id}")
                
                if not chat_id:
                    await client.send_message(
                        message.from_user.id,
                        f"{_t('Invalid chat link')}",
                        reply_to_message_id=message.id
                    )
                    return
                
                entity = await _bot.client.get_chat(chat_id)
                logger.info(f"获取聊天实体: id={entity.id if entity else None}, title={entity.title if entity else None}")
                
                if not entity:
                    await client.send_message(
                        message.from_user.id,
                        f"{_t('Chat not found')}",
                        reply_to_message_id=message.id
                    )
                    return
                
                # 构建下载任务
                chat_title = entity.title
                reply_message = f"from {chat_title} "
                if is_single_comment:
                    reply_message += f"download comment id = {start_comment_id} for message {base_message_id} !"
                else:
                    reply_message += f"download comment id = {start_comment_id} - {end_comment_id} for message {base_message_id} !"
                last_reply_message = await client.send_message(
                    message.from_user.id, reply_message, reply_to_message_id=message.id
                )
                
                # 创建评论下载任务
                node = TaskNode(
                    chat_id=entity.id,
                    from_user_id=message.from_user.id,
                    reply_message_id=last_reply_message.id,
                    replay_message=reply_message,
                    bot=_bot.bot,
                    task_id=_bot.gen_task_id(),
                )
                
                # 设置文件名标签
                # 如果用户没有手动提供标签，尝试从原始消息获取标题
                if not file_name_tag:
                    try:
                        # 获取原始消息（基础消息）
                        base_message = await _bot.client.get_messages(entity.id, base_message_id)
                        if base_message and base_message.text:
                            # 使用消息文本的前30个字符作为标签
                            from utils.format import validate_title
                            file_name_tag = validate_title(base_message.text[:30])
                            logger.info(f"从原始消息获取标签: {file_name_tag}")
                        elif base_message and base_message.caption:
                            # 如果没有文本，使用caption
                            from utils.format import validate_title
                            file_name_tag = validate_title(base_message.caption[:30])
                            logger.info(f"从原始消息caption获取标签: {file_name_tag}")
                    except Exception as e:
                        logger.warning(f"获取原始消息标题失败: {e}")
                
                # 设置标签到node
                if file_name_tag:
                    node.file_name_tag = file_name_tag
                    logger.info(f"设置文件名标签: {file_name_tag}")
                
                _bot.add_task_node(node)
                add_active_task_node(node)
                
                # 设置任务为运行状态
                node.is_running = True
                
                # 获取并下载评论
                # 局部导入避免循环导入
                from media_downloader import download_comments
                _bot.app.loop.create_task(
                    download_comments(_bot.client, entity.id, base_message_id, start_comment_id, end_comment_id, download_filter, node)
                )
                return
            except Exception as e:
                await client.send_message(
                    message.from_user.id,
                    f"{_t('Comment download error')}: {e}",
                    reply_to_message_id=message.id
                )
                return
        
        # 普通消息下载模式
        if len(args) < 4:
            await client.send_message(
                message.from_user.id, msg, parse_mode=pyrogram.enums.ParseMode.HTML
            )
            return
        
        start_offset_id = int(args[2])
        end_offset_id = int(args[3])
        download_filter = args[4] if len(args) > 4 else None
    except Exception:
        await client.send_message(
            message.from_user.id, msg, parse_mode=pyrogram.enums.ParseMode.HTML
        )
        return

    limit = 0
    if end_offset_id:
        if end_offset_id < start_offset_id:
            raise ValueError(
                f"end_offset_id < start_offset_id, {end_offset_id} < {start_offset_id}"
            )

        limit = end_offset_id - start_offset_id + 1

    if download_filter:
        download_filter = replace_date_time(download_filter)
        res, err = _bot.filter.check_filter(download_filter)
        if not res:
            await client.send_message(
                message.from_user.id, err, reply_to_message_id=message.id
            )
            return
    try:
        chat_id, _, _ = await parse_link(_bot.client, url)
        if chat_id:
            entity = await _bot.client.get_chat(chat_id)
        if entity:
            chat_title = entity.title
            reply_message = f"from {chat_title} "
            chat_download_config = ChatDownloadConfig()
            chat_download_config.last_read_message_id = start_offset_id
            chat_download_config.download_filter = download_filter
            reply_message += (
                f"download message id = {start_offset_id} - {end_offset_id} !"
            )
            last_reply_message = await client.send_message(
                message.from_user.id, reply_message, reply_to_message_id=message.id
            )
            node = TaskNode(
                chat_id=entity.id,
                from_user_id=message.from_user.id,
                reply_message_id=last_reply_message.id,
                replay_message=reply_message,
                limit=limit,
                start_offset_id=start_offset_id,
                end_offset_id=end_offset_id,
                bot=_bot.bot,
                task_id=_bot.gen_task_id(),
            )
            _bot.add_task_node(node)
            add_active_task_node(node)
            _bot.app.loop.create_task(
                _bot.download_chat_task(_bot.client, chat_download_config, node)
            )
    except Exception as e:
        await client.send_message(
            message.from_user.id,
            f"{_t('chat input error, please enter the channel or group link')}\n\n"
            f"{_t('Error type')}: {e.__class__}"
            f"{_t('Exception message')}: {e}",
        )
        return


async def get_forward_task_node(
    client: pyrogram.Client,
    message: pyrogram.types.Message,
    task_type: TaskType,
    src_chat_link: str,
    dst_chat_link: str,
    offset_id: int = 0,
    end_offset_id: int = 0,
    download_filter: str = None,
    reply_comment: bool = False,
):
    """Get task node"""
    limit: int = 0

    if end_offset_id:
        if end_offset_id < offset_id:
            await client.send_message(
                message.from_user.id,
                f" end_offset_id({end_offset_id}) < start_offset_id({offset_id}),"
                f" end_offset_id{_t('must be greater than')} offset_id",
            )
            return None

        limit = end_offset_id - offset_id + 1

    src_chat_id, _, _ = await parse_link(_bot.client, src_chat_link)
    dst_chat_id, target_msg_id, topic_id = await parse_link(_bot.client, dst_chat_link)

    if not src_chat_id or not dst_chat_id:
        logger.info(f"{src_chat_id} {dst_chat_id}")
        await client.send_message(
            message.from_user.id,
            _t("Invalid chat link") + f"{src_chat_id} {dst_chat_id}",
            reply_to_message_id=message.id,
        )
        return None

    try:
        src_chat = await _bot.client.get_chat(src_chat_id)
        dst_chat = await _bot.client.get_chat(dst_chat_id)
    except Exception as e:
        await client.send_message(
            message.from_user.id,
            f"{_t('Invalid chat link')} {e}",
            reply_to_message_id=message.id,
        )
        logger.exception(f"get chat error: {e}")
        return None

    me = await client.get_me()
    if dst_chat.id == me.id:
        # TODO: when bot receive message judge if download
        await client.send_message(
            message.from_user.id,
            _t("Cannot be forwarded to this bot, will cause an infinite loop"),
            reply_to_message_id=message.id,
        )
        return None

    if download_filter:
        download_filter = replace_date_time(download_filter)
        res, err = _bot.filter.check_filter(download_filter)
        if not res:
            await client.send_message(
                message.from_user.id, err, reply_to_message_id=message.id
            )

    last_reply_message = await client.send_message(
        message.from_user.id,
        "Forwarding message, please wait...",
        reply_to_message_id=message.id,
    )

    node = TaskNode(
        chat_id=src_chat.id,
        from_user_id=message.from_user.id,
        upload_telegram_chat_id=dst_chat_id,
        reply_message_id=last_reply_message.id,
        replay_message=last_reply_message.text,
        has_protected_content=src_chat.has_protected_content,
        download_filter=download_filter,
        limit=limit,
        start_offset_id=offset_id,
        end_offset_id=end_offset_id,
        bot=_bot.bot,
        task_id=_bot.gen_task_id(),
        task_type=task_type,
        topic_id=topic_id,
    )

    if target_msg_id and reply_comment:
        node.reply_to_message = await _bot.client.get_discussion_message(
            dst_chat_id, target_msg_id
        )

    _bot.add_task_node(node)
    add_active_task_node(node)

    node.upload_user = _bot.client
    if not dst_chat.type is pyrogram.enums.ChatType.BOT:
        has_permission = await check_user_permission(_bot.client, me.id, dst_chat.id)
        if has_permission:
            node.upload_user = _bot.bot

    if node.upload_user is _bot.client:
        await client.edit_message_text(
            message.from_user.id,
            last_reply_message.id,
            "Note that the robot may not be in the target group,"
            " use the user account to forward",
        )

    return node


# pylint: disable = R0914
async def forward_message_impl(
    client: pyrogram.Client, message: pyrogram.types.Message, reply_comment: bool
):
    """
    Forward message
    """

    async def report_error(client: pyrogram.Client, message: pyrogram.types.Message):
        """Report error"""

        await client.send_message(
            message.from_user.id,
            f"{_t('Invalid command format')}."
            f"{_t('Please use')} "
            "/forward https://t.me/c/src_chat https://t.me/c/dst_chat "
            f"1 400 `[`{_t('Filter')}`]`\n",
        )

    args = message.text.split(maxsplit=5)
    if len(args) < 5:
        await report_error(client, message)
        return

    src_chat_link = args[1]
    dst_chat_link = args[2]

    try:
        offset_id = int(args[3])
        end_offset_id = int(args[4])
    except Exception:
        await report_error(client, message)
        return

    download_filter = args[5] if len(args) > 5 else None

    node = await get_forward_task_node(
        client,
        message,
        TaskType.Forward,
        src_chat_link,
        dst_chat_link,
        offset_id,
        end_offset_id,
        download_filter,
        reply_comment,
    )

    if not node:
        return

    if not node.has_protected_content:
        try:
            async for item in get_chat_history_v2(  # type: ignore
                _bot.client,
                node.chat_id,
                limit=node.limit,
                max_id=node.end_offset_id,
                offset_id=offset_id,
                reverse=True,
            ):
                await forward_normal_content(client, node, item)
                if node.is_stop_transmission:
                    await client.edit_message_text(
                        message.from_user.id,
                        node.reply_message_id,
                        f"{_t('Stop Forward')}",
                    )
                    break
        except Exception as e:
            await client.edit_message_text(
                message.from_user.id,
                node.reply_message_id,
                f"{_t('Error forwarding message')} {e}",
            )
        finally:
            await report_bot_status(client, node, immediate_reply=True)
            node.stop_transmission()
    else:
        await forward_msg(node, offset_id)


async def forward_messages(client: pyrogram.Client, message: pyrogram.types.Message):
    """
    Forwards messages from one chat to another.

    Parameters:
        client (pyrogram.Client): The pyrogram client.
        message (pyrogram.types.Message): The message containing the command.

    Returns:
        None
    """
    return await forward_message_impl(client, message, False)


async def forward_normal_content(
    client: pyrogram.Client, node: TaskNode, message: pyrogram.types.Message
):
    """Forward normal content"""
    forward_ret = ForwardStatus.FailedForward
    if node.download_filter:
        meta_data = MetaData()
        caption = message.caption
        if caption:
            caption = validate_title(caption)
            _bot.app.set_caption_name(node.chat_id, message.media_group_id, caption)
        else:
            caption = _bot.app.get_caption_name(node.chat_id, message.media_group_id)
        set_meta_data(meta_data, message, caption)
        _bot.filter.set_meta_data(meta_data)
        if not _bot.filter.exec(node.download_filter):
            forward_ret = ForwardStatus.SkipForward
            if message.media_group_id:
                node.upload_status[message.id] = UploadStatus.SkipUpload
                await proc_cache_forward(_bot.client, node, message, False)
            await report_bot_forward_status(client, node, forward_ret)
            return

    await upload_telegram_chat_message(
        _bot.client, node.upload_user, _bot.app, node, message
    )


async def forward_msg(node: TaskNode, message_id: int):
    """Forward normal message"""

    chat_download_config = ChatDownloadConfig()
    chat_download_config.last_read_message_id = message_id
    chat_download_config.download_filter = node.download_filter  # type: ignore

    await _bot.download_chat_task(_bot.client, chat_download_config, node)


async def set_listen_forward_msg(
    client: pyrogram.Client, message: pyrogram.types.Message
):
    """
    Set the chat to listen for forwarded messages.

    Args:
        client (pyrogram.Client): The pyrogram client.
        message (pyrogram.types.Message): The message sent by the user.

    Returns:
        None
    """
    args = message.text.split(maxsplit=3)

    if len(args) < 3:
        await client.send_message(
            message.from_user.id,
            f"{_t('Invalid command format')}. {_t('Please use')} /listen_forward "
            f"https://t.me/c/src_chat https://t.me/c/dst_chat [{_t('Filter')}]\n",
        )
        return

    src_chat_link = args[1]
    dst_chat_link = args[2]

    download_filter = args[3] if len(args) > 3 else None

    node = await get_forward_task_node(
        client,
        message,
        TaskType.ListenForward,
        src_chat_link,
        dst_chat_link,
        download_filter=download_filter,
    )

    if not node:
        return

    if node.chat_id in _bot.listen_forward_chat:
        _bot.remove_task_node(_bot.listen_forward_chat[node.chat_id].task_id)

    node.is_running = True
    _bot.listen_forward_chat[node.chat_id] = node


async def listen_forward_msg(client: pyrogram.Client, message: pyrogram.types.Message):
    """
    Forwards messages from a chat to another chat if the message does not contain protected content.
    If the message contains protected content, it will be downloaded and forwarded to the other chat.

    Parameters:
        client (pyrogram.Client): The pyrogram client.
        message (pyrogram.types.Message): The message to be forwarded.
    """

    if message.chat and message.chat.id in _bot.listen_forward_chat:
        node = _bot.listen_forward_chat[message.chat.id]

        # TODO(tangyoha):fix run time change protected content
        if not node.has_protected_content:
            await forward_normal_content(client, node, message)
            await report_bot_status(client, node, immediate_reply=True)
        else:
            await _bot.add_download_task(
                message,
                node,
            )


async def stop(client: pyrogram.Client, message: pyrogram.types.Message):
    """Stops listening for forwarded messages."""

    await client.send_message(
        message.chat.id,
        _t("Please select:"),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        _t("Stop Download"), callback_data="stop_download"
                    ),
                    InlineKeyboardButton(
                        _t("Stop Forward"), callback_data="stop_forward"
                    ),
                ],
                [  # Second row
                    InlineKeyboardButton(
                        _t("Stop Listen Forward"), callback_data="stop_listen_forward"
                    )
                ],
            ]
        ),
    )


async def stop_task(
    client: pyrogram.Client,
    query: pyrogram.types.CallbackQuery,
    queryHandler: str,
    task_type: TaskType,
):
    """Stop task"""
    if query.data == queryHandler:
        buttons: List[InlineKeyboardButton] = []
        temp_buttons: List[InlineKeyboardButton] = []
        for key, value in _bot.task_node.copy().items():
            if not value.is_finish() and value.task_type is task_type:
                if len(temp_buttons) == 3:
                    buttons.append(temp_buttons)
                    temp_buttons = []
                temp_buttons.append(
                    InlineKeyboardButton(
                        f"{key}", callback_data=f"{queryHandler} task {key}"
                    )
                )
        if temp_buttons:
            buttons.append(temp_buttons)

        if buttons:
            buttons.insert(
                0,
                [
                    InlineKeyboardButton(
                        _t("all"), callback_data=f"{queryHandler} task all"
                    )
                ],
            )
            await client.edit_message_text(
                query.message.from_user.id,
                query.message.id,
                f"{_t('Stop')} {_t(task_type.name)}...",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
        else:
            await client.edit_message_text(
                query.message.from_user.id,
                query.message.id,
                f"{_t('No Task')}",
            )
    else:
        task_id = query.data.split(" ")[2]
        await client.edit_message_text(
            query.message.from_user.id,
            query.message.id,
            f"{_t('Stop')} {_t(task_type.name)}...",
        )
        _bot.stop_task(task_id)


async def on_query_handler(
    client: pyrogram.Client, query: pyrogram.types.CallbackQuery
):
    """
    Asynchronous function that handles query callbacks.

    Parameters:
        client (pyrogram.Client): The Pyrogram client object.
        query (pyrogram.types.CallbackQuery): The callback query object.

    Returns:
        None
    """

    for it in QueryHandler:
        queryHandler = QueryHandlerStr.get_str(it.value)
        if queryHandler in query.data:
            await stop_task(client, query, queryHandler, TaskType(it.value))


async def forward_to_comments(client: pyrogram.Client, message: pyrogram.types.Message):
    """
    Forwards specified media to a designated comment section.

    Usage: /forward_to_comments <source_chat_link> <destination_chat_link> <msg_start_id> <msg_end_id>

    Parameters:
        client (pyrogram.Client): The pyrogram client.
        message (pyrogram.types.Message): The message containing the command.
    """
    return await forward_message_impl(client, message, True)

import os
import asyncio
import random
import time
from collections import defaultdict
from datetime import datetime

from telethon import events
from telethon.tl import functions
from telethon.tl.functions.messages import SendReactionRequest, ImportChatInviteRequest, SendVoteRequest, \
    GetMessagesViewsRequest
from telethon.tl.types import ReactionEmoji
from telethon.errors import (
    FloodWaitError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    SessionPasswordNeededError,
    UserDeactivatedError,
    AuthKeyDuplicatedError,
    PhoneNumberBannedError, UserNotParticipantError,
)

from config import REACTION_DELAY_MIN, REACTION_DELAY_MAX, MAX_COMMENTING_ACCOUNTS, FREE_REACTIONS, COMMENT_DELAY_MIN, \
    COMMENT_DELAY_MAX, DB_FILE, GLOBAL_RATE_LIMIT, VIEW_ACCOUNTS_MIN, VIEW_ACCOUNTS_MAX, COMMENT_COUNT
from utils import logger, normalize_chat_id, normalize_emoji, get_single_proxy, generate_comments_binary_options
from telegram_client import get_client, client_connection_lock, view_post, test_proxy
from database import with_db_connection, get_comments, get_settings
from telethon.utils import get_peer_id as make_peer

class AutoManager:
    def __init__(self):
        self.clients = {}
        self.reaction_queue = asyncio.Queue()
        self.comment_queue = asyncio.Queue()
        self.poll_queue = asyncio.Queue()
        self.view_queue = asyncio.Queue()
        self.global_rate_semaphore = asyncio.Semaphore(GLOBAL_RATE_LIMIT)
        self.processed_messages = set()
        self.tasks = {}
        self.message_lock = asyncio.Lock()
        self.running = True
        self._view_cache = set()  # (account_id, msg_id)
        self._album_cache = {}  # grouped_id -> (root_msg_id, timestamp)
        self.comment_usage = {}  # {chat_id: count}
        self.used_comments = set()  # {(chat_id, "comment text")}

    async def start_clients(self):
        from telethon.errors import RPCError
        self.processed_messages.clear()

        # Отримуємо всі акаунти, які не заблоковані
        accounts = await with_db_connection(
            "SELECT id, session_path, proxy FROM accounts WHERE banned IS NULL OR banned = 0", fetchall=True)
        logger.info(f"Starting {len(accounts)} non-banned clients")

        if not accounts:
            logger.warning("No non-banned accounts found in database to start.")
            return

        for account_id, session_path, proxy_str in accounts:
            # Якщо сесія не існує, видаляємо акаунт та підписки з бази даних
            if not os.path.exists(session_path):
                logger.warning(f"Session file {session_path} for account {account_id} does not exist")
                await with_db_connection("DELETE FROM accounts WHERE id = ?", (account_id,))
                await with_db_connection("DELETE FROM subscriptions WHERE account_id = ?", (account_id,))
                logger.info(f"Deleted account {account_id} and its subscriptions due to missing session file")
                continue

            # Призначаємо проксі для акаунта
            proxy = get_single_proxy(account_id)
            if proxy and not await test_proxy(proxy):
                logger.error(f"Proxy {proxy} for account {account_id} is not working. Skipping.")
                continue

            # Блокуємо доступ до клієнтів під час підключення
            async with client_connection_lock:  # Блокування доступу до клієнта
                try:
                    # Отримуємо клієнта з бази даних та перевіряємо, чи він успішно підключений
                    client = await get_client(session_path, account_id, proxy)
                    if client:
                        # Якщо клієнт успішно підключений, зберігаємо його в словнику клієнтів
                        self.clients[account_id] = client
                        await self.update_event_handlers(account_id)

                        # Якщо задачі ще не створені, створюємо їх
                        if not self.tasks:
                            self.tasks["reaction_processor"] = asyncio.create_task(self.process_reactions())
                            self.tasks["comment_processor"] = asyncio.create_task(self.process_comments())
                            self.tasks["poll_processor"] = asyncio.create_task(self.process_polls())
                            self.tasks["view_processor"] = asyncio.create_task(self.process_views())

                        logger.info(f"Started client for account {account_id} successfully")
                        await asyncio.sleep(2)
                    else:
                        # Якщо клієнт не підключений, видаляємо акаунт і його підписки з бази
                        logger.warning(f"Failed to start client for account {account_id}")
                        await with_db_connection("DELETE FROM accounts WHERE id = ?", (account_id,))
                        await with_db_connection("DELETE FROM subscriptions WHERE account_id = ?", (account_id,))
                        logger.info(f"Deleted account {account_id} and its subscriptions due to failed initialization")
                except (UserDeactivatedError, AuthKeyDuplicatedError, PhoneNumberBannedError, RPCError) as e:
                    # Якщо клієнт заблокований або виникла інша помилка
                    if isinstance(e, RPCError) and (
                            "FROZEN_METHOD_INVALID" in str(e) or "FROZEN_PARTICIPANT_MISSING" in str(e)):
                        logger.warning(
                            f"Account {account_id} is restricted: {str(e)}. Deleting account and subscriptions.")
                        await with_db_connection("DELETE FROM accounts WHERE id = ?", (account_id,))
                        await with_db_connection("DELETE FROM subscriptions WHERE account_id = ?", (account_id,))
                        logger.info(f"Deleted account {account_id} and its subscriptions due to {str(e)}")
                    else:
                        logger.warning(f"Account {account_id} is banned: {str(e)}. Deleting account and subscriptions.")
                        await with_db_connection("DELETE FROM accounts WHERE id = ?", (account_id,))
                        await with_db_connection("DELETE FROM subscriptions WHERE account_id = ?", (account_id,))
                        logger.info(f"Deleted account {account_id} and its subscriptions due to {str(e)}")

                    # Відключаємо клієнта, якщо він був підключений
                    if 'client' in locals() and client and client.is_connected():
                        await client.disconnect()

            # Після обробки всіх акаунтів виводимо загальний статус
        logger.info(f"Completed starting clients. Active clients: {len(self.clients)}")

    # async def update_event_handlers(self, account_id=None):
    #     if account_id:
    #         clients = {account_id: self.clients[account_id]}
    #     else:
    #         clients = self.clients
    #     auto_reaction_chats = {int(chat_id[0]) for chat_id in
    #                           await with_db_connection("SELECT chat_id FROM auto_reactions", fetchall=True)}
    #     auto_comment_chats = {int(chat_id[0]) for chat_id in
    #                          await with_db_connection("SELECT chat_id FROM auto_comments", fetchall=True)}
    #
    #
    #     auto_poll_chats = set()  # Add if needed
    #     all_auto_chats = auto_reaction_chats.union(auto_comment_chats).union(auto_poll_chats)
    #     for acc_id, client in clients.items():
    #         if client.is_connected():
    #             client.remove_event_handler(self.handle_new_message)
    #             client.add_event_handler(self.handle_new_message, events.NewMessage(incoming=True, chats=all_auto_chats))
    #             logger.info(f"Updated event handler for account {acc_id} with {len(all_auto_chats)} chats")

    async def update_event_handlers(self, account_id=None):
        if account_id:
            clients = {account_id: self.clients.get(account_id)}
        else:
            clients = self.clients
        auto_reaction_chats = {int(row[0]) for row in
                               await with_db_connection("SELECT chat_id FROM auto_reactions", fetchall=True)}
        auto_comment_chats = {int(row[0]) for row in
                              await with_db_connection("SELECT chat_id FROM auto_comments", fetchall=True)}

        all_auto_chats = {
            int(f"-100{chat_id}") if not str(chat_id).startswith("-100") else int(chat_id)
            for chat_id in auto_reaction_chats.union(auto_comment_chats)
        }
        for acc_id, client in clients.items():
            if client and client.is_connected():
                try:
                    client.remove_event_handler(self.handle_new_message)
                except Exception:
                    pass
                if all_auto_chats:
                    client.add_event_handler(
                        self.handle_new_message,
                        events.NewMessage(incoming=True, chats=list(all_auto_chats))
                    )
                    logger.info(f"Updated event handler for account {acc_id} with chats: {list(all_auto_chats)}")
                else:
                    logger.info(f"No auto chats to track for account {acc_id}")

    async def subscribe_account(self, account_id, chat_input, target_channel_id):
        client = self.clients.get(account_id)
        if not client or not client.is_connected():
            logger.error(f"No active client for account {account_id}")
            return account_id, False, "Client not active"

        existing_sub = await with_db_connection(
            "SELECT chat_id FROM subscriptions WHERE account_id = ? AND chat_id = ?",
            (account_id, target_channel_id),
        )
        if existing_sub:
            logger.info(f"Account {account_id} is already subscribed to channel {target_channel_id}")
            return account_id, False, "Already subscribed"

        try:
            logger.info(f"Attempting to join {chat_input} (target ID: {target_channel_id}) for account {account_id}")
            # Robust invite link parsing
            invite_hash = chat_input.split('/')[-1].lstrip('+').strip()
            if not invite_hash:
                logger.error(f"Invalid invite link format: {chat_input}")
                return account_id, False, "Invalid invite link format"

            # Correct Telethon call
            await client(ImportChatInviteRequest(hash=invite_hash))
            logger.info(f"ImportChatInviteRequest sent for {invite_hash}")
            await asyncio.sleep(5)  # Allow Telegram to process

            # Check dialogs
            dialogs = await client.get_dialogs()
            chat_id = None
            chat_title = None
            chat_type = None
            for dialog in dialogs:
                if dialog.entity.id == abs(int(target_channel_id)):
                    chat_id = normalize_chat_id(dialog.entity.id)
                    chat_title = dialog.entity.title
                    chat_type = "channel" if dialog.is_channel else "group"
                    break

            if chat_id:
                logger.info(f"Successfully joined {chat_type} {chat_title} (ID: {chat_id}) for account {account_id}")
                await with_db_connection(
                    "INSERT OR IGNORE INTO subscriptions (account_id, chat_id, chat_title, chat_type) VALUES (?, ?, ?, ?)",
                    (account_id, chat_id, chat_title, chat_type),
                )
                await with_db_connection(
                    "INSERT INTO history (account_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                    (account_id, "add_subscription", f"Added {chat_title} ({chat_id}) via {chat_input}",
                     datetime.now().isoformat()),
                )
                # Update event handlers to include new chat
                await self.update_event_handlers(account_id)
                return account_id, True, "Success"
            else:
                logger.info(f"Channel {target_channel_id} not in dialogs, retrying entity fetch")
                try:
                    entity = await client.get_entity(int(f"-100{target_channel_id}"))
                    chat_id = normalize_chat_id(entity.id)
                    chat_title = entity.title
                    chat_type = "channel" if hasattr(entity, "broadcast") and entity.broadcast else "group"
                    logger.info(f"Entity fetch succeeded: {chat_title} (ID: {chat_id})")
                    await with_db_connection(
                        "INSERT OR IGNORE INTO subscriptions (account_id, chat_id, chat_title, chat_type) VALUES (?, ?, ?, ?)",
                        (account_id, chat_id, chat_title, chat_type),
                    )
                    await with_db_connection(
                        "INSERT INTO history (account_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                        (account_id, "add_subscription", f"Added {chat_title} ({chat_id}) via entity fetch",
                         datetime.now().isoformat()),
                    )
                    # Update event handlers
                    await self.update_event_handlers(account_id)
                    return account_id, True, "Success via entity fetch"
                except Exception as retry_e:
                    logger.error(f"Entity fetch failed for {target_channel_id}: {str(retry_e)}")
                    return account_id, False, f"Failed after retry: {str(retry_e)}"

        except InviteHashExpiredError as e:
            logger.error(f"Invite link expired for {chat_input}: {str(e)}")
            return account_id, False, f"Invite link expired: {str(e)}"
        except InviteHashInvalidError as e:
            logger.error(f"Invalid invite link for {chat_input}: {str(e)}")
            return account_id, False, f"Invalid invite link: {str(e)}"
        except FloodWaitError as e:
            logger.warning(f"Flood wait for account {account_id}: {e.seconds}s")
            await asyncio.sleep(e.seconds)
            # Retry once after flood wait
            return await self.subscribe_account(account_id, chat_input, target_channel_id)
        except Exception as e:
            logger.error(f"Failed to subscribe account {account_id} to {chat_input}: {str(e)}")
            return account_id, False, str(e)

    async def process_reactions(self):
        while self.running:
            account_id, chat_id, msg_id, reaction = await self.reaction_queue.get()
            await self._process_action(account_id, chat_id, msg_id, "reaction", reaction)

    # async def process_comments(self):
    #     while self.running:
    #         account_id, chat_id, msg_id, comment = await self.comment_queue.get()
    #         await self._process_action(account_id, chat_id, msg_id, "comment", comment)

    async def process_comments(self):
        next_available_time = defaultdict(lambda: 0)

        while self.running:
            try:
                account_id, chat_id, msg_id, comment, delay = await self.comment_queue.get()
                key = (chat_id, msg_id)
                start_time = max(
                    asyncio.get_event_loop().time() + delay,
                    next_available_time[key]
                )

                async def delayed_comment(account_id, chat_id, msg_id, comment, start_time, key):
                    try:
                        now = asyncio.get_event_loop().time()
                        wait_time = max(0, start_time - now)
                        if wait_time > 0:
                            logger.info(
                                f"Delaying comment for {wait_time:.2f}s acc={account_id} chat={chat_id} msg={msg_id}"
                            )
                            await asyncio.sleep(wait_time)

                        client = self.clients.get(account_id)

                        # Якщо клієнт не знайдений або не підключений, пробуємо реконектити
                        if not client or not client.is_connected():
                            logger.warning(f"Account {account_id} not connected. Attempting to reconnect.")
                            try:
                                # Спроба реконекту клієнта
                                await client.connect()
                                if not await client.is_user_authorized():
                                    logger.warning(f"Account {account_id} could not reconnect (not authorized).")
                                    return
                                logger.info(f"Account {account_id} reconnected successfully.")
                            except Exception as reconnect_error:
                                logger.warning(f"Failed to reconnect account {account_id}: {reconnect_error}")
                                return

                        async with self.global_rate_semaphore:
                            await asyncio.sleep(random.uniform(0.1, 0.3))
                            entity = await client.get_entity(make_peer(chat_id))
                            await client.send_message(entity, comment, comment_to=msg_id)
                            logger.info(f"Commented '{comment}' on {chat_id}/{msg_id} with account {account_id}")
                            await with_db_connection(
                                "INSERT INTO history (account_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                                (
                                    account_id,
                                    "auto_comment",
                                    f"Commented '{comment}' on {chat_id}/{msg_id}",
                                    datetime.now().isoformat(),
                                ),
                            )

                    except Exception as e:
                        logger.error(f"Comment error for {account_id} on {chat_id}/{msg_id}: {e}")
                spacing = delay
                next_available_time[key] = start_time + spacing

                asyncio.create_task(delayed_comment(account_id, chat_id, msg_id, comment, start_time, key))

            except Exception as e:
                logger.error(f"Error scheduling comment: {e}")
            finally:
                self.comment_queue.task_done()

    async def process_polls(self):
        while self.running:
            account_id, chat_id, msg_id, poll_option = await self.poll_queue.get()
            await self._process_action(account_id, chat_id, msg_id, "poll", poll_option)

    async def process_views(self):
        while self.running:
            account_id, chat_id, msg_id = await self.view_queue.get()
            await self._process_action(account_id, chat_id, msg_id, "view", None)

    async def _process_action(self, account_id, chat_id, msg_id, action_type, action_value):
        from telethon.errors import RPCError
        client = self.clients.get(account_id)
        if not client or not client.is_connected():
            logger.warning(f"No active client for {account_id}")
            return

        try:
            settings = await get_settings(chat_id) or {
                'reaction_delay_min': REACTION_DELAY_MIN,
                'reaction_delay_max': REACTION_DELAY_MAX,
                'comment_delay_min': COMMENT_DELAY_MIN,
                'comment_delay_max': COMMENT_DELAY_MAX,
                'max_accounts': MAX_COMMENTING_ACCOUNTS
            }

            peer = make_peer(chat_id)

            # 1️⃣ Основна затримка перед входом у семафор
            if action_type == "reaction":
                await asyncio.sleep(random.uniform(settings['reaction_delay_min'], settings['reaction_delay_max']))
            elif action_type == "comment":
                await asyncio.sleep(random.uniform(settings['comment_delay_min'], settings['comment_delay_max']))
            elif action_type == "poll":
                await asyncio.sleep(random.uniform(1, 5))
            elif action_type == "view":
                await asyncio.sleep(random.uniform(0.5, 2))

            # 2️⃣ Заходимо в глобальний семафор
            async with self.global_rate_semaphore:
                # Додатковий джиттер, щоб уникнути піків одночасних запитів
                await asyncio.sleep(random.uniform(0.1, 0.3))

                if action_type == "reaction":
                    await client(SendReactionRequest(
                        peer=peer,
                        msg_id=msg_id,
                        big=True,  # ✅ критично
                        reaction=[ReactionEmoji(emoticon=action_value)]
                    ))
                    logger.info(f"Reacted {action_value} to {chat_id}/{msg_id} for account {account_id}")
                    await with_db_connection(
                        "INSERT INTO history (account_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                        (account_id, "auto_reaction", f"Set {action_value} on {chat_id}/{msg_id}",
                         datetime.now().isoformat())
                    )

                elif action_type == "comment":
                    self.comment_usage[chat_id] = self.comment_usage.get(chat_id, 0) + 1
                    if self.comment_usage[chat_id] >= 5:
                        try:
                            new_comments = await generate_comments_binary_options(count=15)
                            comments_str = "|".join(new_comments)
                            await with_db_connection(
                                "UPDATE auto_comments SET comments = ? WHERE chat_id = ?",
                                (comments_str, chat_id)
                            )
                            logger.info(f"AI regenerated comments for chat {chat_id}")
                        except Exception as e:
                            logger.error(f"Failed to regenerate comments for {chat_id}: {e}")

                        self.comment_usage[chat_id] = 0  # обнуляємо лічильник
                    entity = await client.get_entity(peer)
                    message = await client.get_messages(entity, ids=msg_id)

                    if message and message.replies and message.replies.comments:
                        await client.send_message(entity, action_value, comment_to=msg_id)
                        logger.info(f"Commented '{action_value}' to {chat_id}/{msg_id} for account {account_id}")
                        await with_db_connection(
                            "INSERT INTO history (account_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                            (account_id, "auto_comment", f"Commented '{action_value}' on {chat_id}/{msg_id}",
                             datetime.now().isoformat())
                        )
                    else:
                        logger.info(f"Skipping comment on {chat_id}/{msg_id} - comments not enabled")

                elif action_type == "poll":
                    await client(SendVoteRequest(peer=peer, msg_id=msg_id, options=action_value))
                    logger.info(f"Voted {action_value} on poll {chat_id}/{msg_id} for account {account_id}")
                    await with_db_connection(
                        "INSERT INTO history (account_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                        (account_id, "auto_poll", f"Voted {action_value} on {chat_id}/{msg_id}",
                         datetime.now().isoformat())
                    )

                elif action_type == "view":
                    view_key = (account_id, msg_id)
                    if view_key in self._view_cache:
                        logger.debug(f"Skipping duplicate view for account {account_id} msg {msg_id}")
                        return
                    self._view_cache.add(view_key)
                    await client(GetMessagesViewsRequest(
                        peer=peer,
                        id=[msg_id],
                        increment=True
                    ))
                    logger.info(f"Viewed {chat_id}/{msg_id} for account {account_id}")
                    await with_db_connection(
                        "INSERT INTO history (account_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                        (account_id, "auto_view", f"Viewed {chat_id}/{msg_id}",
                         datetime.now().isoformat())
                    )

        except FloodWaitError as e:
            logger.warning(f"Flood wait for {account_id}: {e.seconds}s")
            await asyncio.sleep(e.seconds)
            queue_map = {
                "reaction": self.reaction_queue,
                "comment": self.comment_queue,
                "poll": self.poll_queue,
                "view": self.view_queue
            }
            if action_type in queue_map:
                if action_type == "view":
                    await queue_map[action_type].put((account_id, chat_id, msg_id))
                else:
                    await queue_map[action_type].put((account_id, chat_id, msg_id, action_value))
        except RPCError as e:
            if "FROZEN_METHOD_INVALID" in str(e) or "FROZEN_PARTICIPANT_MISSING" in str(e):
                logger.error(f"Account {account_id} is restricted: {str(e)}. Deleting account and subscriptions.")
                await with_db_connection("DELETE FROM accounts WHERE id = ?", (account_id,))
                await with_db_connection("DELETE FROM subscriptions WHERE account_id = ?", (account_id,))
                if client and client.is_connected():
                    await client.disconnect()
                if account_id in self.clients:
                    del self.clients[account_id]
                logger.info(f"Deleted account {account_id} and its subscriptions due to {str(e)}")
            else:
                logger.error(f"Failed {action_type} for {account_id} on {chat_id}/{msg_id}: {str(e)}")
        except Exception as e:
            logger.error(f"Failed {action_type} for {account_id} on {chat_id}/{msg_id}: {str(e)}")

    async def handle_new_message(self, event):
        chat_id = normalize_chat_id(event.chat_id)
        msg_id = event.message.id
        message_key = f"{chat_id}:{msg_id}"

        async with self.message_lock:
            if message_key in self.processed_messages:
                logger.info(f"Skipping already processed message: {chat_id}/{msg_id}")
                return
            self.processed_messages.add(message_key)
            logger.info(f"New message detected: chat_id={chat_id}, message_id={msg_id}")

            # ===== Album fix =====
            if event.message.grouped_id:
                grouped_id = event.message.grouped_id
                now = time.time()
                ttl = 10
                if grouped_id in self._album_cache:
                    root_id, ts = self._album_cache[grouped_id]
                    if now - ts < ttl:
                        if msg_id < root_id:
                            self._album_cache[grouped_id] = (msg_id, now)
                            root_id = msg_id
                    else:
                        self._album_cache[grouped_id] = (msg_id, now)
                        root_id = msg_id
                else:
                    self._album_cache[grouped_id] = (msg_id, now)
                    root_id = msg_id

                if msg_id != root_id:
                    logger.info(f"Ignoring non-root album media: {chat_id}/{msg_id} (root={root_id})")
                    return

                # Додаткова перевірка через iter_messages
                group_messages = [
                    m async for m in event.client.iter_messages(
                        event.chat_id,
                        reverse=True,
                        limit=50
                    ) if m.grouped_id == grouped_id
                ]
                if group_messages:
                    first_msg_id = min(m.id for m in group_messages)
                    if msg_id != first_msg_id:
                        logger.info(
                            f"Ignoring media in album (iter_messages check): {chat_id}/{msg_id}, root={first_msg_id}")
                        return

        all_accounts = await with_db_connection(
            "SELECT account_id FROM subscriptions WHERE chat_id = ?",
            (chat_id,),
            fetchall=True
        )
        logger.info(f"Found {len(all_accounts)} subscribed accounts for chat {chat_id}")

        settings = await get_settings(chat_id) or {
            'max_accounts': MAX_COMMENTING_ACCOUNTS,
            'comment_count': COMMENT_COUNT,
            'reaction_delay_min': REACTION_DELAY_MIN,
            'reaction_delay_max': REACTION_DELAY_MAX,
            'comment_delay_min': COMMENT_DELAY_MIN,
            'comment_delay_max': COMMENT_DELAY_MAX
        }

        # ===== Auto-views =====
        num_views = random.randint(VIEW_ACCOUNTS_MIN, VIEW_ACCOUNTS_MAX)
        view_accounts = random.sample(all_accounts, min(num_views, len(all_accounts))) if all_accounts else []
        for (account_id,) in view_accounts:
            if account_id in self.clients and (account_id, msg_id) not in self._view_cache:
                self._view_cache.add((account_id, msg_id))

                async def do_view(acc_id=account_id):
                    await asyncio.sleep(random.uniform(0.5, 2))

                    client = self.clients.get(acc_id)
                    if not client or not client.is_connected():
                        logger.warning(f"Client not active for account {acc_id}, attempting to reconnect.")
                        try:
                            # Спроба реконекту
                            await client.connect()
                            if not await client.is_user_authorized():
                                logger.warning(f"Account {acc_id} could not reconnect (not authorized).")
                                return
                            logger.info(f"Account {acc_id} reconnected successfully.")
                        except Exception as reconnect_error:
                            logger.warning(f"Failed to reconnect account {acc_id}: {reconnect_error}")
                            return  # Не продовжуємо, якщо реконект не вдався

                    try:
                        await client(GetMessagesViewsRequest(
                            peer=int(f"-100{chat_id}"),
                            id=[msg_id],
                            increment=True
                        ))
                        logger.info(f"Viewed {chat_id}/{msg_id} for account {acc_id}")
                        await with_db_connection(
                            "INSERT INTO history (account_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                            (acc_id, "auto_view", f"Viewed {chat_id}/{msg_id}", datetime.now().isoformat())
                        )
                    except UserNotParticipantError:
                        logger.warning(f"Account {acc_id} not a participant of {chat_id}, skipping view")
                    except FloodWaitError as e:
                        logger.warning(f"Flood wait {e.seconds}s for account {acc_id} on view")
                        asyncio.create_task(self._delayed_requeue(e.seconds, ("view", acc_id, chat_id, msg_id)))
                    except Exception as e:
                        logger.error(f"View error for {acc_id} on {chat_id}/{msg_id}: {e}")

                asyncio.create_task(do_view())
        # ===== Auto-reactions =====
        reaction_data = await with_db_connection(
            "SELECT reaction FROM auto_reactions WHERE chat_id = ?",
            (chat_id,),
            fetchone=True
        )

        if reaction_data:
            reaction_str = reaction_data[0]
            reaction_accounts = [acc_id for (acc_id,) in all_accounts if acc_id in self.clients]

            if reaction_str.startswith("mode=manual;"):
                parts = reaction_str.replace("mode=manual;", "").split(";")
                counts = {}
                extra_mode = "fill_none"
                for p in parts:
                    if not p:
                        continue
                    if p.startswith("extra="):
                        extra_mode = p.split("=")[1]
                    elif ":" in p:
                        emoji, num = p.split(":")
                        counts[normalize_emoji(emoji.strip())] = int(num.strip())
                assigned = []
                for emoji, num in counts.items():
                    assigned.extend([emoji] * num)
                random.shuffle(assigned)

                for i, account_id in enumerate(reaction_accounts):
                    if account_id not in self.clients:
                        continue
                    if i < len(assigned):
                        reaction = assigned[i]
                    else:
                        if extra_mode == "fill_random":
                            reaction = random.choice(list(counts.keys()))
                        else:
                            continue

                    reaction_key = f"{account_id}:{chat_id}:{msg_id}:reaction"
                    async with self.message_lock:
                        if reaction_key in self.processed_messages:
                            continue
                        self.processed_messages.add(reaction_key)
                    logger.info(
                        f"Queuing manual auto-reaction '{reaction}' for {chat_id}/{msg_id} with account {account_id}"
                    )
                    await self.reaction_queue.put((account_id, chat_id, msg_id, reaction))

            else:
                # режим random (старий варіант)
                # reactions = [normalize_emoji(r.strip()) for r in reaction_str.split(",") if r.strip()]
                clean_str = reaction_str.replace("mode=random;", "")
                reactions = [normalize_emoji(r.strip()) for r in clean_str.split(",") if r.strip()]

                for account_id in reaction_accounts:
                    if account_id not in self.clients:
                        continue
                    reaction = random.choice(reactions)
                    reaction_key = f"{account_id}:{chat_id}:{msg_id}:reaction"
                    async with self.message_lock:
                        if reaction_key in self.processed_messages:
                            continue
                        self.processed_messages.add(reaction_key)
                    logger.info(
                        f"Queuing auto-reaction '{reaction}' for {chat_id}/{msg_id} with account {account_id}"
                    )
                    await self.reaction_queue.put((account_id, chat_id, msg_id, reaction))

        # ===== Auto-comments через чергу =====
        if all_accounts and event.message.replies and event.message.replies.comments:
            num_accounts_to_use = random.randint(1, len(all_accounts))
            shuffled_accounts = [aid[0] for aid in all_accounts]
            random.shuffle(shuffled_accounts)
            comment_accounts = shuffled_accounts[:num_accounts_to_use]

            comments = await get_next_comments(chat_id, 50)
            num_comments_needed = min(len(comment_accounts), len(comments))
            comments = random.sample(comments, num_comments_needed)

            logger.info(
                f"Preparing to queue {num_comments_needed} comments for chat {chat_id}/msg {msg_id} "
                f"from {len(comment_accounts)} selected accounts"
            )

            for idx in range(num_comments_needed):
                account_id = comment_accounts[idx]
                comment = comments[idx]
                if (chat_id, comment) in self.used_comments:
                    logger.info(
                        f"Skipping duplicate comment text '{comment}' for chat {chat_id}, searching replacement..."
                    )
                    replacement = next((c for c in comments if (chat_id, c) not in self.used_comments), None)
                    if replacement:
                        comment = replacement
                    else:
                        logger.warning(f"No unique comments left for chat {chat_id}, skipping account {account_id}")
                        continue

                self.used_comments.add((chat_id, comment))

                if account_id in self.clients:
                    comment_key = f"{account_id}:{chat_id}:{msg_id}:comment"
                    async with self.message_lock:
                        if comment_key in self.processed_messages:
                            logger.warning(
                                f"Skipping duplicate comment for account {account_id} on {chat_id}/{msg_id}"
                            )
                            continue
                        self.processed_messages.add(comment_key)

                    base_delay = random.uniform(
                        settings['comment_delay_min'],
                        settings['comment_delay_max']
                    )
                    extra_delay = idx * random.uniform(3.5, 9.5)
                    total_delay = base_delay + extra_delay

                    await self.comment_queue.put(
                        (account_id, chat_id, msg_id, comment, total_delay)
                    )
                    logger.info(
                        f"Queued comment '{comment}' for account {account_id} on {chat_id}/{msg_id} "
                        f"with total_delay={total_delay:.2f}s"
                    )
                else:
                    logger.warning(
                        f"Skipping comment for account {account_id} on {chat_id}/{msg_id}: no active client"
                    )

        # ===== Polls =====
        if event.message.poll:
            pass

    async def shutdown(self):
        self.running = False

        queues = [self.reaction_queue, self.comment_queue, self.poll_queue, self.view_queue]
        for queue in queues:
            while not queue.empty():
                logger.info(f"Waiting for queue to drain: {queue.qsize()} items remaining")
                await asyncio.sleep(1)

        for task_name, task in self.tasks.items():
            logger.info(f"Stopping {task_name} task...")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.info(f"{task_name} task cancelled successfully")

        self.tasks.clear()

        for account_id, client in list(self.clients.items()):
            if client.is_connected():
                try:
                    await asyncio.wait_for(client.disconnect(), timeout=10)
                    logger.info(f"Disconnected client for account {account_id}")
                except asyncio.TimeoutError:
                    logger.error(f"Timeout disconnecting client {account_id}, forcing closure")
                except Exception as e:
                    logger.error(f"Error disconnecting client {account_id}: {e}")
                finally:
                    del self.clients[account_id]

        self.clients.clear()
        self.processed_messages.clear()
        logger.info("AutoManager shutdown completed")

    def _get_album_root_id(self, grouped_id, msg_id):
        now = time.time()
        ttl = 10
        if grouped_id in self._album_cache:
            root_id, ts = self._album_cache[grouped_id]
            if now - ts < ttl:
                if msg_id < root_id:
                    self._album_cache[grouped_id] = (msg_id, now)
                    return msg_id
                return root_id
            else:
                del self._album_cache[grouped_id]

        self._album_cache[grouped_id] = (msg_id, now)
        return msg_id

    async def handle_album(self, event: events.Album):
        chat_id = normalize_chat_id(event.chat_id)
        # Telethon дає список повідомлень альбому у event.messages
        msg_ids = [m.id for m in event.messages]
        root_msg_id = min(msg_ids)

        logger.info(f"Album detected in {chat_id} with root msg_id {root_msg_id}, messages: {msg_ids}")

        # Далі викликаємо єдину обробку так само, як для звичайного повідомлення
        await self._process_new_post(chat_id, root_msg_id)

auto_manager = AutoManager()


def make_peer(chat_id: str | int) -> int:
    return int(chat_id) if str(chat_id).startswith("-100") else int(f"-100{chat_id}")


async def get_next_comments(chat_id: int, needed_count: int) -> list[str]:
    row = await with_db_connection(
        "SELECT comments FROM auto_comments WHERE chat_id = ? LIMIT 1",
        (chat_id,),
        fetchone=True
    )
    comments = []
    if row and row[0]:
        comments = [c.strip() for c in row[0].split("|") if c.strip()]

    # Якщо не вистачає — генеруємо нові
    if len(comments) < needed_count:
        logger.info(f"Not enough comments for chat {chat_id}. Generating new ones via AI...")
        new_comments = await generate_comments_binary_options(count=15)
        comments_str = "|".join(new_comments)
        await with_db_connection(
            "UPDATE auto_comments SET comments = ? WHERE chat_id = ?",
            (comments_str, chat_id)
        )
        comments.extend(new_comments[:needed_count - len(comments)])

    return comments[:needed_count]

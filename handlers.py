# handlers.py
import json
import os
import re
import asyncio
import random
import sqlite3

import socks
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler
from telethon.errors import UserNotParticipantError, ChannelInvalidError, ChannelPrivateError, \
    UserAlreadyParticipantError, InviteHashExpiredError

from auto_manager import auto_manager
from config import FREE_REACTIONS, ACCOUNTS_PER_PAGE, BUTTONS_PER_ROW, ZIP_RAR_DIR, EXTRACT_BASE_DIR, \
    COMMENT_VOCABULARY, REACTION_DELAY_MIN, REACTION_DELAY_MAX, DB_FILE, AUTO_REACTION, AUTO_CHAT_ID, \
    COMMENT_DELAY_MIN, COMMENT_DELAY_MAX, MAX_COMMENTING_ACCOUNTS, VIEW_ACCOUNTS_MIN, VIEW_ACCOUNTS_MAX, AUTO_COMMENTS
from database import with_db_connection, get_comments, get_settings, set_comments, set_settings
from telegram_client import get_client, extract_archive, get_session_files, client_connection_lock, test_proxy
from utils import logger, normalize_emoji, normalize_chat_id, get_single_proxy, save_proxy, \
    generate_comments_binary_options
from datetime import datetime
from telethon.tl.functions.channels import LeaveChannelRequest, JoinChannelRequest
from telethon.tl.functions.messages import SendReactionRequest, ImportChatInviteRequest, CheckChatInviteRequest
from telethon.tl.types import ReactionEmoji, ChatInvite, ChatInviteAlready
from telethon.tl.types import MessageMediaPoll, PollAnswer

from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
from telethon.tl.types import ChatInvite, ChatInviteAlready
from telethon.errors import ChannelInvalidError, ChannelPrivateError, InviteHashExpiredError, InviteRequestSentError, UserAlreadyParticipantError
import re
from telegram.ext import ConversationHandler
from config import (BOT_TOKEN, BOT_NAME, CHANNEL_ID, INVITE_LINK, CHAT_ID, AUTO_CHAT_ID, AUTO_REACTION,
                    VIEW_LINK, POLL_ACCOUNTS, POLL_OPTION, POLL_LINK, COMMENTS_TEXT, COMMENTS_LANGUAGE,
                    COMMENTS_CHAT_ID, SETTINGS_VALUES, SETTINGS_CHAT_ID, AUTO_COMMENTS, PROXY_DETAILS,
                    PROXY_TYPE, UNSUB_CHANNEL_ID, AUTO_REACTION_COUNTS, AUTO_REACTION_RANDOM_FILL, REACTION_INPUT,
                    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.chat_data.clear()

    # скидаємо всі розмови для цього чату/юзера
    if update.effective_chat:
        context.application.chat_data[update.effective_chat.id].clear()
    if update.effective_user:
        context.application.user_data[update.effective_user.id].clear()

    keyboard = [
        [InlineKeyboardButton("Add Accounts", callback_data="add_accounts")],
        [InlineKeyboardButton("View Accounts", callback_data="view_accounts_1")],
        [InlineKeyboardButton("Manage Subscriptions", callback_data="manage_subs")],
        [InlineKeyboardButton("View History", callback_data="view_history")],
        [InlineKeyboardButton("Reaction Info", callback_data="reaction_info")],
        [InlineKeyboardButton("Manage Auto-Reactions", callback_data="manage_auto_reactions")],
        # [InlineKeyboardButton("Manage Auto-Comments", callback_data="manage_auto_comments")],
        # [InlineKeyboardButton("Set Manual Settings", callback_data="set_settings")],
        # [InlineKeyboardButton("Manage Comments", callback_data="manage_comments")],
        # [InlineKeyboardButton("Manual Vote", callback_data="manual_vote")],
        # [InlineKeyboardButton("Manual View", callback_data="manual_view")],
        [InlineKeyboardButton("Add Proxy", callback_data="add_proxy")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text("Welcome to the Telegram Bot! Choose an option:", reply_markup=reply_markup)
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Welcome to the Telegram Bot! Choose an option:", reply_markup=reply_markup)

    # Завжди повертаємо END → це закриває активні розмови
    return ConversationHandler.END


async def restart_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Restarting the bot... Please wait a few seconds.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
    )
    user_id = query.from_user.id
    logger.info(f"Bot restart initiated by user {user_id}")
    raise SystemExit("Bot restart requested")

async def reaction_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer(text=f"Supported free reactions:\n{' '.join(FREE_REACTIONS.keys())}", show_alert=True)

async def add_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["pending_files"] = []
    context.user_data["file_processing_message"] = None
    keyboard = [
        [InlineKeyboardButton("Done Uploading", callback_data="process_files")],
        [InlineKeyboardButton("Back", callback_data="start")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "Please upload ZIP or RAR files containing Telegram sessions. You can send multiple files.\n"
        "Click 'Done Uploading' when you're finished.",
        reply_markup=reply_markup
    )

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        keyboard = [[InlineKeyboardButton("Back", callback_data="start")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Please upload a ZIP or RAR file.", reply_markup=reply_markup)
        return

    file = update.message.document
    file_name = file.file_name
    if not file_name.endswith((".zip", ".rar")):
        keyboard = [[InlineKeyboardButton("Back", callback_data="start")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Only ZIP or RAR files are supported.", reply_markup=reply_markup)
        return

    context.user_data["pending_files"].append((file, file_name))
    status_text = f"Received {len(context.user_data['pending_files'])} file(s). Send more files or click 'Done Uploading' to process."
    if "file_processing_message" not in context.user_data or not context.user_data["file_processing_message"]:
        keyboard = [[InlineKeyboardButton("Done Uploading", callback_data="process_files")],
                   [InlineKeyboardButton("Back", callback_data="start")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = await update.message.reply_text(status_text, reply_markup=reply_markup)
        context.user_data["file_processing_message"] = message
    else:
        try:
            await context.user_data["file_processing_message"].edit_text(
                status_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Done Uploading", callback_data="process_files")],
                    [InlineKeyboardButton("Back", callback_data="start")]
                ])
            )
        except Exception as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Failed to update status message: {str(e)}")

async def process_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    files = context.user_data.get("pending_files", [])
    if not files:
        await query.edit_message_text("No files uploaded.", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Back", callback_data="start")]]))
        return

    total_files = len(files)
    results = []
    status_msg = await query.message.reply_text(f"Processing {total_files} file(s)...\nProgress: 0/{total_files}")

    single_proxy = get_single_proxy()

    for idx, (file, file_name) in enumerate(files):
        os.makedirs(ZIP_RAR_DIR, exist_ok=True)
        archive_path = os.path.join(ZIP_RAR_DIR, file_name)
        try:
            file_obj = await file.get_file()
            await file_obj.download_to_drive(archive_path)
        except Exception as e:
            logger.error(f"Failed to download {file_name}: {str(e)}")
            results.append(f"Failed to download {file_name}: {str(e)}")
            continue

        extract_dir = os.path.join(EXTRACT_BASE_DIR, os.path.splitext(file_name)[0])
        if not await extract_archive(archive_path, extract_dir):
            results.append(f"Failed to extract {file_name}.")
            continue

        session_files = get_session_files(extract_dir)
        if not session_files:
            results.append(f"No session files in {file_name}.")
            continue

        for session_file in session_files:
            logger.info(f"Processing session file: {session_file}")
            result = await with_db_connection("SELECT id FROM accounts WHERE session_path = ?", (session_file,))
            if result:
                results.append(f"Account from {session_file} already in database.")
                continue

            account_id = await with_db_connection("SELECT COUNT(*) FROM accounts")
            account_id = account_id[0] + 1 if account_id else 1
            async with client_connection_lock:
                client = await get_client(session_file, account_id, single_proxy)

                if client:
                    try:
                        me = await client.get_me()
                        phone = me.phone or "Unknown"
                        tg_id = me.id
                        await with_db_connection(
                            "INSERT INTO accounts (session_path, phone, added_at, proxy, tg_id) VALUES (?, ?, ?, ?, ?)",
                            (session_file, phone, datetime.now().isoformat(),
                             json.dumps(single_proxy) if single_proxy else None, tg_id)
                        )
                        results.append(f"Added account from {session_file} (Phone: {phone}).")
                    finally:
                        await client.disconnect()
                else:
                    results.append(f"Session {session_file} not authorized or banned.")
        await status_msg.edit_text(f"Processing {total_files} file(s)...\nProgress: {idx + 1}/{total_files}")

    await auto_manager.start_clients()
    context.user_data["pending_files"] = []
    msg = "\n".join(results)
    await status_msg.edit_text(msg or "No accounts processed.", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("Back", callback_data="start")]]))

async def view_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = int(query.data.split("_")[-1])

    accounts = await with_db_connection("SELECT id, phone FROM accounts", fetchall=True)
    total_accounts = len(accounts)
    total_pages = (total_accounts + ACCOUNTS_PER_PAGE - 1) // ACCOUNTS_PER_PAGE
    start_idx = (page - 1) * ACCOUNTS_PER_PAGE
    end_idx = min(start_idx + ACCOUNTS_PER_PAGE, total_accounts)

    keyboard = []
    for i in range(start_idx, end_idx):
        account_id, phone = accounts[i]
        button = InlineKeyboardButton(f"{phone}", callback_data=f"view_account_{account_id}")
        if i % BUTTONS_PER_ROW == 0:
            keyboard.append([])
        keyboard[-1].append(button)

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("Previous", callback_data=f"view_accounts_{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(f"Page {page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("Next", callback_data=f"view_accounts_{page + 1}"))
    nav_buttons.append(InlineKeyboardButton("Back", callback_data="start"))
    keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"Accounts (Page {page}/{total_pages}):"
    await query.edit_message_text(text, reply_markup=reply_markup)

async def view_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_id = int(query.data.split("_")[-1])

    session_path, phone = await with_db_connection(
        "SELECT session_path, phone FROM accounts WHERE id = ?", (account_id,)
    )
    text = f"Account ID: {account_id}\nPhone: {phone}\nSession Path: {session_path}"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("Back", callback_data="view_accounts_1")]]))

async def manage_subs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Add Subscription", callback_data="add_sub")],
        [InlineKeyboardButton("Unsubscribe All from Channel", callback_data="unsub_all_channel")],
        [InlineKeyboardButton("Back", callback_data="start")],
    ]
    await query.edit_message_text("Manage Subscriptions:", reply_markup=InlineKeyboardMarkup(keyboard))


# async def handle_sub_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
#     invite_link = update.message.text.strip()
#     match = re.match(r"https://t\.me/\+([A-Za-z0-9_-]+)", invite_link)
#     if not match:
#         await update.message.reply_text("Invalid invite link. Try again or /cancel.")
#         return INVITE_LINK
#     hash_code = match.group(1)
#     accounts = await with_db_connection("SELECT id FROM accounts", fetchall=True)
#     total_accounts = len(accounts)
#     status_msg = await update.message.reply_text(f"Subscribing {total_accounts} accounts...\nProgress: 0/{total_accounts}")
#     success_count = 0
#     for (account_id,) in accounts:
#         client = auto_manager.clients.get(account_id)
#         if client:
#             try:
#                 await client(ImportChatInviteRequest(hash=hash_code))
#
#                 success_count += 1
#             except Exception as e:
#                 logger.error(f"Failed to subscribe account {account_id}: {e}")
#         await status_msg.edit_text(f"Subscribing...\nProgress: {success_count}/{total_accounts}")
#     await status_msg.edit_text(f"Subscribed {success_count}/{total_accounts} accounts.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]]))
#     return ConversationHandler.END





async def add_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        if "Query is too old" not in str(e):
            logger.error(f"Failed to answer callback query in add_sub: {str(e)}")
    await query.edit_message_text("Send invite link (https://t.me/+abcdefg) or chat ID")
    return INVITE_LINK

# async def handle_sub_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
#     from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
#     from telethon.errors import (
#         InviteHashExpiredError, InviteHashInvalidError,
#         UserAlreadyParticipantError, ChannelInvalidError,
#         ChannelPrivateError, InviteRequestSentError
#     )
#
#     input_text = update.message.text.strip()
#     logger.info(f"Processing subscription for input: {input_text}")
#
#     # Check if input is an invite link or chat ID
#     match = re.match(r"https://t\.me/\+([A-Za-z0-9_-]+)", input_text)
#     is_invite_link = bool(match)
#     hash_code = match.group(1) if match else None
#
#     # Get non-banned accounts
#     accounts = await with_db_connection(
#         "SELECT id FROM accounts WHERE banned IS NULL OR banned = 0",
#         fetchall=True
#     )
#     total_accounts = len(accounts)
#     logger.info(f"Total non-banned accounts: {total_accounts}")
#
#     if total_accounts == 0:
#         await update.message.reply_text(
#             "No accounts available for subscription.",
#             reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
#         )
#         return ConversationHandler.END
#
#     status_msg = await update.message.reply_text(
#         f"Subscribing {total_accounts} accounts...\nProgress: 0/{total_accounts}"
#     )
#     success_count = 0
#     skipped_count = 0
#     chat_id = None
#     chat_title = "Unknown"
#
#     # Try resolving chat_id and title before the loop
#     if is_invite_link:
#         try:
#             client = next(iter(auto_manager.clients.values()), None)
#             if not client:
#                 await update.message.reply_text(
#                     "No active clients available to resolve invite link.",
#                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
#                 )
#                 return ConversationHandler.END
#
#             invite = await client(CheckChatInviteRequest(hash_code))
#             logger.info(f"Invite response type: {type(invite)}, value: {invite}")
#
#             if isinstance(invite, ChatInviteAlready):
#                 if hasattr(invite, "chat") and invite.chat:
#                     chat_id = normalize_chat_id(str(invite.chat.id))
#                     chat_title = getattr(invite.chat, "title", "Unknown")
#                 elif hasattr(invite, "channel") and invite.channel:
#                     chat_id = normalize_chat_id(str(invite.channel.id))
#                     chat_title = getattr(invite.channel, "title", "Unknown")
#                 else:
#                     logger.error(f"Invite link {input_text} has no valid chat or channel attribute")
#                     await update.message.reply_text(
#                         "Error processing invite link: No valid chat or channel found. Try again or /cancel.",
#                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
#                     )
#                     return ConversationHandler.END
#
#             elif isinstance(invite, ChatInvite):
#                 chat_title = getattr(invite, "title", "Unknown")
#                 logger.info(f"Invite preview: {chat_title}, will join accounts in loop")
#                 # chat_id визначиться пізніше після ImportChatInviteRequest у циклі
#
#             else:
#                 logger.error(f"Unexpected invite type for link {input_text}: {type(invite)}")
#                 await update.message.reply_text(
#                     "Error processing invite link: Invalid response from Telegram. Try again or /cancel.",
#                     reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
#                 )
#                 return ConversationHandler.END
#
#         except (InviteHashExpiredError, ChannelInvalidError, ChannelPrivateError) as e:
#             logger.error(f"Failed to resolve invite link {input_text}: {str(e)}")
#             await update.message.reply_text(
#                 f"Failed to resolve invite link: {str(e)}. Try again or /cancel.",
#                 reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
#             )
#             return ConversationHandler.END
#         except Exception as e:
#             logger.error(f"Unexpected error resolving invite link {input_text}: {str(e)}")
#             await update.message.reply_text(
#                 "Error processing invite link. Try again or /cancel.",
#                 reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
#             )
#             return ConversationHandler.END
#     else:
#         chat_id = normalize_chat_id(input_text)
#
#     # Loop through accounts to actually join
#     for (account_id,) in accounts:
#         client = auto_manager.clients.get(account_id)
#         if not client:
#             logger.warning(f"Client not active for account {account_id}, skipping.")
#             continue
#
#         try:
#             if is_invite_link:
#                 try:
#                     updates = await client(ImportChatInviteRequest(hash=hash_code))
#                     if updates.chats:
#                         chat = updates.chats[0]
#                         chat_id = normalize_chat_id(str(chat.id))
#                         chat_title = getattr(chat, "title", chat_title)
#                         logger.info(f"Account {account_id} joined {chat_title} (ID: {chat_id}) via invite link")
#                 except UserAlreadyParticipantError:
#                     logger.info(f"Account {account_id} already subscribed to channel {chat_id}, skipping.")
#                     skipped_count += 1
#                     continue
#                 except (InviteHashExpiredError, InviteHashInvalidError) as e:
#                     logger.error(f"Failed to join account {account_id} to channel {chat_id}: {str(e)}")
#                     continue
#                 except InviteRequestSentError:
#                     logger.info(f"Join request sent for account {account_id} to channel {chat_id}")
#                     continue
#             else:
#                 try:
#                     await client.get_entity(int(f"-100{chat_id}"))
#                     logger.info(f"Account {account_id} already subscribed to channel {chat_id}, skipping.")
#                     skipped_count += 1
#                     continue
#                 except (ChannelInvalidError, ChannelPrivateError):
#                     entity = await client.get_entity(int(f"-100{chat_id}"))
#                     await client(JoinChannelRequest(entity))
#
#             # Fetch chat details
#             entity = await client.get_entity(int(f"-100{chat_id}"))
#             chat_title = getattr(entity, "title", chat_title)
#             chat_type = "channel" if getattr(entity, "broadcast", False) else "group"
#
#             # Save subscription
#             await with_db_connection(
#                 "INSERT OR IGNORE INTO subscriptions (account_id, chat_id, chat_title, chat_type) VALUES (?, ?, ?, ?)",
#                 (account_id, chat_id, chat_title, chat_type)
#             )
#             await auto_manager.update_event_handlers(account_id)
#
#             success_count += 1
#             logger.info(f"Account {account_id} successfully subscribed to {chat_type} {chat_title} (ID: {chat_id})")
#
#             # Update progress
#             new_text = f"Subscribing...\nProgress: {success_count}/{total_accounts}"
#             if status_msg.text != new_text:
#                 try:
#                     await status_msg.edit_text(new_text)
#                 except Exception as e:
#                     if "Message is not modified" not in str(e):
#                         logger.error(f"Failed to edit status message for account {account_id}: {str(e)}")
#         except Exception as e:
#             logger.error(f"Unexpected error subscribing account {account_id} to channel {chat_id}: {str(e)}")
#
#     final_text = f"Subscribed {success_count}/{total_accounts} accounts."
#     if skipped_count > 0:
#         final_text += f"\nSkipped {skipped_count} accounts already subscribed."
#     try:
#         await status_msg.edit_text(
#             final_text,
#             reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
#         )
#     except Exception as e:
#         if "Message is not modified" not in str(e):
#             logger.error(f"Failed to edit final status message: {str(e)}")
#
#     return ConversationHandler.END


async def delete_account(account_id: int, client=None):
    """Видаляє акаунт і його підписки з БД, закриває клієнт"""
    try:
        await with_db_connection("DELETE FROM accounts WHERE id = ?", (account_id,))
        await with_db_connection("DELETE FROM subscriptions WHERE account_id = ?", (account_id,))
        if client and client.is_connected():
            await client.disconnect()
        if account_id in auto_manager.clients:
            del auto_manager.clients[account_id]
        logger.info(f"Deleted account {account_id} and its subscriptions.")
    except Exception as e:
        logger.error(f"Failed to delete account {account_id}: {str(e)}")


async def handle_sub_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
    from telethon.errors import (
        InviteHashExpiredError, InviteHashInvalidError,
        UserAlreadyParticipantError, ChannelInvalidError,
        ChannelPrivateError, InviteRequestSentError, RPCError
    )
    from telethon.tl.types import ChatInvite, ChatInviteAlready, ChatInvitePeek
    from telethon.tl.functions.channels import JoinChannelRequest

    input_text = update.message.text.strip()
    logger.info(f"Processing subscription for input: {input_text}")

    # Check if input is an invite link
    match = re.match(r"https://t\.me/\+([A-Za-z0-9_-]+)", input_text)
    is_invite_link = bool(match)
    hash_code = match.group(1) if match else None

    # Get non-banned accounts
    accounts = await with_db_connection(
        "SELECT id FROM accounts WHERE banned IS NULL OR banned IN (0, 1)",
        fetchall=True
    )

    total_accounts = len(accounts)
    logger.info(f"Total non-banned accounts: {total_accounts}")

    if total_accounts == 0:
        await update.message.reply_text(
            "No accounts available for subscription.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]]))
        return ConversationHandler.END

    status_msg = await update.message.reply_text(
        f"Subscribing {total_accounts} accounts...\nProgress: 0/{total_accounts}"
    )
    success_count, skipped_count = 0, 0
    chat_id, chat_title, invite_type, invite = None, "Unknown", None, None

    # === Resolve invite link (одним акаунтом) ===
    if is_invite_link:
        resolver_client = None
        for acc_id, client in auto_manager.clients.items():
            if not client or not client.is_connected():
                continue
            try:
                invite = await client(CheckChatInviteRequest(hash_code))
                resolver_client = client
                logger.info(f"Resolved invite link with account {acc_id}")
                break
            except RPCError as e:
                if "FROZEN_METHOD_INVALID" in str(e):
                    logger.warning(f"Account {acc_id} is restricted (FROZEN) – deleting it")
                    await delete_account(acc_id, client)
                    continue
                raise

        if not invite:
            await update.message.reply_text(
                "No valid account could resolve this invite link (all frozen/restricted).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]]))
            return ConversationHandler.END

        if isinstance(invite, ChatInviteAlready):
            invite_type = "already"
            if hasattr(invite, "chat") and invite.chat:
                chat_id = normalize_chat_id(str(invite.chat.id))
                chat_title = getattr(invite.chat, "title", "Unknown")
            elif hasattr(invite, "channel") and invite.channel:
                chat_id = normalize_chat_id(str(invite.channel.id))
                chat_title = getattr(invite.channel, "title", "Unknown")
            logger.info(f"Invite already: {chat_title}")
        elif isinstance(invite, ChatInvite):
            invite_type = "chat_invite"
            chat_title = getattr(invite, "title", "Unknown")
            logger.info(f"Invite preview: {chat_title}, will join accounts in loop")
        elif isinstance(invite, ChatInvitePeek):
            invite_type = "peek"
            chat_id = normalize_chat_id(str(invite.chat.id))
            chat_title = getattr(invite.chat, "title", "Unknown")
            logger.info(f"Invite peek: {chat_title}, will join accounts via JoinChannelRequest/Import")
        else:
            logger.error(f"Unexpected invite type for link {input_text}: {type(invite)}")
            await update.message.reply_text(
                "Error processing invite link: Invalid response from Telegram. Try again or /cancel.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]]))
            return ConversationHandler.END
    else:
        chat_id = normalize_chat_id(input_text)

    # === LOOP THROUGH ACCOUNTS ===
    for (account_id,) in accounts:
        banned_flag = await with_db_connection(
            "SELECT banned FROM accounts WHERE id = ?", (account_id,), fetchone=True
        )
        if banned_flag and banned_flag[0]:
            logger.warning(f"Skipping banned account {account_id}")
            continue

        client = auto_manager.clients.get(account_id)

        # Перевірка на наявність активного клієнта для цього акаунта
        if not client:
            logger.warning(f"No client found for account {account_id}, creating a new client.")
            session_path, = await with_db_connection(
                "SELECT session_path FROM accounts WHERE id = ?", (account_id,), fetchone=True
            )
            client = await get_client(session_path, account_id)
            if not client:
                logger.error(f"Failed to create a client for account {account_id}.")
                continue
        else:
            # Перевіряємо, чи клієнт підключений
            if not client.is_connected():
                logger.warning(f"Client for account {account_id} is not connected. Attempting to reconnect.")
                try:
                    await client.connect()  # Спроба реконекту
                    if not await client.is_user_authorized():  # Якщо після реконекту клієнт не авторизований
                        logger.warning(f"Account {account_id} could not reconnect (not authorized).")
                        continue  # Якщо не вдалося авторизувати, пропускаємо акаунт
                    logger.info(f"Account {account_id} reconnected successfully.")
                except Exception as reconnect_error:
                    logger.error(f"Failed to reconnect account {account_id}: {reconnect_error}")
                    continue  # Не продовжуємо, якщо реконект не вдався

        if not client.is_connected():
            logger.warning(f"Client not connected for account {account_id}, attempting to reconnect.")
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    logger.warning(f"Account {account_id} could not reconnect (not authorized).")
                    continue
                logger.info(f"Account {account_id} reconnected successfully.")
            except Exception as reconnect_error:
                logger.warning(f"Failed to reconnect account {account_id}: {reconnect_error}")
                continue

        try:
            if is_invite_link:
                try:
                    if invite_type == "chat_invite":
                        updates = await client(ImportChatInviteRequest(hash=hash_code))
                        if updates.chats:
                            chat = updates.chats[0]
                            chat_id = normalize_chat_id(str(chat.id))
                            chat_title = getattr(chat, "title", chat_title)
                            logger.info(f"Account {account_id} joined {chat_title} via ImportChatInviteRequest")

                    elif invite_type in ("peek", "already"):
                        if getattr(invite.chat, "username", None):
                            entity = await client.get_entity(invite.chat.username)
                            await client(JoinChannelRequest(entity))
                        else:
                            updates = await client(ImportChatInviteRequest(hash=hash_code))
                            if updates.chats:
                                chat = updates.chats[0]
                                chat_id = normalize_chat_id(str(chat.id))
                                chat_title = getattr(chat, "title", chat_title)

                        logger.info(f"Account {account_id} joined {chat_title} via JoinChannelRequest/Import")

                except UserAlreadyParticipantError:
                    logger.info(f"Account {account_id} already subscribed to {chat_title}, skipping.")
                    skipped_count += 1
                    continue
                except (InviteHashExpiredError, InviteHashInvalidError) as e:
                    logger.error(f"Failed to join account {account_id}: {e}")
                    continue
                except InviteRequestSentError:
                    logger.info(f"Join request sent for account {account_id} to {chat_title}")
                    continue
            else:
                try:
                    await client.get_entity(int(f"-100{chat_id}"))
                    logger.info(f"Account {account_id} already subscribed to channel {chat_id}, skipping.")
                    skipped_count += 1
                    continue
                except (ChannelInvalidError, ChannelPrivateError):
                    entity = await client.get_entity(int(f"-100{chat_id}"))
                    await client(JoinChannelRequest(entity))

            # Save subscription
            entity = await client.get_entity(int(f"-100{chat_id}"))
            chat_title = getattr(entity, "title", chat_title)
            chat_type = "channel" if getattr(entity, "broadcast", False) else "group"

            await with_db_connection(
                "INSERT OR IGNORE INTO subscriptions (account_id, chat_id, chat_title, chat_type) VALUES (?, ?, ?, ?)",
                (account_id, chat_id, chat_title, chat_type)
            )
            await auto_manager.update_event_handlers(account_id)

            success_count += 1
            logger.info(f"Account {account_id} successfully subscribed to {chat_type} {chat_title} (ID: {chat_id})")

            new_text = f"Subscribing...\nProgress: {success_count}/{total_accounts}"
            if status_msg.text != new_text:
                try:
                    await status_msg.edit_text(new_text)
                except Exception as e:
                    if "Message is not modified" not in str(e):
                        logger.error(f"Failed to edit status message for account {account_id}: {str(e)}")

        except Exception as e:
            if "FROZEN_METHOD_INVALID" in str(e) or "FROZEN_PARTICIPANT_MISSING" in str(e):
                logger.error(f"Account {account_id} is restricted during subscription: {str(e)}")
                await delete_account(account_id, client)
                continue
            else:
                logger.error(f"Unexpected error subscribing account {account_id} to channel {chat_id}: {str(e)}")

    final_text = f"Subscribed {success_count}/{total_accounts} accounts."
    if skipped_count > 0:
        final_text += f"\nSkipped {skipped_count} accounts already subscribed."
    try:
        await status_msg.edit_text(
            final_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]]))
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Failed to edit final status message: {str(e)}")

    return ConversationHandler.END


async def retry_with_backoff(func, max_retries=5):
    for attempt in range(max_retries):
        try:
            return await func()
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                logger.warning(f"Database locked, retrying... (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(2 ** attempt)  # Експоненціальна затримка
                continue
            raise



async def handle_sub_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.message.text.strip()
    accounts = await with_db_connection("SELECT id FROM accounts", fetchall=True)
    total_accounts = len(accounts)
    status_msg = await update.message.reply_text(f"Subscribing {total_accounts} accounts...\nProgress: 0/{total_accounts}")
    success_count = 0
    for (account_id,) in accounts:
        client = auto_manager.clients.get(account_id)
        if client:
            try:
                entity = await client.get_entity(int(chat_id))
                await client(JoinChannelRequest(entity))
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to subscribe account {account_id}: {e}")
        await status_msg.edit_text(f"Subscribing...\nProgress: {success_count}/{total_accounts}")
    await status_msg.edit_text(f"Subscribed {success_count}/{total_accounts} accounts.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]]))
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    context.chat_data.clear()

    if update.message:
        await update.message.reply_text("Operation canceled.")
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Operation canceled.")

    # 2️⃣ Одразу запускаємо меню /start як нове повідомлення
    if update.effective_chat:
        fake_update = Update(update.update_id, message=update.message)
        # Викликаємо твою функцію start (вона сама віддасть кнопки)
        await start(update, context)

    return ConversationHandler.END



async def safe_edit_or_send(query, text, reply_markup=None, parse_mode=None, force_new=False):
    try:
        if not force_new:
            await query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            return
        # Якщо force_new → одразу видаляємо і кидаємо нове
        await query.message.delete()
    except Exception as e:
        if "Message is not modified" not in str(e):
            try:
                await query.message.delete()
            except Exception:
                pass
    # Надсилаємо нове повідомлення
    await query.message.reply_text(
        text,
        reply_markup=reply_markup,
        parse_mode=parse_mode
    )

async def safe_answer(query, text=None, show_alert=False):
    try:
        await query.answer(text=text, show_alert=show_alert)
    except Exception:
        pass

async def auto_reactions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await safe_answer(query)

    # очистимо попередні дані, щоб не лишались старі chat_id чи mode
    context.user_data.clear()

    await safe_edit_or_send(
        query,
        "Select auto-reaction mode:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Auto (random)", callback_data="auto_random")],
            [InlineKeyboardButton("Manual setup", callback_data="auto_manual")],
            [InlineKeyboardButton("⬅️ Back", callback_data="start")]
        ]),
    )

    return AUTO_CHAT_ID


async def choose_auto_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "auto_random":
        context.user_data["reaction_mode"] = "random"
        await safe_edit_or_send(query, "Enter chat ID for auto-reactions:")
        return AUTO_CHAT_ID

    elif query.data == "auto_manual":
        context.user_data["reaction_mode"] = "manual"
        await safe_edit_or_send(query, "Enter the chat ID for manual reactions:")
        return AUTO_CHAT_ID


async def handle_auto_chat_id_reactions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.message.text.strip()
    context.user_data['auto_chat_id'] = chat_id
    await update.message.reply_text("Enter reactions (e.g., 👍,❤️,🔥):")
    return AUTO_REACTION


async def set_auto_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from utils import normalize_chat_id

    reactions_input = update.message.text.strip()
    reactions = [normalize_emoji(r.strip()) for r in reactions_input.split(",")]
    invalid_reactions = [r for r in reactions if r not in FREE_REACTIONS]
    if invalid_reactions:
        await update.message.reply_text(
            f"Invalid reactions: {', '.join(invalid_reactions)}. Supported: {' '.join(FREE_REACTIONS.keys())}"
        )
        return AUTO_REACTION

    raw_chat_id = context.user_data['auto_chat_id']
    chat_id = normalize_chat_id(raw_chat_id)

    if context.user_data.get("reaction_mode") == "random":
        reactions_str = "mode=random;" + ",".join(reactions)
        await with_db_connection(
            "INSERT OR REPLACE INTO auto_reactions (chat_id, reaction) VALUES (?, ?)",
            (chat_id, reactions_str)
        )
        await update.message.reply_text(f"✅ Auto-random reactions set: {','.join(reactions)}")
        await auto_manager.update_event_handlers()
        return ConversationHandler.END

    elif context.user_data.get("reaction_mode") == "manual":
        context.user_data["manual_reactions"] = reactions
        await update.message.reply_text(
            "Specify the quantity for each reaction (format: 👍:3, ❤️:2, 🔥:1)"
        )
        return AUTO_REACTION_COUNTS


async def set_manual_counts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    counts = {}
    try:
        for part in text.split(","):
            emoji, num = part.split(":")
            counts[normalize_emoji(emoji.strip())] = int(num.strip())
    except Exception:
        await update.message.reply_text("❌ Incorrect format. Example: 👍:3, ❤️:2, 🔥:1")
        return AUTO_REACTION_COUNTS

    context.user_data["manual_counts"] = counts
    keyboard = [
        [InlineKeyboardButton("Yes", callback_data="fill_random")],
        [InlineKeyboardButton("No", callback_data="fill_none")]
    ]
    await update.message.reply_text("Should other accounts post random reactions?",
                                    reply_markup=InlineKeyboardMarkup(keyboard))
    return AUTO_REACTION_RANDOM_FILL


async def finalize_manual_reactions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    raw_chat_id = context.user_data['auto_chat_id']
    from utils import normalize_chat_id
    chat_id = normalize_chat_id(raw_chat_id)

    fill_mode = "fill_random" if query.data == "fill_random" else "fill_none"
    counts = context.user_data["manual_counts"]

    reactions_str = "mode=manual;" + ";".join([f"{k}:{v}" for k, v in counts.items()]) + f";extra={fill_mode}"

    await with_db_connection(
        "INSERT OR REPLACE INTO auto_reactions (chat_id, reaction) VALUES (?, ?)",
        (chat_id, reactions_str)
    )
    await safe_edit_or_send(query, f"✅ Manual auto-reactions saved: {reactions_str}")
    await auto_manager.update_event_handlers()
    return ConversationHandler.END



async def cancel_auto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Auto-reaction setup canceled.")
    return ConversationHandler.END

async def add_auto_comments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Enter the chat ID for auto-comments:")
    return AUTO_CHAT_ID

# async def handle_auto_chat_id_comments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
#     chat_id = update.message.text.strip()
#     context.user_data['auto_chat_id'] = chat_id
#     keyboard = [[InlineKeyboardButton(lang, callback_data=f"lang_{lang}")] for lang in COMMENT_VOCABULARY.keys()]
#     keyboard.append([InlineKeyboardButton("Custom Comments", callback_data="custom_comments")])
#     await update.message.reply_text("Choose language or custom:", reply_markup=InlineKeyboardMarkup(keyboard))
#     return AUTO_COMMENTS
#
# async def set_auto_comments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
#     from utils import normalize_chat_id
#
#     raw_chat_id = context.user_data['auto_chat_id']
#     chat_id = normalize_chat_id(raw_chat_id)
#
#     # ---- Отримуємо реальну назву чату ----
#     client = next(iter(auto_manager.clients.values()), None)
#     chat_title = "Unknown"
#     chat_type = "channel"
#     if client:
#         try:
#             entity = await client.get_entity(int(chat_id))
#             chat_title = getattr(entity, "title", "Unknown")
#             chat_type = "channel" if getattr(entity, "broadcast", False) else "group"
#         except Exception as e:
#             logger.warning(f"Failed to fetch entity for {chat_id}: {e}")
#
#     # ---- Обробка callback або кастомних коментарів ----
#     if update.callback_query:
#         query = update.callback_query
#         await query.answer()
#         data = query.data
#
#         if data == "custom_comments":
#             context.user_data['comments_language'] = None
#             await query.message.reply_text("Enter custom comments, separated by | :")
#             return AUTO_COMMENTS
#         else:
#             language = data.split("_", 1)[1]
#             context.user_data['comments_language'] = language
#
#             if language in COMMENT_VOCABULARY:
#                 comments = COMMENT_VOCABULARY[language]
#                 comments_str = "|".join(comments)
#                 full_comments = f"{language}:{comments_str}"
#             else:
#                 await query.message.reply_text(
#                     f"⚠️ Language '{language}' not found in COMMENT_VOCABULARY."
#                 )
#                 return ConversationHandler.END
#
#     else:
#         comments_str = update.message.text.strip()
#         language = context.user_data.get('comments_language')
#
#         if language:
#             full_comments = f"{language}:{comments_str}"
#         else:
#             full_comments = comments_str
#
#     # ---- Запис у БД ----
#     await with_db_connection(
#         "INSERT OR REPLACE INTO auto_comments (chat_id, comments) VALUES (?, ?)",
#         (chat_id, full_comments)
#     )
#     await with_db_connection(
#         "INSERT OR IGNORE INTO subscriptions (account_id, chat_id, chat_title, chat_type) VALUES (?, ?, ?, ?)",
#         (1, chat_id, chat_title, chat_type)
#     )
#
#     lang_display = language if language else "Custom"
#     await (update.message or query.message).reply_text(
#         f"✅ Auto-comments set for {chat_title} ({chat_id}) ({lang_display}).",
#         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
#     )
#
#     await auto_manager.update_event_handlers()
#     return ConversationHandler.END


async def handle_auto_chat_id_comments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.message.text.strip()
    context.user_data['auto_chat_id'] = chat_id

    keyboard = [
        [InlineKeyboardButton("AI Generate", callback_data="ai_generate")],
        [InlineKeyboardButton("Custom", callback_data="custom_comments")]
    ]

    await update.message.reply_text("Choose comment type:", reply_markup=InlineKeyboardMarkup(keyboard))
    return AUTO_COMMENTS

async def set_auto_comments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from utils import normalize_chat_id
    raw_chat_id = context.user_data['auto_chat_id']
    chat_id = normalize_chat_id(raw_chat_id)

    client = next(iter(auto_manager.clients.values()), None)
    chat_title = "Unknown"
    chat_type = "channel"
    if client:
        try:
            entity = await client.get_entity(int(chat_id))
            chat_title = getattr(entity, "title", "Unknown")
            chat_type = "channel" if getattr(entity, "broadcast", False) else "group"
        except Exception as e:
            logger.warning(f"Failed to fetch entity for {chat_id}: {e}")

    # === Обробка callback ===
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        data = query.data

        if data == "ai_generate":
            await query.message.reply_text("⏳ Generating comments with AI, please wait...")
            logger.info("AI Generate button clicked. Starting request to Perplexity API...")

            try:
                comments = await asyncio.wait_for(generate_comments_binary_options(count=15), timeout=20)
                logger.info(f"AI response received: {comments}")
                if not comments:
                    await query.message.reply_text("❌ AI returned no comments.")
                    return ConversationHandler.END

                comments_str = "|".join(comments)
                full_comments = comments_str

            except asyncio.TimeoutError:
                logger.error("AI request timed out after 20 seconds")
                await query.message.reply_text("❌ AI request timed out. Try again later.")
                return ConversationHandler.END

            except Exception as e:
                logger.error(f"AI request failed: {e}", exc_info=True)
                await query.message.reply_text(f"❌ AI generation failed: {e}")
                return ConversationHandler.END


        elif data == "custom_comments":
            await query.message.reply_text("Enter custom comments, separated by | :")
            context.user_data['awaiting_custom'] = True
            return AUTO_COMMENTS

    # === Якщо користувач вводить свої коментарі ===
    elif context.user_data.get('awaiting_custom'):
        comments_str = update.message.text.strip()
        full_comments = comments_str
        context.user_data['awaiting_custom'] = False

    else:
        await update.message.reply_text("⚠️ Unexpected state. Try again.")
        return ConversationHandler.END

    # === Запис у БД ===
    await with_db_connection(
        "INSERT OR REPLACE INTO auto_comments (chat_id, comments) VALUES (?, ?)",
        (chat_id, full_comments)
    )
    await with_db_connection(
        "INSERT OR IGNORE INTO subscriptions (account_id, chat_id, chat_title, chat_type) VALUES (?, ?, ?, ?)",
        (1, chat_id, chat_title, chat_type)
    )

    await (update.message or query.message).reply_text(
        f"✅ Auto-comments set for {chat_title} ({chat_id}).",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
    )

    await auto_manager.update_event_handlers()
    return ConversationHandler.END


async def cancel_auto_comments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Auto-comment setup canceled.")
    return ConversationHandler.END

async def remove_auto_comments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    auto_comments = await with_db_connection("SELECT chat_id, comments FROM auto_comments", fetchall=True)
    if not auto_comments:
        await query.edit_message_text("No auto-comments to remove.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="manage_auto_comments")]]))
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(f"Chat {chat_id}", callback_data=f"remove_comment_{chat_id}")] for chat_id, _ in auto_comments]
    keyboard.append([InlineKeyboardButton("Back", callback_data="manage_auto_comments")])
    await query.edit_message_text("Select auto-comment to remove:", reply_markup=InlineKeyboardMarkup(keyboard))
    return 0

async def confirm_remove_auto_comments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    chat_id = query.data.split("_")[-1]
    await with_db_connection("DELETE FROM auto_comments WHERE chat_id = ?", (chat_id,))
    await query.edit_message_text(f"Auto-comments removed for chat {chat_id}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="manage_auto_comments")]]))
    await auto_manager.update_event_handlers()
    return ConversationHandler.END

async def manage_auto_reactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    auto_reactions = await with_db_connection("SELECT chat_id, reaction FROM auto_reactions", fetchall=True)

    chat_titles = {}
    client = next(iter(auto_manager.clients.values()), None)

    for chat_id, _ in auto_reactions:
        row = await with_db_connection("SELECT chat_title FROM subscriptions WHERE chat_id = ? LIMIT 1", (chat_id,))
        title = row[0] if row else "Unknown"

        if title == "Unknown" and client:
            try:
                entity = await client.get_entity(int(chat_id))
                title = getattr(entity, "title", "Unknown")
                # оновлюємо БД
                await with_db_connection(
                    "UPDATE subscriptions SET chat_title = ? WHERE chat_id = ?",
                    (title, chat_id)
                )
            except Exception as e:
                logger.warning(f"Could not resolve title for {chat_id}: {e}")

        chat_titles[chat_id] = title

    text = "Current Auto-Reactions:\n" + "\n".join(
        f"Chat {chat_id} ({chat_titles[chat_id]}): {reaction}" for chat_id, reaction in auto_reactions
    ) or "No auto-reactions set."

    keyboard = [
        [InlineKeyboardButton("Add Auto-Reaction", callback_data="auto_reactions")],
        [InlineKeyboardButton("Remove Auto-Reaction", callback_data="remove_auto_reaction")],
        [InlineKeyboardButton("Back to Main", callback_data="start")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def remove_auto_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    auto_reactions = await with_db_connection("SELECT chat_id, reaction FROM auto_reactions", fetchall=True)
    if not auto_reactions:
        await query.edit_message_text("No auto-reactions to remove.", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Back", callback_data="manage_auto_reactions")]]))
        return ConversationHandler.END
    chat_titles = {}
    for chat_id, _ in auto_reactions:
        title = await with_db_connection("SELECT chat_title FROM subscriptions WHERE chat_id = ? LIMIT 1", (chat_id,))
        chat_titles[chat_id] = title[0] if title else "Unknown"
    keyboard = [[InlineKeyboardButton(f"Chat {chat_id} ({chat_titles[chat_id]}): {reaction}",
                                      callback_data=f"remove_{chat_id}")] for chat_id, reaction in auto_reactions]
    keyboard.append([InlineKeyboardButton("Back", callback_data="manage_auto_reactions")])
    await query.edit_message_text("Select an auto-reaction to remove:", reply_markup=InlineKeyboardMarkup(keyboard))
    return 0

async def confirm_remove_auto_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    chat_id = query.data.split("_")[-1]
    await with_db_connection("DELETE FROM auto_reactions WHERE chat_id = ?", (chat_id,))
    accounts = await with_db_connection("SELECT account_id FROM subscriptions WHERE chat_id = ?", (chat_id,),
                                        fetchall=True)
    for (account_id,) in accounts:
        await with_db_connection(
            "INSERT INTO history (account_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
            (account_id, "remove_auto_reaction", f"Removed auto-reaction for chat {chat_id}",
             datetime.now().isoformat()),
        )
    await auto_manager.update_event_handlers()
    await query.edit_message_text(
        f"Auto-reaction removed for chat {chat_id}.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="manage_auto_reactions")]])
    )
    return ConversationHandler.END

async def set_reactions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    logger.info("set_reactions triggered with callback data: set_reactions")
    await query.edit_message_text(
        "Send message link (e.g., https://t.me/channel/123) and reactions (e.g., 👍,❤️,🔥) separated by a space. "
        "Use commas to separate multiple reactions (e.g., 👍,❤️,🔥)."
    )
    return REACTION_INPUT

async def handle_reaction_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        logger.warning("Received update with no message or text in handle_reaction_input")
        await update.message.reply_text(
            "Invalid format. Use: https://t.me/channel/123 👍,❤️,🔥"
        )
        return REACTION_INPUT

    text = update.message.text.strip()
    logger.info(f"Received reaction input: {text}")
    try:
        link, reactions_input = text.split(" ", 1)
        match = re.match(r"https://t\.me/([^/]+)/(\d+)", link)
        if not match:
            logger.warning(f"Invalid link format: {link}")
            await update.message.reply_text("Invalid link format. Use: https://t.me/channel/123")
            return REACTION_INPUT

        channel, msg_id = match.groups()
        chat_id = await with_db_connection("SELECT chat_id FROM subscriptions WHERE chat_title = ? LIMIT 1", (channel,))
        chat_id = chat_id[0] if chat_id else None

        if "," not in reactions_input:
            reaction_list = [normalize_emoji(r) for r in reactions_input]
            if len(reaction_list) > 1:
                logger.warning(f"Invalid reaction format: {reactions_input}")
                await update.message.reply_text(
                    "Please separate reactions with commas (e.g., 👍,❤️,🔥). "
                    f"Received: {reactions_input}\nSupported: {' '.join(FREE_REACTIONS.keys())}"
                )
                return REACTION_INPUT
            reactions = [normalize_emoji(reactions_input.strip())]
        else:
            reactions = [normalize_emoji(reaction.strip()) for reaction in reactions_input.split(",")]

        invalid_reactions = [r for r in reactions if r not in FREE_REACTIONS]
        if invalid_reactions:
            logger.warning(f"Invalid reactions received: {invalid_reactions}")
            await update.message.reply_text(
                f"Invalid reactions: {', '.join(invalid_reactions)}. "
                f"Please separate reactions with commas (e.g., 👍,❤️,🔥).\nSupported: {' '.join(FREE_REACTIONS.keys())}"
            )
            return REACTION_INPUT

        accounts = await with_db_connection("SELECT id FROM accounts", fetchall=True)
        if not accounts:
            logger.info("No accounts available for setting reactions")
            await update.message.reply_text("No accounts available.")
            return ConversationHandler.END

        total_accounts = len(accounts)
        status_msg = await update.message.reply_text(
            f"Setting reactions {reactions_input} on {link}...\nProgress: 0/{total_accounts}"
        )
        success_count = 0

        weights = [1.0 / len(reactions)] * len(reactions)
        reaction_assignments = random.choices(reactions, weights=weights, k=total_accounts)

        logger.info(f"Reaction distribution: {reaction_assignments}")

        settings = await get_settings(chat_id) or {
            'reaction_delay_min': REACTION_DELAY_MIN,
            'reaction_delay_max': REACTION_DELAY_MAX
        }

        for idx, (account_id,) in enumerate(accounts):
            client = auto_manager.clients.get(account_id)
            reaction = reaction_assignments[idx]
            if client and client.is_connected():
                try:
                    delay = random.uniform(settings['reaction_delay_min'], settings['reaction_delay_max'])
                    await asyncio.sleep(delay)
                    entity = await client.get_entity(f"@{channel}")
                    await client(SendReactionRequest(
                        peer=entity,
                        msg_id=int(msg_id),
                        reaction=[ReactionEmoji(emoticon=reaction)]
                    ))
                    success_count += 1
                    logger.info(f"Set reaction {reaction} on {channel}/{msg_id} for account {account_id}")
                    await with_db_connection(
                        "INSERT INTO history (account_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                        (account_id, "set_reaction", f"Set {reaction} on {channel}/{msg_id}",
                         datetime.now().isoformat()),
                    )
                except Exception as e:
                    logger.error(f"Failed to set reaction for account {account_id}: {e}")
            await status_msg.edit_text(
                f"Setting reactions {reactions_input} on {link}...\nProgress: {success_count}/{total_accounts}"
            )

        await status_msg.edit_text(
            f"Set reactions {reactions_input} on {link} for {success_count}/{total_accounts} accounts.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
        )
        return ConversationHandler.END
    except ValueError:
        logger.warning(f"Invalid input format: {text}")
        await update.message.reply_text(
            "Invalid format. Use: https://t.me/channel/123 👍,❤️,🔥"
        )
        return REACTION_INPUT
    except Exception as e:
        logger.error(f"Error setting reactions: {str(e)}")
        await update.message.reply_text(f"Error: {str(e)}")
        return REACTION_INPUT

async def cancel_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Reaction setup canceled.")
    return ConversationHandler.END

async def view_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    history = await with_db_connection(
        "SELECT a.phone, h.action, h.details, h.timestamp FROM history h JOIN accounts a ON h.account_id = a.id ORDER BY h.timestamp DESC LIMIT 10",
        fetchall=True,
    )
    text = "Recent History:\n" + "\n".join(
        [f"{phone}: {action} - {details} ({timestamp})" for phone, action, details, timestamp in
         history]) or "No history yet."
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("Back", callback_data="start")]]))

async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

async def set_manual_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Enter the chat ID for settings:")
    return SETTINGS_CHAT_ID

async def handle_settings_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.message.text.strip()
    context.user_data['settings_chat_id'] = chat_id
    await update.message.reply_text("Enter settings values (e.g., max_accounts:10 comment_count:5 comment_delay_min:5.3 comment_delay_max:15.6 reaction_delay_min:1.3 reaction_delay_max:3.1)")
    return SETTINGS_VALUES

async def handle_settings_values(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from utils import normalize_chat_id

    values_str = update.message.text.strip()
    settings = {}
    for part in values_str.split():
        if ':' not in part:
            await update.message.reply_text(f"❌ Invalid format: '{part}'. Use key:value.")
            return SETTINGS_VALUES
        key, value = part.split(':', 1)
        try:
            settings[key] = float(value) if '.' in value else int(value)
        except ValueError:
            await update.message.reply_text(f"❌ Invalid number for key '{key}': {value}")
            return SETTINGS_VALUES

    chat_id = normalize_chat_id(context.user_data['settings_chat_id'])
    await set_settings(
        chat_id,
        settings.get('max_accounts', MAX_COMMENTING_ACCOUNTS),
        settings.get('comment_count', 5),
        settings.get('comment_delay_min', COMMENT_DELAY_MIN),
        settings.get('comment_delay_max', COMMENT_DELAY_MAX),
        settings.get('reaction_delay_min', REACTION_DELAY_MIN),
        settings.get('reaction_delay_max', REACTION_DELAY_MAX)
    )
    await update.message.reply_text(
        f"✅ Settings updated for chat {chat_id}.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
    )
    return ConversationHandler.END


async def manage_comments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Enter the chat ID for comments (or 'global' for all):")
    return COMMENTS_CHAT_ID

async def manage_auto_comments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    auto_comments = await with_db_connection("SELECT chat_id, comments FROM auto_comments", fetchall=True)

    chat_titles = {}
    client = next(iter(auto_manager.clients.values()), None)

    for chat_id, _ in auto_comments:
        row = await with_db_connection("SELECT chat_title FROM subscriptions WHERE chat_id = ? LIMIT 1", (chat_id,))
        title = row[0] if row else "Unknown"

        if title == "Unknown" and client:
            try:
                entity = await client.get_entity(int(chat_id))
                title = getattr(entity, "title", "Unknown")
                await with_db_connection(
                    "UPDATE subscriptions SET chat_title = ? WHERE chat_id = ?",
                    (title, chat_id)
                )
            except Exception as e:
                logger.warning(f"Could not resolve title for {chat_id}: {e}")

        chat_titles[chat_id] = title

    text_lines = []
    for chat_id, comments in auto_comments:
        if comments and ":" in comments:
            language, comments_str = comments.split(":", 1)
        else:
            language = "Default"
            comments_str = comments or ""

        all_comments = [c.strip() for c in comments_str.split("|") if c.strip()]
        preview_comments = all_comments[:3]
        preview_text = ", ".join(preview_comments)
        if len(all_comments) > 3:
            preview_text += "..."

        text_lines.append(
            f"Chat {chat_id} ({chat_titles[chat_id]}): {language}: {preview_text}"
        )

    text = "Current Auto-Comments:\n" + "\n".join(text_lines) if text_lines else "No auto-comments set."
    keyboard = [
        [InlineKeyboardButton("Add Auto-Comments", callback_data="add_auto_comments")],
        [InlineKeyboardButton("Remove Auto-Comments", callback_data="remove_auto_comments")],
        [InlineKeyboardButton("Back to Main", callback_data="start")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_comments_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.message.text.strip()
    # Якщо global — записуємо рядок 'global', а не None
    context.user_data['comments_chat_id'] = chat_id if chat_id.lower() != 'global' else 'global'
    await update.message.reply_text("Enter the language (e.g., English, or custom):")
    return COMMENTS_LANGUAGE

async def handle_comments_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    language = update.message.text.strip()
    context.user_data['comments_language'] = language
    await update.message.reply_text("Enter comments, one per line:")
    return COMMENTS_TEXT

async def handle_comments_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    comments = [c.strip() for c in text.split('\n') if c.strip()]
    comments_str = '|'.join(comments)
    chat_id = context.user_data['comments_chat_id']
    language = context.user_data['comments_language']
    await set_comments(chat_id, language, comments_str)
    await update.message.reply_text(f"Comments updated for chat {chat_id or 'global'} in {language}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]]))
    return ConversationHandler.END
# ============================
# Manual Vote Handlers
# ============================

async def manual_vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Send the poll message link (example: https://t.me/c/123456789/47):")
    return POLL_LINK

async def handle_poll_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        num_accounts = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please send a valid number.")
        return POLL_ACCOUNTS

    chat_id = context.user_data['poll_chat_id']
    msg_id = context.user_data['poll_msg_id']
    option_bytes = context.user_data['poll_option_bytes']

    accounts = await with_db_connection(
        "SELECT account_id FROM subscriptions WHERE chat_id = ?",
        (chat_id,), fetchall=True
    )
    selected_accounts = random.sample(accounts, min(num_accounts, len(accounts))) if accounts else []

    for (account_id,) in selected_accounts:
        await auto_manager.poll_queue.put((account_id, chat_id, msg_id, option_bytes))

    await update.message.reply_text(
        f"Votes queued for {len(selected_accounts)} accounts on poll {chat_id}/{msg_id}.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
    )
    return ConversationHandler.END

async def handle_poll_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    link = update.message.text.strip()

    # Патерни для t.me/c/<id>/<msg> і t.me/<username>/<msg>
    match_c = re.match(r"https?://t\.me/c/(\d+)/(\d+)", link)
    match_u = re.match(r"https?://t\.me/([\w\d_]+)/(\d+)", link)

    if match_c:
        chat_id = int(match_c.group(1))
        msg_id = int(match_c.group(2))
    elif match_u:
        username = match_u.group(1)
        msg_id = int(match_u.group(2))
        first_client = next(iter(auto_manager.clients.values()), None)
        if not first_client:
            await update.message.reply_text("No active clients to fetch username chat ID.")
            return ConversationHandler.END
        try:
            entity = await first_client.get_entity(username)
            chat_id = abs(entity.id)
        except UserNotParticipantError:
            await update.message.reply_text("Bot/user is not a participant of this chat.")
            return ConversationHandler.END
    else:
        await update.message.reply_text("Invalid link format. Try again.")
        return POLL_LINK

    context.user_data['poll_chat_id'] = chat_id
    context.user_data['poll_msg_id'] = msg_id

    first_client = next(iter(auto_manager.clients.values()), None)
    if not first_client:
        await update.message.reply_text("No active clients to fetch poll options.")
        return ConversationHandler.END

    try:
        message = await first_client.get_messages(chat_id, ids=msg_id)
        if not message or not isinstance(message.media, MessageMediaPoll):
            await update.message.reply_text("Message does not contain a poll.")
            return ConversationHandler.END

        poll = message.media.poll

        # Збережемо info для multi-answer / quiz
        context.user_data['poll_multiple'] = poll.multiple_choice
        context.user_data['poll_quiz'] = bool(poll.quiz)
        context.user_data['poll_closed'] = poll.closed

        # Створюємо список кортежів (текст, bytes)
        poll_options = [(opt.text, opt.option) for opt in poll.answers]
        context.user_data['poll_options'] = poll_options

        # Формуємо додаткову інфу
        extra_info = []
        if poll.multiple_choice:
            extra_info.append("multiple answers allowed")
        if poll.quiz:
            extra_info.append("quiz mode")
        if poll.closed:
            extra_info.append("poll closed")
        context.user_data['poll_extra_info'] = extra_info

        # Красивий вивід
        opts_list = "\n".join([f"*{i + 1}.* {text}" for i, (text, _) in enumerate(poll_options)])
        await update.message.reply_text(
            f"📊 *Poll options:*\n{opts_list}"
            + (f"\n\nℹ️ {', '.join(extra_info)}" if extra_info else "")
            + "\n\nSend the option number to vote, `random`, or comma-separated numbers for multi-choice:",
            parse_mode="Markdown"
        )
        return POLL_OPTION

    except UserNotParticipantError:
        await update.message.reply_text("Bot/user is not a participant of this chat.")
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"Failed to fetch poll: {e}")
        return ConversationHandler.END

async def handle_poll_option(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text.strip().lower()
    poll_options = context.user_data.get('poll_options', [])
    multiple = context.user_data.get('poll_multiple', False)
    extra_info = context.user_data.get('poll_extra_info', [])

    chosen_opts = []

    if choice == "random":
        if multiple:
            count = random.randint(1, len(poll_options))
            chosen_opts = [opt_bytes for _, opt_bytes in random.sample(poll_options, count)]
        else:
            _, opt_bytes = random.choice(poll_options)
            chosen_opts = [opt_bytes]
    else:
        try:
            nums = [int(x.strip()) for x in choice.split(",") if x.strip().isdigit()]
            for n in nums:
                if 1 <= n <= len(poll_options):
                    chosen_opts.append(poll_options[n - 1][1])
        except ValueError:
            pass

    if not chosen_opts:
        await update.message.reply_text(
            "Invalid choice. Send a number, 'random', or comma-separated numbers for multi-choice."
        )
        return POLL_OPTION

    # Зберігаємо список bytes
    context.user_data['poll_option_bytes'] = chosen_opts

    # Показуємо варіанти ще раз
    opts_list = "\n".join([f"*{i + 1}.* {text}" for i, (text, _) in enumerate(poll_options)])
    await update.message.reply_text(
        f"📊 *Poll options:*\n{opts_list}"
        + (f"\n\nℹ️ {', '.join(extra_info)}" if extra_info else ""),
        parse_mode="Markdown"
    )

    await update.message.reply_text("How many accounts should vote?")
    return POLL_ACCOUNTS

# ============================
# Manual View Handlers
# ============================

async def manual_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 1: Ask user for the message link."""
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "Send the message link to view (example: https://t.me/c/123456789/47"
    )
    return VIEW_LINK

async def handle_view_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 2-3: Parse link and get chat_id/msg_id."""
    link = update.message.text.strip()

    # Match both private group/channel (t.me/c) and public username formats
    match_c = re.match(r"https?://t\.me/c/(\d+)/(\d+)", link)
    match_u = re.match(r"https?://t\.me/([\w\d_]+)/(\d+)", link)

    if match_c:
        chat_id = int(match_c.group(1))
        msg_id = int(match_c.group(2))
    elif match_u:
        username = match_u.group(1)
        msg_id = int(match_u.group(2))
        first_client = next(iter(auto_manager.clients.values()), None)
        if not first_client:
            await update.message.reply_text("No active clients to fetch username chat ID.")
            return ConversationHandler.END
        try:
            entity = await first_client.get_entity(username)
            chat_id = abs(entity.id)
        except Exception as e:
            await update.message.reply_text(f"Failed to get chat ID from username: {e}")
            return ConversationHandler.END
    else:
        await update.message.reply_text("Invalid link format. Try again.")
        return VIEW_LINK

    context.user_data['view_chat_id'] = chat_id
    context.user_data['view_msg_id'] = msg_id

    # Step 4: Ask number of accounts
    await update.message.reply_text(
        f"Link parsed successfully.\nChat ID: {chat_id}, Message ID: {msg_id}\n"
        f"How many accounts should view this message?"
    )
    return 1  # next state: VIEW_ACCOUNTS_COUNT

async def handle_view_accounts_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Step 5: Perform views immediately."""
    from telethon.tl.functions.messages import GetMessagesViewsRequest
    from telethon.errors import UserNotParticipantError, FloodWaitError

    try:
        num_accounts = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please send a valid number.")
        return 1

    chat_id = context.user_data['view_chat_id']
    msg_id = context.user_data['view_msg_id']

    accounts = await with_db_connection(
        "SELECT account_id FROM subscriptions WHERE chat_id = ?",
        (chat_id,), fetchall=True
    )

    if not accounts:
        await update.message.reply_text("No subscribed accounts found for this chat.")
        return ConversationHandler.END

    selected_accounts = random.sample(accounts, min(num_accounts, len(accounts)))
    success_count = 0

    for (account_id,) in selected_accounts:
        client = auto_manager.clients.get(account_id)
        if not client:
            continue
        try:
            await client(GetMessagesViewsRequest(
                peer=int(f"-100{chat_id}"),
                id=[msg_id],
                increment=True
            ))
            success_count += 1
            await with_db_connection(
                "INSERT INTO history (account_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                (account_id, "manual_view", f"Viewed {chat_id}/{msg_id}", datetime.now().isoformat())
            )
        except UserNotParticipantError:
            logger.warning(f"Account {account_id} not a participant of {chat_id}, skipping view")
        except FloodWaitError as e:
            logger.warning(f"Flood wait {e.seconds}s for account {account_id} on view")
        except Exception as e:
            logger.error(f"Manual view error for {account_id} on {chat_id}/{msg_id}: {e}")

    await update.message.reply_text(
        f"📈 Viewed {chat_id}/{msg_id} with {success_count}/{len(selected_accounts)} accounts.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
    )
    return ConversationHandler.END

async def _delayed_requeue(self, seconds, params):
    await asyncio.sleep(seconds)
    action_type, account_id, chat_id, msg_id = params
    if action_type == "view":
        await self.view_queue.put((account_id, chat_id, msg_id))


async def add_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("HTTP", callback_data="http")],
        [InlineKeyboardButton("SOCKS5", callback_data="socks5")],
    ]
    await query.edit_message_text("Select proxy type:", reply_markup=InlineKeyboardMarkup(keyboard))
    return PROXY_TYPE

async def handle_proxy_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    proxy_type = query.data
    context.user_data['proxy_type'] = proxy_type
    await query.edit_message_text("Enter proxy details (host:port:username:password):")
    return PROXY_DETAILS

async def handle_proxy_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    details = update.message.text.strip().split(':')
    if len(details) < 2:
        await update.message.reply_text("Invalid format. Use host:port:username:password")
        return PROXY_DETAILS
    host, port = details[:2]
    username, password = details[2:4] if len(details) > 2 else (None, None)
    proxy = {
        "type": context.user_data['proxy_type'],
        "host": host,
        "port": int(port),
        "username": username,
        "password": password
    }
    if await test_proxy(proxy):
        save_proxy(proxy)  # Додаємо до списку проксі
        await update.message.reply_text(
            "Proxy added successfully.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
        )
    else:
        await update.message.reply_text("Proxy test failed. Try again.")
        return PROXY_DETAILS
    return ConversationHandler.END

async def cancel_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Proxy setup canceled.")
    return ConversationHandler.END

async def unsub_all_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Enter the channel ID to unsubscribe all accounts:")
    return UNSUB_CHANNEL_ID

# handlers.py
async def handle_unsub_channel_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    channel_id = normalize_chat_id(update.message.text.strip())

    # Get unique account_ids for the given chat_id, excluding banned accounts
    accounts = await with_db_connection(
        "SELECT DISTINCT s.account_id FROM subscriptions s JOIN accounts a ON s.account_id = a.id WHERE s.chat_id = ? AND (a.banned IS NULL OR a.banned = 0)",
        (channel_id,), fetchall=True
    )
    total_accounts = len(accounts)

    if total_accounts == 0:
        await update.message.reply_text(
            "No valid accounts subscribed to this channel.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
        )
        return ConversationHandler.END

    status_msg = await update.message.reply_text(
        f"Unsubscribing {total_accounts} accounts...\nProgress: 0/{total_accounts}")
    success_count = 0

    for (account_id,) in accounts:
        client = auto_manager.clients.get(account_id)
        if not client:
            logger.warning(f"Client for account {account_id} not found, skipping.")
            continue

        try:
            # Check if the account is actually subscribed to the channel
            entity = await client.get_entity(int(f"-100{channel_id}"))
            # If get_entity succeeds, the account has access to the channel (implies subscription)
            await client(LeaveChannelRequest(entity))
            await with_db_connection(
                "DELETE FROM subscriptions WHERE account_id = ? AND chat_id = ?",
                (account_id, channel_id)
            )
            success_count += 1
            new_text = f"Unsubscribing...\nProgress: {success_count}/{total_accounts}"
            if status_msg.text != new_text:
                try:
                    await status_msg.edit_text(new_text)
                except Exception as e:
                    if "Message is not modified" not in str(e):
                        logger.error(f"Failed to edit status message: {str(e)}")
        except (ChannelInvalidError, ChannelPrivateError):
            # Account is not subscribed or banned from the channel
            await with_db_connection(
                "DELETE FROM subscriptions WHERE account_id = ? AND chat_id = ?",
                (account_id, channel_id)
            )
            logger.info(
                f"Account {account_id} not subscribed or banned from channel {channel_id}, removed from subscriptions.")
        except Exception as e:
            logger.error(f"Failed to unsubscribe account {account_id} from channel {channel_id}: {str(e)}")

    final_text = f"Unsubscribed {success_count}/{total_accounts} accounts."
    try:
        await status_msg.edit_text(
            final_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])
        )
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Failed to edit final status message: {str(e)}")

    return ConversationHandler.END

async def cancel_unsub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Unsubscribe canceled.")
    return ConversationHandler.END

async def delete_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_id = int(query.data.split("_")[-1])
    subs = await with_db_connection("SELECT chat_id, chat_title FROM subscriptions WHERE account_id = ?", (account_id,), fetchall=True)
    keyboard = [[InlineKeyboardButton(chat_title, callback_data=f"del_sub_{account_id}_{chat_id}")] for chat_id, chat_title in subs]
    keyboard.append([InlineKeyboardButton("Delete All Subs", callback_data=f"del_all_subs_{account_id}")])
    keyboard.append([InlineKeyboardButton("Back", callback_data=f"view_account_{account_id}")])
    await query.edit_message_text("Select subscription to delete:", reply_markup=InlineKeyboardMarkup(keyboard))

async def confirm_delete_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, account_id, chat_id = query.data.split("_")
    client = auto_manager.clients.get(int(account_id))
    if client:
        try:
            entity = await client.get_entity(int(f"-100{chat_id}"))
            await client(LeaveChannelRequest(entity))
            await with_db_connection("DELETE FROM subscriptions WHERE account_id = ? AND chat_id = ?", (account_id, chat_id))
        except Exception as e:
            logger.error(f"Failed to delete sub {chat_id} for {account_id}: {e}")
    await query.edit_message_text("Subscription deleted.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"view_account_{account_id}")]]))

async def delete_all_subs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_id = int(query.data.split("_")[-1])
    subs = await with_db_connection("SELECT chat_id FROM subscriptions WHERE account_id = ?", (account_id,), fetchall=True)
    client = auto_manager.clients.get(account_id)
    if client:
        for (chat_id,) in subs:
            try:
                entity = await client.get_entity(int(f"-100{chat_id}"))
                await client(LeaveChannelRequest(entity))
            except Exception as e:
                logger.error(f"Failed to delete sub {chat_id} for {account_id}: {e}")
    await with_db_connection("DELETE FROM subscriptions WHERE account_id = ?", (account_id,))
    await query.edit_message_text("All subscriptions deleted.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=f"view_account_{account_id}")]]))


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if update.message:
        await update.message.reply_text("An error occurred. Please try again.")
    elif update.callback_query:
        await update.callback_query.answer("An error occurred. Please try again.", show_alert=True)
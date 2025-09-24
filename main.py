# main.py
import logging
import os
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TimedOut
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from database import init_db, check_and_remove_duplicate_subscriptions
from handlers import (
    start, handle_file, process_files, add_sub, handle_sub_link, handle_sub_id, cancel,
    auto_reactions, handle_auto_chat_id_reactions, set_auto_reaction, cancel_auto,
    set_reactions, handle_reaction_input, cancel_reaction, remove_auto_reaction,
    confirm_remove_auto_reaction, unsub_all_channel, handle_unsub_channel_id, cancel_unsub,
    add_proxy, handle_proxy_type, handle_proxy_details, cancel_proxy, add_accounts,
    view_accounts, view_account, delete_sub, confirm_delete_sub, delete_all_subs,
    manage_subs, view_history, reaction_info, manage_auto_reactions,
    restart_bot, noop,
    # New handlers
    set_manual_settings, handle_settings_chat_id, handle_settings_values,
    manage_comments, handle_comments_chat_id, handle_comments_language, handle_comments_text,
    manual_vote, handle_poll_option,
    manual_view, handle_view_link,
    add_auto_comments, set_auto_comments, handle_auto_chat_id_comments, cancel_auto_comments,
    remove_auto_comments, confirm_remove_auto_comments, manage_auto_comments, handle_poll_link, handle_poll_accounts,
    handle_view_accounts_count, choose_auto_mode,
    finalize_manual_reactions, set_manual_counts
)
from config import (BOT_TOKEN, BOT_NAME, CHANNEL_ID, INVITE_LINK, CHAT_ID, AUTO_CHAT_ID, AUTO_REACTION,
                    VIEW_LINK, POLL_ACCOUNTS, POLL_OPTION, POLL_LINK, COMMENTS_TEXT, COMMENTS_LANGUAGE,
                    COMMENTS_CHAT_ID, SETTINGS_VALUES, SETTINGS_CHAT_ID, AUTO_COMMENTS, PROXY_DETAILS,
                    PROXY_TYPE, UNSUB_CHANNEL_ID, AUTO_REACTION_COUNTS, AUTO_REACTION_RANDOM_FILL, REACTION_INPUT,
                    )
from telegram_client import load_existing_sessions
from utils import logger, TelegramHandler
from auto_manager import auto_manager

async def startup(application: Application):
    init_db()  # ініціалізація бази даних
    await auto_manager.start_clients()
    await check_and_remove_duplicate_subscriptions()

    # Ініціалізація бота для Telegram
    bot = application.bot

    # Налаштовуємо TelegramHandler для відправки повідомлень
    telegram_handler = TelegramHandler(bot, CHANNEL_ID)
    telegram_handler.setLevel(logging.DEBUG)
    logger.addHandler(telegram_handler)

    max_retries = 5
    for attempt in range(max_retries):
        try:
            bot_info = await application.bot.get_me()
            logger.info(f"{BOT_NAME}: Bot started successfully as @{bot_info.username}")
            return
        except TimedOut as e:
            logger.warning(f"Timeout in get_me, attempt {attempt + 1}/{max_retries}: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            logger.error("Failed to connect to Telegram API after retries")
            raise

async def shutdown(application: Application):
    await auto_manager.shutdown()
    logger.info("Bot shut down successfully")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, SystemExit):
        logger.info("SystemExit caught in error handler, likely due to a bot restart request.")
        return
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.message:
        await update.message.reply_text(f"An error occurred: {str(context.error)}")
    elif update and update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(f"An error occurred: {str(context.error)}")

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(startup).post_shutdown(shutdown).build()

    sub_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_sub, pattern="add_sub")],
        states={
            INVITE_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sub_link)],
            CHAT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sub_id)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(start, pattern="^start$")],
        per_chat=True,
        per_user=True,
        per_message=False,
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )

    auto_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(auto_reactions, pattern="auto_reactions")],
        states={
            AUTO_CHAT_ID: [
                CallbackQueryHandler(choose_auto_mode, pattern="auto_random|auto_manual"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auto_chat_id_reactions)
            ],
            AUTO_REACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_auto_reaction)],
            AUTO_REACTION_COUNTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_manual_counts)],
            AUTO_REACTION_RANDOM_FILL: [CallbackQueryHandler(finalize_manual_reactions, pattern="fill_random|fill_none")],
        },
        fallbacks=[CommandHandler("cancel", cancel_auto), CallbackQueryHandler(start, pattern="^start$")],
        per_chat=True,
        per_user=True,
        per_message=False,
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )

    reaction_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_reactions, pattern="set_reactions")],
        states={REACTION_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reaction_input)]},
        fallbacks=[CommandHandler("cancel", cancel_reaction), CallbackQueryHandler(start, pattern="^start$")],
        per_chat=True,
        per_user=True,
        per_message=False,
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )

    remove_auto_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(remove_auto_reaction, pattern="remove_auto_reaction")],
        states={0: [CallbackQueryHandler(confirm_remove_auto_reaction, pattern=r"remove_\d+")]} ,
        fallbacks=[CallbackQueryHandler(start, pattern="^start$")],
        per_message=False,
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )

    unsub_all_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(unsub_all_channel, pattern="unsub_all_channel")],
        states={UNSUB_CHANNEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unsub_channel_id)]},
        fallbacks=[CommandHandler("cancel", cancel_unsub), CallbackQueryHandler(start, pattern="^start$")],
        per_chat=True,
        per_user=True,
        per_message=False,
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )

    proxy_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_proxy, pattern="add_proxy")],
        states={
            PROXY_TYPE: [CallbackQueryHandler(handle_proxy_type, pattern="^(http|socks5)$")],
            PROXY_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_proxy_details)],
        },
        fallbacks=[CommandHandler("cancel", cancel_proxy), CallbackQueryHandler(start, pattern="^start$")],
        per_chat=True,
        per_user=True,
        per_message=False,
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )

    auto_comment_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_auto_comments, pattern="add_auto_comments")],
        states={
            AUTO_CHAT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auto_chat_id_comments)],
            AUTO_COMMENTS: [
                CallbackQueryHandler(set_auto_comments, pattern=r"ai_generate|custom_comments"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_auto_comments)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_auto_comments), CallbackQueryHandler(start, pattern="^start$")],
        per_chat=True,
        per_user=True,
        per_message=False,
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )

    remove_auto_comment_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(remove_auto_comments, pattern="remove_auto_comments")],
        states={0: [CallbackQueryHandler(confirm_remove_auto_comments, pattern=r"remove_comment_\d+")]} ,
        fallbacks=[CallbackQueryHandler(start, pattern="^start$")],
        per_message=False,
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )

    settings_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_manual_settings, pattern="set_settings")],
        states={
            SETTINGS_CHAT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings_chat_id)],
            SETTINGS_VALUES: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings_values)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(start, pattern="^start$")],
        per_chat=True,
        per_user=True,
        per_message=False,
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )

    comments_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(manage_comments, pattern="manage_comments")],
        states={
            COMMENTS_CHAT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_comments_chat_id)],
            COMMENTS_LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_comments_language)],
            COMMENTS_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_comments_text)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(start, pattern="^start$")],
        per_chat=True,
        per_user=True,
        per_message=False,
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )

    poll_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(manual_vote, pattern="manual_vote")],
        states={
            POLL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_poll_link)],
            POLL_OPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_poll_option)],
            POLL_ACCOUNTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_poll_accounts)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(start, pattern="^start$")],
        per_chat=True,
        per_user=True,
        per_message=False,
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )

    view_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(manual_view, pattern="manual_view")],
        states={
            VIEW_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_view_link)],
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_view_accounts_count)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(start, pattern="^start$")],
        per_chat=True,
        per_user=True,
        per_message=False,
        map_to_parent={ConversationHandler.END: ConversationHandler.END}
    )

    app.add_handler(auto_comment_handler)
    app.add_handler(remove_auto_comment_handler)
    app.add_handler(settings_handler)
    app.add_handler(comments_handler)
    app.add_handler(poll_handler)
    app.add_handler(view_handler)
    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(CallbackQueryHandler(process_files, pattern="process_files"))
    app.add_handler(sub_handler)
    app.add_handler(auto_handler)
    app.add_handler(reaction_handler)
    app.add_handler(remove_auto_handler)
    app.add_handler(unsub_all_handler)
    app.add_handler(proxy_handler)
    app.add_handler(CallbackQueryHandler(start, pattern="start"))
    app.add_handler(CallbackQueryHandler(add_accounts, pattern="add_accounts"))
    app.add_handler(CallbackQueryHandler(view_accounts, pattern=r"view_accounts_\d+"))
    app.add_handler(CallbackQueryHandler(view_account, pattern=r"view_account_\d+"))
    app.add_handler(CallbackQueryHandler(delete_sub, pattern=r"delete_sub_\d+"))
    app.add_handler(CallbackQueryHandler(confirm_delete_sub, pattern=r"del_sub_\d+_\d+"))
    app.add_handler(CallbackQueryHandler(delete_all_subs, pattern=r"del_all_subs_\d+"))
    app.add_handler(CallbackQueryHandler(manage_subs, pattern="manage_subs"))
    app.add_handler(CallbackQueryHandler(view_history, pattern="view_history"))
    app.add_handler(CallbackQueryHandler(reaction_info, pattern="reaction_info"))
    app.add_handler(CallbackQueryHandler(manage_auto_reactions, pattern="manage_auto_reactions"))
    app.add_handler(CallbackQueryHandler(manage_auto_comments, pattern="manage_auto_comments"))

    app.add_handler(CallbackQueryHandler(restart_bot, pattern="restart_bot"))
    app.add_handler(CallbackQueryHandler(noop, pattern="noop"))

    logger.info("Starting polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

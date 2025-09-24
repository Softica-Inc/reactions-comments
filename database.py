# database.py
import sqlite3
import asyncio
from config import DB_FILE, DEFAULT_COMMENTS
from utils import logger

# Global database lock to serialize SQLite access
db_lock = asyncio.Lock()

def init_db():
    with sqlite3.connect(DB_FILE, timeout=120) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")   # швидше, ніж FULL
        conn.execute("PRAGMA busy_timeout = 120000") # 120 секунд очікування
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_path TEXT UNIQUE,
                phone TEXT,
                added_at TEXT,
                proxy TEXT,
                banned INTEGER DEFAULT 0,
                tg_id INTEGER  
            )"""
        )

        c.execute(
            """CREATE TABLE IF NOT EXISTS subscriptions (
                account_id INTEGER,
                chat_id TEXT,
                chat_title TEXT,
                chat_type TEXT,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                action TEXT,
                details TEXT,
                timestamp TEXT,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS auto_reactions (
                chat_id TEXT PRIMARY KEY,
                reaction TEXT
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS auto_comments (
                chat_id TEXT PRIMARY KEY,
                comments TEXT
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT,
                language TEXT,
                comments TEXT
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS settings (
                chat_id TEXT PRIMARY KEY,
                max_accounts INTEGER DEFAULT 10,
                comment_count INTEGER DEFAULT 5,
                comment_delay_min FLOAT DEFAULT 5.3,
                comment_delay_max FLOAT DEFAULT 15.6,
                reaction_delay_min FLOAT DEFAULT 1.3,
                reaction_delay_max FLOAT DEFAULT 3.1
            )"""
        )
        conn.commit()
    migrate_auto_reactions()



def migrate_auto_reactions():
    """Міграція таблиці auto_reactions: додає backup і оновлює формат reaction"""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=120)
        cur = conn.cursor()

        # 1. Додати колонку backup, якщо її ще нема
        try:
            cur.execute("ALTER TABLE auto_reactions ADD COLUMN reaction_backup TEXT;")
            logger.info("[+] Додано колонку reaction_backup")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                logger.info("[i] Колонка reaction_backup вже існує, пропускаємо")
            else:
                raise

        # 2. Скопіювати старі дані у backup
        cur.execute("UPDATE auto_reactions SET reaction_backup = reaction WHERE reaction_backup IS NULL;")
        if cur.rowcount > 0:
            logger.info(f"[+] Скопійовано {cur.rowcount} рядків у reaction_backup")

        # 3. Оновити записи без mode=
        cur.execute("UPDATE auto_reactions SET reaction = 'mode=random;' || reaction WHERE reaction NOT LIKE 'mode=%';")
        if cur.rowcount > 0:
            logger.info(f"[+] Оновлено {cur.rowcount} рядків у форматі mode=random")

        conn.commit()
        conn.close()
        logger.info("[✓] Міграція auto_reactions завершена")
    except Exception as e:
        logger.error(f"[x] Помилка міграції auto_reactions: {e}")
async def check_and_remove_duplicate_subscriptions():
    """
    Checks for and removes duplicate subscriptions and subscriptions for non-existent accounts in the subscriptions table.
    """
    try:
        # Identify duplicates
        duplicates = await with_db_connection(
            """
            SELECT account_id, chat_id, COUNT(*) as count
            FROM subscriptions
            GROUP BY account_id, chat_id
            HAVING count > 1
            """,
            fetchall=True
        )

        if duplicates:
            logger.info(f"Found {len(duplicates)} duplicate subscription entries")
            for account_id, chat_id, count in duplicates:
                logger.info(f"Duplicate found: account_id={account_id}, chat_id={chat_id}, count={count}")

            # Remove duplicates, keeping the earliest row (lowest rowid)
            await with_db_connection(
                """
                DELETE FROM subscriptions
                WHERE rowid NOT IN (
                    SELECT MIN(rowid)
                    FROM subscriptions
                    GROUP BY account_id, chat_id
                )
                """
            )
            logger.info("Removed duplicate subscriptions, keeping earliest entries")

        # Identify subscriptions for non-existent accounts
        invalid_accounts = await with_db_connection(
            """
            SELECT s.account_id, s.chat_id
            FROM subscriptions s
            LEFT JOIN accounts a ON s.account_id = a.id
            WHERE a.id IS NULL
            """,
            fetchall=True
        )

        if invalid_accounts:
            logger.info(f"Found {len(invalid_accounts)} subscriptions for non-existent accounts")
            for account_id, chat_id in invalid_accounts:
                logger.info(f"Invalid subscription: account_id={account_id}, chat_id={chat_id}")

            # Remove subscriptions for non-existent accounts
            await with_db_connection(
                """
                DELETE FROM subscriptions
                WHERE account_id NOT IN (SELECT id FROM accounts)
                """
            )
            logger.info("Removed subscriptions for non-existent accounts")

        # Verify remaining subscriptions
        total_subscriptions = (await with_db_connection(
            "SELECT COUNT(*) FROM subscriptions",
            fetchone=True
        ))[0]

        subscriptions_for_2892600861 = (await with_db_connection(
            "SELECT COUNT(*) FROM subscriptions WHERE chat_id = ?",
            ('2892600861',),
            fetchone=True
        ))[0]

        logger.info(f"Total subscriptions after cleanup: {total_subscriptions}")
        logger.info(f"Subscriptions for chat 2892600861: {subscriptions_for_2892600861}")

    except Exception as e:
        logger.error(f"Error checking/removing duplicate or invalid subscriptions: {str(e)}")


# async def with_db_connection(query, params=(), fetchall=False):
#     async with db_lock:
#         try:
#             with sqlite3.connect(DB   _FILE, timeout=120) as conn:
#                 conn.execute("PRAGMA journal_mode=WAL")
#                 conn.execute("PRAGMA busy_timeout = 120000")
#                 c = conn.cursor()
#                 c.execute(query, params)
#                 result = c.fetchall() if fetchall else c.fetchone()
#                 conn.commit()
#                 return result
#         except sqlite3.OperationalError as e:
#             logger.error(f"Database error: {e}")
#             await asyncio.sleep(1)
#             raise




async def with_db_connection(query, params=(), fetchone=False, fetchall=False, many=False):
    """
    Універсальний асинхронний метод для роботи з SQLite.
    - блокує доступ через asyncio.Lock
    - робить повторні спроби при помилці "database is locked"
    - підтримує fetchone, fetchall та executemany
    """
    retries = 5
    delay = 0.5

    for attempt in range(retries):
        async with db_lock:
            try:
                with sqlite3.connect(DB_FILE, timeout=120) as conn:
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA busy_timeout = 120000")
                    c = conn.cursor()

                    if many:
                        c.executemany(query, params)
                    else:
                        c.execute(query, params)

                    result = None
                    if fetchall:
                        result = c.fetchall()
                    elif fetchone:
                        result = c.fetchone()

                    conn.commit()
                    return result

            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < retries - 1:
                    logger.warning(f"[DB] Locked, retry {attempt+1}/{retries} ...")
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                logger.error(f"[DB] SQLite error: {e}")
                raise





# New function for comments management
# async def get_comments(chat_id, language=None):
#     # 1️⃣ Перевіряємо кастомні коментарі (comments)
#     if language:
#         row = await with_db_connection(
#             "SELECT comments FROM comments WHERE chat_id = ? AND language = ?",
#             (chat_id, language)
#         )
#     else:
#         row = await with_db_connection(
#             "SELECT comments FROM comments WHERE chat_id = ?",
#             (chat_id,)
#         )
#
#     if row and row[0] and row[0].strip():
#         return row[0].split("|")
#
#     # 2️⃣ Якщо нема — перевіряємо auto_comments
#     auto_row = await with_db_connection(
#         "SELECT comments FROM auto_comments WHERE chat_id = ?",
#         (chat_id,)
#     )
#
#     if auto_row and auto_row[0] and auto_row[0].strip():
#         # Якщо мова задана — фільтруємо по мові (формат: 'Испанский:...')
#         if language and ":" in auto_row[0]:
#             lang_prefix = f"{language}:"
#             if auto_row[0].startswith(lang_prefix):
#                 comments_str = auto_row[0][len(lang_prefix):]
#                 return comments_str.split("|")
#         else:
#             return auto_row[0].split("|")
#
#     # 3️⃣ Якщо нічого не знайшли — fallback
#     return DEFAULT_COMMENTS

async def get_comments(chat_id):
    from config import DEFAULT_COMMENTS
    result = await with_db_connection(
        "SELECT comments FROM auto_comments WHERE chat_id = ?",
        (chat_id,), fetchall=True
    )
    if result and len(result) > 0:
        comment_str = result[0][0]
        # Strip language prefix (e.g., "English:", "Ukrainian:", etc.)
        for prefix in ['English:', 'Ukrainian:', 'Russian:', 'Spanish:']:  # Add other prefixes as needed
            if comment_str.startswith(prefix):
                comment_str = comment_str[len(prefix):]
                break
        # Split by '|' and clean up
        return [c.strip() for c in comment_str.split('|') if c.strip()]
    logger.info(f"No comments found for chat {chat_id}, using defaults")
    # Clean defaults similarly if they have prefixes
    default_comments = DEFAULT_COMMENTS
    for prefix in ['English:', 'Ukrainian:', 'Russian:', 'Spanish:']:
        if default_comments.startswith(prefix):
            default_comments = default_comments[len(prefix):]
            break
    return [c.strip() for c in default_comments.split('|') if c.strip()]

# async def get_comments(chat_id, language=None):
#     # 1️⃣ Перевіряємо кастомні (ручні) коментарі
#     if language:
#         row = await with_db_connection(
#             "SELECT comments FROM comments WHERE chat_id = ? AND language = ?",
#             (chat_id, language)
#         )
#     else:
#         row = await with_db_connection(
#             "SELECT comments FROM comments WHERE chat_id = ?",
#             (chat_id,)
#         )
#
#     manual_comments = []
#     if row and row[0] and row[0].strip():
#         manual_comments = row[0].split("|")
#
#     # 2️⃣ Перевіряємо авто-коментарі
#     auto_row = await with_db_connection(
#         "SELECT comments FROM auto_comments WHERE chat_id = ?",
#         (chat_id,)
#     )
#
#     auto_comments = []
#     if auto_row and auto_row[0] and auto_row[0].strip():
#         auto_str = auto_row[0]
#         if language and ":" in auto_str:
#             lang_prefix = f"{language}:"
#             if auto_str.startswith(lang_prefix):
#                 auto_str = auto_str[len(lang_prefix):]
#         auto_comments = auto_str.split("|")
#
#     # 3️⃣ Синхронізація між ручними та авто
#     if manual_comments:
#         # якщо в ручних є нові — оновлюємо auto_comments
#         merged = list(dict.fromkeys(manual_comments + auto_comments))  # зберігає порядок і унікальність
#         await with_db_connection(
#             "REPLACE INTO auto_comments (chat_id, comments) VALUES (?, ?)",
#             (chat_id, "|".join(merged))
#         )
#         return manual_comments
#
#     elif auto_comments:
#         # якщо ручних немає — копіюємо з авто у ручні
#         await with_db_connection(
#             "REPLACE INTO comments (chat_id, comments) VALUES (?, ?)",
#             (chat_id, "|".join(auto_comments))
#         )
#         return auto_comments
#
#     # 4️⃣ Фолбек
#     return DEFAULT_COMMENTS



async def set_comments(chat_id, language, comments_str):
    await with_db_connection(
        "INSERT OR REPLACE INTO comments (chat_id, language, comments) VALUES (?, ?, ?)",
        (chat_id, language, comments_str)
    )

# New function for settings
async def get_settings(chat_id):
    row = await with_db_connection("SELECT max_accounts, comment_count, comment_delay_min, comment_delay_max, reaction_delay_min, reaction_delay_max FROM settings WHERE chat_id = ?", (chat_id,))
    if not row:
        return None
    return {
        "max_accounts": row[0],
        "comment_count": row[1],
        "comment_delay_min": row[2],
        "comment_delay_max": row[3],
        "reaction_delay_min": row[4],
        "reaction_delay_max": row[5],
    }


async def set_settings(chat_id, max_accounts, comment_count, comment_delay_min, comment_delay_max, reaction_delay_min, reaction_delay_max):
    await with_db_connection(
        "INSERT OR REPLACE INTO settings (chat_id, max_accounts, comment_count, comment_delay_min, comment_delay_max, reaction_delay_min, reaction_delay_max) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (chat_id, max_accounts, comment_count, comment_delay_min, comment_delay_max, reaction_delay_min, reaction_delay_max)
    )
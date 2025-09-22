# telegram_client.py
import os
import asyncio
import zipfile
import rarfile
import sqlite3
import json

import socks
from telethon import TelegramClient
from telethon.errors import (
    UserDeactivatedError, AuthKeyDuplicatedError, PhoneNumberBannedError
)
from telethon.sessions import MemorySession

from config import API_ID, API_HASH, ZIP_RAR_DIR, EXTRACT_BASE_DIR, CLIENT_CONNECTION_TIMEOUT, DB_FILE
from database import with_db_connection
from utils import logger, get_single_proxy, normalize_chat_id, load_proxies
from datetime import datetime
import patoolib

session_lock = asyncio.Lock()
client_connection_lock = asyncio.Lock()

async def extract_archive(archive_path, extract_dir):
    os.makedirs(extract_dir, exist_ok=True)
    try:
        if archive_path.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zip_ref:
                zip_ref.extractall(extract_dir)
        elif archive_path.endswith(".rar"):
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: patoolib.extract_archive(archive_path, outdir=extract_dir))
        else:
            logger.error(f"Unsupported archive format: {archive_path}")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to extract {archive_path}: {str(e)}")
        return False


def get_session_files(directory):
    session_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".session"):
                session_files.append(os.path.join(root, file))
    return session_files


def proxy_to_requests(proxy):
    """
    Конвертує Telethon proxy tuple у requests proxy dict.
    """
    if not proxy:
        return None
    if isinstance(proxy, tuple):
        scheme = "socks5" if proxy[0] == 2 else "http"
        auth = ""
        if len(proxy) >= 6 and proxy[4] and proxy[5]:
            auth = f"{proxy[4]}:{proxy[5]}@"
        return {
            "http": f"{scheme}://{auth}{proxy[1]}:{proxy[2]}",
            "https": f"{scheme}://{auth}{proxy[1]}:{proxy[2]}"
        }
    return None




async def get_client(session_path, account_id=None, proxy=None):
    from telethon import TelegramClient
    from telethon.errors import (
        UserDeactivatedError, AuthKeyDuplicatedError,
        PhoneNumberBannedError, SessionPasswordNeededError
    )
    from config import API_ID, API_HASH, CLIENT_CONNECTION_TIMEOUT
    from utils import logger, get_single_proxy, load_proxies
    from database import with_db_connection
    import sqlite3, json, socks, os, random, string, requests, asyncio

    max_retries = 5
    proxies = load_proxies()
    proxy_index = 0

    # ===== 1. Якщо задано proxy з rotate_url → викликаємо API для ротації мобільного IP =====
    def rotate_mobile_proxy(p):
        try:
            if isinstance(p, dict) and p.get("rotate_url"):
                r = requests.post(p["rotate_url"], timeout=15)
                logger.info(f"Triggered mobile proxy rotation via {p['rotate_url']} -> status {r.status_code}")
        except Exception as e:
            logger.error(f"Failed to rotate mobile proxy {p}: {e}")

    # ===== 2. Додаємо session-id для backconnect проксі =====
    def with_random_session_id(p):
        if isinstance(p, dict) and p.get("username"):
            sid = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
            p = dict(p)  # робимо копію
            p["username"] = f"{p['username']}-session-{sid}"
        return p

    if proxy is None:
        if proxies:
            working_proxy = None
            for i, p in enumerate(proxies):
                p = with_random_session_id(p)
                rotate_mobile_proxy(p)
                if await test_proxy(p):
                    working_proxy = p
                    proxy_index = i
                    break
            if working_proxy:
                proxy = working_proxy
                logger.info(f"Using working proxy {proxy} for {session_path}")
            else:
                proxy = None
                logger.warning(f"No working proxy found. Using direct connection for {session_path}")
        else:
            proxy = None
            logger.info(f"No proxies defined. Using direct connection for {session_path}")

    # Приводимо у tuple
    if isinstance(proxy, dict):
        proxy = with_random_session_id(proxy)
        rotate_mobile_proxy(proxy)
        proxy_type = socks.SOCKS5 if proxy["type"] == "socks5" else socks.HTTP
        proxy = (proxy_type, proxy["host"], int(proxy["port"]), proxy.get("username"), proxy.get("password"))

    for attempt in range(max_retries):
        async with session_lock:
            try:
                client = TelegramClient(session_path, API_ID, API_HASH, proxy=proxy)
                logger.info(f"[{attempt+1}/{max_retries}] Connecting client for {session_path} with proxy {proxy}")
                await asyncio.wait_for(client.connect(), timeout=CLIENT_CONNECTION_TIMEOUT)

                # ===== Перевірка авторизації =====
                authorized = await asyncio.wait_for(client.is_user_authorized(), timeout=CLIENT_CONNECTION_TIMEOUT)
                if not authorized:
                    session_dir = os.path.dirname(session_path)
                    password_file = os.path.join(session_dir, "pass.txt")

                    # Якщо є файл з паролем → пробуємо тільки у випадку, якщо акаунт вже колись логінився
                    if os.path.exists(password_file):
                        try:
                            with open(password_file, "r", encoding="utf-8") as f:
                                password = f.read().strip()
                            await client.start(password=password)
                            logger.info(f"Client for {session_path} authorized with 2FA.")
                            return client
                        except Exception as e:
                            logger.error(f"Failed 2FA login for {session_path}: {e}")
                            await client.disconnect()
                            return None
                    else:
                        logger.warning(
                            f"Skipping account {account_id or session_path}: session not authorized (needs phone/token).")
                        await client.disconnect()
                        return None

                # ===== Перевіряємо та логуємо зовнішній IP =====
                try:
                    r_proxies = proxy_to_requests(proxy)
                    ip = requests.get("https://api.ipify.org", proxies=r_proxies, timeout=15).text
                    logger.info(f"External IP for account {account_id or '?'}: {ip}")
                except Exception as e:
                    logger.error(f"Failed to fetch external IP: {e}")

                logger.info(f"Client for {session_path} is authorized.")
                return client

            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    logger.warning(f"Database locked for {session_path}, attempt {attempt + 1}/{max_retries}. Retrying...")
                    await asyncio.sleep(2 ** attempt)
                    continue
                logger.error(f"Failed to connect to {session_path} after {max_retries} attempts: {e}")
                if 'client' in locals() and client.is_connected():
                    await client.disconnect()
                return None

            except asyncio.TimeoutError:
                logger.warning(f"Timeout while connecting to {session_path} (attempt {attempt+1}/{max_retries})")
                if 'client' in locals() and client.is_connected():
                    await client.disconnect()
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None

            except (UserDeactivatedError, AuthKeyDuplicatedError, PhoneNumberBannedError) as e:
                logger.warning(f"Account for {session_path} is banned: {e}. Skipping.")
                if account_id:
                    await with_db_connection("DELETE FROM accounts WHERE id = ?", (account_id,))
                    logger.info(f"Removed banned account {account_id} from database.")
                if 'client' in locals() and client.is_connected():
                    await client.disconnect()
                return None

            except Exception as e:
                logger.error(f"Failed to connect to {session_path}: {type(e).__name__}: {e}")
                if "proxy" in str(e).lower() or "authentication methods were rejected" in str(e).lower():
                    if proxy and proxy_index < len(proxies) - 1:
                        logger.warning(f"Proxy {proxy} failed. Trying next proxy...")
                        proxy_index += 1
                        proxy = get_single_proxy(proxy_index)
                        continue
                    logger.warning(f"Proxy {proxy} failed. Retrying without proxy.")
                    proxy = None
                    continue
                if 'client' in locals() and client.is_connected():
                    await client.disconnect()
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None




async def load_existing_sessions():
    proxies = load_proxies()

    # отримуємо всі акаунти
    accounts = await with_db_connection(
        "SELECT id, session_path FROM accounts WHERE banned IS NULL OR banned = 0",
        fetchall=True
    )

    for account_id, session_path in accounts:
        if not os.path.exists(session_path):
            logger.warning(f"Session file {session_path} for account {account_id} does not exist")

            await with_db_connection(
                "UPDATE accounts SET banned = 1 WHERE id = ?",
                (account_id,)
            )
            logger.info(f"Marked account {account_id} as banned due to missing session file")
            continue

        async with client_connection_lock:
            proxy = get_single_proxy(account_id) if proxies else None
            client = await get_client(session_path, account_id, proxy)
            if client:
                try:
                    await client.connect()
                    if await client.is_user_authorized():
                        me = await client.get_me()
                        phone = me.phone or "Unknown"
                        tg_id = me.id

                        dialogs = await client.get_dialogs()
                        subs = [
                            (account_id, normalize_chat_id(d.entity.id), d.entity.title,
                             "channel" if d.is_channel else "group")
                            for d in dialogs if d.is_channel or d.is_group
                        ]

                        # вставляємо підписки
                        if subs:
                            await with_db_connection(
                                "INSERT OR IGNORE INTO subscriptions (account_id, chat_id, chat_title, chat_type) VALUES (?, ?, ?, ?)",
                                subs,
                                many=True
                            )

                        # оновлюємо акаунт
                        await with_db_connection(
                            "INSERT OR REPLACE INTO accounts (id, session_path, phone, added_at, proxy, tg_id) VALUES (?, ?, ?, ?, ?, ?)",
                            (account_id, session_path, phone, datetime.now().isoformat(),
                             json.dumps(proxy) if proxy else None, tg_id)
                        )

                        logger.info(f"Loaded session {phone} with {len(subs)} subscriptions, proxy {proxy}")
                    else:
                        logger.info(f"Session {session_path} not authorized. Skipping.")

                except (UserDeactivatedError, AuthKeyDuplicatedError, PhoneNumberBannedError) as e:
                    logger.warning(f"Account {account_id} is banned: {str(e)}. Marking as banned.")

                    await with_db_connection(
                        "UPDATE accounts SET banned = 1 WHERE id = ?",
                        (account_id,)
                    )

                except Exception as e:
                    logger.error(f"Failed to load session {session_path}: {str(e)}")

                finally:
                    if 'client' in locals() and client and client.is_connected():
                        await client.disconnect()

async def test_proxy(proxy):
    from utils import logger
    from config import API_ID, API_HASH, CLIENT_CONNECTION_TIMEOUT
    from telethon import TelegramClient
    from telethon.sessions import MemorySession
    import sqlite3
    import socks

    if isinstance(proxy, dict):
        proxy_type = socks.SOCKS5 if proxy["type"] == "socks5" else socks.HTTP
        proxy = (proxy_type, proxy["host"], int(proxy["port"]), proxy.get("username"), proxy.get("password"))

    async with client_connection_lock:
        try:
            client = TelegramClient(MemorySession(), API_ID, API_HASH, proxy=proxy)
            logger.info(f"Testing proxy {proxy}")
            await asyncio.wait_for(client.connect(), timeout=CLIENT_CONNECTION_TIMEOUT)
            logger.info(f"Proxy {proxy} tested successfully.")
            await client.disconnect()
            return True
        except sqlite3.OperationalError as e:
            logger.error(f"Proxy {proxy} failed due to database error: {type(e).__name__}: {str(e)}")
            return False
        except asyncio.TimeoutError:
            logger.error(f"Proxy {proxy} timed out during connection test.")
            return False
        except Exception as e:
            logger.error(f"Proxy {proxy} failed: {type(e).__name__}: {str(e)}")
            if "authentication methods were rejected" in str(e).lower():
                logger.warning(f"SOCKS5 auth rejected for {proxy}. Try without credentials or a new proxy.")
            return False



async def view_post(client, peer, msg_id):
    await client.get_messages(peer, ids=msg_id)
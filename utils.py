# utils.py (updated proxy handling)
import os
import json
import logging
import time
import traceback
import aiohttp
import os
from dotenv import load_dotenv
from config import PPLX_API_KEY
import unicodedata
import socks
from datetime import datetime
from logging.handlers import RotatingFileHandler
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from config import LOGS_DIR, PROXY_FILE
import os
import time
from logging.handlers import RotatingFileHandler
from telegram import Bot
from telegram.error import TelegramError
from dotenv import load_dotenv
from datetime import datetime
import traceback
import logging
from telegram import Bot
from telegram.error import TelegramError

import asyncio


class TelegramHandler(logging.Handler):
    def __init__(self, bot: Bot, channel_id: str):
        super().__init__()
        self.bot = bot
        self.channel_id = channel_id

    def emit(self, record):
        # Пропускаємо DEBUG та INFO, обробляємо тільки WARNING та ERROR
        if record.levelno < logging.WARNING:
            return

        log_entry = self.format(record)

        # Якщо рівень помилки - додаємо теги
        if record.levelno == logging.ERROR:
            level_name = "ERROR"
            message = f"Bot: @{self.bot.username}\nLevel: {level_name}\n{log_entry}\n@softica_perceus @ystwa"
        else:  # Якщо рівень WARNING - не додаємо теги
            level_name = "WARNING"
            message = f"Bot: @{self.bot.username}\nLevel: {level_name}\n{log_entry}"

        try:
            # Використовуємо asyncio.create_task, замість asyncio.run
            asyncio.create_task(self._send_to_telegram(message))
        except TelegramError as e:
            print(f"Failed to send message to Telegram channel: {e}")
            print(f"Failed message: {log_entry}")

    async def _send_to_telegram(self, message: str):
        try:
            await self.bot.send_message(chat_id=self.channel_id, text=message)
            print(f"Sent log to Telegram channel: {message}")
        except Exception as e:
            print(f"Error sending message: {str(e)}")


# Ініціалізація логера
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Для тесту встановлюємо рівень DEBUG

# Створення обробників логування (файл та консоль)
file_handler = logging.FileHandler('logs/bot.log')
console_handler = logging.StreamHandler()

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Налаштування рівня логування для Telegram
logging.getLogger("telegram").setLevel(logging.DEBUG)
logging.getLogger("httpx").setLevel(logging.DEBUG)


def normalize_emoji(emoji: str) -> str:
    return unicodedata.normalize('NFC', emoji.strip())

def load_proxy():
    return load_proxies()  # Reuse load_proxies for consistency

def load_proxies():
    if not os.path.exists(PROXY_FILE):
        try:
            with open(PROXY_FILE, 'w') as f:
                json.dump([], f)
                f.flush()
            logger.info(f"Created empty proxies.json at {PROXY_FILE}")
            return []
        except PermissionError as e:
            logger.error(f"Permission denied creating {PROXY_FILE}: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Failed to create {PROXY_FILE}: {str(e)}")
            return []

    retries = 5
    for attempt in range(retries):
        try:
            file_size = os.path.getsize(PROXY_FILE)
            logger.info(f"Attempt {attempt + 1}: Proxy file size: {file_size} bytes")
            with open(PROXY_FILE, 'r') as f:
                content = f.read()
                if not content.strip():
                    logger.warning(f"Proxy file {PROXY_FILE} is empty, initializing as empty list")
                    return []
                proxies = json.loads(content)
                # logger.info(f"Loaded proxies: {proxies}")
                if proxies is None:
                    logger.warning(f"Proxy file {PROXY_FILE} contains null, initializing as empty list")
                    return []
                if not isinstance(proxies, list):
                    logger.warning(f"Proxy file {PROXY_FILE} contains invalid data ({type(proxies)}), initializing as empty list")
                    return []
                return proxies
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse {PROXY_FILE}: {str(e)}. Attempt {attempt + 1}/{retries}")
            if attempt < retries - 1:
                time.sleep(1)
                continue
            logger.error(f"Failed to parse {PROXY_FILE} after {retries} attempts. Initializing as empty list")
            return []
        except PermissionError as e:
            logger.error(f"Permission denied reading {PROXY_FILE}: {str(e)}. Attempt {attempt + 1}/{retries}")
            if attempt < retries - 1:
                time.sleep(1)
                continue
            logger.error(f"Failed to read {PROXY_FILE} after {retries} attempts due to permissions. Initializing as empty list")
            return []
        except Exception as e:
            logger.error(f"Error reading {PROXY_FILE}: {str(e)}. Attempt {attempt + 1}/{retries}")
            if attempt < retries - 1:
                time.sleep(1)
                continue
            logger.error(f"Failed to read {PROXY_FILE} after {retries} attempts. Initializing as empty list")
            return []

def save_proxy(proxy):
    proxies = load_proxies()
    if proxies is None:
        logger.warning(f"load_proxies returned None, initializing as empty list")
        proxies = []
    proxies.append(proxy)
    try:
        with open(PROXY_FILE, 'w') as f:
            json.dump(proxies, f, indent=4)
            f.flush()
        logger.info(f"Successfully saved proxy to {PROXY_FILE}")
    except PermissionError as e:
        logger.error(f"Permission denied writing to {PROXY_FILE}: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Failed to save proxy to {PROXY_FILE}: {str(e)}")
        raise

def get_single_proxy(index=None):
    proxies = load_proxies()
    if not proxies:
        logger.error("No proxies available in proxies.json")
        return None
    if index is None:
        logger.warning("Index not provided, defaulting to first proxy")
        proxy = proxies[0]
    else:
        proxy = proxies[(index - 1) % len(proxies)]

    try:
        if isinstance(proxy, dict):
            proxy_type = socks.SOCKS5 if proxy["type"] == "socks5" else socks.HTTP
            logger.info(f"Selected proxy for account {index}: {proxy_type}, {proxy['host']}:{proxy['port']}")
            return (proxy_type, proxy["host"], int(proxy["port"]), True,
                    proxy.get("username"), proxy.get("password"))
        elif isinstance(proxy, list):
            if len(proxy) < 3:
                logger.error(f"Invalid proxy format in proxies.json: {proxy}")
                return None
            proxy_type = socks.SOCKS5 if proxy[0].lower() == "socks5" else socks.HTTP
            logger.info(f"Selected legacy proxy for account {index}: {proxy_type}, {proxy[1]}:{proxy[2]}")
            return (proxy_type, proxy[1], int(proxy[2]), True,
                    proxy[3] if len(proxy) > 3 else None,
                    proxy[4] if len(proxy) > 4 else None)
        else:
            logger.error(f"Invalid proxy format in proxies.json: {type(proxy)} - {proxy}")
            return None
    except Exception as e:
        logger.error(f"Error processing proxy for account {index}: {str(e)}")
        return None

def normalize_chat_id(chat_id):
    chat_id_str = str(chat_id)
    if chat_id_str.startswith("-100"):
        return chat_id_str[4:]
    return chat_id_str

async def view_post(client, peer, msg_id):
    await client.get_messages(peer, ids=msg_id)


async def generate_comments_binary_options(count: int = 15) -> list:
    url = "https://api.perplexity.ai/chat/completions"
    headers = {
        "Authorization": f"Bearer {PPLX_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "sonar-pro",  # correct model
        "messages": [
            {
                "role": "system",
                "content": "You are an AI assistant that generates authentic, natural-looking comments for social media."
            },
            {
                "role": "user",
                "content": (
                    f"Generate {count} comments for a Telegram channel post about online trading signals and quick profit strategies "
                    "(related to binary options but without explicitly mentioning the phrase 'binary options'). "
                    "The comments must look like they were written by real people from Nigeria. "
                    "The length of comments should vary from 3 to 500 characters. "
                    "About 50% of comments should be short and concise (but still diverse), "
                    "around 45% should be medium-length (make sure they differ in style, tone, and structure, "
                    "include some emojis, and avoid making them look too similar), "
                    "and the remaining 5% should be long and detailed (but written as if by completely different individuals). "
                    "Some comments can be just emojis, some should thank the channel for signals, "
                    "some can share personal trading stories. "
                    "90% of comments should logically relate to trading, profits, or signals (without using the term 'binary options'), "
                    "while up to 10% can be off-topic or random but still natural. "
                    "Make sure every comment is unique and looks authentic. "
                    "Do NOT number the comments, separate them using the '|' symbol."
                )
            }

        ],
        "temperature": 0.95
    }

    logger.info("Sending request to Perplexity API...")
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as resp:
            status = resp.status
            text = await resp.text()
            logger.info(f"Perplexity API status: {status}")
            if status != 200:
                raise Exception(f"API error {status}: {text}")

            response = await resp.json()
            logger.info(f"Perplexity API response content: {response}")
            content = response["choices"][0]["message"]["content"]
            return [c.strip() for c in content.split("|") if c.strip()]


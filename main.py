"""
TELEGRAM WEBSITE DOWNLOADER BOT — PRODUCTION LEVEL v3.1 FULLY FIXED
NO MARKDOWN ERRORS - ALL TEXT ESCAPED PROPERLY
Owner: @LM_S0 | Channel: @D3D0T
"""

# ─── IMPORTS ──────────────────────────────────────────────────────────────────
import asyncio
import hashlib
import html
import ipaddress
import json
import logging
import mimetypes
import os
import random
import re
import shutil
import socket
import string
import time
import traceback
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.markdown import hbold, hcode, hlink, hitalic

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("WebBot")

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
BOT_TOKEN = "8674585395:AAH9el0DxulJyzSCvY7fXWuTVSFYw_BnMEA"
ADMIN_IDS: List[int] = [8495422765, 8722615269]  # Single admin
# Or for multiple admins: ADMIN_IDS: List[int] = [8495422765, 123456789]
DB_PATH = os.getenv("DB_PATH", "webbot.db")
TEMP_DIR = Path(os.getenv("TEMP_DIR", "temp_downloads"))
TEMP_DIR.mkdir(exist_ok=True))

MAX_FILE_SIZE_MB = 2000
JOB_TIMEOUT_SECONDS = 7200
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 10

PLANS: Dict[str, Dict[str, Any]] = {
    "free": {
        "name": "Free",
        "max_pages": 10,
        "max_depth": 2,
        "max_size_mb": 15,
        "priority": 3,
        "concurrent_jobs": 1,
        "description": "Basic plan with limited downloads"
    },
    "plus": {
        "name": "Plus",
        "max_pages": 200,
        "max_depth": 5,
        "max_size_mb": 200,
        "priority": 2,
        "concurrent_jobs": 2,
        "description": "Enhanced plan for regular users"
    },
    "pro": {
        "name": "PRO",
        "max_pages": 5000,
        "max_depth": 20,
        "max_size_mb": 1000,
        "priority": 1,
        "concurrent_jobs": 5,
        "description": "Maximum power - download entire websites"
    },
    "ultimate": {
        "name": "ULTIMATE",
        "max_pages": 20000,
        "max_depth": 50,
        "max_size_mb": 2000,
        "priority": 0,
        "concurrent_jobs": 10,
        "description": "Ultimate plan for heavy duty downloading"
    }
}

# Helper function to escape markdown
def escape_md(text: str) -> str:
    """Escape special characters for MarkdownV2"""
    if not text:
        return ""
    special_chars = r'[_*()[\]~`>#+\-=|{}.!]'
    return re.sub(f'([{re.escape(special_chars)}])', r'\\\1', str(text))

def safe_text(text: str) -> str:
    """Safely format text without markdown errors"""
    if not text:
        return ""
    return str(text).replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[').replace(']', '\\]')

# ─── FSM STATES ───────────────────────────────────────────────────────────────
class DownloadStates(StatesGroup):
    waiting_url = State()
    waiting_mode = State()
    waiting_depth = State()
    waiting_max_pages = State()
    waiting_asset_options = State()
    confirm = State()

class AnalyzeStates(StatesGroup):
    waiting_url = State()

class AdminStates(StatesGroup):
    broadcast_message = State()
    find_user = State()
    generate_code_plan = State()
    generate_code_uses = State()
    redeem_code = State()
    add_channel = State()
    custom_limit_user = State()
    custom_limit_field = State()

# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════════════════════
class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self):
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()
        logger.info("Database connected: %s", self.path)

    async def close(self):
        if self._conn:
            await self._conn.close()

    async def _create_tables(self):
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                full_name   TEXT,
                plan        TEXT    DEFAULT 'free',
                is_banned   INTEGER DEFAULT 0,
                is_admin    INTEGER DEFAULT 0,
                joined_at   TEXT    DEFAULT (datetime('now')),
                last_seen   TEXT    DEFAULT (datetime('now')),
                total_jobs  INTEGER DEFAULT 0,
                custom_limits TEXT  DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                plan        TEXT    NOT NULL,
                started_at  TEXT    DEFAULT (datetime('now')),
                expires_at  TEXT    NOT NULL,
                is_active   INTEGER DEFAULT 1,
                granted_by  INTEGER DEFAULT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                job_type    TEXT    NOT NULL,
                url         TEXT    NOT NULL,
                status      TEXT    DEFAULT 'queued',
                priority    INTEGER DEFAULT 3,
                options     TEXT    DEFAULT '{}',
                result      TEXT    DEFAULT NULL,
                error       TEXT    DEFAULT NULL,
                created_at  TEXT    DEFAULT (datetime('now')),
                started_at  TEXT    DEFAULT NULL,
                finished_at TEXT    DEFAULT NULL,
                message_id  INTEGER DEFAULT NULL,
                chat_id     INTEGER DEFAULT NULL,
                file_id     TEXT    DEFAULT NULL,
                file_size   INTEGER DEFAULT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS files (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id     TEXT    UNIQUE NOT NULL,
                job_id      INTEGER NOT NULL,
                file_name   TEXT    NOT NULL,
                file_size   INTEGER NOT NULL,
                pages       INTEGER DEFAULT 0,
                assets      INTEGER DEFAULT 0,
                created_at  TEXT    DEFAULT (datetime('now')),
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            );

            CREATE TABLE IF NOT EXISTS codes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                code        TEXT    UNIQUE NOT NULL,
                plan        TEXT    NOT NULL,
                duration_days INTEGER NOT NULL,
                max_uses    INTEGER DEFAULT 1,
                used_count  INTEGER DEFAULT 0,
                created_by  INTEGER NOT NULL,
                created_at  TEXT    DEFAULT (datetime('now')),
                is_active   INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS code_uses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                code_id     INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                used_at     TEXT    DEFAULT (datetime('now')),
                FOREIGN KEY(code_id) REFERENCES codes(id)
            );

            CREATE TABLE IF NOT EXISTS required_channels (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id  TEXT    UNIQUE NOT NULL,
                channel_name TEXT   NOT NULL,
                invite_link TEXT    DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                action      TEXT    NOT NULL,
                detail      TEXT    DEFAULT NULL,
                created_at  TEXT    DEFAULT (datetime('now'))
            );
        """)
        await self._conn.commit()

    async def get_or_create_user(self, user_id: int, username: str = None, full_name: str = None) -> dict:
        row = await self.fetchone("SELECT * FROM users WHERE user_id=?", (user_id,))
        if not row:
            is_admin = 1 if user_id in ADMIN_IDS else 0
            await self.execute(
                "INSERT OR IGNORE INTO users (user_id, username, full_name, is_admin) VALUES (?,?,?,?)",
                (user_id, username, full_name, is_admin)
            )
            row = await self.fetchone("SELECT * FROM users WHERE user_id=?", (user_id,))
        else:
            await self.execute(
                "UPDATE users SET username=?, full_name=?, last_seen=datetime('now') WHERE user_id=?",
                (username, full_name, user_id)
            )
        return dict(row)

    async def get_user(self, user_id: int) -> Optional[dict]:
        row = await self.fetchone("SELECT * FROM users WHERE user_id=?", (user_id,))
        return dict(row) if row else None

    async def get_user_plan(self, user_id: int) -> dict:
        user = await self.get_user(user_id)
        if not user:
            return PLANS["free"]
        sub = await self.fetchone(
            "SELECT * FROM subscriptions WHERE user_id=? AND is_active=1 AND expires_at > datetime('now') ORDER BY expires_at DESC LIMIT 1",
            (user_id,)
        )
        plan_key = sub["plan"] if sub else user.get("plan", "free")
        plan = PLANS.get(plan_key, PLANS["free"]).copy()
        plan["plan_key"] = plan_key
        if user.get("custom_limits"):
            try:
                custom = json.loads(user["custom_limits"])
                plan.update(custom)
            except Exception:
                pass
        return plan

    async def ban_user(self, user_id: int):
        await self.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (user_id,))

    async def unban_user(self, user_id: int):
        await self.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (user_id,))

    async def set_custom_limits(self, user_id: int, limits: dict):
        await self.execute(
            "UPDATE users SET custom_limits=? WHERE user_id=?",
            (json.dumps(limits), user_id)
        )

    async def get_all_users(self, only_premium: bool = False) -> List[dict]:
        if only_premium:
            rows = await self.fetchall(
                "SELECT DISTINCT u.* FROM users u JOIN subscriptions s ON u.user_id=s.user_id "
                "WHERE s.is_active=1 AND s.expires_at > datetime('now') AND u.is_banned=0"
            )
        else:
            rows = await self.fetchall("SELECT * FROM users WHERE is_banned=0")
        return [dict(r) for r in rows]

    async def get_stats(self) -> dict:
        total_users = (await self.fetchone("SELECT COUNT(*) as c FROM users"))["c"]
        active_today = (await self.fetchone(
            "SELECT COUNT(*) as c FROM users WHERE last_seen >= datetime('now', '-1 day')"
        ))["c"]
        total_jobs = (await self.fetchone("SELECT COUNT(*) as c FROM jobs"))["c"]
        running_jobs = (await self.fetchone("SELECT COUNT(*) as c FROM jobs WHERE status='running'"))["c"]
        premium_users = (await self.fetchone(
            "SELECT COUNT(DISTINCT user_id) as c FROM subscriptions WHERE is_active=1 AND expires_at > datetime('now')"
        ))["c"]
        total_storage = (await self.fetchone("SELECT SUM(file_size) as c FROM files WHERE created_at > datetime('now', '-7 days')"))["c"] or 0
        return {
            "total_users": total_users,
            "active_today": active_today,
            "total_jobs": total_jobs,
            "running_jobs": running_jobs,
            "premium_users": premium_users,
            "total_storage_mb": total_storage / (1024 * 1024),
        }

    async def add_subscription(self, user_id: int, plan: str, days: int, granted_by: int = None):
        expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat()
        await self.execute(
            "INSERT INTO subscriptions (user_id, plan, expires_at, granted_by) VALUES (?,?,?,?)",
            (user_id, plan, expires_at, granted_by)
        )
        await self.execute("UPDATE users SET plan=? WHERE user_id=?", (plan, user_id))

    async def remove_subscription(self, user_id: int):
        await self.execute(
            "UPDATE subscriptions SET is_active=0 WHERE user_id=? AND is_active=1", (user_id,)
        )
        await self.execute("UPDATE users SET plan='free' WHERE user_id=?", (user_id,))

    async def get_subscription(self, user_id: int) -> Optional[dict]:
        row = await self.fetchone(
            "SELECT * FROM subscriptions WHERE user_id=? AND is_active=1 AND expires_at > datetime('now') "
            "ORDER BY expires_at DESC LIMIT 1",
            (user_id,)
        )
        return dict(row) if row else None

    async def expire_subscriptions(self):
        await self.execute(
            "UPDATE subscriptions SET is_active=0 WHERE expires_at <= datetime('now') AND is_active=1"
        )
        expired_users = await self.fetchall(
            "SELECT DISTINCT user_id FROM subscriptions WHERE is_active=0 AND expires_at <= datetime('now', '+1 second')"
        )
        for row in expired_users:
            active = await self.get_subscription(row["user_id"])
            if not active:
                await self.execute("UPDATE users SET plan='free' WHERE user_id=?", (row["user_id"],))

    async def create_job(self, user_id: int, job_type: str, url: str, options: dict, priority: int, chat_id: int, message_id: int) -> int:
        cur = await self._conn.execute(
            "INSERT INTO jobs (user_id, job_type, url, options, priority, chat_id, message_id) VALUES (?,?,?,?,?,?,?)",
            (user_id, job_type, url, json.dumps(options), priority, chat_id, message_id)
        )
        await self._conn.commit()
        await self.execute("UPDATE users SET total_jobs=total_jobs+1 WHERE user_id=?", (user_id,))
        return cur.lastrowid

    async def get_job(self, job_id: int) -> Optional[dict]:
        row = await self.fetchone("SELECT * FROM jobs WHERE id=?", (job_id,))
        return dict(row) if row else None

    async def update_job(self, job_id: int, **kwargs):
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [job_id]
        await self.execute(f"UPDATE jobs SET {sets} WHERE id=?", vals)

    async def save_file(self, job_id: int, file_id: str, file_name: str, file_size: int, pages: int = 0, assets: int = 0):
        await self.execute(
            "INSERT INTO files (job_id, file_id, file_name, file_size, pages, assets) VALUES (?,?,?,?,?,?)",
            (job_id, file_id, file_name, file_size, pages, assets)
        )
        await self.execute("UPDATE jobs SET file_id=?, file_size=? WHERE id=?", (file_id, file_size, job_id))

    async def get_file(self, job_id: int) -> Optional[dict]:
        row = await self.fetchone("SELECT * FROM files WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,))
        return dict(row) if row else None

    async def get_user_active_job(self, user_id: int) -> Optional[dict]:
        row = await self.fetchone(
            "SELECT * FROM jobs WHERE user_id=? AND status IN ('queued','running') ORDER BY id LIMIT 1",
            (user_id,)
        )
        return dict(row) if row else None

    async def get_queue_position(self, job_id: int) -> int:
        row = await self.fetchone(
            "SELECT COUNT(*) as c FROM jobs WHERE status IN ('queued','running') AND id <= ?",
            (job_id,)
        )
        return row["c"] if row else 1

    async def get_next_queued_job(self) -> Optional[dict]:
        row = await self.fetchone(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY priority ASC, id ASC LIMIT 1"
        )
        return dict(row) if row else None

    async def get_running_jobs(self) -> List[dict]:
        rows = await self.fetchall("SELECT * FROM jobs WHERE status='running'")
        return [dict(r) for r in rows]

    async def get_all_jobs(self, limit: int = 20) -> List[dict]:
        rows = await self.fetchall(
            "SELECT j.*, u.username FROM jobs j LEFT JOIN users u ON j.user_id=u.user_id "
            "ORDER BY j.id DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]

    async def cancel_job(self, job_id: int):
        await self.execute("UPDATE jobs SET status='cancelled' WHERE id=? AND status IN ('queued','running')", (job_id,))

    async def create_code(self, plan: str, duration_days: int, max_uses: int, created_by: int) -> str:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
        await self.execute(
            "INSERT INTO codes (code, plan, duration_days, max_uses, created_by) VALUES (?,?,?,?,?)",
            (code, plan, duration_days, max_uses, created_by)
        )
        return code

    async def redeem_code(self, code_str: str, user_id: int) -> Tuple[bool, str]:
        row = await self.fetchone("SELECT * FROM codes WHERE code=? AND is_active=1", (code_str.upper(),))
        if not row:
            return False, "Invalid or expired code."
        code = dict(row)
        if code["used_count"] >= code["max_uses"]:
            return False, "This code has been fully used."
        already = await self.fetchone(
            "SELECT id FROM code_uses WHERE code_id=? AND user_id=?", (code["id"], user_id)
        )
        if already:
            return False, "You already used this code."
        await self.execute(
            "UPDATE codes SET used_count=used_count+1 WHERE id=?", (code["id"],)
        )
        await self.execute(
            "INSERT INTO code_uses (code_id, user_id) VALUES (?,?)", (code["id"], user_id)
        )
        await self.add_subscription(user_id, code["plan"], code["duration_days"])
        if code["used_count"] + 1 >= code["max_uses"]:
            await self.execute("UPDATE codes SET is_active=0 WHERE id=?", (code["id"],))
        return True, f"Code redeemed! You now have {code['plan'].upper()} for {code['duration_days']} days."

    async def get_required_channels(self) -> List[dict]:
        rows = await self.fetchall("SELECT * FROM required_channels")
        return [dict(r) for r in rows]

    async def add_required_channel(self, channel_id: str, name: str, link: str = None):
        await self.execute(
            "INSERT OR REPLACE INTO required_channels (channel_id, channel_name, invite_link) VALUES (?,?,?)",
            (channel_id, name, link)
        )

    async def remove_required_channel(self, channel_id: str):
        await self.execute("DELETE FROM required_channels WHERE channel_id=?", (channel_id,))

    async def log(self, user_id: int, action: str, detail: str = None):
        await self.execute(
            "INSERT INTO logs (user_id, action, detail) VALUES (?,?,?)",
            (user_id, action, detail)
        )

    async def cleanup_old_files(self, days: int = 30):
        await self.execute(
            "DELETE FROM files WHERE created_at < datetime('now', ?)",
            (f"-{days} days",)
        )

    async def execute(self, query: str, params: tuple = ()):
        await self._conn.execute(query, params)
        await self._conn.commit()

    async def fetchone(self, query: str, params: tuple = ()) -> Optional[aiosqlite.Row]:
        async with self._conn.execute(query, params) as cur:
            return await cur.fetchone()

    async def fetchall(self, query: str, params: tuple = ()) -> List[aiosqlite.Row]:
        async with self._conn.execute(query, params) as cur:
            return await cur.fetchall()

# ═══════════════════════════════════════════════════════════════════════════════
# SECURITY
# ═══════════════════════════════════════════════════════════════════════════════
class SecurityChecker:
    BLOCKED_HOSTS = {
        "localhost", "127.0.0.1", "0.0.0.0", "::1",
        "metadata.google.internal", "169.254.169.254",
    }
    PRIVATE_RANGES = [
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fc00::/7"),
    ]

    @classmethod
    def is_safe_url(cls, url: str) -> Tuple[bool, str]:
        try:
            parsed = urlparse(url)
        except Exception:
            return False, "Invalid URL format."
        if parsed.scheme not in ("http", "https"):
            return False, "Only HTTP/HTTPS URLs are allowed."
        host = parsed.hostname
        if not host:
            return False, "No hostname in URL."
        if host.lower() in cls.BLOCKED_HOSTS:
            return False, "Access to this host is blocked."
        try:
            ip = socket.gethostbyname(host)
            ip_obj = ipaddress.ip_address(ip)
            for net in cls.PRIVATE_RANGES:
                if ip_obj in net:
                    return False, "Access to private/internal IP ranges is blocked."
        except socket.gaierror:
            return False, "Could not resolve hostname."
        except Exception:
            pass
        return True, "OK"

# ═══════════════════════════════════════════════════════════════════════════════
# DOWNLOADER
# ═══════════════════════════════════════════════════════════════════════════════
class Downloader:
    def __init__(self, db: "Database", bot: Bot):
        self.db = db
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None

    async def get_session(self):
        if not self.session or self.session.closed:
            connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
            timeout = aiohttp.ClientTimeout(total=JOB_TIMEOUT_SECONDS)
            self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        return self.session

    async def analyze_url(self, url: str, progress_cb=None) -> dict:
        safe, msg = SecurityChecker.is_safe_url(url)
        if not safe:
            return {"error": msg}

        result = {
            "url": url,
            "pages": 0,
            "images": 0,
            "css_files": 0,
            "js_files": 0,
            "total_size_bytes": 0,
            "technologies": [],
            "title": "",
            "status_code": 0,
        }

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        session = await self.get_session()

        try:
            async with session.get(url) as resp:
                result["status_code"] = resp.status
                html = await resp.text(errors="replace")
                result["total_size_bytes"] += len(html.encode())
                result["pages"] = 1

                if BS4_AVAILABLE:
                    soup = BeautifulSoup(html, "html.parser")
                    title_tag = soup.find("title")
                    result["title"] = title_tag.get_text(strip=True) if title_tag else "N/A"
                    result["images"] = len(soup.find_all("img"))
                    result["css_files"] = len(soup.find_all("link", rel="stylesheet"))
                    result["js_files"] = len(soup.find_all("script", src=True))
                else:
                    result["images"] = html.count("<img")
                    result["css_files"] = html.count('rel="stylesheet"')
                    result["js_files"] = html.count("<script")

        except Exception as e:
            result["error"] = str(e)

        return result

    async def download_site(
        self,
        job_id: int,
        url: str,
        mode: str,
        options: dict,
        progress_cb=None,
    ) -> dict:
        safe, msg = SecurityChecker.is_safe_url(url)
        if not safe:
            return {"error": msg}

        max_pages = options.get("max_pages", 5000)
        max_depth = options.get("max_depth", 20)
        max_size_mb = options.get("max_size_mb", 2000)

        work_dir = TEMP_DIR / f"job_{job_id}"
        work_dir.mkdir(parents=True, exist_ok=True)

        parsed_base = urlparse(url)
        base_domain = parsed_base.netloc

        visited: set = set()
        to_visit: List[Tuple[str, int]] = [(url, 0)]
        total_size = 0
        max_bytes = max_size_mb * 1024 * 1024

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        result_info = {
            "pages_downloaded": 0,
            "assets_downloaded": 0,
            "total_size_bytes": 0,
            "file_id": None,
            "file_size": 0,
        }

        start_time = time.time()

        try:
            session = await self.get_session()
            page_count = 0
            
            while to_visit and page_count < max_pages and total_size < max_bytes:
                current_url, depth = to_visit.pop(0)
                
                if current_url in visited:
                    continue
                
                if progress_cb and page_count % 10 == 0:
                    percent = (page_count / max_pages) * 100 if max_pages > 0 else 0
                    await progress_cb(
                        f"Progress: {page_count}/{max_pages} pages ({percent:.1f}%) | "
                        f"Queue: {len(to_visit)} links | Size: {total_size/(1024*1024):.1f}/{max_size_mb}MB"
                    )
                
                visited.add(current_url)

                try:
                    async with session.get(current_url) as resp:
                        if resp.status != 200:
                            continue
                        html = await resp.text(errors="replace")
                        total_size += len(html.encode())
                except Exception:
                    continue

                page_count += 1

                # Save page
                page_dir = work_dir / "html"
                page_dir.mkdir(exist_ok=True)
                page_name = "index.html" if page_count == 1 else f"page_{page_count}.html"
                (page_dir / page_name).write_text(html, encoding="utf-8")

                # Crawling
                if mode == "full" and depth < max_depth and BS4_AVAILABLE:
                    soup = BeautifulSoup(html, "html.parser")
                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        if not href or href.startswith(('#', 'javascript:', 'mailto:')):
                            continue
                        
                        abs_url = urljoin(current_url, href)
                        parsed_link = urlparse(abs_url)
                        
                        if parsed_link.netloc == base_domain and abs_url not in visited:
                            if abs_url not in [u for u, _ in to_visit]:
                                to_visit.append((abs_url, depth + 1))

            result_info["pages_downloaded"] = page_count
            result_info["elapsed_time"] = time.time() - start_time

            if page_count > 0:
                if progress_cb:
                    await progress_cb(f"Creating ZIP archive... ({page_count} pages)")

                zip_path = work_dir / f"website_{job_id}.zip"
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fpath in work_dir.rglob("*"):
                        if fpath.is_file() and fpath != zip_path:
                            zf.write(fpath, fpath.relative_to(work_dir))

                file_size = zip_path.stat().st_size
                result_info["file_size"] = file_size
                
                if progress_cb:
                    await progress_cb(f"Uploading to Telegram... ({file_size/(1024*1024):.1f} MB)")
                
                with open(zip_path, "rb") as f:
                    result = await self.bot.send_document(
                        chat_id=options.get("chat_id"),
                        document=BufferedInputFile(f.read(), filename=f"website_{job_id}.zip"),
                        caption=f"Download Complete!\nURL: {url}\nPages: {page_count}\nSize: {file_size/(1024*1024):.1f} MB\nTime: {result_info['elapsed_time']:.1f} sec"
                    )
                
                file_id = result.document.file_id
                result_info["file_id"] = file_id
                await self.db.save_file(job_id, file_id, f"website_{job_id}.zip", file_size, page_count, 0)
                
                shutil.rmtree(work_dir, ignore_errors=True)
            else:
                result_info["error"] = "No pages were downloaded"

        except Exception as e:
            result_info["error"] = str(e)
            logger.error("Download error: %s", traceback.format_exc())
            shutil.rmtree(work_dir, ignore_errors=True)

        return result_info

# ═══════════════════════════════════════════════════════════════════════════════
# QUEUE MANAGER
# ═══════════════════════════════════════════════════════════════════════════════
class QueueManager:
    def __init__(self, db: "Database", bot: Bot, downloader: Downloader):
        self.db = db
        self.bot = bot
        self.downloader = downloader
        self._running: Dict[int, asyncio.Task] = {}
        self._max_concurrent = 5
        self._running_flag = False

    async def start(self):
        self._running_flag = True
        asyncio.create_task(self._worker_loop())
        asyncio.create_task(self._expiry_loop())
        logger.info("QueueManager started.")

    async def stop(self):
        self._running_flag = False
        for task in self._running.values():
            if not task.done():
                task.cancel()

    async def _worker_loop(self):
        while self._running_flag:
            try:
                if len(self._running) < self._max_concurrent:
                    job = await self.db.get_next_queued_job()
                    if job:
                        task = asyncio.create_task(self._process_job(job))
                        self._running[job["id"]] = task
                        task.add_done_callback(lambda t, jid=job["id"]: self._running.pop(jid, None))
            except Exception as e:
                logger.error("Worker loop error: %s", e)
            await asyncio.sleep(1)

    async def _expiry_loop(self):
        while self._running_flag:
            try:
                await self.db.expire_subscriptions()
                await self.db.cleanup_old_files(30)
            except Exception as e:
                logger.error("Expiry loop error: %s", e)
            await asyncio.sleep(3600)

    async def _process_job(self, job: dict):
        job_id = job["id"]
        await self.db.update_job(job_id, status="running", started_at=datetime.utcnow().isoformat())
        options = json.loads(job["options"])
        options["chat_id"] = job["chat_id"]
        chat_id = job["chat_id"]
        message_id = job["message_id"]

        async def progress_cb(text: str):
            try:
                await self.bot.edit_message_text(
                    text=f"Job #{job_id}\n\n{text}",
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode=None,
                )
            except Exception:
                pass

        try:
            if job["job_type"] == "download":
                result = await asyncio.wait_for(
                    self.downloader.download_site(job_id, job["url"], options.get("mode", "single"), options, progress_cb),
                    timeout=JOB_TIMEOUT_SECONDS,
                )
            else:
                result = await asyncio.wait_for(
                    self.downloader.analyze_url(job["url"], progress_cb),
                    timeout=60,
                )

            if "error" in result:
                await self.db.update_job(job_id, status="failed", error=result["error"], finished_at=datetime.utcnow().isoformat())
                await self._notify_failure(job, result["error"])
            else:
                await self.db.update_job(job_id, status="done", result=json.dumps(result), finished_at=datetime.utcnow().isoformat())
                
                if job["job_type"] == "analyze":
                    await self._notify_analysis(job, result)

        except asyncio.TimeoutError:
            await self.db.update_job(job_id, status="failed", error="Timed out.", finished_at=datetime.utcnow().isoformat())
            await self._notify_failure(job, "Job timed out")
        except Exception as e:
            await self.db.update_job(job_id, status="failed", error=str(e), finished_at=datetime.utcnow().isoformat())
            await self._notify_failure(job, str(e))

    async def _notify_analysis(self, job: dict, result: dict):
        chat_id = job["chat_id"]
        message_id = job["message_id"]
        
        techs = ", ".join(result.get("technologies", [])) or "None"
        size_mb = result.get("total_size_bytes", 0) / (1024 * 1024)
        text = (
            f"Analysis Complete - Job #{job['id']}\n\n"
            f"URL: {job['url']}\n"
            f"Title: {result.get('title','N/A')}\n"
            f"Status: {result.get('status_code','?')}\n"
            f"Pages: {result.get('pages', 1)}\n"
            f"Images: {result.get('images', 0)}\n"
            f"CSS: {result.get('css_files', 0)}\n"
            f"JS: {result.get('js_files', 0)}\n"
            f"Size: {size_mb:.2f} MB\n"
            f"Tech: {techs}"
        )
        try:
            await self.bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, parse_mode=None)
        except Exception:
            pass

    async def _notify_failure(self, job: dict, error: str):
        try:
            await self.bot.edit_message_text(
                f"Job #{job['id']} Failed\n\n{error[:300]}",
                chat_id=job["chat_id"],
                message_id=job["message_id"],
                parse_mode=None,
            )
        except Exception:
            pass

    async def enqueue(self, user_id: int, job_type: str, url: str, options: dict, priority: int, chat_id: int, message_id: int) -> int:
        return await self.db.create_job(user_id, job_type, url, options, priority, chat_id, message_id)

# ═══════════════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════════
def kb_main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🌐 Download", callback_data="menu_download")
    b.button(text="🔍 Analyze", callback_data="menu_analyze")
    b.button(text="📋 My Jobs", callback_data="menu_jobs")
    b.button(text="💎 Subscription", callback_data="menu_sub")
    b.button(text="⚙️ Settings", callback_data="menu_settings")
    b.button(text="❓ Help", callback_data="menu_help")
    b.adjust(2)
    return b.as_markup()

def kb_download_mode() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📄 Single Page", callback_data="dl_mode_single")
    b.button(text="🌐 Full Crawl", callback_data="dl_mode_full")
    b.button(text="🖼 Extract Images", callback_data="dl_mode_images")
    b.button(text="❌ Cancel", callback_data="cancel_action")
    b.adjust(2)
    return b.as_markup()

def kb_depth(max_d: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for d in [1, 2, 3, 5, 10, 15, 20, 30, 50]:
        if d <= max_d:
            b.button(text=str(d), callback_data=f"dl_depth_{d}")
    b.button(text="❌ Cancel", callback_data="cancel_action")
    b.adjust(5)
    return b.as_markup()

def kb_max_pages(max_p: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for o in [1, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]:
        if o <= max_p:
            b.button(text=str(o), callback_data=f"dl_pages_{o}")
    b.button(text="❌ Cancel", callback_data="cancel_action")
    b.adjust(3)
    return b.as_markup()

def kb_asset_options(data: dict) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"{'✅' if data.get('download_css', True) else '❌'} CSS", callback_data="toggle_css")
    b.button(text=f"{'✅' if data.get('download_js', True) else '❌'} JS", callback_data="toggle_js")
    b.button(text=f"{'✅' if data.get('download_images', True) else '❌'} Images", callback_data="toggle_images")
    b.button(text="✅ Confirm", callback_data="asset_confirm")
    b.button(text="❌ Cancel", callback_data="cancel_action")
    b.adjust(2)
    return b.as_markup()

def kb_confirm() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Start", callback_data="dl_confirm_yes")
    b.button(text="❌ Cancel", callback_data="cancel_action")
    return b.as_markup()

def kb_admin_panel() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👥 Users", callback_data="admin_users")
    b.button(text="📊 Stats", callback_data="admin_stats")
    b.button(text="💼 Jobs", callback_data="admin_jobs")
    b.button(text="📢 Broadcast", callback_data="admin_broadcast")
    b.button(text="🎟 Codes", callback_data="admin_codes")
    b.button(text="📡 Channels", callback_data="admin_channels")
    b.adjust(2)
    return b.as_markup()

def kb_admin_user(user_id: int, banned: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💎 Upgrade", callback_data=f"admin_upgrade_{user_id}")
    b.button(text="🚫 Ban" if not banned else "✅ Unban", callback_data=f"admin_ban_{user_id}")
    b.button(text="◀️ Back", callback_data="admin_panel")
    return b.as_markup()

def kb_plan_select(user_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for plan in ["plus", "pro", "ultimate"]:
        b.button(text=PLANS[plan]["name"], callback_data=f"admin_setplan_{user_id}_{plan}")
    b.button(text="◀️ Back", callback_data=f"admin_showuser_{user_id}")
    return b.as_markup()

def kb_days_select(user_id: int, plan: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for d in [7, 30, 90, 365]:
        b.button(text=f"{d} days", callback_data=f"admin_setdays_{user_id}_{plan}_{d}")
    b.button(text="◀️ Back", callback_data=f"admin_showuser_{user_id}")
    return b.as_markup()

def kb_sub_info(has_sub: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🎟 Redeem Code", callback_data="sub_redeem")
    if not has_sub:
        b.button(text="💎 View Plans", callback_data="sub_plans")
    b.button(text="◀️ Menu", callback_data="menu_main")
    return b.as_markup()

# ═══════════════════════════════════════════════════════════════════════════════
# CHECK SUBSCRIPTION
# ═══════════════════════════════════════════════════════════════════════════════
async def check_forced_subscription(user_id: int, bot: Bot, db: Database) -> Tuple[bool, Optional[InlineKeyboardMarkup]]:
    channels = await db.get_required_channels()
    if not channels:
        return True, None
    not_joined = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch["channel_id"], user_id)
            if member.status in ("left", "kicked"):
                not_joined.append(ch)
        except:
            not_joined.append(ch)
    if not not_joined:
        return True, None
    b = InlineKeyboardBuilder()
    for ch in not_joined:
        link = ch.get("invite_link") or f"https://t.me/{ch['channel_id'].lstrip('@')}"
        b.button(text=f"📢 {ch['channel_name']}", url=link)
    b.button(text="✅ Joined", callback_data="check_joined")
    return False, b.as_markup()

# ═══════════════════════════════════════════════════════════════════════════════
# USER ROUTER
# ═══════════════════════════════════════════════════════════════════════════════
user_router = Router()

async def guard(message: Message, db: Database, bot: Bot) -> bool:
    user = await db.get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if user["is_banned"]:
        await message.answer("You are banned.")
        return False
    ok, kb = await check_forced_subscription(message.from_user.id, bot, db)
    if not ok:
        await message.answer("Join required channels:", reply_markup=kb)
        return False
    return True

@user_router.message(Command("start"))
async def cmd_start(message: Message, db: Database, bot: Bot):
    user = await db.get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if user["is_banned"]:
        return await message.answer("Banned.")
    
    ok, kb = await check_forced_subscription(message.from_user.id, bot, db)
    if not ok:
        return await message.answer("Join required channels:", reply_markup=kb)
    
    plan = await db.get_user_plan(message.from_user.id)
    await message.answer(
        f"Welcome {message.from_user.first_name} To DeadDownloader Bot!!\n\n"
        f"Plan: {plan['name']}\n"
        f"Max Pages: {plan['max_pages']}\n"
        f"Max Depth: {plan['max_depth']}\n"
        f"Max Size: {plan['max_size_mb']} MB\n\n"
        f"For more plans contact: @LM_S0\n\n"
        f"Channel: @D3D0T\n\n"
        f"Choose an option:",
        reply_markup=kb_main_menu()
    )

@user_router.callback_query(F.data == "menu_main")
async def cb_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Main Menu:", reply_markup=kb_main_menu())

@user_router.callback_query(F.data == "menu_help")
async def cb_help(cb: CallbackQuery):
    await cb.message.edit_text(
        "Help !!\n\n"
        "1. Run The Bot by /start"
        "Send The Targeted Website"
        "The Bot will Crawl Into The Target, .zip file\n"
        "PRO Plan: 5000 pages, depth 20\n"
        "ULTIMATE Plan: 20000 pages, depth 50\n\n"
        "Contact @LM_S0 for upgrades\n"
        "Join @D3D0T for updates",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Back", callback_data="menu_main")]])
    )

@user_router.callback_query(F.data == "menu_download")
async def cb_download(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    user_id = cb.from_user.id
    active = await db.get_user_active_job(user_id)
    if active:
        return await cb.answer(f"Active job #{active['id']} in progress", show_alert=True)
    
    await state.set_state(DownloadStates.waiting_url)
    await cb.message.edit_text(
        "Send me the URL:\nExample: https://example.com\n\nYour download will be sent as a Telegram file!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")]])
    )

@user_router.message(DownloadStates.waiting_url)
async def dl_url(message: Message, state: FSMContext):
    url = message.text.strip()
    if not url.startswith("http"):
        url = "https://" + url
    safe, err = SecurityChecker.is_safe_url(url)
    if not safe:
        return await message.answer(f"Invalid URL: {err}")
    
    await state.update_data(url=url)
    await state.set_state(DownloadStates.waiting_mode)
    await message.answer("Select mode:", reply_markup=kb_download_mode())

@user_router.callback_query(F.data.startswith("dl_mode_"))
async def dl_mode(cb: CallbackQuery, state: FSMContext, db: Database):
    mode_map = {
        "dl_mode_single": "single",
        "dl_mode_full": "full",
        "dl_mode_images": "images",
    }
    mode = mode_map.get(cb.data, "single")
    extract = "images" if "images" in cb.data else None
    
    await state.update_data(mode=mode, extract_only=extract)
    plan = await db.get_user_plan(cb.from_user.id)
    
    if mode == "full" and not extract:
        await state.set_state(DownloadStates.waiting_depth)
        await cb.message.edit_text(f"Select depth (max: {plan['max_depth']}):", reply_markup=kb_depth(plan["max_depth"]))
    else:
        await state.update_data(depth=1)
        await state.set_state(DownloadStates.waiting_max_pages)
        await cb.message.edit_text(f"Select max pages (max: {plan['max_pages']}):", reply_markup=kb_max_pages(plan["max_pages"]))

@user_router.callback_query(F.data.startswith("dl_depth_"))
async def dl_depth(cb: CallbackQuery, state: FSMContext, db: Database):
    depth = int(cb.data.split("_")[2])
    await state.update_data(depth=depth)
    plan = await db.get_user_plan(cb.from_user.id)
    await state.set_state(DownloadStates.waiting_max_pages)
    await cb.message.edit_text(f"Select max pages (max: {plan['max_pages']}):", reply_markup=kb_max_pages(plan["max_pages"]))

@user_router.callback_query(F.data.startswith("dl_pages_"))
async def dl_pages(cb: CallbackQuery, state: FSMContext):
    pages = int(cb.data.split("_")[2])
    await state.update_data(max_pages=pages, download_css=True, download_js=True, download_images=True)
    await state.set_state(DownloadStates.waiting_asset_options)
    data = await state.get_data()
    await cb.message.edit_text("Asset options:", reply_markup=kb_asset_options(data))

@user_router.callback_query(F.data.startswith("toggle_"))
async def toggle_asset(cb: CallbackQuery, state: FSMContext):
    key_map = {"toggle_css": "download_css", "toggle_js": "download_js", "toggle_images": "download_images"}
    field = key_map.get(cb.data)
    if field:
        data = await state.get_data()
        data[field] = not data.get(field, True)
        await state.update_data(**{field: data[field]})
        await cb.message.edit_reply_markup(reply_markup=kb_asset_options(data))
    await cb.answer()

@user_router.callback_query(F.data == "asset_confirm")
async def asset_confirm(cb: CallbackQuery, state: FSMContext):
    await state.set_state(DownloadStates.confirm)
    data = await state.get_data()
    await cb.message.edit_text(
        f"Confirm Download\n\n"
        f"URL: {data['url']}\n"
        f"Mode: {data.get('mode', 'single')}\n"
        f"Depth: {data.get('depth', 1)}\n"
        f"Pages: {data.get('max_pages', 1)}\n\n"
        f"The ZIP file will be sent directly to this chat!\n\n"
        f"Start?",
        reply_markup=kb_confirm()
    )

@user_router.callback_query(F.data == "dl_confirm_yes")
async def dl_confirm(cb: CallbackQuery, state: FSMContext, db: Database, queue: QueueManager):
    data = await state.get_data()
    await state.clear()
    
    plan = await db.get_user_plan(cb.from_user.id)
    options = {
        "mode": data.get("mode", "single"),
        "extract_only": data.get("extract_only"),
        "max_pages": min(data.get("max_pages", 10), plan["max_pages"]),
        "max_depth": min(data.get("depth", 1), plan["max_depth"]),
        "max_size_mb": plan["max_size_mb"],
        "download_css": data.get("download_css", True),
        "download_js": data.get("download_js", True),
        "download_images": data.get("download_images", True),
    }
    
    msg = await cb.message.edit_text("Queuing job...")
    job_id = await queue.enqueue(cb.from_user.id, "download", data["url"], options, plan["priority"], cb.message.chat.id, msg.message_id)
    pos = await db.get_queue_position(job_id)
    await cb.message.edit_text(f"Job #{job_id} queued!\nPosition: {pos}\n\nI'll send the file here when it's ready.")

@user_router.callback_query(F.data == "menu_analyze")
async def cb_analyze(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AnalyzeStates.waiting_url)
    await cb.message.edit_text("Send URL to analyze:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_action")]]))

@user_router.message(AnalyzeStates.waiting_url)
async def analyze_url(message: Message, state: FSMContext, db: Database, queue: QueueManager):
    url = message.text.strip()
    if not url.startswith("http"):
        url = "https://" + url
    safe, err = SecurityChecker.is_safe_url(url)
    if not safe:
        return await message.answer(f"Invalid URL: {err}")
    await state.clear()
    plan = await db.get_user_plan(message.from_user.id)
    msg = await message.answer(f"Analyzing {url}...")
    await queue.enqueue(message.from_user.id, "analyze", url, {}, plan["priority"], message.chat.id, msg.message_id)

@user_router.callback_query(F.data == "menu_jobs")
async def cb_jobs(cb: CallbackQuery, db: Database):
    active = await db.get_user_active_job(cb.from_user.id)
    if active:
        pos = await db.get_queue_position(active["id"])
        await cb.message.edit_text(
            f"Job #{active['id']}\nStatus: {active['status']}\nPosition: {pos}\nURL: {active['url']}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data=f"cancel_job_{active['id']}"), InlineKeyboardButton(text="◀️ Back", callback_data="menu_main")]])
        )
    else:
        await cb.message.edit_text("No active jobs.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Back", callback_data="menu_main")]]))

@user_router.callback_query(F.data.startswith("cancel_job_"))
async def cb_cancel(cb: CallbackQuery, db: Database):
    job_id = int(cb.data.split("_")[2])
    job = await db.get_job(job_id)
    if job and job["user_id"] == cb.from_user.id:
        await db.cancel_job(job_id)
        await cb.message.edit_text(f"Job #{job_id} cancelled.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Menu", callback_data="menu_main")]]))
    else:
        await cb.answer("Job not found")

@user_router.callback_query(F.data == "menu_sub")
async def cb_sub(cb: CallbackQuery, db: Database):
    plan = await db.get_user_plan(cb.from_user.id)
    sub = await db.get_subscription(cb.from_user.id)
    has_sub = sub is not None
    text = f"Your Plan: {plan['name']}\n"
    if sub:
        text += f"Expires: {sub['expires_at'][:10]}\n"
    else:
        text += "No active subscription\n"
    text += f"\nMax Pages: {plan['max_pages']}\nMax Depth: {plan['max_depth']}\nMax Size: {plan['max_size_mb']} MB"
    await cb.message.edit_text(text, reply_markup=kb_sub_info(has_sub))

@user_router.callback_query(F.data == "sub_plans")
async def cb_plans(cb: CallbackQuery):
    text = "Plans\n\nFree: 10 pages, depth 2, 15MB\nPlus: 200 pages, depth 5, 200MB\nPRO: 5000 pages, depth 20, 1GB\nULTIMATE: 20000 pages, depth 50, 2GB\n\nContact @LM_S0 to upgrade"
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Back", callback_data="menu_sub")]]))

@user_router.callback_query(F.data == "sub_redeem")
async def cb_redeem(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.redeem_code)
    await cb.message.edit_text("Send your code:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="menu_sub")]]))

@user_router.message(AdminStates.redeem_code)
async def do_redeem(message: Message, state: FSMContext, db: Database):
    await state.clear()
    ok, msg = await db.redeem_code(message.text.strip().upper(), message.from_user.id)
    await message.answer(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Menu", callback_data="menu_main")]]))

@user_router.callback_query(F.data == "menu_settings")
async def cb_settings(cb: CallbackQuery, db: Database):
    user = await db.get_user(cb.from_user.id)
    plan = await db.get_user_plan(cb.from_user.id)
    await cb.message.edit_text(
        f"Settings\n\nID: {cb.from_user.id}\nPlan: {plan['name']}\nJobs: {user.get('total_jobs', 0)}\n\nBy OMAR | @LM_S0",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Menu", callback_data="menu_main")]])
    )

@user_router.callback_query(F.data == "cancel_action")
async def cb_cancel_action(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Cancelled.", reply_markup=kb_main_menu())

@user_router.callback_query(F.data == "check_joined")
async def cb_check_joined(cb: CallbackQuery, db: Database, bot: Bot):
    ok, kb = await check_forced_subscription(cb.from_user.id, bot, db)
    if ok:
        await cb.message.edit_text("Verified! Use /start")
    else:
        await cb.message.edit_text("Still not joined:", reply_markup=kb)

# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN ROUTER
# ═══════════════════════════════════════════════════════════════════════════════
admin_router = Router()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

@admin_router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("Admin only")
    await message.answer("Admin Panel", reply_markup=kb_admin_panel())

@admin_router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Admin only")
    await cb.message.edit_text("Admin Panel", reply_markup=kb_admin_panel())

@admin_router.callback_query(F.data == "admin_stats")
async def cb_stats(cb: CallbackQuery, db: Database):
    if not is_admin(cb.from_user.id):
        return
    stats = await db.get_stats()
    await cb.message.edit_text(
        f"Stats\n\n"
        f"Users: {stats['total_users']}\n"
        f"Active today: {stats['active_today']}\n"
        f"Premium: {stats['premium_users']}\n"
        f"Jobs: {stats['total_jobs']}\n"
        f"Running: {stats['running_jobs']}\n"
        f"Storage (7d): {stats['total_storage_mb']:.1f} MB\n\n"
        f"Files stored on Telegram servers",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Back", callback_data="admin_panel")]])
    )

@admin_router.callback_query(F.data == "admin_users")
async def cb_users(cb: CallbackQuery, db: Database):
    if not is_admin(cb.from_user.id):
        return
    rows = await db.fetchall("SELECT user_id, username, plan, is_banned FROM users ORDER BY joined_at DESC LIMIT 20")
    text = "Recent Users\n\n"
    for r in rows:
        username = r['username'] or 'N/A'
        banned_flag = " [BANNED]" if r['is_banned'] else ""
        text += f"{r['user_id']} @{username} - {r['plan']}{banned_flag}\n"
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔍 Find", callback_data="admin_find"), InlineKeyboardButton(text="◀️ Back", callback_data="admin_panel")]]))

@admin_router.callback_query(F.data == "admin_find")
async def cb_find(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AdminStates.find_user)
    await cb.message.edit_text("Send user_id or @username:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_panel")]]))

@admin_router.message(AdminStates.find_user)
async def find_user(message: Message, state: FSMContext, db: Database):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    query = message.text.strip()
    if query.isdigit():
        user = await db.get_user(int(query))
    else:
        row = await db.fetchone("SELECT * FROM users WHERE username=?", (query.lstrip("@"),))
        user = dict(row) if row else None
    if not user:
        return await message.answer("User not found")
    plan = await db.get_user_plan(user["user_id"])
    await message.answer(
        f"User {user['user_id']}\nPlan: {plan['name']}\nBanned: {'Yes' if user['is_banned'] else 'No'}\nJobs: {user.get('total_jobs', 0)}",
        reply_markup=kb_admin_user(user["user_id"], user["is_banned"])
    )

@admin_router.callback_query(F.data.startswith("admin_upgrade_"))
async def cb_upgrade(cb: CallbackQuery, db: Database):
    if not is_admin(cb.from_user.id):
        return
    user_id = int(cb.data.split("_")[2])
    await cb.message.edit_text("Select plan:", reply_markup=kb_plan_select(user_id))

@admin_router.callback_query(F.data.startswith("admin_setplan_"))
async def cb_setplan(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    parts = cb.data.split("_")
    user_id = int(parts[2])
    plan = parts[3]
    await cb.message.edit_text("Select duration:", reply_markup=kb_days_select(user_id, plan))

@admin_router.callback_query(F.data.startswith("admin_setdays_"))
async def cb_setdays(cb: CallbackQuery, db: Database):
    if not is_admin(cb.from_user.id):
        return
    parts = cb.data.split("_")
    user_id = int(parts[2])
    plan = parts[3]
    days = int(parts[4])
    await db.add_subscription(user_id, plan, days, cb.from_user.id)
    await cb.message.edit_text(f"Added {plan} for {days} days to user {user_id}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Admin", callback_data="admin_panel")]]))

@admin_router.callback_query(F.data.startswith("admin_ban_"))
async def cb_ban(cb: CallbackQuery, db: Database):
    if not is_admin(cb.from_user.id):
        return
    user_id = int(cb.data.split("_")[2])
    user = await db.get_user(user_id)
    if user["is_banned"]:
        await db.unban_user(user_id)
        await cb.answer(f"Unbanned {user_id}")
    else:
        await db.ban_user(user_id)
        await cb.answer(f"Banned {user_id}")
    await cb.message.delete()
    await cb.message.answer(f"User {user_id} updated")

@admin_router.callback_query(F.data == "admin_jobs")
async def cb_admin_jobs(cb: CallbackQuery, db: Database):
    if not is_admin(cb.from_user.id):
        return
    jobs = await db.get_all_jobs(10)
    text = "Recent Jobs\n\n"
    for j in jobs:
        username = j.get('username', j['user_id'])
        text += f"#{j['id']} @{username} - {j['status']} - {j['url'][:40]}\n"
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Back", callback_data="admin_panel")]]))

@admin_router.callback_query(F.data == "admin_broadcast")
async def cb_broadcast(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AdminStates.broadcast_message)
    await cb.message.edit_text("Send message to broadcast:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_panel")]]))

@admin_router.message(AdminStates.broadcast_message)
async def do_broadcast(message: Message, state: FSMContext, db: Database, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    users = await db.get_all_users()
    sent = 0
    for user in users:
        try:
            await bot.send_message(user["user_id"], f"Broadcast from @LM_S0\n\n{message.text}")
            sent += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"Broadcast sent to {sent} users")

@admin_router.callback_query(F.data == "admin_codes")
async def cb_codes(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    b = InlineKeyboardBuilder()
    b.button(text="🎟 Generate Code", callback_data="gencode_start")
    b.button(text="📋 List Codes", callback_data="gencode_list")
    b.button(text="◀️ Back", callback_data="admin_panel")
    await cb.message.edit_text("Codes Management", reply_markup=b.as_markup())

@admin_router.callback_query(F.data == "gencode_start")
async def gencode_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AdminStates.generate_code_plan)
    b = InlineKeyboardBuilder()
    for plan in ["plus", "pro", "ultimate"]:
        b.button(text=PLANS[plan]["name"], callback_data=f"gencode_plan_{plan}")
    await cb.message.edit_text("Select plan:", reply_markup=b.as_markup())

@admin_router.callback_query(F.data.startswith("gencode_plan_"))
async def gencode_plan(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    plan = cb.data.split("_")[2]
    await state.update_data(code_plan=plan)
    b = InlineKeyboardBuilder()
    for d in [7, 30, 90, 365]:
        b.button(text=f"{d} days", callback_data=f"gencode_days_{d}")
    await cb.message.edit_text("Select duration:", reply_markup=b.as_markup())

@admin_router.callback_query(F.data.startswith("gencode_days_"))
async def gencode_days(cb: CallbackQuery, state: FSMContext, db: Database):
    if not is_admin(cb.from_user.id):
        return
    days = int(cb.data.split("_")[2])
    data = await state.get_data()
    code = await db.create_code(data["code_plan"], days, 1, cb.from_user.id)
    await state.clear()
    await cb.message.edit_text(f"Code: {code}\nPlan: {data['code_plan']}\nDays: {days}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Codes", callback_data="admin_codes")]]))

@admin_router.callback_query(F.data == "gencode_list")
async def gencode_list(cb: CallbackQuery, db: Database):
    if not is_admin(cb.from_user.id):
        return
    rows = await db.fetchall("SELECT code, plan, duration_days, used_count, max_uses, is_active FROM codes ORDER BY id DESC LIMIT 10")
    text = "Codes\n\n"
    for r in rows:
        active_flag = "ACTIVE" if r['is_active'] else "INACTIVE"
        text += f"{r['code']} - {r['plan']} {r['duration_days']}d - {r['used_count']}/{r['max_uses']} {active_flag}\n"
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Back", callback_data="admin_codes")]]))

@admin_router.callback_query(F.data == "admin_channels")
async def cb_channels(cb: CallbackQuery, db: Database):
    if not is_admin(cb.from_user.id):
        return
    channels = await db.get_required_channels()
    text = "Required Channels\n\n"
    b = InlineKeyboardBuilder()
    for ch in channels:
        text += f"- {ch['channel_name']} ({ch['channel_id']})\n"
        b.button(text=f"❌ Remove {ch['channel_name']}", callback_data=f"rmchan_{ch['channel_id'].replace('@','AT')}")
    b.button(text="➕ Add", callback_data="addchan_start")
    b.button(text="◀️ Back", callback_data="admin_panel")
    await cb.message.edit_text(text, reply_markup=b.as_markup())

@admin_router.callback_query(F.data == "addchan_start")
async def addchan_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AdminStates.add_channel)
    await cb.message.edit_text("Send: @channel ChannelName invite_link", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_channels")]]))

@admin_router.message(AdminStates.add_channel)
async def add_channel(message: Message, state: FSMContext, db: Database):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        return await message.answer("Invalid format")
    ch_id = parts[0]
    ch_name = parts[1]
    invite = parts[2] if len(parts) > 2 else None
    await db.add_required_channel(ch_id, ch_name, invite)
    await message.answer(f"Added {ch_name}")

@admin_router.callback_query(F.data.startswith("rmchan_"))
async def rmchan(cb: CallbackQuery, db: Database):
    if not is_admin(cb.from_user.id):
        return
    ch_id = cb.data[7:].replace("AT", "@")
    await db.remove_required_channel(ch_id)
    await cb.answer(f"Removed {ch_id}")
    await cb_channels(cb, db)

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════════════════════════════
class DependencyMiddleware(BaseMiddleware):
    def __init__(self, db: Database, queue: QueueManager):
        self.db = db
        self.queue = queue
    async def __call__(self, handler, event: TelegramObject, data: dict):
        data["db"] = self.db
        data["queue"] = self.queue
        return await handler(event, data)

class BotApp:
    def __init__(self):
        self.db = Database(DB_PATH)
        self.bot = Bot(token=BOT_TOKEN)
        self.dp = Dispatcher(storage=MemoryStorage())
        self.downloader = None
        self.queue_manager = None

    async def setup(self):
        await self.db.connect()
        self.downloader = Downloader(self.db, self.bot)
        self.queue_manager = QueueManager(self.db, self.bot, self.downloader)
        await self.queue_manager.start()
        self.dp.update.middleware(DependencyMiddleware(self.db, self.queue_manager))
        self.dp.include_router(admin_router)
        self.dp.include_router(user_router)

    async def start(self):
        await self.setup()
        await self.dp.start_polling(self.bot, allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("ERROR: Set BOT_TOKEN environment variable")
        exit(1)
    print("=" * 50)
    print("WEBSITE DOWNLOADER BOT v3.1")
    print(f"Owner: @LM_S0 | Channel: @D3D0T")
    print("=" * 50)
    asyncio.run(BotApp().start())

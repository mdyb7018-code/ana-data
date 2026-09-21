"""
ANA DATA - Telegram Search Backend
FastAPI + Pyrogram (MTProto) for real Telegram lookups.

Quick start:
  1) pip install -r requirements.txt
  2) cp .env.example .env  (edit if needed)
  3) python main.py
  4) Open http://localhost:8000  (serves frontend)
  5) First run will ask for phone code — enter the code Telegram sends you

Production:
  - Use a real reverse proxy (nginx) + HTTPS
  - Change JWT_SECRET in .env
  - Use Postgres instead of SQLite if you expect high traffic
"""
import os
import re
import time
import sqlite3
import secrets
import asyncio
import logging
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from passlib.context import CryptContext
from jose import jwt, JWTError
from pyrogram import Client
from pyrogram.errors import (
    UsernameNotOccupied,
    UsernameInvalid,
    FloodWait,
    PeerIdInvalid,
)
from dotenv import load_dotenv

load_dotenv()

# ============================================
# Config
# ============================================
API_ID = int(os.getenv("API_ID", "36041141"))
API_HASH = os.getenv("API_HASH", "192dd9c6f9a766c7880bc74a59d53d2d")
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "+201143645282")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "mdyb7018@gmail.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123456")
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-in-production-" + secrets.token_urlsafe(16))
JWT_ALGO = "HS256"
JWT_EXPIRE_HOURS = 24 * 30  # 30 days

DEFAULT_POINTS = int(os.getenv("DEFAULT_POINTS", "100"))
SEARCH_COST = int(os.getenv("SEARCH_COST", "1"))
SITE_NAME = os.getenv("SITE_NAME", "ANA DATA")

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"
DB_PATH = BASE_DIR / "anadata.db"
SESSION_PATH = BASE_DIR / "anadata_session"

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("anadata")

# ============================================
# Telegram client
# ============================================
telegram_app: Client | None = None
telegram_connected: bool = False
telegram_user_info: dict | None = None


async def start_telegram():
    """Initialize and connect the Telegram client."""
    global telegram_app, telegram_connected, telegram_user_info

    telegram_app = Client(
        str(SESSION_PATH),
        api_id=API_ID,
        api_hash=API_HASH,
        phone_number=ADMIN_PHONE,
    )

    try:
        await telegram_app.start()
        me = await telegram_app.get_me()
        telegram_connected = True
        telegram_user_info = {
            "id": me.id,
            "first_name": me.first_name,
            "username": me.username,
            "phone": me.phone_number,
        }
        log.info(f"Telegram connected as @{me.username or me.first_name} (id={me.id})")
    except Exception as e:
        telegram_connected = False
        log.warning(f"Telegram not connected yet: {e}")
        log.warning("Run interactive setup: python auth_telegram.py")


# ============================================
# Database
# ============================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            points INTEGER NOT NULL DEFAULT 100,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            found INTEGER NOT NULL DEFAULT 0,
            phone TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    # Seed admin if missing
    c.execute("SELECT id FROM users WHERE email = ?", (ADMIN_EMAIL,))
    if not c.fetchone():
        c.execute(
            "INSERT INTO users (name, email, password_hash, points, role, created_at) VALUES (?,?,?,?,?,?)",
            ("Admin", ADMIN_EMAIL, pwd_ctx.hash(ADMIN_PASSWORD), 10_000_000, "admin", datetime.utcnow().isoformat()),
        )
        log.info(f"Created admin account: {ADMIN_EMAIL}")

    # Seed config
    defaults = {
        "site_name": SITE_NAME,
        "default_points": str(DEFAULT_POINTS),
        "search_cost": str(SEARCH_COST),
        "admin_email": ADMIN_EMAIL,
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?,?)", (k, v))

    conn.commit()
    conn.close()


def get_conn():
    return sqlite3.connect(DB_PATH)


# ============================================
# Schemas
# ============================================
class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=6)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class SearchIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class UpdateUserIn(BaseModel):
    points: int | None = None
    role: str | None = None


# ============================================
# Auth helpers
# ============================================
def create_token(user_id: int, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        return None


async def current_user(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "لازم تسجل دخول")
    payload = decode_token(auth[7:])
    if not payload:
        raise HTTPException(401, "الجلسة منتهية، سجل دخول تاني")
    uid = int(payload["sub"])
    conn = get_conn()
    row = conn.execute("SELECT id,name,email,points,role FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(401, "حساب مش موجود")
    return {"id": row[0], "name": row[1], "email": row[2], "points": row[3], "role": row[4]}


async def require_admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "مش مسموحلك")
    return user


# ============================================
# Helpers
# ============================================
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{4,32}$")


def normalize_username(s: str) -> str:
    s = s.strip().lstrip("@").strip()
    return s


def get_config(key: str, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    conn.close()
    return row[0] if row else default


def set_config(key: str, value: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO config (key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def log_search(user_id: int, username: str, found: bool, phone: str | None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO searches (user_id, username, found, phone, created_at) VALUES (?,?,?,?,?)",
        (user_id, username, 1 if found else 0, phone, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


# ============================================
# Telegram search (real)
# ============================================
async def telegram_resolve(username: str) -> dict:
    """Resolve a Telegram username to user info via Pyrogram."""
    global telegram_app, telegram_connected

    if not telegram_connected or telegram_app is None:
        return {"found": False, "error": "خدمة تليجرام غير متصلة حالياً. تواصل مع الأدمن."}

    try:
        # Resolve username
        try:
            user = await telegram_app.get_users(username)
        except (UsernameNotOccupied, UsernameInvalid):
            return {"found": False, "error": "اليوزر ده مش موجود أو مش صحيح"}
        except FloodWait as e:
            return {"found": False, "error": f"تيليجرام طلب استنى {e.value} ثانية"}
        except PeerIdInvalid:
            return {"found": False, "error": "اليوزر ده مش موجود"}
        except Exception as e:
            return {"found": False, "error": f"حصل خطأ: {str(e)[:100]}"}

        if not user:
            return {"found": False, "error": "لم يتم العثور على نتائج"}

        # Get full user object
        full = await telegram_app.get_users(user.id)

        # Phone numbers on Telegram are gated by user privacy settings.
        # full.phone_number is None for almost all users (unless they share it).
        # We return what we can and clearly indicate the rest.
        phone = getattr(full, "phone_number", None)
        # `status` may be "online", "offline", "recently", "within_week", "within_month", "long_time_ago", "hidden"
        status_enum = getattr(full, "status", None)
        status_str = str(status_enum).split(".")[-1] if status_enum else "unknown"

        # Last seen date -> approximate active months
        last_seen = getattr(full, "last_seen_date", None)
        active_months = None
        if last_seen:
            delta = datetime.utcnow() - last_seen.replace(tzinfo=None) if last_seen.tzinfo else datetime.utcnow() - last_seen
            # "Active" if last_seen within 6 months
            active_months = max(0, round(delta.days / 30))

        # Use `is_contact` and `is_mutual_contact` to flag phone visibility
        # But these are user-specific; we still return None for non-shared phones.
        phone_visible = bool(phone)

        return {
            "found": True,
            "data": {
                "username": getattr(full, "username", None) or username,
                "name": (
                    (getattr(full, "first_name", "") or "") +
                    (" " + getattr(full, "last_name", "") if getattr(full, "last_name", "") else "")
                ).strip() or username,
                "id": full.id,
                "phone": phone if phone_visible else None,
                "phone_visible": phone_visible,
                "status": "نشط" if status_str in ("online", "recently") else (
                    "متصل منذ فترة" if status_str in ("within_week", "within_month") else "غير متصل"
                ),
                "activeMonths": active_months,
                "is_bot": bool(getattr(full, "is_bot", False)),
                "is_verified": bool(getattr(full, "is_verified", False)),
                "is_premium": bool(getattr(full, "is_premium", False)),
            },
        }
    except Exception as e:
        log.exception("telegram_resolve error")
        return {"found": False, "error": f"خطأ غير متوقع: {str(e)[:100]}"}


# ============================================
# FastAPI app
# ============================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await start_telegram()
    yield
    if telegram_app and telegram_connected:
        await telegram_app.stop()


app = FastAPI(title="ANA DATA API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================
# Routes — Auth
# ============================================
@app.post("/api/auth/register")
async def register(data: RegisterIn):
    conn = get_conn()
    try:
        default_pts = int(get_config("default_points", DEFAULT_POINTS))
        conn.execute(
            "INSERT INTO users (name,email,password_hash,points,role,created_at) VALUES (?,?,?,?,?,?)",
            (data.name.strip(), data.email.lower(), pwd_ctx.hash(data.password), default_pts, "user", datetime.utcnow().isoformat()),
        )
        conn.commit()
        uid = conn.execute("SELECT id FROM users WHERE email=?", (data.email.lower(),)).fetchone()[0]
        token = create_token(uid, "user")
        return {
            "ok": True,
            "token": token,
            "user": {"id": uid, "name": data.name.strip(), "email": data.email.lower(),
                     "points": default_pts, "role": "user"},
        }
    except sqlite3.IntegrityError:
        raise HTTPException(400, "الإيميل ده مسجل قبل كده")
    finally:
        conn.close()


@app.post("/api/auth/login")
async def login(data: LoginIn):
    conn = get_conn()
    row = conn.execute(
        "SELECT id,name,email,password_hash,points,role FROM users WHERE email=?",
        (data.email.lower(),),
    ).fetchone()
    conn.close()
    if not row or not pwd_ctx.verify(data.password, row[3]):
        raise HTTPException(401, "الإيميل أو كلمة المرور غلط")
    uid, name, email, _h, points, role = row
    token = create_token(uid, role)
    return {
        "ok": True,
        "token": token,
        "user": {"id": uid, "name": name, "email": email, "points": points, "role": role},
    }


@app.get("/api/auth/me")
async def me(user=Depends(current_user)):
    return {"ok": True, "user": user}


# ============================================
# Routes — Search
# ============================================
@app.post("/api/search")
async def search(data: SearchIn, user=Depends(current_user)):
    username = normalize_username(data.username)
    if not USERNAME_RE.match(username):
        raise HTTPException(400, "اليوزر لازم يكون 4 حروف على الأقل، حروف وأرقام و _")

    cost = int(get_config("search_cost", SEARCH_COST))
    if user["points"] < cost:
        raise HTTPException(402, f"النقاط مش كافية. محتاج {cost} نقطة على الأقل.")

    # Decrement points
    conn = get_conn()
    conn.execute("UPDATE users SET points = points - ? WHERE id = ?", (cost, user["id"]))
    conn.commit()
    conn.close()

    result = await telegram_resolve(username)

    if result["found"]:
        log_search(user["id"], username, True, result["data"].get("phone"))
        return {
            "ok": True,
            "data": result["data"],
            "points_remaining": user["points"] - cost,
        }
    else:
        log_search(user["id"], username, False, None)
        # Refund on not-found
        conn = get_conn()
        conn.execute("UPDATE users SET points = points + ? WHERE id = ?", (cost, user["id"]))
        conn.commit()
        conn.close()
        raise HTTPException(404, result.get("error", "لم يتم العثور على نتائج"))


# ============================================
# Routes — Admin
# ============================================
@app.get("/api/admin/stats")
async def admin_stats(_=Depends(require_admin)):
    conn = get_conn()
    users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    searches = conn.execute("SELECT COUNT(*) FROM searches").fetchone()[0]
    success = conn.execute("SELECT COUNT(*) FROM searches WHERE found=1").fetchone()[0]
    spent = conn.execute(
        "SELECT COALESCE(SUM(?),0) FROM searches WHERE found=1",
        (int(get_config("search_cost", SEARCH_COST)),),
    ).fetchone()[0]
    conn.close()
    return {
        "ok": True,
        "data": {
            "users": users,
            "searches": searches,
            "success": success,
            "spent": spent,
            "telegram": {
                "connected": telegram_connected,
                "account": telegram_user_info,
            },
        },
    }


@app.get("/api/admin/users")
async def admin_users(_=Depends(require_admin)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id,name,email,points,role,created_at FROM users ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return {"ok": True, "users": [
        {"id": r[0], "name": r[1], "email": r[2], "points": r[3], "role": r[4], "created_at": r[5]}
        for r in rows
    ]}


@app.get("/api/admin/searches")
async def admin_searches(limit: int = 50, _=Depends(require_admin)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT s.id,s.username,u.email,s.found,s.created_at FROM searches s "
        "JOIN users u ON u.id = s.user_id ORDER BY s.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return {"ok": True, "searches": [
        {"id": r[0], "username": r[1], "user_email": r[2], "found": bool(r[3]), "created_at": r[4]}
        for r in rows
    ]}


@app.patch("/api/admin/users/{uid}")
async def admin_update_user(uid: int, data: UpdateUserIn, _=Depends(require_admin)):
    conn = get_conn()
    if data.points is not None:
        conn.execute("UPDATE users SET points=? WHERE id=?", (data.points, uid))
    if data.role is not None:
        if data.role not in ("user", "admin"):
            raise HTTPException(400, "دور غير صحيح")
        conn.execute("UPDATE users SET role=? WHERE id=?", (data.role, uid))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/admin/users/{uid}")
async def admin_delete_user(uid: int, _=Depends(require_admin)):
    conn = get_conn()
    conn.execute("DELETE FROM users WHERE id=? AND role != 'admin'", (uid,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/admin/config")
async def admin_get_config(_=Depends(require_admin)):
    conn = get_conn()
    rows = conn.execute("SELECT key,value FROM config").fetchall()
    conn.close()
    return {"ok": True, "config": {k: v for k, v in rows}}


class ConfigUpdate(BaseModel):
    site_name: str | None = None
    default_points: int | None = None
    search_cost: int | None = None
    admin_email: str | None = None


@app.patch("/api/admin/config")
async def admin_update_config(data: ConfigUpdate, _=Depends(require_admin)):
    if data.site_name is not None:
        set_config("site_name", data.site_name)
    if data.default_points is not None:
        set_config("default_points", str(data.default_points))
    if data.search_cost is not None:
        set_config("search_cost", str(data.search_cost))
    if data.admin_email is not None:
        set_config("admin_email", data.admin_email)
    return {"ok": True}


# ============================================
# Public config (site name etc.)
# ============================================
@app.get("/api/config")
async def public_config():
    return {"ok": True, "config": {
        "site_name": get_config("site_name", SITE_NAME),
    }}


# ============================================
# Static frontend (mount after API)
# ============================================
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


# ============================================
# Run
# ============================================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)

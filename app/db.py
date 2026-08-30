"""SQLite 存储：生成历史 + AI 主持会话。单文件库，随 data/ 目录一起备份。"""
import json
import sqlite3
import threading
import time
from pathlib import Path

from .config import DATA_DIR

DB_PATH = Path(DATA_DIR) / "app.db"
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("""CREATE TABLE IF NOT EXISTS soups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            settings TEXT,
            data TEXT,
            image_path TEXT)""")
        _conn.execute("""CREATE TABLE IF NOT EXISTS host_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            soup_id INTEGER,
            created_at TEXT,
            messages TEXT)""")
        _conn.commit()
    return _conn


def _row_to_soup(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "created_at": r["created_at"], "settings": json.loads(r["settings"] or "{}"),
            "data": json.loads(r["data"] or "{}"), "image_path": r["image_path"]}


def save_soup(settings: dict, data: dict, image_path) -> int:
    image_path = str(image_path) if image_path else None
    with _lock:
        c = _get().execute("INSERT INTO soups (created_at, settings, data, image_path) VALUES (?,?,?,?)",
                           (time.strftime("%Y-%m-%d %H:%M:%S"), json.dumps(settings, ensure_ascii=False),
                            json.dumps(data, ensure_ascii=False), image_path))
        _get().commit()
        return c.lastrowid


def update_soup_image(soup_id: int, image_path: str):
    with _lock:
        _get().execute("UPDATE soups SET image_path=? WHERE id=?", (image_path, soup_id))
        _get().commit()


def list_soups() -> list[dict]:
    with _lock:
        rows = _get().execute("SELECT id, created_at, settings, data, image_path FROM soups ORDER BY id DESC").fetchall()
    out = []
    for r in rows:
        s = _row_to_soup(r)
        s["preview"] = (s["data"].get("surface") or "")[:60]
        s["has_image"] = bool(s["image_path"])
        out.append(s)
    return out


def get_soup(soup_id: int) -> dict | None:
    with _lock:
        r = _get().execute("SELECT id, created_at, settings, data, image_path FROM soups WHERE id=?", (soup_id,)).fetchone()
    return _row_to_soup(r) if r else None


def delete_soup(soup_id: int):
    with _lock:
        _get().execute("DELETE FROM soups WHERE id=?", (soup_id,))
        _get().commit()


# ---------- AI 主持会话 ----------

def create_host_session(soup_id: int | None) -> int:
    with _lock:
        c = _get().execute("INSERT INTO host_sessions (soup_id, created_at, messages) VALUES (?,?,?)",
                           (soup_id, time.strftime("%Y-%m-%d %H:%M:%S"), json.dumps([], ensure_ascii=False)))
        _get().commit()
        return c.lastrowid


def get_host_messages(session_id: int) -> list[dict]:
    with _lock:
        r = _get().execute("SELECT messages FROM host_sessions WHERE id=?", (session_id,)).fetchone()
    return json.loads(r["messages"] or "[]") if r else []


def append_host_message(session_id: int, role: str, content: str):
    with _lock:
        r = _get().execute("SELECT messages FROM host_sessions WHERE id=?", (session_id,)).fetchone()
        if r is None:
            return
        msgs = json.loads(r["messages"] or "[]")
        msgs.append({"role": role, "content": content})
        _get().execute("UPDATE host_sessions SET messages=? WHERE id=?", (json.dumps(msgs, ensure_ascii=False), session_id))
        _get().commit()

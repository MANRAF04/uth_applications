"""SQLite storage for chats and the student profile."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from fetch_theses import HERE

DB_PATH = HERE / "app.db"
TITLE_CHARS = 60
PROFILE_FIELDS = {
    "bio": str,
    "liked_professors": list,
    "disliked_professors": list,
    "liked_directions": str,
    "disliked_directions": str,
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    focus_id INTEGER,
    steps TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_by_chat ON messages (chat_id, id);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@contextmanager
def database():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init():
    with database() as db:
        db.executescript(SCHEMA)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_profile(profile):
    if not isinstance(profile, dict):
        return None
    cleaned = {}
    for key, kind in PROFILE_FIELDS.items():
        value = profile.get(key, kind())
        if not isinstance(value, kind) or (kind is list and not all(isinstance(item, str) for item in value)):
            return None
        cleaned[key] = value
    return cleaned


def load_profile():
    with database() as db:
        row = db.execute("SELECT value FROM settings WHERE key = 'profile'").fetchone()
    return json.loads(row["value"]) if row else clean_profile({})


def save_profile(profile):
    with database() as db:
        db.execute(
            "INSERT INTO settings (key, value) VALUES ('profile', ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (json.dumps(profile, ensure_ascii=False),),
        )


def list_chats():
    with database() as db:
        rows = db.execute("SELECT id, title, updated_at FROM chats ORDER BY updated_at DESC, id DESC").fetchall()
    return [dict(row) for row in rows]


def get_chat(chat_id):
    with database() as db:
        chat = db.execute("SELECT id, title, updated_at FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if not chat:
            return None
        rows = db.execute(
            "SELECT role, content, focus_id, steps FROM messages WHERE chat_id = ? ORDER BY id", (chat_id,)
        ).fetchall()
    messages = [dict(row, steps=json.loads(row["steps"])) for row in rows]
    return dict(chat, messages=messages)


def delete_chat(chat_id):
    with database() as db:
        return db.execute("DELETE FROM chats WHERE id = ?", (chat_id,)).rowcount > 0


def save_exchange(chat_id, question, focus_id, reply, steps):
    """Store one question and its answer; creates the chat when chat_id is None. Returns the chat summary or None if the chat was deleted meanwhile."""
    timestamp = now()
    with database() as db:
        if chat_id is None:
            title = " ".join(question.split())[:TITLE_CHARS]
            chat_id = db.execute(
                "INSERT INTO chats (title, created_at, updated_at) VALUES (?, ?, ?)", (title, timestamp, timestamp)
            ).lastrowid
        elif not db.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (timestamp, chat_id)).rowcount:
            return None
        db.executemany(
            "INSERT INTO messages (chat_id, role, content, focus_id, steps, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (chat_id, "user", question, focus_id, "[]", timestamp),
                (chat_id, "assistant", reply, None, json.dumps(steps, ensure_ascii=False), timestamp),
            ],
        )
        chat = db.execute("SELECT id, title, updated_at FROM chats WHERE id = ?", (chat_id,)).fetchone()
    return dict(chat)

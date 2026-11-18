import json
import sqlite3
import uuid
import urllib.request
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "app.db"
API_URL = "http://127.0.0.1:8080/v1/chat/completions"
MODEL = "Qwen3-4B"

app = FastAPI(title="Local AI")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            instructions TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT 'New chat',
            project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id);
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)
        defaults = {
            "theme": "dark",
            "accent": "#8b7cff",
            "font": "Inter",
            "font_size": "15",
            "effort": "medium"
        }
        for key, value in defaults.items():
            con.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
                (key, value)
            )


init_db()


class NewChat(BaseModel):
    project_id: Optional[str] = None


class NewProject(BaseModel):
    name: str
    instructions: str = ""


class UpdateProject(BaseModel):
    name: Optional[str] = None
    instructions: Optional[str] = None


class SendMessage(BaseModel):
    content: str
    effort: Optional[str] = None


class UpdateSettings(BaseModel):
    theme: Optional[str] = None
    accent: Optional[str] = None
    font: Optional[str] = None
    font_size: Optional[str] = None
    effort: Optional[str] = None


class RenameChat(BaseModel):
    title: str


def model_call(messages, effort="medium", max_tokens=1200):
    # Qwen3 uses /think and /no_think control markers.
    # The selected effort is mapped to its supported thinking mode.
    marker = "/no_think" if effort == "low" else "/think"
    messages = [dict(m) for m in messages]
    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] += "\n" + marker

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.6,
        "max_tokens": max_tokens
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=2400) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Cannot reach Qwen at {API_URL}. Is llama-server running? {exc}"
        )

    try:
        content = data["choices"][0]["message"].get("content", "")
    except (KeyError, IndexError, TypeError):
        raise HTTPException(status_code=502, detail=f"Unexpected model response: {data}")

    if isinstance(content, list):
        content = "".join(
            p.get("text", "") for p in content if isinstance(p, dict)
        )
    if not content or not content.strip():
        raise HTTPException(status_code=502, detail="Qwen returned an empty response.")
    # Hide private reasoning text; retain only the final answer.
    if "</think>" in content:
        content = content.rsplit("</think>", 1)[-1]
    return content.strip()


def retrieve_personal_memory(question, effort="low"):
    router = [
        {
            "role": "system",
            "content": (
                "Decide whether answering the user's question requires their "
                "personal past conversations or facts. Greetings, general "
                "knowledge, coding help and ordinary conversation do NOT need "
                "memory. Return only JSON: "
                '{"needs_memory":false,"search_terms":[]} '
                "If needed, return 5-8 specific keywords or short phrases. "
                "The archive is mostly Russian, with some Hebrew and English. "
                "Include useful Russian/English variants. Do not answer."
            )
        },
        {"role": "user", "content": question}
    ]
    raw = model_call(router, effort="low", max_tokens=180)
    try:
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end + 1])
        if not data.get("needs_memory") or not isinstance(data.get("search_terms"), list):
            return ""
        terms = [str(x).strip() for x in data["search_terms"] if str(x).strip()]
        if not terms:
            return ""
        # Import lazily so the web app still starts if the personal DB is absent.
        import memory
        rows = memory.search(terms)
        if not rows:
            return ""
        return "\n\n".join(
            f"Date: {date}\nChat: {chat}\nSpeaker: {speaker}\nMessage: {snippet}"
            for date, chat, speaker, snippet in rows
        )
    except Exception:
        # Memory retrieval must never prevent ordinary chat.
        return ""


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/chats")
def list_chats():
    with connect() as con:
        rows = con.execute("""
            SELECT c.id,c.title,c.project_id,c.updated_at,
                   p.name AS project_name,
                   (SELECT content FROM messages m WHERE m.chat_id=c.id
                    ORDER BY m.id DESC LIMIT 1) AS last_message
            FROM chats c LEFT JOIN projects p ON p.id=c.project_id
            ORDER BY c.updated_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/chats")
def create_chat(data: NewChat):
    chat_id = str(uuid.uuid4())
    with connect() as con:
        if data.project_id:
            exists = con.execute(
                "SELECT 1 FROM projects WHERE id=?", (data.project_id,)
            ).fetchone()
            if not exists:
                raise HTTPException(404, "Project not found")
        con.execute(
            "INSERT INTO chats(id,title,project_id) VALUES(?,?,?)",
            (chat_id, "New chat", data.project_id)
        )
    return {"id": chat_id, "title": "New chat", "project_id": data.project_id}


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str):
    with connect() as con:
        chat = con.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not chat:
            raise HTTPException(404, "Chat not found")
        messages = con.execute(
            "SELECT id,role,content,created_at FROM messages WHERE chat_id=? ORDER BY id",
            (chat_id,)
        ).fetchall()
    return {"chat": dict(chat), "messages": [dict(m) for m in messages]}


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str):
    with connect() as con:
        con.execute("DELETE FROM chats WHERE id=?", (chat_id,))
    return {"ok": True}


@app.patch("/api/chats/{chat_id}")
def rename_chat(chat_id: str, data: RenameChat):
    title = data.title.strip()[:100]
    if not title:
        raise HTTPException(400, "Title cannot be empty")
    with connect() as con:
        cur = con.execute(
            "UPDATE chats SET title=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (title, chat_id)
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Chat not found")
    return {"ok": True, "title": title}


@app.post("/api/chats/{chat_id}/messages")
def send_message(chat_id: str, data: SendMessage):
    question = data.content.strip()
    if not question:
        raise HTTPException(400, "Message cannot be empty")

    with connect() as con:
        chat = con.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not chat:
            raise HTTPException(404, "Chat not found")
        project = None
        if chat["project_id"]:
            project = con.execute(
                "SELECT * FROM projects WHERE id=?", (chat["project_id"],)
            ).fetchone()
        con.execute(
            "INSERT INTO messages(chat_id,role,content) VALUES(?,?,?)",
            (chat_id, "user", question)
        )
        history = con.execute(
            "SELECT role,content FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT 24",
            (chat_id,)
        ).fetchall()
        history = list(reversed(history))

    effort = data.effort or "medium"
    memory_text = retrieve_personal_memory(question, effort="low")
    instructions = (
        "You are a helpful private local AI assistant. Answer in the same "
        "language as the user. Be direct, useful and honest. "
        "Do not claim to remember something unless it is in the supplied memory."
    )
    if project and project["instructions"].strip():
        instructions += "\n\nProject instructions:\n" + project["instructions"]
    if memory_text:
        instructions += (
            "\n\nRelevant excerpts from the user's personal history database. "
            "Use these only as evidence about the user's past; if irrelevant, "
            "ignore them:\n" + memory_text
        )

    messages = [{"role": "system", "content": instructions}]
    messages.extend({"role": m["role"], "content": m["content"]} for m in history)
    answer = model_call(messages, effort=effort)

    with connect() as con:
        con.execute(
            "INSERT INTO messages(chat_id,role,content) VALUES(?,?,?)",
            (chat_id, "assistant", answer)
        )
        count = con.execute(
            "SELECT COUNT(*) FROM messages WHERE chat_id=?", (chat_id,)
        ).fetchone()[0]
        if count <= 2 and chat["title"] == "New chat":
            title = question[:48] + ("…" if len(question) > 48 else "")
            con.execute(
                "UPDATE chats SET title=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (title, chat_id)
            )
        else:
            con.execute(
                "UPDATE chats SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (chat_id,)
            )
    return {"answer": answer}


@app.get("/api/projects")
def list_projects():
    with connect() as con:
        rows = con.execute("""
            SELECT p.*,
              (SELECT COUNT(*) FROM chats c WHERE c.project_id=p.id) AS chat_count
            FROM projects p ORDER BY p.created_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/projects")
def create_project(data: NewProject):
    name = data.name.strip()[:80]
    if not name:
        raise HTTPException(400, "Project name is required")
    project_id = str(uuid.uuid4())
    with connect() as con:
        con.execute(
            "INSERT INTO projects(id,name,instructions) VALUES(?,?,?)",
            (project_id, name, data.instructions.strip())
        )
    return {"id": project_id, "name": name}


@app.patch("/api/projects/{project_id}")
def update_project(project_id: str, data: UpdateProject):
    with connect() as con:
        row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")
        name = data.name.strip()[:80] if data.name is not None else row["name"]
        instructions = data.instructions if data.instructions is not None else row["instructions"]
        con.execute(
            "UPDATE projects SET name=?,instructions=? WHERE id=?",
            (name, instructions, project_id)
        )
    return {"ok": True}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    with connect() as con:
        con.execute("DELETE FROM projects WHERE id=?", (project_id,))
    return {"ok": True}


@app.get("/api/settings")
def get_settings():
    with connect() as con:
        return {r["key"]: r["value"] for r in con.execute("SELECT * FROM settings")}


@app.patch("/api/settings")
def update_settings(data: UpdateSettings):
    allowed = {"theme", "accent", "font", "font_size", "effort"}
    values = data.model_dump(exclude_none=True)
    with connect() as con:
        for key, value in values.items():
            if key not in allowed:
                continue
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value))
            )
    return get_settings()


@app.get("/api/search")
def search_chats(q: str):
    q = q.strip()
    if not q:
        return []
    with connect() as con:
        rows = con.execute("""
            SELECT DISTINCT c.id,c.title,c.updated_at
            FROM chats c JOIN messages m ON m.chat_id=c.id
            WHERE c.title LIKE ? OR m.content LIKE ?
            ORDER BY c.updated_at DESC LIMIT 30
        """, (f"%{q}%", f"%{q}%")).fetchall()
    return [dict(r) for r in rows]

import os
import logging
from logging.handlers import RotatingFileHandler
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
import uvicorn


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("SMS_STORE_DB", BASE_DIR / "messages.sqlite3"))
LOG_DIR = BASE_DIR / "logs"
LOG_PATH = LOG_DIR / "app.log"
API_TOKEN = os.getenv("SMS_STORE_TOKEN", "")

logger = logging.getLogger("sms_store_restore")


class MessageIn(BaseModel):
    chat_id: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1)


class MessageOut(BaseModel):
    message_id: int
    chat_id: str
    text: str
    created_at: str


class DeleteOut(BaseModel):
    deleted: int


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc_iso(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid ISO-8601 time: {value}") from exc

    if parsed.tzinfo is None:
        raise HTTPException(status_code=422, detail=f"Time must include timezone: {value}")

    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def init_db() -> None:
    global DB_PATH

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_chat_id_created_at ON messages(chat_id, created_at)"
            )
    except (sqlite3.OperationalError, PermissionError):
        fallback_db = Path(os.getenv("SMS_STORE_FALLBACK_DB", DB_PATH.parent / "messages.sqlite3"))
        DB_PATH = fallback_db
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_chat_id_created_at ON messages(chat_id, created_at)"
            )


def init_logging() -> None:
    global LOG_DIR, LOG_PATH

    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_PATH,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    except (OSError, PermissionError):
        fallback_log_dir = Path(
            os.getenv("SMS_STORE_FALLBACK_LOG_DIR", str(LOG_DIR.parent / "logs"))
        )
        LOG_DIR = fallback_log_dir
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        LOG_PATH = LOG_DIR / "app.log"
        file_handler = RotatingFileHandler(
            LOG_PATH,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )

    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def require_token(authorization: str | None) -> None:
    if not API_TOKEN:
        return

    expected = f"Bearer {API_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing token")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_logging()
    init_db()
    logger.info("startup complete db=%s log=%s", DB_PATH, LOG_PATH)
    yield


app = FastAPI(title="SMS Store Restore", version="1.0.0", lifespan=lifespan)


@app.post("/messages", response_model=MessageOut)
def save_message(
    payload: MessageIn,
    authorization: Annotated[str | None, Header()] = None,
) -> MessageOut:
    require_token(authorization)
    created_at = utc_now_iso()

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO messages (chat_id, text, created_at)
            VALUES (?, ?, ?)
            """,
            (payload.chat_id, payload.text, created_at),
        )
        message_id = cursor.lastrowid

    logger.info("message saved message_id=%s chat_id=%s", message_id, payload.chat_id)

    return MessageOut(
        message_id=message_id,
        chat_id=payload.chat_id,
        text=payload.text,
        created_at=created_at,
    )


@app.get("/messages", response_model=list[MessageOut])
def list_messages(
    chat_id: str = Query(min_length=1),
    authorization: Annotated[str | None, Header()] = None,
    from_time: str | None = Query(default=None, alias="from"),
    to_time: str | None = Query(default=None, alias="to"),
) -> list[MessageOut]:
    require_token(authorization)

    from_utc = parse_utc_iso(from_time) if from_time else None
    to_utc = parse_utc_iso(to_time) if to_time else None

    query = [
        "SELECT id, chat_id, text, created_at",
        "FROM messages",
        "WHERE chat_id = ?",
    ]
    params: list[object] = [chat_id]

    if from_utc is not None:
        query.append("AND created_at >= ?")
        params.append(from_utc)

    if to_utc is not None:
        query.append("AND created_at <= ?")
        params.append(to_utc)

    query.append("ORDER BY created_at ASC, id ASC")

    with get_connection() as conn:
        rows = conn.execute(" ".join(query), params).fetchall()

    logger.info(
        "messages listed chat_id=%s from=%s to=%s count=%s",
        chat_id,
        from_utc,
        to_utc,
        len(rows),
    )

    return [
        MessageOut(
            message_id=row["id"],
            chat_id=row["chat_id"],
            text=row["text"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


@app.delete("/messages", response_model=DeleteOut)
def delete_messages(
    authorization: Annotated[str | None, Header()] = None,
    message_id: int | None = Query(default=None, ge=1),
    from_time: str | None = Query(default=None, alias="from"),
    to_time: str | None = Query(default=None, alias="to"),
    chat_id: str | None = Query(default=None, min_length=1),
) -> DeleteOut:
    require_token(authorization)

    if message_id is None and from_time is None and to_time is None:
        raise HTTPException(
            status_code=422,
            detail="Provide message_id or at least one time filter",
        )

    from_utc = parse_utc_iso(from_time) if from_time else None
    to_utc = parse_utc_iso(to_time) if to_time else None

    query = ["DELETE FROM messages WHERE 1=1"]
    params: list[object] = []

    if message_id is not None:
        query.append("AND id = ?")
        params.append(message_id)

    if chat_id is not None:
        query.append("AND chat_id = ?")
        params.append(chat_id)

    if from_utc is not None:
        query.append("AND created_at >= ?")
        params.append(from_utc)

    if to_utc is not None:
        query.append("AND created_at <= ?")
        params.append(to_utc)

    with get_connection() as conn:
        cursor = conn.execute(" ".join(query), params)

    logger.info(
        "messages deleted message_id=%s chat_id=%s from=%s to=%s deleted=%s",
        message_id,
        chat_id,
        from_utc,
        to_utc,
        cursor.rowcount,
    )

    return DeleteOut(deleted=cursor.rowcount)


def main() -> None:
    ssl_keyfile = os.getenv("SSL_KEYFILE")
    ssl_certfile = os.getenv("SSL_CERTFILE")
    ssl_ca_certs = os.getenv("SSL_CA_CERTS")

    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        ssl_keyfile=ssl_keyfile or None,
        ssl_certfile=ssl_certfile or None,
        ssl_ca_certs=ssl_ca_certs or None,
    )


if __name__ == "__main__":
    main()

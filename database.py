import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "bot.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(initial_admin_ids: list[int] = None):
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            max_user_id BIGINT UNIQUE NOT NULL,
            full_name VARCHAR(255),
            role TEXT DEFAULT 'user' CHECK(role IN ('user','admin')),
            created_at TEXT DEFAULT (datetime('now')),
            last_active_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS material_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_number VARCHAR(20) UNIQUE,
            user_id BIGINT NOT NULL,
            applicant_name VARCHAR(255),
            material_name VARCHAR(255),
            quantity REAL,
            unit VARCHAR(50),
            object_or_task VARCHAR(255),
            resp_name VARCHAR(255),
            resp_phone VARCHAR(50),
            tech_list TEXT DEFAULT '',
            status TEXT DEFAULT 'new' CHECK(status IN ('new','in_progress','issued','rejected','withdrawn')),
            status_comment TEXT,
            processed_by_user_id BIGINT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS request_counter (
            id INTEGER PRIMARY KEY CHECK(id=1),
            last_num INTEGER DEFAULT 0
        )
    """)
    c.execute("INSERT OR IGNORE INTO request_counter (id, last_num) VALUES (1, 0)")

    conn.commit()
    conn.close()

    # Добавляем начальных администраторов
    if initial_admin_ids:
        for uid in initial_admin_ids:
            ensure_user(uid, "Администратор", role="admin")


# ── Пользователи ──────────────────────────────────────────────────────────────

def ensure_user(max_user_id: int, full_name: str, role: str = "user") -> dict:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE max_user_id=?", (max_user_id,))
    row = c.fetchone()
    if row is None:
        c.execute(
            "INSERT INTO users (max_user_id, full_name, role) VALUES (?,?,?)",
            (max_user_id, full_name, role)
        )
        conn.commit()
        c.execute("SELECT * FROM users WHERE max_user_id=?", (max_user_id,))
        row = c.fetchone()
    else:
        c.execute(
            "UPDATE users SET last_active_at=datetime('now'), full_name=? WHERE max_user_id=?",
            (full_name, max_user_id)
        )
        conn.commit()
    result = dict(row)
    conn.close()
    return result


def get_user(max_user_id: int) -> dict | None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE max_user_id=?", (max_user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def is_admin(max_user_id: int) -> bool:
    user = get_user(max_user_id)
    return user is not None and user["role"] == "admin"


def set_role(max_user_id: int, role: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET role=? WHERE max_user_id=?", (role, max_user_id))
    conn.commit()
    conn.close()


def get_all_admins() -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE role='admin'")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def find_users(query: str) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    like = f"%{query}%"
    c.execute("SELECT * FROM users WHERE full_name LIKE ? OR CAST(max_user_id AS TEXT) LIKE ?", (like, like))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_stats() -> dict:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as total FROM users")
    total_users = c.fetchone()["total"]
    c.execute("SELECT COUNT(*) as total FROM users WHERE role='admin'")
    total_admins = c.fetchone()["total"]
    c.execute("SELECT COUNT(*) as total FROM material_requests")
    total_req = c.fetchone()["total"]
    stats = {"new": 0, "in_progress": 0, "issued": 0, "rejected": 0}
    for s in stats:
        c.execute("SELECT COUNT(*) as cnt FROM material_requests WHERE status=?", (s,))
        stats[s] = c.fetchone()["cnt"]
    conn.close()
    return {
        "total_users": total_users,
        "total_admins": total_admins,
        "total_requests": total_req,
        **stats,
    }


# ── Заявки на материал ────────────────────────────────────────────────────────

def next_request_number() -> str:
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE request_counter SET last_num = last_num + 1 WHERE id=1")
    conn.commit()
    c.execute("SELECT last_num FROM request_counter WHERE id=1")
    num = c.fetchone()["last_num"]
    conn.close()
    year = datetime.now().year
    return f"ЗМ-{year}-{num:04d}"


def create_request(data: dict) -> dict:
    req_num = next_request_number()
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO material_requests
            (request_number, user_id, applicant_name, material_name, quantity, unit,
             object_or_task, resp_name, resp_phone, tech_list, status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        req_num,
        data["user_id"],
        data.get("applicant_name", ""),
        data.get("material_name", ""),
        data.get("quantity", 0),
        data.get("unit", "шт"),
        data.get("object_or_task", ""),
        data.get("resp_name", ""),
        data.get("resp_phone", ""),
        data.get("tech_list", ""),
        "new",
    ))
    conn.commit()
    c.execute("SELECT * FROM material_requests WHERE request_number=?", (req_num,))
    row = dict(c.fetchone())
    conn.close()
    return row


def get_my_requests(user_id: int) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM material_requests WHERE user_id=? ORDER BY id DESC", (user_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_all_requests(status: str = None) -> list[dict]:
    conn = get_conn()
    c = conn.cursor()
    if status:
        c.execute("SELECT * FROM material_requests WHERE status=? ORDER BY id DESC", (status,))
    else:
        c.execute("SELECT * FROM material_requests ORDER BY id DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_request_by_number(req_num: str) -> dict | None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM material_requests WHERE request_number=?", (req_num,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_request_by_id(req_id: int) -> dict | None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM material_requests WHERE id=?", (req_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def update_request_status(req_id: int, status: str, comment: str = "", admin_id: int = None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE material_requests
        SET status=?, status_comment=?, processed_by_user_id=?, updated_at=datetime('now')
        WHERE id=?
    """, (status, comment, admin_id, req_id))
    conn.commit()
    conn.close()

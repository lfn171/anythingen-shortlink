import os
import secrets
import sqlite3
import string
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlparse

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "shortlinks.db"))
BASE_URL = os.getenv("BASE_URL", "https://anythingen.com").rstrip("/")
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))
API_KEY = os.getenv("API_KEY", "change-me")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me-now")
ALLOWED_DOMAINS = {
    d.strip().lower()
    for d in os.getenv("ALLOWED_DOMAINS", "pan.quark.cn,pan.baidu.com").split(",")
    if d.strip()
}

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "1") == "1",
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            target_url TEXT NOT NULL,
            note TEXT DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            visits INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_visit_at TEXT,
            expires_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    # Store a password hash so the .env password is only used to initialize or reset it.
    row = conn.execute("SELECT value FROM settings WHERE key='admin_password_hash'").fetchone()
    if not row:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('admin_password_hash', ?)",
            (generate_password_hash(ADMIN_PASSWORD),),
        )
    conn.commit()
    conn.close()


def get_admin_password_hash():
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key='admin_password_hash'").fetchone()
    conn.close()
    return row["value"] if row else ""


def set_admin_password(password):
    conn = get_db()
    conn.execute(
        "INSERT INTO settings(key, value) VALUES('admin_password_hash', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (generate_password_hash(password),),
    )
    conn.commit()
    conn.close()


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)

    return wrapper


def api_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        supplied = request.headers.get("X-API-Key", "")
        if not supplied or not secrets.compare_digest(supplied, API_KEY):
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return fn(*args, **kwargs)

    return wrapper


def generate_code(length=8):
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def is_valid_code(code):
    if not code or len(code) > 64:
        return False
    allowed = set(string.ascii_letters + string.digits + "-_")
    return all(ch in allowed for ch in code)


def normalize_url(url):
    return (url or "").strip()


def is_allowed_url(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        host = parsed.hostname.lower()
        return host in ALLOWED_DOMAINS
    except Exception:
        return False


def normalize_expiry(value):
    value = (value or "").strip()
    if not value:
        return None
    # HTML datetime-local: 2026-12-31T23:59
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def is_expired(expires_at):
    if not expires_at:
        return False
    try:
        dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
        return datetime.now() >= dt
    except ValueError:
        return False


def unique_random_code(conn):
    while True:
        code = generate_code()
        exists = conn.execute("SELECT 1 FROM links WHERE code=?", (code,)).fetchone()
        if not exists:
            return code


def row_to_dict(row):
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    item["short_url"] = f"{BASE_URL}/s/{item['code']}"
    return item


@app.get("/health")
def health():
    return jsonify({"success": True, "status": "ok"})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == ADMIN_USERNAME and check_password_hash(get_admin_password_hash(), password):
            session.clear()
            session["logged_in"] = True
            session["username"] = username
            flash("登录成功", "success")
            next_url = request.args.get("next")
            if next_url and next_url.startswith("/"):
                return redirect(next_url)
            return redirect(url_for("admin"))
        flash("用户名或密码错误", "danger")
    return render_template("login.html")


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
def index():
    if session.get("logged_in"):
        return redirect(url_for("admin"))
    return redirect(url_for("login"))


@app.get("/admin")
@login_required
def admin():
    q = request.args.get("q", "").strip()
    page = max(int(request.args.get("page", 1) or 1), 1)
    per_page = 20
    offset = (page - 1) * per_page

    conn = get_db()
    where = ""
    params = []
    if q:
        where = "WHERE code LIKE ? OR note LIKE ? OR target_url LIKE ?"
        pattern = f"%{q}%"
        params = [pattern, pattern, pattern]

    total = conn.execute(f"SELECT COUNT(*) AS c FROM links {where}", params).fetchone()["c"]
    rows = conn.execute(
        f"SELECT * FROM links {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        [*params, per_page, offset],
    ).fetchall()
    stats = conn.execute(
        "SELECT COUNT(*) AS total_links, COALESCE(SUM(visits),0) AS total_visits, "
        "SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) AS enabled_links FROM links"
    ).fetchone()
    conn.close()

    pages = max((total + per_page - 1) // per_page, 1)
    return render_template(
        "admin.html",
        links=[row_to_dict(r) for r in rows],
        q=q,
        page=page,
        pages=pages,
        total=total,
        stats=stats,
        base_url=BASE_URL,
    )


@app.route("/admin/links/new", methods=["GET", "POST"])
@login_required
def add_link():
    if request.method == "POST":
        target_url = normalize_url(request.form.get("target_url"))
        code = request.form.get("code", "").strip()
        note = request.form.get("note", "").strip()
        enabled = 1 if request.form.get("enabled") == "on" else 0
        expires_raw = request.form.get("expires_at", "")
        expires_at = normalize_expiry(expires_raw)

        if not is_allowed_url(target_url):
            flash("目标链接无效，或域名不在允许列表中", "danger")
            return render_template("link_form.html", mode="new", form=request.form, allowed_domains=ALLOWED_DOMAINS)
        if code and not is_valid_code(code):
            flash("短码只能使用字母、数字、-、_，最多 64 位", "danger")
            return render_template("link_form.html", mode="new", form=request.form, allowed_domains=ALLOWED_DOMAINS)
        if expires_raw and not expires_at:
            flash("过期时间格式无效", "danger")
            return render_template("link_form.html", mode="new", form=request.form, allowed_domains=ALLOWED_DOMAINS)

        conn = get_db()
        if not code:
            code = unique_random_code(conn)
        try:
            conn.execute(
                "INSERT INTO links(code,target_url,note,enabled,expires_at) VALUES(?,?,?,?,?)",
                (code, target_url, note, enabled, expires_at),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            flash("这个短码已经存在", "danger")
            return render_template("link_form.html", mode="new", form=request.form, allowed_domains=ALLOWED_DOMAINS)
        conn.close()
        flash(f"短链接已创建：{BASE_URL}/s/{code}", "success")
        return redirect(url_for("admin"))

    return render_template("link_form.html", mode="new", form={}, allowed_domains=ALLOWED_DOMAINS)


@app.route("/admin/links/<code>/edit", methods=["GET", "POST"])
@login_required
def edit_link(code):
    conn = get_db()
    row = conn.execute("SELECT * FROM links WHERE code=?", (code,)).fetchone()
    if not row:
        conn.close()
        return "Not found", 404

    if request.method == "POST":
        target_url = normalize_url(request.form.get("target_url"))
        note = request.form.get("note", "").strip()
        enabled = 1 if request.form.get("enabled") == "on" else 0
        expires_raw = request.form.get("expires_at", "")
        expires_at = normalize_expiry(expires_raw)

        if not is_allowed_url(target_url):
            conn.close()
            flash("目标链接无效，或域名不在允许列表中", "danger")
            return render_template("link_form.html", mode="edit", link=row_to_dict(row), form=request.form, allowed_domains=ALLOWED_DOMAINS)
        if expires_raw and not expires_at:
            conn.close()
            flash("过期时间格式无效", "danger")
            return render_template("link_form.html", mode="edit", link=row_to_dict(row), form=request.form, allowed_domains=ALLOWED_DOMAINS)

        conn.execute(
            "UPDATE links SET target_url=?, note=?, enabled=?, expires_at=?, updated_at=CURRENT_TIMESTAMP WHERE code=?",
            (target_url, note, enabled, expires_at, code),
        )
        conn.commit()
        conn.close()
        flash("修改已保存", "success")
        return redirect(url_for("admin"))

    conn.close()
    return render_template("link_form.html", mode="edit", link=row_to_dict(row), form={}, allowed_domains=ALLOWED_DOMAINS)


@app.post("/admin/links/<code>/toggle")
@login_required
def toggle_link(code):
    conn = get_db()
    row = conn.execute("SELECT enabled FROM links WHERE code=?", (code,)).fetchone()
    if not row:
        conn.close()
        return "Not found", 404
    conn.execute(
        "UPDATE links SET enabled=?, updated_at=CURRENT_TIMESTAMP WHERE code=?",
        (0 if row["enabled"] else 1, code),
    )
    conn.commit()
    conn.close()
    flash("状态已更新", "success")
    return redirect(request.referrer or url_for("admin"))


@app.post("/admin/links/<code>/delete")
@login_required
def delete_link_admin(code):
    conn = get_db()
    conn.execute("DELETE FROM links WHERE code=?", (code,))
    conn.commit()
    conn.close()
    flash("链接已删除", "success")
    return redirect(url_for("admin"))


@app.route("/admin/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not check_password_hash(get_admin_password_hash(), old_password):
            flash("当前密码不正确", "danger")
        elif len(new_password) < 10:
            flash("新密码至少 10 位", "danger")
        elif new_password != confirm_password:
            flash("两次输入的新密码不一致", "danger")
        else:
            set_admin_password(new_password)
            flash("密码已修改", "success")
            return redirect(url_for("admin"))
    return render_template("password.html")


@app.get("/s/<code>")
def redirect_link(code):
    conn = get_db()
    row = conn.execute("SELECT * FROM links WHERE code=?", (code,)).fetchone()
    if not row:
        conn.close()
        return render_template("message.html", title="链接不存在", message="这个短链接不存在或已被删除。"), 404
    if not row["enabled"]:
        conn.close()
        return render_template("message.html", title="链接已停用", message="这个短链接目前已被管理员停用。"), 410
    if is_expired(row["expires_at"]):
        conn.close()
        return render_template("message.html", title="链接已过期", message="这个短链接已经过期。"), 410

    conn.execute(
        "UPDATE links SET visits=visits+1,last_visit_at=CURRENT_TIMESTAMP WHERE code=?",
        (code,),
    )
    conn.commit()
    target_url = row["target_url"]
    conn.close()
    return redirect(target_url, code=302)


# ---------------- API ----------------
@app.get("/api/links")
@api_required
def api_list_links():
    q = request.args.get("q", "").strip()
    conn = get_db()
    if q:
        pattern = f"%{q}%"
        rows = conn.execute(
            "SELECT * FROM links WHERE code LIKE ? OR note LIKE ? OR target_url LIKE ? ORDER BY id DESC",
            (pattern, pattern, pattern),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM links ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify({"success": True, "count": len(rows), "data": [row_to_dict(r) for r in rows]})


@app.post("/api/links")
@api_required
def api_create_link():
    data = request.get_json(silent=True) or {}
    target_url = normalize_url(data.get("target_url"))
    code = (data.get("code") or "").strip()
    note = (data.get("note") or "").strip()
    enabled = bool(data.get("enabled", True))
    expires_at = normalize_expiry(data.get("expires_at"))

    if not is_allowed_url(target_url):
        return jsonify({"success": False, "error": "target_url domain not allowed"}), 400
    if code and not is_valid_code(code):
        return jsonify({"success": False, "error": "invalid code"}), 400
    if data.get("expires_at") and not expires_at:
        return jsonify({"success": False, "error": "invalid expires_at"}), 400

    conn = get_db()
    if not code:
        code = unique_random_code(conn)
    try:
        conn.execute(
            "INSERT INTO links(code,target_url,note,enabled,expires_at) VALUES(?,?,?,?,?)",
            (code, target_url, note, 1 if enabled else 0, expires_at),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM links WHERE code=?", (code,)).fetchone()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"success": False, "error": "code already exists"}), 409
    conn.close()
    return jsonify({"success": True, "data": row_to_dict(row)}), 201


@app.get("/api/links/<code>")
@api_required
def api_get_link(code):
    conn = get_db()
    row = conn.execute("SELECT * FROM links WHERE code=?", (code,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"success": False, "error": "not found"}), 404
    return jsonify({"success": True, "data": row_to_dict(row)})


@app.route("/api/links/<code>", methods=["PUT", "PATCH"])
@api_required
def api_update_link(code):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    row = conn.execute("SELECT * FROM links WHERE code=?", (code,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"success": False, "error": "not found"}), 404

    target_url = normalize_url(data.get("target_url", row["target_url"]))
    note = str(data.get("note", row["note"])).strip()
    enabled = 1 if bool(data.get("enabled", bool(row["enabled"]))) else 0
    expires_value = data.get("expires_at", row["expires_at"])
    expires_at = normalize_expiry(expires_value) if expires_value else None

    if not is_allowed_url(target_url):
        conn.close()
        return jsonify({"success": False, "error": "target_url domain not allowed"}), 400
    if expires_value and not expires_at:
        conn.close()
        return jsonify({"success": False, "error": "invalid expires_at"}), 400

    conn.execute(
        "UPDATE links SET target_url=?,note=?,enabled=?,expires_at=?,updated_at=CURRENT_TIMESTAMP WHERE code=?",
        (target_url, note, enabled, expires_at, code),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM links WHERE code=?", (code,)).fetchone()
    conn.close()
    return jsonify({"success": True, "data": row_to_dict(updated)})


@app.delete("/api/links/<code>")
@api_required
def api_delete_link(code):
    conn = get_db()
    cursor = conn.execute("DELETE FROM links WHERE code=?", (code,))
    conn.commit()
    deleted = cursor.rowcount
    conn.close()
    if not deleted:
        return jsonify({"success": False, "error": "not found"}), 404
    return jsonify({"success": True, "message": "deleted"})


init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

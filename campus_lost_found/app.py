import os
import sqlite3
import secrets
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from flask import Flask, g, render_template, request, redirect, url_for, flash, session
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "lost_found.db"
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

app = Flask(__name__)
app.config["SECRET_KEY"] = "campus-lost-found-secret-key"
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "123456"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def generate_manage_code():
    return secrets.token_hex(3).upper()


def add_column_if_missing(table_name, column_name, column_def):
    db = get_db()
    columns = db.execute(f"PRAGMA table_info({table_name})").fetchall()
    column_names = [col["name"] for col in columns]
    if column_name not in column_names:
        db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
        db.commit()


def get_table_name(kind):
    return "lost_items" if kind == "lost" else "found_items"


def require_admin():
    return session.get("is_admin") is True


def save_uploaded_file(file_storage):
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        return None

    filename = secure_filename(file_storage.filename)
    unique_name = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{filename}"
    save_path = UPLOAD_FOLDER / unique_name
    file_storage.save(save_path)
    return unique_name


def similarity(a, b):
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def calc_match_score(lost, found):
    score = 0
    reasons = []

    if lost["category"] == found["category"]:
        score += 35
        reasons.append("类别一致")

    if similarity(lost["item_name"], found["item_name"]) >= 0.45:
        score += 25
        reasons.append("物品名称相似")

    if lost["color"] and similarity(lost["color"], found["color"]) >= 0.8:
        score += 10
        reasons.append("颜色接近")

    if similarity(lost["location"], found["location"]) >= 0.2:
        score += 15
        reasons.append("地点相近")

    if similarity(lost["description"], found["description"]) >= 0.2:
        score += 15
        reasons.append("描述相似")

    return score, reasons


def init_db():
    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS lost_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT NOT NULL,
            category TEXT NOT NULL,
            color TEXT,
            event_date TEXT,
            location TEXT,
            description TEXT,
            contact TEXT,
            status TEXT DEFAULT '未找回',
            created_at TEXT NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS found_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT NOT NULL,
            category TEXT NOT NULL,
            color TEXT,
            event_date TEXT,
            location TEXT,
            description TEXT,
            contact TEXT,
            status TEXT DEFAULT '待认领',
            created_at TEXT NOT NULL
        )
    """)

    db.commit()

    add_column_if_missing("lost_items", "image_filename", "TEXT")
    add_column_if_missing("found_items", "image_filename", "TEXT")
    add_column_if_missing("lost_items", "manage_code", "TEXT")
    add_column_if_missing("found_items", "manage_code", "TEXT")

    seed_demo_data()
    fill_missing_manage_codes()


def seed_demo_data():
    db = get_db()

    lost_count = db.execute("SELECT COUNT(*) AS c FROM lost_items").fetchone()["c"]
    found_count = db.execute("SELECT COUNT(*) AS c FROM found_items").fetchone()["c"]

    if lost_count == 0:
        demo_lost = [
            ("校园卡", "证件卡类", "蓝色", "2026-04-22", "图书馆三楼", "蓝色挂绳，透明卡套", "张 18800000001", "未找回", now_str(), None, "A1B2C3"),
            ("保温杯", "日用品", "银色", "2026-04-21", "逸夫443", "银色杯身，黑色杯套", "陈 18800000005", "未找回", now_str(), None, "D4E5F6"),
            ("高数教材", "书本文具", "蓝白色", "2026-04-17", "博文201", "封面有姓名缩写", "赵 18800000004", "未找回", now_str(), None, "G7H8J9"),
        ]
        db.executemany("""
            INSERT INTO lost_items (
                item_name, category, color, event_date, location, description, contact, status, created_at, image_filename, manage_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, demo_lost)

    if found_count == 0:
        demo_found = [
            ("保温杯", "日用品", "银色", "2026-04-21", "逸夫443", "银色杯身，黑色杯盖", "服务台 18810000004", "待认领", now_str(), None, "K1L2M3"),
            ("白色耳机盒", "电子产品", "白色", "2026-04-18", "操场主席台附近", "疑似无线耳机盒", "失物站 18810000003", "待认领", now_str(), None, "N4P5Q6"),
            ("校园卡", "证件卡类", "蓝色", "2026-04-20", "图书馆三楼自习区", "挂有蓝色挂绳", "管理员 18810000001", "待认领", now_str(), None, "R7S8T9"),
        ]
        db.executemany("""
            INSERT INTO found_items (
                item_name, category, color, event_date, location, description, contact, status, created_at, image_filename, manage_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, demo_found)

    db.commit()


def fill_missing_manage_codes():
    db = get_db()

    lost_rows = db.execute(
        "SELECT id FROM lost_items WHERE manage_code IS NULL OR manage_code = ''"
    ).fetchall()
    for row in lost_rows:
        db.execute(
            "UPDATE lost_items SET manage_code = ? WHERE id = ?",
            (generate_manage_code(), row["id"])
        )

    found_rows = db.execute(
        "SELECT id FROM found_items WHERE manage_code IS NULL OR manage_code = ''"
    ).fetchall()
    for row in found_rows:
        db.execute(
            "UPDATE found_items SET manage_code = ? WHERE id = ?",
            (generate_manage_code(), row["id"])
        )

    db.commit()


@app.route("/")
def index():
    db = get_db()
    lost_total = db.execute("SELECT COUNT(*) AS c FROM lost_items").fetchone()["c"]
    found_total = db.execute("SELECT COUNT(*) AS c FROM found_items").fetchone()["c"]
    unresolved_lost = db.execute("SELECT COUNT(*) AS c FROM lost_items WHERE status='未找回'").fetchone()["c"]
    unclaimed_found = db.execute("SELECT COUNT(*) AS c FROM found_items WHERE status='待认领'").fetchone()["c"]

    recent_lost = db.execute("SELECT * FROM lost_items ORDER BY id DESC LIMIT 5").fetchall()
    recent_found = db.execute("SELECT * FROM found_items ORDER BY id DESC LIMIT 5").fetchall()

    return render_template(
        "index.html",
        lost_total=lost_total,
        found_total=found_total,
        unresolved_lost=unresolved_lost,
        unclaimed_found=unclaimed_found,
        recent_lost=recent_lost,
        recent_found=recent_found,
    )


@app.route("/publish/<kind>", methods=["GET", "POST"])
def publish(kind):
    if kind not in {"lost", "found"}:
        return redirect(url_for("index"))

    if request.method == "POST":
        item_name = request.form.get("item_name", "").strip()
        category = request.form.get("category", "").strip()
        color = request.form.get("color", "").strip()
        event_date = request.form.get("event_date", "").strip()
        location = request.form.get("location", "").strip()
        description = request.form.get("description", "").strip()
        contact = request.form.get("contact", "").strip()
        image_file = request.files.get("image")

        if not item_name or not category or not event_date or not location or not contact:
            flash("请至少填写：物品名称、类别、日期、地点、联系方式。", "error")
            return render_template("publish.html", kind=kind)

        image_filename = save_uploaded_file(image_file)
        manage_code = generate_manage_code()

        db = get_db()
        table = get_table_name(kind)

        db.execute(f"""
            INSERT INTO {table} (
                item_name, category, color, event_date, location, description, contact, status, created_at, image_filename, manage_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item_name,
            category,
            color,
            event_date,
            location,
            description,
            contact,
            "未找回" if kind == "lost" else "待认领",
            now_str(),
            image_filename,
            manage_code
        ))
        db.commit()

        item_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

        flash(f"发布成功！信息ID：{item_id}，管理码：{manage_code}。请立即截图保存。", "success")
        return redirect(url_for("detail", kind=kind, item_id=item_id, show_code=1))

    return render_template("publish.html", kind=kind)


@app.route("/list/<kind>")
def list_items(kind):
    if kind not in {"lost", "found"}:
        return redirect(url_for("index"))

    keyword = request.args.get("keyword", "").strip()
    category = request.args.get("category", "").strip()
    location = request.args.get("location", "").strip()

    table = get_table_name(kind)
    sql = f"SELECT * FROM {table} WHERE 1=1"
    params = []

    if keyword:
        sql += " AND (item_name LIKE ? OR description LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    if category:
        sql += " AND category = ?"
        params.append(category)

    if location:
        sql += " AND location LIKE ?"
        params.append(f"%{location}%")

    sql += " ORDER BY id DESC"

    db = get_db()
    items = db.execute(sql, params).fetchall()

    all_categories = [
        "证件卡类", "电子产品", "书本文具", "日用品",
        "衣物配饰", "钥匙门禁", "其他"
    ]

    return render_template(
        "list.html",
        kind=kind,
        items=items,
        keyword=keyword,
        category=category,
        location=location,
        all_categories=all_categories
    )


@app.route("/detail/<kind>/<int:item_id>")
def detail(kind, item_id):
    if kind not in {"lost", "found"}:
        return redirect(url_for("index"))

    table = get_table_name(kind)
    db = get_db()
    item = db.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()

    if not item:
        flash("未找到对应记录。", "error")
        return redirect(url_for("index"))

    show_code = request.args.get("show_code") == "1"
    return render_template("detail.html", kind=kind, item=item, show_code=show_code)


@app.route("/match")
def match_page():
    keyword = request.args.get("keyword", "").strip()
    category = request.args.get("category", "").strip()
    min_score_raw = request.args.get("min_score", "").strip()

    try:
        min_score = int(min_score_raw) if min_score_raw else 35
    except ValueError:
        min_score = 35

    db = get_db()
    lost_items = db.execute("SELECT * FROM lost_items WHERE status!='已找回' ORDER BY id DESC").fetchall()
    found_items = db.execute("SELECT * FROM found_items WHERE status!='已认领' ORDER BY id DESC").fetchall()

    results = []
    for lost in lost_items:
        if keyword:
            text = f"{lost['item_name']} {lost['description'] or ''} {lost['location'] or ''}"
            if keyword.lower() not in text.lower():
                continue

        if category and lost["category"] != category:
            continue

        candidates = []
        for found in found_items:
            score, reasons = calc_match_score(lost, found)
            if score >= min_score:
                candidates.append({
                    "found": found,
                    "score": score,
                    "reasons": "、".join(reasons) if reasons else "基础匹配"
                })

        candidates.sort(key=lambda x: x["score"], reverse=True)
        if candidates:
            results.append({
                "lost": lost,
                "candidates": candidates[:3]
            })

    all_categories = [
        "证件卡类", "电子产品", "书本文具", "日用品",
        "衣物配饰", "钥匙门禁", "其他"
    ]

    return render_template(
        "match.html",
        results=results,
        keyword=keyword,
        category=category,
        min_score=min_score,
        all_categories=all_categories
    )


@app.route("/manage", methods=["GET", "POST"])
def manage_lookup():
    item = None
    kind = None

    if request.method == "POST":
        kind = request.form.get("kind", "").strip()
        item_id = request.form.get("item_id", "").strip()
        manage_code = request.form.get("manage_code", "").strip().upper()

        if kind not in {"lost", "found"} or not item_id or not manage_code:
            flash("请完整填写信息类型、信息ID和管理码。", "error")
            return render_template("manage_lookup.html", item=None, kind=None)

        table = get_table_name(kind)
        db = get_db()
        item = db.execute(
            f"SELECT * FROM {table} WHERE id = ? AND manage_code = ?",
            (item_id, manage_code)
        ).fetchone()

        if not item:
            flash("未找到对应信息，或管理码错误。", "error")
            return render_template("manage_lookup.html", item=None, kind=None)

        return render_template("manage_lookup.html", item=item, kind=kind)

    return render_template("manage_lookup.html", item=None, kind=None)


@app.route("/manage/action/<kind>/<int:item_id>", methods=["POST"])
def manage_action(kind, item_id):
    if kind not in {"lost", "found"}:
        return redirect(url_for("manage_lookup"))

    action = request.form.get("action", "").strip()
    manage_code = request.form.get("manage_code", "").strip().upper()
    new_status = request.form.get("status", "").strip()

    table = get_table_name(kind)
    db = get_db()
    item = db.execute(
        f"SELECT * FROM {table} WHERE id = ? AND manage_code = ?",
        (item_id, manage_code)
    ).fetchone()

    if not item:
        flash("操作失败，管理码错误。", "error")
        return redirect(url_for("manage_lookup"))

    if action == "delete":
        db.execute(f"DELETE FROM {table} WHERE id = ?", (item_id,))
        db.commit()
        flash("删除成功。", "success")
        return redirect(url_for("manage_lookup"))

    if action == "status":
        db.execute(f"UPDATE {table} SET status = ? WHERE id = ?", (new_status, item_id))
        db.commit()
        flash("状态修改成功。", "success")
        return redirect(url_for("detail", kind=kind, item_id=item_id))

    flash("未知操作。", "error")
    return redirect(url_for("manage_lookup"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["is_admin"] = True
            flash("管理员登录成功。", "success")
            return redirect(url_for("admin"))

        flash("账号或密码错误。", "error")

    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("已退出管理员登录。", "success")
    return redirect(url_for("index"))


@app.route("/admin")
def admin():
    if not require_admin():
        return redirect(url_for("admin_login"))

    db = get_db()
    lost_items = db.execute("SELECT * FROM lost_items ORDER BY id DESC").fetchall()
    found_items = db.execute("SELECT * FROM found_items ORDER BY id DESC").fetchall()
    return render_template("admin.html", lost_items=lost_items, found_items=found_items)


@app.route("/status/<kind>/<int:item_id>", methods=["POST"])
def update_status(kind, item_id):
    if not require_admin():
        return redirect(url_for("admin_login"))

    if kind not in {"lost", "found"}:
        return redirect(url_for("admin"))

    new_status = request.form.get("status", "").strip()
    table = get_table_name(kind)

    db = get_db()
    db.execute(f"UPDATE {table} SET status = ? WHERE id = ?", (new_status, item_id))
    db.commit()

    flash("状态更新成功。", "success")
    return redirect(url_for("admin"))


@app.route("/delete/<kind>/<int:item_id>", methods=["POST"])
def delete_item(kind, item_id):
    if not require_admin():
        return redirect(url_for("admin_login"))

    if kind not in {"lost", "found"}:
        return redirect(url_for("admin"))

    table = get_table_name(kind)
    db = get_db()
    db.execute(f"DELETE FROM {table} WHERE id = ?", (item_id,))
    db.commit()

    flash("记录已删除。", "success")
    return redirect(url_for("admin"))


with app.app_context():
    init_db()


import os  # 建议加在文件最顶部，和其他 import 放一起

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))  # 优先用 Render 分配的端口，默认 10000
    app.run(host='0.0.0.0', port=port)

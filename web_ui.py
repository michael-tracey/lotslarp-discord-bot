import os
from flask import Flask, redirect, url_for, session, render_template, request
import hashlib
from db_helper import get_db_connection

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersekrit")
app.config["SESSION_TYPE"] = "filesystem"
client_id = os.environ.get("GOOGLE_CLIENT_ID")
client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")


def create_user(username, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    hashed_password = hash_password(password)
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, hashed_password),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return False  # Username already exists
    finally:
        conn.close()
    return True


def check_password(username, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    conn.close()
    if result:
        stored_hash = result["password_hash"]
        return verify_password(password, stored_hash)
    return False


def hash_password(password):
    # In a real app, use a proper salting and hashing library like bcrypt
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password, stored_hash):
    return hash_password(password) == stored_hash


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if check_password(username, password):
            session["logged_in"] = True
            return redirect(url_for("home"))
        else:
            return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")



@app.route("/stats")
def stats(page=1):
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    page = int(request.args.get("page", 1))
    per_page = 10
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM stats_log")
    total_items = cursor.fetchone()[0]
    cursor.execute("SELECT message, user_id, user_name, display_name, result, created_at FROM stats_log ORDER BY created_at DESC LIMIT ? OFFSET ?", (per_page, offset))
    stats = cursor.fetchall()
    conn.close()
    
    total_pages = (total_items + per_page - 1) // per_page

    return render_template("stats.html", stats=stats, page=page, total_pages=total_pages)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def home():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    else:
        return redirect(url_for("stats"))

def setup_database():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stats_log (
            command_name TEXT,
            user_id INTEGER,
            user_name TEXT,
            display_name TEXT,
            result TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

if __name__ == "__main__":
    setup_database()
    app.run(host='0.0.0.0', port=8080)
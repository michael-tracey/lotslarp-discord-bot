import os
from flask import Flask, redirect, url_for, session, render_template, request
import sqlite3
import hashlib

stats = []

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersekrit")
app.config["SESSION_TYPE"] = "filesystem"
client_id = os.environ.get("GOOGLE_CLIENT_ID")
client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

def get_db_connection():
    conn = sqlite3.connect("stats.db")
    conn.row_factory = sqlite3.Row
    return conn

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


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


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

@app.route("/")
def home():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    else:
        return redirect(url_for("stats"))


def run_flask():
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if admin_password:
        if not check_password("lotslarp", admin_password):
            if not create_user("lotslarp", admin_password):
                print("Failed to create admin user, may already exist.")
            else:
                print("Created admin user successfully.")
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
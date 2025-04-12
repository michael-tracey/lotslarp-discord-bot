import os
from flask import Flask, redirect, url_for, session, render_template, request
from google_auth_oauthlib.flow import Flow
import google.auth.transport.requests
import requests
from google.oauth2 import id_token
from dotenv import load_dotenv
import sqlite3
load_dotenv()

HTTP_STATUS_OK = 200
HTTP_STATUS_UNAUTHORIZED = 401

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersekrit")
app.config["SESSION_TYPE"] = "filesystem"
client_id = os.environ.get("GOOGLE_CLIENT_ID")
client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
credentials = None


@app.route("/callback")
def callback():
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    flow = Flow.from_client_config(
        client_config={
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/userinfo.email",
            "openid",
        ],
        redirect_uri=os.environ.get("GOOGLE_CALLBACK_URL"),
    )
    flow.fetch_token(authorization_response=request.url)
    global credentials
    credentials = flow.credentials
    session["token"] = credentials.id_token
    user_info = get_user_info()  # Call get_user_info to fetch and store picture
    if user_info:
        session["picture"] = user_info.get("picture")
    return redirect(url_for("index"))


def get_user_info():
    if "token" in session:
        token = session["token"]
        id_info = id_token.verify_token(token, requests.Request())
        if "picture" in session:
            return {"info": id_info, "picture": session["picture"]}
        user_info = requests.get(
            "https://people.googleapis.com/v1/people/me?personFields=photos",
            headers={"Authorization": f"Bearer {credentials.token}"},
        ).json()

        if "photos" in user_info and len(user_info["photos"]) > 0:
            picture_url = user_info["photos"][0].get("url", None)
            session["picture"] = picture_url  # Store in session
            return {"info": id_info, "picture": picture_url}
        else:
            return {"info": id_info, "picture": None}  # Or some default
    return False


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/")
def index():
    user_info = get_user_info()

    stats = []
    if user_info:
        conn = sqlite3.connect("stats.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT user_id, messages_count FROM users")
            stats = cursor.fetchall()
        finally:
            conn.close()
    else:
        conn = sqlite3.connect("stats.db")
        cursor = conn.cursor()
        try:
            pass
        finally:
            conn.close()

    return render_template("index.html", user=user_info, stats=stats)


def run_flask():
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
import os
import threading
import sqlite3
import logging
logging.basicConfig(level=logging.INFO)
from dotenv import load_dotenv
from discord_bot import run_discord_bot
from web_ui import run_flask


load_dotenv()


def setup_database():
    conn = sqlite3.connect("stats.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Create users table for login info
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT)"
        )

    # Create stats_log table to log statistics
    cursor.execute("CREATE TABLE IF NOT EXISTS stats_log (message TEXT, user_id INTEGER, user_name TEXT, display_name TEXT, result TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")

    # Check if stats_log table has needed columns, and update if needed


    cursor.execute("PRAGMA table_info(stats_log)")
    columns = [column[1] for column in cursor.fetchall()]

    if "display_name" not in columns:
        cursor.execute("ALTER TABLE stats_log ADD COLUMN display_name TEXT")

    if "created_at" not in columns:
        cursor.execute("ALTER TABLE stats_log ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP")
    conn.commit()
    conn.close()




if __name__ == "__main__":

    logging.info("Starting application...")

    setup_database()  # Initialize the database
    flask_thread = threading.Thread(target=run_flask)  # Start Flask web UI
    discord_thread = threading.Thread(target=run_discord_bot)  # Start Discord bot
    flask_thread.start()  # Run Flask UI
    discord_thread.start()  # Run Discord Bot
    flask_thread.join()  # Keep main process alive while threads are running
import os
import threading
from discord_bot import run_discord_bot
from web_ui import run_flask

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    discord_thread = threading.Thread(target=run_discord_bot)

    flask_thread.start()
    discord_thread.start()
    flask_thread.join()
    discord_thread.join()
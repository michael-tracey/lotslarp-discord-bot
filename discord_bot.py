import os
import random
import discord
from dotenv import load_dotenv
import sqlite3

load_dotenv()

DEBUG = False


class MyClient(discord.Client):
    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")

    async def on_message(self, message):
        if DEBUG:
            print(f"DEBUG: Received message: {message.content}")

        if message.author.id == self.user.id:
            return

        if message.content.startswith("!hello"):
            await message.reply("Hello!", mention_author=True)

        if message.content.startswith("/throw"):
            if len(message.content.split()) < 2:
                await message.reply(
                    "Please specify your throw: /throw <rock|paper|scissors|random>",
                    mention_author=True,
                )
                return

            user_choice = message.content.split("/throw ")[1].lower()

            if user_choice == "random":
                user_throw = random.choice(["rock", "paper", "scissors"])
            else:
                user_throw = user_choice.lower()

            if user_throw not in ["rock", "paper", "scissors"]:
                await message.reply(
                    "Please throw rock, paper, scissors, or random.",
                    mention_author=True,
                )
                return
            bot_throw = random.choice(["rock", "paper", "scissors"])

            if user_throw == bot_throw:
                result = "It's a tie!"
            elif (user_throw == "rock" and bot_throw == "scissors") or (
                user_throw == "paper" and bot_throw == "rock"
            ) or (user_throw == "scissors" and bot_throw == "paper"):
                result = "You win!"
            else:
                result = "You lose!"

            await message.reply(
                f"You threw {user_throw}. I threw {bot_throw}. {result}",
                mention_author=True,
            )

        else:
            result = ""
            local_conn = sqlite3.connect("stats.db")
            local_conn.execute("PRAGMA foreign_keys = 1")
            local_conn.row_factory = sqlite3.Row
            cursor = local_conn.cursor()
            cursor.execute(
                "SELECT messages_count FROM users WHERE user_id = ?",
                (message.author.id,),
            )
            database_result = cursor.fetchone()
            if database_result:
                messages_count = database_result[0] + 1
                cursor.execute(
                    "UPDATE users SET messages_count = ? WHERE user_id = ?",
                    (messages_count, message.author.id),
                )
            else:
                cursor.execute(
                    "INSERT INTO users (user_id, messages_count) VALUES (?, ?)",
                    (message.author.id, 1),
                )
            local_conn.close()

        if message.content.startswith(("!", "/")):
            if message.content.startswith("/throw"):
                log_stat(message.content, message.author.id, message.author.name, result)
            elif message.content.startswith("!hello"):
                log_stat(
                    message.content, message.author.id, message.author.name, "Success"
                )
            elif message.content.startswith("/"):
                log_stat(
                    message.content, message.author.id, message.author.name, "Success"
                )


intents = discord.Intents.default()
intents.message_content = True
client = MyClient(intents=intents)


def log_stat(message, user_id, user_name, result):
    conn = sqlite3.connect("stats.db")
    conn.execute("PRAGMA foreign_keys = 1")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    create_table_query = (
        "CREATE TABLE IF NOT EXISTS stats_log (id INTEGER PRIMARY KEY "
        "AUTOINCREMENT, message TEXT, user_id INTEGER, user_name TEXT, "
        "result TEXT)"
    )
    cursor.execute(create_table_query)

    insert_query = (
        "INSERT INTO stats_log (message, user_id, user_name, result) "
        "VALUES (?, ?, ?, ?)"
    )
    cursor.execute(insert_query, (message, user_id, user_name, result))

    conn.commit()
    conn.close()


def run_discord_bot():
    conn = sqlite3.connect("stats.db")
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
          CREATE TABLE IF NOT EXISTS users (
              user_id INTEGER PRIMARY KEY,
              messages_count INTEGER
          )
          """
        )

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN username TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE users ADD COLUMN discord_username TEXT")
        except sqlite3.OperationalError:
            pass

    finally:
        conn.close()

    try:
        client.run(os.environ["DISCORD_BOT_TOKEN"])
    except KeyError:
        print(
            "Please set the environment variable DISCORD_BOT_TOKEN with your bot token."
        )
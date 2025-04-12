import os
import sqlite3
from importlib import import_module
import traceback

import discord
from dotenv import load_dotenv

DEBUG = False

intents = discord.Intents.default()
intents.message_content = True


class MyClient(discord.Client):
    def __init__(self, intents, template_env):
        super().__init__(intents=intents)
        self.template_env = template_env

    async def process_command(self, message):
        try:
            command_prefix = message.content[0]
            parts = message.content[1:].split()
            command_name = parts[0].lower() if parts else ""

            command_map = {
                "!": {"hello": import_module("modules.hello").Hello},
                "/": {"throw": import_module("modules.throw").Throw},
            }

            if command_prefix in command_map and command_name in command_map[command_prefix]:
                command_class = command_map[command_prefix][command_name]
                command_instance = command_class(self.template_env)
                result = await command_instance.run(message)
                await message.reply(result, mention_author=True)
                return command_name, result
            else:
                await message.reply("**Command not found.**", mention_author=True)
                return command_name, "Command not found"
        except Exception:
            await message.reply("**An error occurred while processing the command.**", mention_author=True)
            return command_name, "An error occurred while processing the command."

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")

    async def on_message(self, message):
        display_name = message.author.display_name
        if DEBUG:
            print(f"DEBUG: Received message: {message.content}")

        if message.author.id == self.user.id:
            return

        if message.content.startswith("!") or message.content.startswith("/"):
            command_name, command_result = await self.process_command(message)
            log_stat(command_name, message.author.id, message.author.name, display_name, command_result)



def log_stat(command_name, user_id, user_name, display_name, command_result):
    conn = sqlite3.connect("stats.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO stats_log (message, user_id, user_name, display_name, result) VALUES (?, ?, ?, ?, ?)", (command_name, user_id, user_name, display_name, command_result))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Error logging stat: {e}")
    finally:
        conn.close()


def run_discord_bot():
    from jinja2 import Environment, FileSystemLoader
    template_env = Environment(loader=FileSystemLoader("templates"))
    client = MyClient(intents=intents, template_env=template_env)
    client.run(os.getenv("DISCORD_TOKEN"))
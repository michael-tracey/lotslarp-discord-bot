import os
import logging
import sqlite3
from dotenv import load_dotenv, find_dotenv
import discord
import asyncio
import importlib
load_dotenv()


async def process_command(client, message, command_map):
    conn = sqlite3.connect("stats.db")
    try:
        parts = message.content[1:].split()
        command_name = parts[0].lower() if parts else ""

        logging.info(f"Processing command: {command_name}")
        if command_name in command_map:
            logging.info(f"In the command_map for: {command_name}")
            command_instance = command_map[command_name]
            result = command_instance.run(message)
            if asyncio.iscoroutinefunction(command_instance.run):
                result = await result
            logging.info(f"Result of command '{command_name}': {result[:100]}...")  # Log first 100 chars of result
            if isinstance(result, str) and len(result) > 2000:
                chunks = [result[i: i + 2000] for i in range(0, len(result), 2000)]
                for chunk in chunks:
                    await message.channel.send(chunk, suppress_embeds=True)
            else:
                await message.channel.send(result, suppress_embeds=True)
            log_stat(conn, command_name, message.author.id, message.author.name, message.author.display_name, f"Sent message with {len(result)} characters")
    except Exception as e:
        logging.error(f"Error processing command: {e}")
        message.reply("**An error occurred while processing the command.**", mention_author=False)
        log_stat(conn, "command_error", message.author.id, message.author.name, message.author.display_name, f"Command processing error: {e}")
    finally:
        conn.close()


def log_stat(conn, command_name, user_id, user_name, display_name, command_result):
    try:
        with conn:
            conn.execute("INSERT INTO stats_log (message, user_id, user_name, display_name, result) VALUES (?, ?, ?, ?, ?)", (command_name, user_id, user_name, display_name, command_result))
    except Exception as e:
        logging.error(f"Error logging stat: {e}")

class MyClient(discord.Client):
    def __init__(self, command_map, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.command_map = command_map

    async def on_ready(self):
        logging.info(f"Logged in as {self.user} (ID: {self.user.id})")

    async def on_message(self, message):
        if message.author == self.user:
            return
        # logging.info(f"Message: {message.content}")
        if message.content.startswith("/"):
            await process_command(self, message, self.command_map)


def run_discord_bot():
    logging.info("Starting Discord bot...")

    intents = discord.Intents.default()
    intents.message_content = True  # Enable message content intent

    # Load commands here
    command_map = {}
    for module_name in ["hello", "throw", "huh"]:
        module = importlib.import_module(f"modules.{module_name}")
        for name, item in module.__dict__.items():
            if isinstance(item, type) and name.lower() == module_name:
                command_map[module_name] = item

    # Instantiate commands, passing template_env where needed
    instances = {
        name: cls() for name, cls in command_map.items()
    }

    # Update command_map to hold instances
    command_map.update(instances)

    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        logging.error("Discord token not found in environment variables.")
        return
    client = MyClient(command_map, intents=intents)
    client.run(token)

if __name__ == "__main__":
    run_discord_bot()

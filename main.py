import os
import random
import discord
import threading, sqlite3
from flask import Flask, request
from werkzeug.http import HTTP_STATUS_CODES

app = Flask(__name__)

def authenticate():
    auth = request.authorization
    if not auth or not (auth.username == 'admin' and auth.password == 'admin'):
        return HTTP_STATUS_CODES[401], 401, {'WWW-Authenticate': 'Basic realm="Login Required"'}
    return None, 200

class MyClient(discord.Client):
    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

    async def on_message(self, message):
        # we do not want the bot to reply to itself
        if message.author.id == self.user.id:
            return

        if message.content.startswith('!hello'):
            await message.reply('Hello!', mention_author=True)

        if message.content.startswith('/throw'):
            # Check if the user provided a throw
            if len(message.content.split()) < 2:
                await message.reply("Please specify your throw: /throw <rock|paper|scissors>", mention_author=True)
                return

            user_choice = message.content.split('/throw ')[1].lower()

            if user_choice == "random":
                user_throw = random.choice(['rock', 'paper', 'scissors'])
            else:
                user_throw = user_choice

            # Check if the user's throw is valid
            if user_throw not in ['rock', 'paper', 'scissors']:
                await message.reply(f"Please throw rock, paper, scissors, or random.", mention_author=True)
                return
            bot_throw = random.choice(['rock', 'paper', 'scissors'])

            # Determine the winner
            if user_throw == bot_throw:
                result = "It's a tie!"
            elif (user_throw == 'rock' and bot_throw == 'scissors') or \
                 (user_throw == 'paper' and bot_throw == 'rock') or \
                 (user_throw == 'scissors' and bot_throw == 'paper'):
                result = "You win!"
            else:
                result = "You lose!"

            await message.reply(f"You threw {user_throw}. I threw {bot_throw}. {result}", mention_author=True)

        conn = sqlite3.connect('stats.db')
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT messages_count FROM users WHERE user_id = ?', (message.author.id,))
            result = cursor.fetchone()
            if result:
                messages_count = result[0] + 1
                cursor.execute('UPDATE users SET messages_count = ? WHERE user_id = ?', (messages_count, message.author.id))
            else:
                cursor.execute('INSERT INTO users (user_id, messages_count) VALUES (?, ?)', (message.author.id, 1))
            conn.commit()
        finally: conn.close()

intents = discord.Intents.default()
intents.message_content = True
client = MyClient(intents=intents)

def get_stats():
    conn = sqlite3.connect('stats.db')
    cursor = conn.cursor()
    try: cursor.execute('SELECT user_id, messages_count FROM users'); return cursor.fetchall()
    finally: conn.close()


@app.route('/')
def index():
    auth_response = authenticate()
    if auth_response:
        auth_result, status_code, headers = auth_response
        return auth_result, status_code, headers
    stats = get_stats()
    stats_string = "Discord Bot Statistics:\n"
    for user_id, messages_count in stats:
        stats_string += f"User ID: {user_id}, Messages: {messages_count}\n"
    return stats_string


def run_flask():
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

def run_discord_bot():
    conn = sqlite3.connect('stats.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, messages_count INTEGER)
    ''')
    conn.commit()
    try:
        client.run(os.environ["DISCORD_BOT_TOKEN"])
    except KeyError:
        print("Please set the environment variable DISCORD_BOT_TOKEN with your bot token.")

if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask)
    discord_thread = threading.Thread(target=run_discord_bot)

    flask_thread.start()
    discord_thread.start()

    flask_thread.join()
    discord_thread.join()
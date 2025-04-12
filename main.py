import os
import random
import discord
import typing

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

intents = discord.Intents.default()
intents.message_content = True
client = MyClient(intents=intents)
try:
    client.run(os.environ["DISCORD_BOT_TOKEN"])
except KeyError:
    print("Please set the environment variable DISCORD_BOT_TOKEN with your bot token.")
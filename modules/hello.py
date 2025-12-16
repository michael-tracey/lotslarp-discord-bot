import discord
from jinja2 import Environment, FileSystemLoader

class Hello:
    async def run(self, client: discord.Client, message: discord.Message):
        display_name = message.author.display_name
        return "Hello, {}!".format(display_name)
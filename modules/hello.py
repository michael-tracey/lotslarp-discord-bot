import discord
from jinja2 import Environment, FileSystemLoader

class Hello:
    def __init__(self, template_env: Environment):
        self.template_env = template_env

    async def run(self, message: discord.Message):
        template = self.template_env.get_template("hello.jinja2")
        display_name = message.author.display_name
        return "Hello, {}!".format(display_name)
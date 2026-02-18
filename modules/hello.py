import discord
import logging

logger = logging.getLogger(__name__)

class Hello:

    async def run(self, client: discord.Client, message: discord.Message):

        logger.info(f"Command started: /hello by {message.author} in {message.channel}")

        display_name = message.author.display_name

        response = "Hello, {}!".format(display_name)

        logger.info(f"Greeting generated for {display_name}")

        return response

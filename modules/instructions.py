import discord
import os
import logging
from modules.utils import get_admin_roles

logger = logging.getLogger(__name__)

class Instructions:
    def __init__(self):
        self.name = "lotslarp-instructions"
        self.admin_roles = get_admin_roles()

    async def run(self, client: discord.Client, message: discord.Message):
        """
        Provides detailed instructions for using the bot's advanced features.
        Usage: /lotslarp instructions
        """
        logger.info(f"Command started: /lotslarp instructions by {message.author} in {message.channel}")

        is_admin = False
        if isinstance(message.author, discord.Member):
            for role in message.author.roles:
                if role.name in self.admin_roles:
                    is_admin = True
                    break
        
        if not is_admin:
            logger.warning(f"Permission denied for {message.author}")
            await message.channel.send("🚫 These instructions are intended for Storytellers.")
            return

        embed = discord.Embed(
            title="📖 Storyteller Instructions",
            description="How to get the most out of the LotsLarp Bot.",
            color=discord.Color.gold()
        )

        embed.add_field(
            name="🔖 How to Bookmark for Digests",
            value=(
                "Mention the **Summary Role** (e.g., `@summary`) in any message you want to include in the automatic PDF digests. "
                "The bot caches these messages and packages them when the threshold is met (count or time)."
            ),
            inline=False
        )

        embed.add_field(
            name="✍️ Channel Summaries",
            value=(
                "Use `/summarize #channel` to recap roleplay. The bot looks back to the **last time** the summary role was mentioned "
                "in that channel. This allows you to 'bookmark' where your last summary ended."
            ),
            inline=False
        )

        embed.add_field(
            name="📅 Monthly Cycle",
            value=(
                "The bot is aware of your Game Schedule. `/lotslarp report month` always looks back to the **previous game**. "
                "It also reads previous monthly summaries to maintain continuity in long-running plots."
            ),
            inline=False
        )

        embed.add_field(
            name="🧠 Lore & RAG",
            value=(
                "The bot uses a **Lore Glossary**. If roleplay messages contain keywords found in the glossary, "
                "those lore entries are automatically fed to the AI as context to improve summary accuracy."
            ),
            inline=False
        )

        embed.add_field(
            name="👥 Channel Groups",
            value=(
                "You can organize multiple roleplay channels into **Groups** (e.g., 'Southeast', 'Garou'). "
                "Use `/lotslarp group <name> add #channel` to build a group, and `/lotslarp group <name> summarize` "
                "to get a long-form report of all activity in those channels from the last 30 days."
            ),
            inline=False
        )

        embed.set_footer(text="For a quick list of all commands, use /lotslarp help.")

        try:
            await message.channel.send(embed=embed)
            logger.info("Instructions message sent successfully.")
        except Exception as e:
            logger.error(f"Failed to send instructions message: {e}", exc_info=True)
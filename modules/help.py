import discord
import os
import logging
from modules.utils import get_admin_roles

logger = logging.getLogger(__name__)

class LotslarpHelp:
    def __init__(self):
        self.name = "lotslarp-help"
        self.admin_roles = get_admin_roles()

    async def run(self, client: discord.Client, message: discord.Message):
        """
        Lists available commands based on user permissions.
        Usage: /lotslarp-help
        """
        logger.info(f"Command started: /lotslarp help by {message.author} in {message.channel}")

        is_admin = False
        if isinstance(message.author, discord.Member):
            for role in message.author.roles:
                if role.name in self.admin_roles:
                    is_admin = True
                    break
        
        embed = discord.Embed(
            title="🏰 Larp-Bot Command List",
            description="Use these commands to interact with the Storytellers and manage roleplay history.",
            color=discord.Color.blue()
        )
        
        # Public Commands
        public_cmds = [
            "**/lotslarp help**: Show this help message.",
            "**/lotslarp hello**: Say hello to the bot.",
            "**/lotslarp map**: Get the link to the interactive sect map.",
            "**/throw <object>**: For when you need to toss something.",
            "**/huh <question>**: Ask the bot questions about the LARP or rules."
        ]
        embed.add_field(name="🌍 Public Commands", value="\n".join(public_cmds), inline=False)
        
        # Admin Commands
        if is_admin:
            report_cmds = [
                "**/lotslarp summarize <channel_id>**: Summarize a specific channel since the last summary mention.",
                "**/lotslarp report month**: Generate a summary from the **last game** until today.",
                "**/lotslarp report digest [day|week|month|now]**: Generate a PDF digest (defaults to 'month'). Use 'now' to force the scheduled digest.",
                "**/lotslarp report voice [days]**: See who has been active in voice channels.",
                "**/lotslarp group summarize**: Summarize a group (last 30 days).",
                "**/lotslarp stale**: Find channels that haven't been summarized recently."
            ]
            embed.add_field(name="📊 Storyteller Reports", value="\n".join(report_cmds), inline=False)

            mgmt_cmds = [
                "**/lotslarp group list**: List all channel groups.",
                "**/lotslarp group <name> add [#channel]**: Add a channel to a group.",
                "**/lotslarp group <name> rename <new_name>**: Rename a channel group.",
                "**/lotslarp archive [#channel]**: Archive a channel to PDF and make it read-only.",
                "**/lotslarp unarchive [#channel]**: Restore permissions to an archived channel.",
                "**/lotslarp status**: Check bot health and AI connection.",
                "**/lotslarp instructions**: View detailed Storyteller guides.",
                "**/lotslarp purge-archives**: Manually trigger cleanup job."
            ]
            embed.add_field(name="🛡️ Management & Groups", value="\n".join(mgmt_cmds), inline=False)
            
            embed.set_footer(text="Tip: Mentions of the summary role are used to track where reports leave off.")

        try:
            await message.channel.send(embed=embed)
            logger.info("Help message sent successfully.")
        except Exception as e:
            logger.error(f"Failed to send help message: {e}", exc_info=True)


import discord
import os

class LotslarpHelp:
    def __init__(self):
        self.name = "lotslarp-help"
        self.admin_role_name = os.environ.get("LOTSLARP_BOT_ADMIN_USER", "@storytellers").strip("@")

    async def run(self, client: discord.Client, message: discord.Message):
        """
        Lists available commands based on user permissions.
        Usage: /lotslarp-help
        """
        is_admin = False
        if isinstance(message.author, discord.Member):
            for role in message.author.roles:
                if role.name == self.admin_role_name:
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
            "**/throw <object>**: For when you need to toss something.",
            "**/huh <question>**: Ask the bot questions about the LARP or rules."
        ]
        embed.add_field(name="🌍 Public Commands", value="\n".join(public_cmds), inline=False)
        
        # Admin Commands
        if is_admin:
            admin_cmds = [
                "**/lotslarp archive [#channel]**: Archive a channel to PDF, make it read-only, and post it to ST archives.",
                "**/lotslarp unarchive [#channel]**: Cancel deletion and unarchive a channel (restore permissions).",
                "**/lotslarp purge-archives**: Manually trigger the daily cleanup and reporting job.",
                "**/lotslarp summarize <channel_id>**: Summarize a specific channel since the last summary mention.",
                "**/lotslarp report month**: Generate a summary from the **last game** until today.",
                "**/lotslarp report digest [day|week|month|now]**: Generate a PDF digest (defaults to 'month'). Use 'now' to force the scheduled digest.",
                "**/lotslarp report voice [days]**: See who has been active in voice channels.",
                "**/lotslarp stale**: Find roleplay channels that haven't been summarized recently.",
                "**/lotslarp status**: Check the bot's health, database, and AI connection.",
                "**/lotslarp instructions**: View detailed guides for Storyteller features."
            ]
            embed.add_field(name="🛡️ Storyteller Commands", value="\n".join(admin_cmds), inline=False)
            
            embed.set_footer(text="Tip: Mentions of the summary role are used to track where reports leave off.")

        
        await message.channel.send(embed=embed)


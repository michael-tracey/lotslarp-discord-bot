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
            title="Larp-Bot Command List",
            description="Here are the commands you can use:",
            color=discord.Color.green()
        )
        
        # Public Commands
        public_cmds = [
            "**/lotslarp-help**: Show this help message.",
            "**/hello**: Say hello!",
            "**/throw**: Throw an object (e.g. `/throw rock`).",
            "**/huh**: Ask the bot a question."
        ]
        embed.add_field(name="🌍 Public Commands", value="\n".join(public_cmds), inline=False)
        
        # Admin Commands
        if is_admin:
            admin_cmds = [
                "**/summarize <channel_id>**: Summarize a channel's recent history.",
                "**/digest <day|week|month>**: Generate a PDF digest of recent messages.",
                "**/digest-now**: Force an immediate digest generation.",
                "**/voice-report [days]**: Generate a voice activity report.",
                "**/stale-channels [limit|all]**: Find channels that need summarizing.",
                "**/larpbot-status**: Check bot health and connections."
            ]
            embed.add_field(name="🛡️ Storyteller Commands", value="\n".join(admin_cmds), inline=False)
        
        await message.channel.send(embed=embed)

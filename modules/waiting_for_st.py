import os
import discord
import logging
from modules.utils import smart_chunk_message

logger = logging.getLogger(__name__)

STOPWATCH_EMOJI = "⏱️"
STOPWATCH_EMOJI_ALT = "⏱"

_DEFAULT_ST_ROLES = "storyteller,storyteller-helper"


def _get_st_roles() -> set:
    raw = os.environ.get("LOTSLARP_BOT_WAITING_ST_ROLE_NAMES", _DEFAULT_ST_ROLES)
    return {r.strip().lower() for r in raw.split(",") if r.strip()}


class WaitingForST:
    def __init__(self):
        self.name = "waiting-for-st"

        try:
            channel_id_str = os.environ.get("LOTSLARP_BOT_REPORT_CHANNEL_ID") or \
                             os.environ.get("LOTSLARP_BOT_SUMMARY_CHANNEL_ID", "0")
            self.report_channel_id = int(channel_id_str.strip().strip('"').strip("'"))
        except (ValueError, TypeError):
            logger.error("Could not parse report channel ID for WaitingForST.")
            self.report_channel_id = 0

    async def get_waiting_channels(self, client: discord.Client) -> list:
        """Return list of channels whose last message has a :stopwatch: reaction from an ST."""
        st_roles = _get_st_roles()
        waiting = []

        for guild in client.guilds:
            me = guild.me
            for channel in guild.text_channels:
                try:
                    if not channel.permissions_for(me).read_message_history:
                        continue

                    last_msg = None
                    async for msg in channel.history(limit=1):
                        last_msg = msg

                    if not last_msg or not last_msg.reactions:
                        continue

                    for reaction in last_msg.reactions:
                        emoji_str = str(reaction.emoji)
                        if emoji_str not in (STOPWATCH_EMOJI, STOPWATCH_EMOJI_ALT):
                            continue

                        async for user in reaction.users():
                            member = guild.get_member(user.id)
                            if not member:
                                continue
                            member_role_names = {r.name.lower() for r in member.roles}
                            if st_roles & member_role_names:
                                waiting.append(channel)
                                break
                        break

                except discord.Forbidden:
                    continue
                except Exception as e:
                    logger.error(f"WaitingForST: error checking channel {channel.name}: {e}")

        return waiting

    async def run_report(self, client: discord.Client, output_channel: discord.abc.Messageable = None):
        """Scan all channels and post the report. Used by the scheduler and slash command."""
        if output_channel is None:
            output_channel = client.get_channel(self.report_channel_id)
        if not output_channel:
            logger.error(f"WaitingForST: report channel {self.report_channel_id} not found.")
            return

        waiting = await self.get_waiting_channels(client)

        if not waiting:
            await output_channel.send(
                "⏱️ **Waiting for ST Report**\n\nNo channels are currently waiting for a Storyteller response."
            )
            return

        lines = [f"⏱️ **Channels Waiting for Storyteller Response** — {len(waiting)} channel(s):"]
        for channel in waiting:
            lines.append(f"• {channel.mention}")

        report = "\n".join(lines)
        chunks = smart_chunk_message(report, 1950)
        for chunk in chunks:
            await output_channel.send(chunk)

    async def run(self, client: discord.Client, message):
        """Entry point for /lotslarp waiting-for-st slash command."""
        report_channel = client.get_channel(self.report_channel_id)
        await message.channel.send("🔍 Scanning channels waiting for Storyteller response...")
        await self.run_report(client, report_channel)
        if report_channel and report_channel.id != getattr(message.channel, 'id', None):
            await message.channel.send(f"✅ Report posted to {report_channel.mention}.")

import discord
import logging
import os
import re
import sys
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Button View
class RemindSummaryView(discord.ui.View):
    def __init__(self, target_channel_id):
        super().__init__(timeout=None)
        # Custom ID must be persistent: "remind_summary:<channel_id>"
        self.add_item(discord.ui.Button(
            label="Send Reminder", 
            style=discord.ButtonStyle.danger, 
            custom_id=f"remind_summary:{target_channel_id}",
            emoji="⚠️"
        ))

async def handle_remind_interaction(interaction: discord.Interaction):
    """
    Handles the 'Send Reminder' button click.
    """
    try:
        custom_id = interaction.data['custom_id']
        channel_id = int(custom_id.split(':')[1])
        
        # Log the button click interaction
        logger.info(f"Button click: Reminder requested for channel ID {channel_id} by {interaction.user} (ID: {interaction.user.id})")
        
        target_channel = interaction.client.get_channel(channel_id)
        if not target_channel:
            await interaction.response.send_message("❌ Channel not found.", ephemeral=True)
            logger.warning(f"Reminder failed: Channel ID {channel_id} not found.")
            return

        # Send the reminder message
        reminder_msg = get_reminder_message(target_channel)
        await target_channel.send(reminder_msg)
        logger.info(f"Reminder sent successfully to channel '{target_channel.name}' (ID: {target_channel.id})")
        
        # Disable the button on the report message
        view = discord.ui.View(timeout=None)
        button = discord.ui.Button(
            label="Reminder Sent", 
            style=discord.ButtonStyle.secondary, 
            disabled=True, 
            emoji="✅"
        )
        view.add_item(button)
        
        await interaction.response.edit_message(view=view)

    except Exception as e:
        logger.error(f"Error handling reminder interaction: {e}", exc_info=True)
        try:
            await interaction.response.send_message(f"Failed to send reminder: {e}", ephemeral=True)
        except:
            pass

def get_reminder_message(channel):
    msg = (
        "(( :wave: Lotslarp bot has noticed that the conversation has slowed down here, "
        "and we do not yet have a summary. Please summarize this channel's contents for the storytellers "
        "and include a mention to `@summary` ))"
    )
    summary_role_name = os.environ.get("LOTSLARP_DISCORD_BOT_SUMMARY_ROLE_NAME")
    if summary_role_name and channel.guild:
        role = discord.utils.get(channel.guild.roles, name=summary_role_name)
        if role:
            msg = msg.replace("`@summary`", f"`@{role.name}`")
    return msg

class SummaryReminder:
    def __init__(self):
        self.name = "stale-channels"
        self.admin_role_name = os.environ.get("LOTSLARP_BOT_ADMIN_USER", "@storytellers").strip("@")
        
        try:
            self.msg_count_threshold = int(os.environ.get("LOTSLARP_BOT_SUMMARY_REMINDER_MESSAGES_COUNT", 3))
            self.lookback_days = int(os.environ.get("LOTSLARP_BOT_SUMMARY_REMINDER_LOOKBACK_DAYS", 90))
            self.activity_days = int(os.environ.get("LOTSLARP_BOT_SUMMARY_REMINDER_ACTIVITY_DAYS", 5))
            self.default_throttle_count = int(os.environ.get("LOTSLARP_BOT_SUMMARY_THROTTLE_CHANNEL_COUNT", 25))
            self.min_words = int(os.environ.get("LOTSLARP_BOT_SUMMARY_REMINDER_MIN_WORDS", 5))
            
            # Archival settings
            self.archive_reminder_inactivity = int(os.environ.get("LOTSLARP_BOT_ARCHIVE_REMINDER_INACTIVITY_DAYS", 14))
            self.archive_inactivity = int(os.environ.get("LOTSLARP_BOT_ARCHIVE_INACTIVITY_DAYS", 180))
            
            output_channel_str = os.environ.get("LOTSLARP_BOT_SUMMARY_CHANNEL_ID", "0")
            self.output_channel_id = int(output_channel_str.strip().strip("'").strip("'"))
        except ValueError as e:
            logger.error(f"Invalid env var for SummaryReminder: {e}")
            self.msg_count_threshold = 3
            self.lookback_days = 90
            self.activity_days = 5
            self.default_throttle_count = 25
            self.min_words = 5
            self.archive_reminder_inactivity = 14
            self.archive_inactivity = 180
            self.output_channel_id = 0
            
        self.summary_role_name = os.environ.get("LOTSLARP_DISCORD_BOT_SUMMARY_ROLE_NAME")
        
        # Parse multiple role names for detection
        role_names_str = os.environ.get("LOTSLARP_BOT_SUMMARY_REMINDER_ROLE_NAMES", "")
        if not role_names_str and self.summary_role_name:
            role_names_str = self.summary_role_name
        self.summary_detection_roles = [r.strip().strip("@") for r in role_names_str.split(",") if r.strip()]
        
        # Parse Ignore Guilds
        ignore_guilds_str = os.environ.get("LOTSLARP_BOT_STALE_CHANNELS_IGNORE_GUILDS", "")
        self.ignore_guild_ids = []
        for g_id in ignore_guilds_str.split(","):
            if g_id.strip().isdigit():
                self.ignore_guild_ids.append(int(g_id.strip()))

    async def run(self, client: discord.Client, message: discord.Message):
        """
        Scans for stale channels.
        Usage: /stale-channels [limit|all] [run]
        """
        # Log command start
        logger.info(f"Stale channel scan initiated by {message.author} (ID: {message.author.id}). Command: '{message.content}'")

        # 1. Check Permissions
        has_permission = False
        if isinstance(message.author, discord.Member):
            for role in message.author.roles:
                if role.name == self.admin_role_name:
                    has_permission = True
                    break
        
        if not has_permission:
            logger.warning(f"Permission denied for stale channel scan for user {message.author}.")
            await message.channel.send("🚫 You do not have permission to run this command.")
            return

        # 2. Get Output Channel
        output_channel = client.get_channel(self.output_channel_id)
        if not output_channel:
            logger.error(f"Summary output channel (ID {self.output_channel_id}) not found.")
            await message.channel.send("❌ Summary output channel (LOTSLARP_BOT_SUMMARY_CHANNEL_ID) not found.")
            return

        # 3. Parse Arguments
        throttle_count = self.default_throttle_count
        auto_run_mode = False
        limit_specified = False
        
        parts = message.content.split()
        args = parts[1:] if len(parts) > 1 else []
        
        for arg in args:
            arg = arg.lower()
            if arg == 'all':
                throttle_count = sys.maxsize
                limit_specified = True
            elif arg == 'run':
                auto_run_mode = True
            elif arg.isdigit():
                throttle_count = int(arg)
                limit_specified = True
        
        if auto_run_mode:
            # Automated run defaults to ALL unless a limit was explicitly specified
            if not limit_specified:
                throttle_count = sys.maxsize
            
            await message.add_reaction("✅")
            await message.channel.send(f"🔄 Running automated stale channel task (Limit: {'ALL' if throttle_count == sys.maxsize else throttle_count})...", delete_after=10)
            await self.execute_auto_scan(client, output_channel, throttle_count)
        else:
            await message.channel.send(f"🔍 Scanning for stale channels (Limit: {throttle_count if throttle_count != sys.maxsize else 'ALL'})...")
            await self.execute_manual_scan(client, message.channel, output_channel, throttle_count)

    async def _scan_channels(self, client, throttle_count):
        """
        Core scanning logic. Returns (stale_channels, archive_candidates).
        """
        category_regex = re.compile(r"^chat-.*$", re.IGNORECASE)
        ooc_regex = re.compile(r"^\s*\(\(")
        
        stale_channels = []
        archive_candidates = []
        
        now = discord.utils.utcnow()
        cutoff_date = now - timedelta(days=self.lookback_days)
        activity_cutoff = now - timedelta(days=self.activity_days)
        archive_cutoff = now - timedelta(days=self.archive_inactivity)
        archive_reminder_cutoff = now - timedelta(days=self.archive_reminder_inactivity)
        
        # Iterate Guilds
        for guild in client.guilds:
            if guild.id in self.ignore_guild_ids:
                continue
                
            if len(stale_channels) >= throttle_count:
                break
                
            # Iterate Categories
            for category in guild.categories:
                if len(stale_channels) >= throttle_count:
                    break
                    
                if not category_regex.match(category.name):
                    continue
                
                # Iterate Channels
                for channel in category.text_channels:
                    if len(stale_channels) >= throttle_count:
                        break
                    
                    try:
                        if not channel.permissions_for(guild.me).read_message_history:
                            continue

                        # Fetch recent message
                        last_message = None
                        async for msg in channel.history(limit=1):
                            last_message = msg
                            break
                        
                        if not last_message:
                            continue 
                        
                        # --- Archive Candidate Check 1: Long Inactivity ---
                        if last_message.created_at < archive_cutoff:
                            archive_candidates.append({
                                'channel': channel,
                                'reason': f"No activity for > {self.archive_inactivity} days."
                            })
                            continue 
                        
                        # Check if last message is a bot reminder
                        last_was_reminder = (last_message.author.id == client.user.id and 
                                           "Lotslarp bot has noticed" in last_message.content)

                        if last_was_reminder:
                            # --- Archive Candidate Check 2 ---
                            if last_message.created_at < archive_reminder_cutoff:
                                archive_candidates.append({
                                    'channel': channel,
                                    'reason': f"Reminder sent > {self.archive_reminder_inactivity} days ago with no reply."
                                })
                            
                            # Skip if already reminded (one message is enough)
                            continue
                        
                        # If normal activity is recent, skip
                        elif last_message.created_at > activity_cutoff:
                            continue

                        # Count messages since last summary
                        msg_count_since_summary = 0
                        
                        async for msg in channel.history(limit=100): 
                            if msg.created_at < cutoff_date:
                                break 
                            
                            if self.summary_detection_roles and msg.role_mentions:
                                if any(r.name in self.summary_detection_roles for r in msg.role_mentions):
                                    break 
                            
                            if ooc_regex.match(msg.content):
                                continue

                            word_count = len(msg.content.split())
                            if word_count < self.min_words:
                                continue

                            if not msg.author.bot:
                                msg_count_since_summary += 1
                        
                        if msg_count_since_summary >= self.msg_count_threshold:
                            stale_channels.append({
                                'channel': channel,
                                'count': msg_count_since_summary,
                                'last_was_reminder': last_was_reminder
                            })
                            
                    except Exception as e:
                        logger.error(f"Error scanning channel {channel.name}: {e}")
                        continue
                        
        return stale_channels, archive_candidates

    async def execute_manual_scan(self, client, command_channel, output_channel, throttle_count):
        """
        Original logic: Sends buttons to output channel.
        """
        stale_channels, archive_candidates = await self._scan_channels(client, throttle_count)
        
        if stale_channels:
            for item in stale_channels:
                channel = item['channel']
                count = item['count']
                
                msg_text = (
                    f"**Channel:** {channel.mention}\n"
                    f"**Unsummarized Messages:** {count} (in last {self.lookback_days} days)\n"
                    f"**Status:** Inactive for > {self.activity_days} days."
                )
                
                view = RemindSummaryView(channel.id)
                await output_channel.send(msg_text, view=view)
        else:
            await command_channel.send("✅ No stale channels found.")

        # Final Report
        hit_limit = len(stale_channels) >= throttle_count
        status_msg = f"🛑 Hit channel limit ({throttle_count})." if hit_limit else "✅ Scan complete."
        
        final_report = (
            f"**Scan Finished**\n"
            f"{status_msg}\n"
            f"Found {len(stale_channels)} stale channels."
        )
        
        if archive_candidates:
            final_report += f"\n\n**🗑️ Archive Candidates ({len(archive_candidates)})**\n"
            for item in archive_candidates[:20]:
                final_report += f"• {item['channel'].mention}: {item['reason']}\n"
            if len(archive_candidates) > 20:
                final_report += f"...and {len(archive_candidates) - 20} more."

        # Send to command channel
        if len(final_report) > 1950:
            from modules.utils import smart_chunk_message
            chunks = smart_chunk_message(final_report, 1950)
            for chunk in chunks:
                await command_channel.send(chunk)
        else:
            await command_channel.send(final_report)

    async def execute_auto_scan(self, client, output_channel, throttle_count=None):
        """
        Automated logic: Sends reminders directly and reports summary.
        Can be called via cron or manually via /stale-channels run.
        """
        if throttle_count is None:
             throttle_count = sys.maxsize # Default to ALL for auto scan

        logger.info(f"Starting automated stale channel scan (Limit: {throttle_count})")
        
        stale_channels, archive_candidates = await self._scan_channels(client, throttle_count)
        
        reminded_channels = []
        
        for item in stale_channels:
            channel = item['channel']
            
            # In auto mode, we send the reminder immediately
            try:
                msg = get_reminder_message(channel)
                await channel.send(msg)
                reminded_channels.append(channel)
                # Sleep briefly to avoid rate limits
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Failed to auto-send reminder to {channel.name}: {e}")

        # Generate Report
        logger.info(f"Generating report for {len(stale_channels)} stale channels. Reminded: {len(reminded_channels)}")
        
        report_lines = [
            f"**🤖 Automated Stale Channel Report**",
            f"**Date:** {discord.utils.utcnow().strftime('%Y-%m-%d')}",
            f"**Scanned Guilds:** {len(client.guilds) - len(self.ignore_guild_ids)}",
            f"**Stale Channels Found:** {len(stale_channels)}"
        ]
        
        if reminded_channels:
            report_lines.append(f"\n**📢 Reminders Sent ({len(reminded_channels)}):**")
            for ch in reminded_channels:
                count_val = "N/A"
                try:
                    count_val = next(i['count'] for i in stale_channels if i['channel'] == ch)
                except StopIteration:
                    pass
                report_lines.append(f"• {ch.mention} (Count: {count_val})")
        else:
            report_lines.append("\n✅ No reminders needed.")
            
        if archive_candidates:
            report_lines.append(f"\n**🗑️ Archive Candidates ({len(archive_candidates)})**")
            for item in archive_candidates[:20]:
                report_lines.append(f"• {item['channel'].mention}: {item['reason']}")
            if len(archive_candidates) > 20:
                report_lines.append(f"...and {len(archive_candidates) - 20} more.")

        full_report = "\n".join(report_lines)
        
        # Send to output channel
        try:
            if len(full_report) > 1950:
                from modules.utils import smart_chunk_message
                chunks = smart_chunk_message(full_report, 1950)
                for chunk in chunks:
                    await output_channel.send(chunk)
            else:
                await output_channel.send(full_report)
            logger.info("Report sent successfully.")
        except Exception as e:
            logger.error(f"Failed to send stale channel report: {e}")
            
        logger.info("Automated stale channel scan complete.")

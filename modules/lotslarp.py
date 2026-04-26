import os
import discord
import logging
from modules.help import LotslarpHelp
from modules.instructions import Instructions
from modules.larpbot_status import LarpbotStatus
from modules.hello import Hello
from modules.voice import Voice
from modules.digest_now import DigestNow
from modules.digest import Digest
from modules.monthly_summary import MonthlySummary
from modules.summary_reminder import SummaryReminder
from modules.channel_summarize import ChannelSummarize
from modules.channel_group import ChannelGroup
from modules.archive_channel import ArchiveChannel, UnarchiveChannel
from modules.archive_cleanup import cleanup_old_archives

logger = logging.getLogger(__name__)

class Lotslarp:
    def __init__(self, db_path=None, gemini_model=None, firestore_client=None, summary_module=None, pdf_gen=None, lore_manager=None, send_digest_callback=None):
        self.name = "lotslarp"
        self.firestore_client = firestore_client
        
        # Instantiate sub-handlers
        self.help_handler = LotslarpHelp()
        self.instructions_handler = Instructions()
        self.status_handler = LarpbotStatus(db_path, gemini_model)
        self.hello_handler = Hello()
        
        # Report Handlers
        # Voice needs firestore_client
        if firestore_client:
            self.voice_handler = Voice(firestore_client)
        else:
            self.voice_handler = None
            
        # DigestNow needs callback, summary, gemini, lore
        self.digest_handler = DigestNow(send_digest_callback, summary_module, gemini_model, lore_manager)
        
        # Range Digest needs summary, gemini, pdf, lore
        self.digest_range_handler = Digest(summary_module, gemini_model, pdf_gen, lore_manager)
        
        # Monthly needs summary, gemini, pdf, lore
        self.monthly_handler = MonthlySummary(summary_module, gemini_model, pdf_gen, lore_manager)
        
        # Stale Channels Handler
        self.stale_handler = SummaryReminder()
        
        # Channel Summarize Handler
        self.summarize_handler = ChannelSummarize(gemini_model, firestore_client, lore_manager)
        
        # Group Summarize/Management Handler
        self.group_handler = ChannelGroup(gemini_model, firestore_client, lore_manager)
        
        # Archive Handler
        self.archive_handler = ArchiveChannel(firestore_client)
        self.unarchive_handler = UnarchiveChannel(firestore_client)

    async def run(self, client: discord.Client, message: discord.Message):
        """
        Main entry point for /lotslarp commands.
        Usage: /lotslarp <subcommand> [args]
        """
        logger.info(f"Lotslarp wrapper received message: '{message.content}' from {message.author}")
        parts = message.content.split()
        
        # Default to help if no subcommand provided
        if len(parts) < 2:
            logger.info("No subcommand provided, defaulting to help.")
            await self.help_handler.run(client, message)
            return

        subcommand = parts[1].lower()
        logger.info(f"Lotslarp subcommand detected: '{subcommand}'")

        if subcommand == "help":
            await self.help_handler.run(client, message)
        
        elif subcommand == "status":
            await self.status_handler.run(client, message)
            
        elif subcommand == "instructions":
            await self.instructions_handler.run(client, message)
            
        elif subcommand == "hello":
            # Hello module returns string, others send messages directly
            response = await self.hello_handler.run(client, message)
            if response:
                await message.channel.send(response)

        elif subcommand == "map":
            map_url = os.environ.get("LOTSLARP_MAP_URL")
            if map_url:
                await message.channel.send(f"🗺️ **LotsLarp Sect Map:** {map_url}")
            else:
                await message.channel.send("❌ Map URL is not configured. Please contact the Storytellers.")

        elif subcommand == "archive":
            await self.archive_handler.run(client, message)

        elif subcommand == "unarchive":
            await self.unarchive_handler.run(client, message)

        elif subcommand == "stale":
            # Map /lotslarp stale [args] -> /stale-channels [args]
            args = parts[2:]
            fake_content = "/stale-channels " + " ".join(args)
            original_content = message.content
            message.content = fake_content.strip()
            await self.stale_handler.run(client, message)
            message.content = original_content # Restore

        elif subcommand == "summarize":
            # Map /lotslarp summarize <channel> -> /summarize <channel>
            args = parts[2:]
            fake_content = "/summarize " + " ".join(args)
            original_content = message.content
            message.content = fake_content.strip()
            result = await self.summarize_handler.run(client, message)
            message.content = original_content # Restore
            if result:
                 await message.channel.send(result)

        elif subcommand == "group":
            await self.group_handler.run(client, message)

        elif subcommand == "report":
            if len(parts) < 3:
                await message.channel.send("Usage: `/lotslarp report <voice|digest|month> [args]`")
                return
            
            report_type = parts[2].lower()
            
            if report_type == "voice":
                if self.voice_handler:
                    # Handle argument mapping: /lotslarp report voice 10 -> /voice-report 10
                    args = parts[3:]
                    fake_content = "/voice-report " + " ".join(args)
                    original_content = message.content
                    message.content = fake_content.strip()
                    await self.voice_handler.run(client, message)
                    message.content = original_content # Restore
                else:
                    await message.channel.send("❌ Voice module is not initialized (Database unavailable).")

            elif report_type == "digest":
                # Handle /lotslarp report digest [now|day|week|month]
                # Default to 'month' if no args
                args = parts[3:]
                timeframe = args[0].lower() if args else "month"
                
                if timeframe == "now":
                    # Maps to /digest-now
                    await self.digest_handler.run(client, message)
                else:
                    # Maps to /digest <timeframe>
                    # Valid inputs for Digest module: day, week, month
                    # We synthesize the message content to /digest <timeframe>
                    fake_content = f"/digest {timeframe}"
                    original_content = message.content
                    message.content = fake_content
                    await self.digest_range_handler.run(client, message)
                    message.content = original_content

            elif report_type == "month":
                # Maps to /summarize-month
                await self.monthly_handler.run(client, message)

            else:
                await message.channel.send(f"❌ Unknown report type: `{report_type}`. Available: `voice`, `digest`, `month`.")

        elif subcommand == "purge-archives":
            await message.channel.send("⚙️ Manually triggering archive cleanup task...")
            await cleanup_old_archives(client, self.firestore_client)
            await message.channel.send("✅ Archive cleanup task finished.")

        else:
            await message.channel.send(f"❌ Unknown subcommand: `{subcommand}`. Try `/lotslarp help`.")

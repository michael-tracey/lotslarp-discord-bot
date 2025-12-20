import discord
import logging

logger = logging.getLogger(__name__)

class DigestNow:
    def __init__(self, send_digest_callback, summary_module, gemini_model, lore_manager):
        self.send_digest_callback = send_digest_callback
        self.summary_module = summary_module
        self.gemini_model = gemini_model
        self.lore_manager = lore_manager
        self.name = "digest-now"

    async def run(self, client: discord.Client, message: discord.Message):
        """
        Forces an immediate digest send, bypassing thresholds.
        Usage: /digest-now
        """
        await message.channel.send("🔄 Triggering immediate digest...", delete_after=10)
        
        try:
            # We call the callback (send_digest_pdf) with force=True
            await self.send_digest_callback(
                client, 
                self.summary_module, 
                self.gemini_model, 
                self.lore_manager, 
                force=True
            )
            await message.add_reaction("✅")
        except Exception as e:
            logger.error(f"Error triggering digest-now: {e}", exc_info=True)
            await message.channel.send(f"❌ Failed to trigger digest: {e}")

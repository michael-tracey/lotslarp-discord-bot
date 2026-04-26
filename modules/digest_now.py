import os
import discord
import logging
from modules.utils import get_admin_roles

logger = logging.getLogger(__name__)

class DigestNow:
    def __init__(self, send_digest_callback, summary_module, gemini_model, lore_manager):
        self.send_digest_callback = send_digest_callback
        self.summary_module = summary_module
        self.gemini_model = gemini_model
        self.lore_manager = lore_manager
        self.name = "digest-now"
        self.admin_roles = get_admin_roles()

    async def run(self, client: discord.Client, message: discord.Message):
        """
        Forces an immediate digest send, bypassing thresholds.
        Usage: /digest-now
        """
        logger.info(f"Command started: /digest-now by {message.author} in {message.channel}")

        # Check Permissions
        has_permission = False
        if isinstance(message.author, discord.Member):
            for role in message.author.roles:
                if role.name in self.admin_roles:
                    has_permission = True
                    break
        
        if not has_permission:
            logger.warning(f"Permission denied for {message.author}")
            await message.channel.send("🚫 You do not have permission to run this command.")
            return

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
            logger.info("Immediate digest triggered successfully.")
        except Exception as e:
            logger.error(f"Error triggering digest-now: {e}", exc_info=True)
            await message.channel.send(f"❌ Failed to trigger digest: {e}")

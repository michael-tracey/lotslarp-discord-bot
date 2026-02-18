import os
import discord
import logging
import asyncio
import subprocess
import shlex
import tempfile
import shutil
import re
from datetime import datetime, timedelta, timezone
from google.cloud import firestore
from modules.utils import compress_pdf, JobQueue, get_shared_archive_queue

logger = logging.getLogger(__name__)

class ArchiveChannel:
    def __init__(self, firestore_client):
        self.name = "archive"
        self.db = firestore_client
        # Default to the path found in the other repo if env var is not set
        self.dce_cli_path = os.environ.get("DCE_CLI_PATH", "/home/michael/bin/DiscordChatExport/DiscordChatExporter.Cli")
        
        # Get the shared queue
        try:
            max_concurrent = int(os.environ.get("LOTSLARP_MAX_CONCURRENT_ARCHIVES", 2))
        except (ValueError, TypeError):
            max_concurrent = 2
        self.archive_queue = get_shared_archive_queue(max_concurrent=max_concurrent)

    def sanitize_filename(self, name):
        """
        Sanitizes a string to be used as a filename.
        """
        s = re.sub(r'[\\/:*?"<>|]', '_', name)
        s = s.strip()
        s = re.sub(r'[\s_]+', '_', s)
        return s[:200]

    async def run_command(self, command, description):
        """
        Executes a shell command asynchronously.
        """
        logger.info(f"Executing {description}: {' '.join(command)}")
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"Command failed with exit code {process.returncode}")
                logger.error(f"STDOUT: {stdout.decode()}")
                logger.error(f"STDERR: {stderr.decode()}")
                return False
            return True
        except Exception as e:
            logger.error(f"Error executing command: {e}", exc_info=True)
            return False

    async def make_read_only(self, channel, guild):
        """
        Makes the channel read-only for non-admins.
        """
        try:
            if isinstance(channel, discord.Thread):
                await channel.edit(locked=True)
                logger.info(f"Locked thread {channel.name}.")
            else:
                # TextChannel
                # Deny send_messages for @everyone, preserving other permissions
                overwrite = channel.overwrites_for(guild.default_role)
                overwrite.send_messages = False
                await channel.set_permissions(guild.default_role, overwrite=overwrite)
                logger.info(f"Set {channel.name} to read-only for @everyone.")
        except discord.Forbidden:
            logger.warning(f"Missing permissions to make {channel.name} read-only.")
        except Exception as e:
            logger.error(f"Error making {channel.name} read-only: {e}")

    async def run(self, client: discord.Client, message: discord.Message):
        """
        Archives the current channel or the mentioned channel.
        Usage: /lotslarp archive [channel_mention]
        """
        logger.info(f"Command started: /lotslarp archive by {message.author} in {message.channel}")

        if not self.db:
            logger.error("Database connection unavailable for archive command.")
            await message.channel.send("❌ Database connection unavailable. Cannot archive.")
            return

        if not os.path.exists(self.dce_cli_path):
            await message.channel.send("❌ Configuration Error: `DiscordChatExporter.Cli` not found.")
            logger.error(f"DCE_CLI_PATH not found: {self.dce_cli_path}")
            return

        target_channel = message.channel
        if message.channel_mentions:
            target_channel = message.channel_mentions[0]

        logger.info(f"Targeting channel {target_channel.name} ({target_channel.id}) for archive.")

        # Check permissions
        if not target_channel.permissions_for(message.guild.me).read_messages:
            logger.warning(f"Bot lacks read permission for {target_channel.name}")
            await message.channel.send(f"❌ I do not have permission to read messages in {target_channel.mention}.")
            return
        
        # 0. Make Read-Only
        await self.make_read_only(target_channel, message.guild)

        status_msg = None

        async def update_pos_callback(pos):
            nonlocal status_msg
            msg_text = f"⏳ Archive for {target_channel.mention} is queued and will start shortly (Position in queue: {pos})..."
            if status_msg is None:
                status_msg = await message.channel.send(msg_text)
            else:
                try:
                    await status_msg.edit(content=msg_text)
                except discord.NotFound:
                    status_msg = await message.channel.send(msg_text)
                except Exception as e:
                    logger.error(f"Failed to edit status message: {e}")

        # This will wait until it's our turn, updating the message as it moves
        await self.archive_queue.run_task(
            self._do_archive, 
            client, message, target_channel, status_msg,
            update_callback=update_pos_callback
        )

    async def _do_archive(self, client, message, target_channel, status_msg):
        if status_msg is None:
            status_msg = await message.channel.send(f"⏳ Starting archive for {target_channel.mention}... This may take a while.")
        else:
            try:
                await status_msg.edit(content=f"⏳ Starting archive for {target_channel.mention}... This may take a while.")
            except:
                status_msg = await message.channel.send(f"⏳ Starting archive for {target_channel.mention}... This may take a while.")
        
        # Create a temporary directory for the operation
        with tempfile.TemporaryDirectory() as temp_dir:
            channel_name = self.sanitize_filename(target_channel.name)
            output_base = f"archive_{channel_name}_{target_channel.id}_{datetime.now().strftime('%Y%m%d')}"
            html_file = os.path.join(temp_dir, f"{output_base}.html")
            pdf_file = os.path.join(temp_dir, f"{output_base}.pdf")

            token = os.environ.get("LOTSLARP_DISCORD_BOT_DISCORD_TOKEN")
            if not token:
                logger.error("Bot token missing from environment variables.")
                await status_msg.edit(content="❌ Error: Bot token not found in environment.")
                return

            # 1. Export to HTML
            logger.info(f"Exporting channel {target_channel.name} to HTML...")
            await status_msg.edit(content=f"⏳ Exporting {target_channel.mention} to HTML...")
            export_cmd = [
                self.dce_cli_path,
                "export",
                "-t", token,
                "-c", str(target_channel.id),
                "-o", html_file,
                "--media", "--markdown", "--bot" # Added --bot flag as we are using a bot token
            ]
            
            if not await self.run_command(export_cmd, "DiscordChatExporter"):
                await status_msg.edit(content="❌ Export failed. Check logs.")
                return

            if not os.path.exists(html_file):
                logger.error("Export failed: HTML file was not created.")
                await status_msg.edit(content="❌ Export failed: HTML file not created.")
                return

            # 2. Convert to PDF using WeasyPrint
            logger.info("Converting HTML archive to PDF...")
            await status_msg.edit(content=f"⏳ Converting {target_channel.mention} archive to PDF...")
            
            # Create a temp CSS for margins
            css_file_path = os.path.join(temp_dir, "style.css")
            with open(css_file_path, "w") as f:
                f.write("@page { margin: 0; }")

            convert_cmd = [
                "weasyprint",
                "--stylesheet", css_file_path,
                "--encoding", "utf-8",
                html_file, pdf_file
            ]

            if not await self.run_command(convert_cmd, "WeasyPrint"):
                await status_msg.edit(content="❌ PDF Conversion failed. Check logs.")
                return

            if not os.path.exists(pdf_file):
                logger.error("PDF Conversion failed: PDF file was not created.")
                await status_msg.edit(content="❌ PDF Conversion failed: PDF file not created.")
                return

            # 3. Send PDF
            logger.info("PDF generated successfully. Uploading...")
            await status_msg.edit(content=f"✅ Archive complete! Uploading PDF...")
            try:
                # Discord default limit for non-boosted servers is 10MB
                DISCORD_LIMIT_MB = 10
                DISCORD_LIMIT_BYTES = DISCORD_LIMIT_MB * 1024 * 1024
                
                original_size = os.path.getsize(pdf_file)
                logger.info(f"Original PDF size: {original_size/1024/1024:.2f} MB. Compressing...")
                await status_msg.edit(content=f"⏳ Optimizing PDF size...")
                
                compressed_pdf_file = os.path.join(temp_dir, f"{output_base}_compressed.pdf")
                # Default to /printer (300dpi) for the first pass as standard optimization
                success = await compress_pdf(pdf_file, compressed_pdf_file, power=2)
                
                if success:
                    pdf_file = compressed_pdf_file
                    file_size = os.path.getsize(pdf_file)
                    
                    # If still too large, try /ebook settings (150 dpi)
                    if file_size > DISCORD_LIMIT_BYTES:
                        logger.info("Still too large. Trying ebook compression...")
                        ebook_pdf = os.path.join(temp_dir, f"{output_base}_ebook.pdf")
                        if await compress_pdf(pdf_file, ebook_pdf, power=3):
                            pdf_file = ebook_pdf
                            file_size = os.path.getsize(pdf_file)
                            
                        # If STILL too large, try /screen settings (72 dpi)
                        if file_size > DISCORD_LIMIT_BYTES:
                            logger.info("Still too large. Trying maximum compression...")
                            max_pdf = os.path.join(temp_dir, f"{output_base}_max.pdf")
                            if await compress_pdf(pdf_file, max_pdf, power=4):
                                pdf_file = max_pdf
                                file_size = os.path.getsize(pdf_file)

                file_size = os.path.getsize(pdf_file)
                if file_size > DISCORD_LIMIT_BYTES:
                     logger.warning(f"Archive PDF is STILL too large ({file_size/1024/1024:.2f} MB) after compression.")
                     await status_msg.edit(content=f"⚠️ The archive PDF is too large ({file_size/1024/1024:.2f} MB) to upload directly, even after compression.")
                else:
                    retention_days = int(os.environ.get("LOTSLARP_ARCHIVE_RETENTION_DAYS", "7"))
                    deletion_date = datetime.now(timezone.utc) + timedelta(days=retention_days)
                    
                    final_msg_content = (
                        f"📂 **Archive for {target_channel.mention} is complete!**\n\n"
                        f"This channel has been set to read-only. Please download the attached PDF for your records if you wish to keep a copy of this conversation.\n\n"
                        f"⚠️ **Note:** This channel is scheduled to be automatically deleted in **{retention_days} days**."
                    )
                    
                    sent_msg = None
                    with open(pdf_file, "rb") as f:
                        discord_file = discord.File(f, filename=f"{channel_name}_archive.pdf")
                        sent_msg = await message.channel.send(content=final_msg_content, file=discord_file)
                    await status_msg.delete()
                    logger.info(f"Archive PDF uploaded to {message.channel.name}.")
                    
                    # SAVE TO FIRESTORE
                    if sent_msg:
                        try:
                            doc_ref = self.db.collection('archived_channels').document(str(target_channel.id))
                            doc_ref.set({
                                'guild_id': target_channel.guild.id,
                                'channel_name': target_channel.name,
                                'archived_at': datetime.now(timezone.utc),
                                'deletion_date': deletion_date,
                                'last_message_url': sent_msg.jump_url,
                                'status': 'pending'
                            })
                            logger.info(f"Saved archive record for channel {target_channel.id} to Firestore.")
                        except Exception as e:
                            logger.error(f"Failed to save archive record to Firestore: {e}")

                # 4. Send to ST Archive Channel
                archive_channel_id_str = os.environ.get("LOTSLARP_ARCHIVE_CHANNEL_ID")
                if archive_channel_id_str:
                    try:
                        archive_channel_id = int(archive_channel_id_str)
                        archive_channel = client.get_channel(archive_channel_id)
                        if archive_channel:
                             with open(pdf_file, "rb") as f:
                                st_archive_file = discord.File(f, filename=f"{channel_name}_archive.pdf")
                                await archive_channel.send(
                                    content=f"📦 **Archive Report**\n**Source:** {target_channel.guild.name} -> {target_channel.mention}\n**Date:** {datetime.now().strftime('%Y-%m-%d')}",
                                    file=st_archive_file
                                )
                             logger.info(f"Archive PDF sent to ST Archive Channel ({archive_channel.name}).")
                        else:
                            logger.warning(f"Could not find ST Archive Channel with ID {archive_channel_id}")
                    except ValueError:
                        logger.error(f"Invalid LOTSLARP_ARCHIVE_CHANNEL_ID: {archive_channel_id_str}")
                    except Exception as e:
                        logger.error(f"Failed to send to ST Archive Channel: {e}")

            except Exception as e:
                logger.error(f"Failed to upload PDF: {e}", exc_info=True)
                await status_msg.edit(content="❌ Failed to upload PDF to Discord.")

class UnarchiveChannel:
    def __init__(self, firestore_client):
        self.name = "unarchive"
        self.db = firestore_client

    async def make_read_write(self, channel, guild):
        """
        Restores read/write permissions for @everyone (or unlocks thread).
        """
        try:
            if isinstance(channel, discord.Thread):
                await channel.edit(locked=False)
                logger.info(f"Unlocked thread {channel.name}.")
            else:
                # TextChannel
                # Reset send_messages for @everyone (set to None to inherit/default), preserving other permissions
                overwrite = channel.overwrites_for(guild.default_role)
                overwrite.send_messages = None
                await channel.set_permissions(guild.default_role, overwrite=overwrite)
                logger.info(f"Restored {channel.name} permissions for @everyone.")
        except discord.Forbidden:
            logger.warning(f"Missing permissions to unlock {channel.name}.")
        except Exception as e:
            logger.error(f"Error unlocking {channel.name}: {e}")

    async def run(self, client: discord.Client, message: discord.Message):
        """
        Unarchives a channel: removes from deletion queue and restores permissions.
        Usage: /lotslarp unarchive [channel_mention]
        """
        logger.info(f"Command started: /lotslarp unarchive by {message.author} in {message.channel}")
        
        if not self.db:
            logger.error("Database connection unavailable for unarchive command.")
            await message.channel.send("❌ Database connection unavailable.")
            return

        target_channel = message.channel
        if message.channel_mentions:
            target_channel = message.channel_mentions[0]

        logger.info(f"Targeting channel {target_channel.name} ({target_channel.id}) for unarchive.")

        try:
            doc_ref = self.db.collection('archived_channels').document(str(target_channel.id))
            doc = doc_ref.get()
            
            if doc.exists:
                doc_ref.delete()
                await self.make_read_write(target_channel, message.guild)
                await message.channel.send(f"✅ **{target_channel.mention} has been unarchived.**\nDeletion canceled and permissions restored.")
                logger.info(f"Unarchived channel {target_channel.id} (removed from Firestore).")
            else:
                logger.info(f"Channel {target_channel.id} was not in archive queue.")
                await message.channel.send(f"ℹ️ {target_channel.mention} is not in the archive queue.")
        except Exception as e:
            logger.error(f"Error unarchiving channel: {e}", exc_info=True)
            await message.channel.send("❌ An error occurred while unarchiving.")

import os
import discord
import logging
import asyncio
import subprocess
import shlex
import tempfile
import shutil
import re
from collections import deque
from datetime import datetime, timedelta, timezone
from google.cloud import firestore, storage
from modules.utils import compress_pdf, get_pdf_page_count, JobQueue, get_shared_archive_queue

logger = logging.getLogger(__name__)

_ARCHIVE_STEPS = [
    "Export chat history",
    "Convert to PDF",
    "Optimize PDF",
    "Deliver archive",
]

class ArchiveChannel:
    def __init__(self, firestore_client):
        self.name = "archive"
        self.db = firestore_client
        # Default to the path found in the other repo if env var is not set
        self.dce_cli_path = os.environ.get("DCE_CLI_PATH", "/home/michael/bin/DiscordChatExporter/DiscordChatExporter.Cli")

        # Get the shared queue - Default to 1 concurrent archive to save resources on small VMs
        try:
            max_concurrent = int(os.environ.get("LOTSLARP_MAX_CONCURRENT_ARCHIVES", 1))
        except (ValueError, TypeError):
            max_concurrent = 1
        self.archive_queue = get_shared_archive_queue(max_concurrent=max_concurrent)

    def sanitize_filename(self, name):

        """
        Sanitizes a string to be used as a filename.
        """
        s = re.sub(r'[\\/:*?"<>|]', '_', name)
        s = s.strip()
        s = re.sub(r'[\s_]+', '_', s)
        return s[:200]

    async def run_command(self, command, description, timeout=1200, progress_callback=None):
        """
        Executes a shell command asynchronously with a timeout.
        Reads output line-by-line and can call a progress_callback.
        Throttles the process using nice and ionice if available.
        """
        # Prefix with nice and ionice to prevent system lockup
        throttled_command = []
        if shutil.which("nice"):
            throttled_command.extend(["nice", "-n", "15"])
        if shutil.which("ionice"):
            throttled_command.extend(["ionice", "-c", "3"])
        
        full_command = throttled_command + command
        
        logger.info(f"Executing {description}: {' '.join(full_command)}")
        try:
            process = await asyncio.create_subprocess_exec(
                *full_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout_lines = deque(maxlen=10)
            stderr_lines = deque(maxlen=10)

            async def read_stream(stream, is_stderr=False):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    line_str = line.decode().strip()
                    if is_stderr:
                        stderr_lines.append(line_str)
                        if line_str: logger.debug(f"[{description} STDERR] {line_str}")
                    else:
                        stdout_lines.append(line_str)
                        if line_str: logger.debug(f"[{description}] {line_str}")
                        if progress_callback:
                            try:
                                # Ensure callback doesn't block stream reading
                                asyncio.create_task(progress_callback(line_str))
                            except:
                                pass

            try:
                # Wait for both reading tasks and the process to complete
                await asyncio.wait_for(
                    asyncio.gather(
                        read_stream(process.stdout),
                        read_stream(process.stderr, is_stderr=True),
                        process.wait()
                    ),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"{description} timed out after {timeout} seconds.")
                try:
                    process.terminate()
                    await asyncio.sleep(1)
                    if process.returncode is None:
                        process.kill()
                except:
                    pass
                return False

            if process.returncode != 0:
                logger.error(f"Command failed with exit code {process.returncode}")
                # Log only the last few lines of output to avoid flooding logs
                logger.error(f"Last STDOUT lines: {' | '.join(stdout_lines[-10:])}")
                logger.error(f"Last STDERR lines: {' | '.join(stderr_lines[-10:])}")
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
        Archives the current channel or the mentioned channel(s).
        Usage: /lotslarp archive [channel_mention1] [channel_mention2] ...
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

        targets = message.channel_mentions
        if not targets:
            targets = [message.channel]

        logger.info(f"Targeting {len(targets)} channels for archive.")

        for target_channel in targets:
            # Check permissions
            if not target_channel.permissions_for(message.guild.me).read_messages:
                logger.warning(f"Bot lacks read permission for {target_channel.name}")
                await message.channel.send(f"❌ I do not have permission to read messages in {target_channel.mention}.")
                continue
            
            # Create a localized tracker for status_msg per target
            class StatusTracker:
                def __init__(self):
                    self.msg = None

            tracker = StatusTracker()
            channel_mention = target_channel.mention # Capture for closure

            async def update_pos_callback(pos, tracker=tracker, cm=channel_mention):
                msg_text = f"⏳ Archive for {cm} is queued and will start shortly (Position in queue: {pos})..."
                if tracker.msg is None:
                    tracker.msg = await message.channel.send(msg_text)
                else:
                    try:
                        await tracker.msg.edit(content=msg_text)
                    except discord.NotFound:
                        tracker.msg = await message.channel.send(msg_text)
                    except Exception as e:
                        logger.error(f"Failed to edit status message: {e}")

            # Queue the task as a background task so we don't block the loop
            asyncio.create_task(self.archive_queue.run_task(
                self._do_archive, 
                client, message, target_channel, tracker,
                update_callback=update_pos_callback
            ))

        if len(targets) > 1:
            await message.channel.send(f"✅ Queued {len(targets)} channels for archiving.")

    def get_progress_bar(self, percentage, length=20):
        """Generates a text-based progress bar."""
        filled_length = int(length * percentage // 100)
        bar = '█' * filled_length + '░' * (length - filled_length)
        return f"`|{bar}|` {percentage}%"

    def _step_status(self, channel_mention, current_step, detail=""):
        """Builds a cumulative step checklist for the archive status message."""
        lines = [f"📂 **Archiving {channel_mention}**"]
        for i, name in enumerate(_ARCHIVE_STEPS):
            num = i + 1
            if num < current_step:
                lines.append(f"  ✅ {name}")
            elif num == current_step:
                lines.append(f"  ⏳ **{name}**" + (f"\n  {detail}" if detail else ""))
            else:
                lines.append(f"  ◻ {name}")
        return "\n".join(lines)

    def get_indeterminate_bar(self, count):
        """Generates a pulsing activity bar for unknown totals."""
        bars = ["`[■       ]`", "`[ ■      ]`", "`[  ■     ]`", "`[   ■    ]`", 
                "`[    ■   ]`", "`[     ■  ]`", "`[      ■ ]`", "`[       ■]`",
                "`[      ■ ]`", "`[     ■  ]`", "`[    ■   ]`", "`[   ■    ]`",
                "`[  ■     ]`", "`[ ■      ]`"]
        return bars[count % len(bars)]

    async def upload_to_gcs(self, file_path, bucket_name, destination_blob_name):
        """Uploads a file to a GCS bucket and returns the public or signed URL."""
        try:
            # Use the same project as Firestore if available to ensure we use a valid project ID
            # instead of potentially an invalid project name/alias from the environment.
            project = None
            if hasattr(self, 'db') and self.db:
                project = self.db.project
                logger.info(f"Initializing storage client with project ID from Firestore: {project}")
            else:
                logger.warning("Firestore client not available, storage client will use default project discovery.")

            storage_client = storage.Client(project=project)
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(destination_blob_name)
            
            # Upload the file
            logger.info(f"Uploading {file_path} to GCS bucket {bucket_name} as {destination_blob_name}...")
            # Use a thread pool as this is a blocking call (gcs-python-client isn't natively async)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, blob.upload_from_filename, file_path)
            
            # Try to make public (only works on Fine-grained ACL buckets)
            try:
                # This only works if the bucket uses Fine-grained ACLs.
                # If Uniform Bucket-Level Access is enabled, this will throw a 400 error.
                blob.make_public()
                logger.info(f"Successfully made {destination_blob_name} public via object ACL.")
            except Exception as e:
                # Fallback: We don't try to generate a signed URL here because on GCE/Cloud Run,
                # generate_signed_url requires a private key which is not available in the 
                # default Compute Engine credentials. 
                # Instead, we return the public URL and assume the bucket permissions (IAM) 
                # are handled by the administrator.
                logger.info(f"Note: Could not set object ACL (likely due to Uniform Bucket-Level Access): {e}")
            
            return blob.public_url
        except Exception as e:
            logger.error(f"Error uploading to GCS: {e}", exc_info=True)
            return None

    async def _do_archive(self, client, message, target_channel, tracker):
        # 0. Make Read-Only right before starting
        await self.make_read_only(target_channel, message.guild)

        _initial = self._step_status(target_channel.mention, 1)
        if tracker.msg is None:
            tracker.msg = await message.channel.send(_initial)
        else:
            try:
                await tracker.msg.edit(content=_initial)
            except:
                tracker.msg = await message.channel.send(_initial)
        
        status_msg = tracker.msg
        last_update_time = 0
        
        async def update_status(new_content, force=False):
            nonlocal last_update_time, status_msg
            now = datetime.now().timestamp()
            # Discord rate limits are roughly 1 edit per 1-2 seconds.
            # We use a 3s window to be safe and avoid flooding.
            if force or (now - last_update_time > 3):
                # Update timestamp IMMEDIATELY to prevent other concurrent tasks 
                # from passing the check while this edit is in progress.
                last_update_time = now
                try:
                    await status_msg.edit(content=new_content)
                except discord.NotFound:
                    # Message was deleted, try to send a new one
                    try:
                        status_msg = await message.channel.send(new_content)
                    except:
                        pass
                except Exception as e:
                    logger.warning(f"Failed to update status message: {e}")

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
            await update_status(self._step_status(target_channel.mention, 1), force=True)

            async def dce_progress(line):
                match = re.search(r"(\d+)%", line)
                if match:
                    percent = int(match.group(1))
                    bar = self.get_progress_bar(percent)
                    await update_status(self._step_status(target_channel.mention, 1, bar))

            export_cmd = [
                self.dce_cli_path,
                "export",
                "-t", token,
                "-c", str(target_channel.id),
                "-o", html_file,
                "--media", "--markdown", "--bot"
            ]
            
            if not await self.run_command(export_cmd, "DiscordChatExporter", progress_callback=dce_progress):
                await status_msg.edit(content="❌ Export failed. Check logs.")
                return

            if not os.path.exists(html_file):
                logger.error("Export failed: HTML file was not created.")
                await status_msg.edit(content="❌ Export failed: HTML file not created.")
                return

            # 2. Convert to PDF using WeasyPrint
            html_size_mb = os.path.getsize(html_file) / (1024 * 1024)
            logger.info(f"HTML Export successful. Size: {html_size_mb:.2f} MB. Starting PDF conversion...")
            
            if html_size_mb > 10:
                warn_text = f"⚠️ **Large Channel Detected ({html_size_mb:.1f}MB HTML)**\nPDF conversion may be very slow or fail on this server's hardware."
                await message.channel.send(warn_text)
                await asyncio.sleep(1) # Give Discord a moment to process

            await update_status(self._step_status(target_channel.mention, 2, "(This part is slow for long channels)"), force=True)
            
            # Create a temp CSS for margins and a cache folder for WeasyPrint
            css_file_path = os.path.join(temp_dir, "style.css")
            with open(css_file_path, "w") as f:
                f.write("@page { margin: 0; }")
            
            wp_cache_dir = os.path.join(temp_dir, "weasy_cache")
            os.makedirs(wp_cache_dir, exist_ok=True)

            activity_count = 0
            current_rendering_page = None

            async def weasy_progress(line):
                nonlocal activity_count, current_rendering_page
                activity_count += 1
                pulse = self.get_indeterminate_bar(activity_count)
                if "Rendering page" in line:
                    match = re.search(r"Rendering page (\d+)", line)
                    if match:
                        current_rendering_page = match.group(1)
                        detail = f"{pulse} 📄 Rendering page **{current_rendering_page}**..."
                    else:
                        detail = f"{pulse} 📄 {line.strip()}"
                    await update_status(self._step_status(target_channel.mention, 2, detail))
                elif "Step" in line:
                    await update_status(self._step_status(target_channel.mention, 2, f"{pulse} ⚙️ {line.strip()}"))

            # Background task for periodic size updates
            stop_monitoring = asyncio.Event()
            async def monitor_file_size():
                while not stop_monitoring.is_set():
                    try:
                        await asyncio.wait_for(stop_monitoring.wait(), timeout=60)
                        break
                    except asyncio.TimeoutError:
                        if os.path.exists(pdf_file):
                            size_bytes = os.path.getsize(pdf_file)
                            if size_bytes > 0:
                                size_mb = size_bytes / (1024 * 1024)
                                now_str = datetime.now().strftime("%H:%M:%S")
                                pulse = self.get_indeterminate_bar(activity_count)
                                detail = f"{pulse} 📊 Size: **{size_mb:.2f} MB** (at {now_str})"
                                if current_rendering_page:
                                    detail += f" — last page: {current_rendering_page}"
                                await update_status(self._step_status(target_channel.mention, 2, detail))
                    except Exception as e:
                        logger.debug(f"File monitoring error: {e}")
            
            monitor_task = asyncio.create_task(monitor_file_size())

            # Optimize WeasyPrint for Memory:
            # 1. Lower DPI (96 instead of 150)
            # 2. REMOVE --optimize-images (save RAM, let Ghostscript do it later)
            # 3. Add --presentational-hints to assist layout engine
            convert_cmd = [
                "weasyprint",
                "-v", # Verbose to get progress
                "--stylesheet", css_file_path,
                "--encoding", "utf-8",
                "--presentational-hints",
                "--dpi", "96",
                "--cache-folder", wp_cache_dir,
                html_file, pdf_file
            ]

            try:
                if not await self.run_command(convert_cmd, "WeasyPrint", timeout=3600, progress_callback=weasy_progress):
                    try:
                        await status_msg.edit(content="❌ PDF Conversion failed or timed out (1 hour limit). Check logs.")
                    except:
                        pass
                    return
            finally:
                stop_monitoring.set()
                try:
                    await asyncio.wait_for(monitor_task, timeout=5)
                except:
                    pass

            if not os.path.exists(pdf_file):
                logger.error("PDF Conversion failed: PDF file was not created.")
                await status_msg.edit(content="❌ PDF Conversion failed: PDF file not created.")
                return

            # 3. Optimize PDF
            logger.info("PDF generated successfully. Optimizing...")
            await update_status(self._step_status(target_channel.mention, 3), force=True)
            
            try:
                # Discord default limit for non-boosted servers is 10MB
                DISCORD_LIMIT_MB = 10
                DISCORD_LIMIT_BYTES = DISCORD_LIMIT_MB * 1024 * 1024
                
                original_size = os.path.getsize(pdf_file)
                logger.info(f"Original PDF size: {original_size/1024/1024:.2f} MB. Compressing...")
                
                # Get total pages for optimization progress bar
                total_pages = await get_pdf_page_count(pdf_file)
                
                async def gs_progress(line):
                    if "Page" in line:
                        match = re.search(r"Page (\d+)", line)
                        if match and total_pages > 0:
                            current_page = int(match.group(1))
                            percent = int((current_page / total_pages) * 100)
                            bar = self.get_progress_bar(percent)
                            await update_status(self._step_status(target_channel.mention, 3, bar))

                compressed_pdf_file = os.path.join(temp_dir, f"{output_base}_compressed.pdf")
                # Default to /printer (300dpi) for the first pass as standard optimization
                if await compress_pdf(pdf_file, compressed_pdf_file, power=2, progress_callback=gs_progress):
                    if os.path.getsize(compressed_pdf_file) < original_size:
                        pdf_file = compressed_pdf_file
                        file_size = os.path.getsize(pdf_file)
                    else:
                        logger.info("Compressed PDF is not smaller than original, keeping original.")
                        file_size = original_size
                else:
                    file_size = original_size
                
                # Attempt GCS upload — failure is non-fatal if the file fits in Discord
                gcs_bucket = os.environ.get("LOTSLARP_ARCHIVE_STORAGE_BUCKET")
                gcs_url = None

                if not gcs_bucket:
                    logger.warning("LOTSLARP_ARCHIVE_STORAGE_BUCKET not set — skipping cloud upload.")
                    await message.channel.send(
                        "⚠️ Cloud storage is not configured. Archive will be Discord-only."
                    )
                else:
                    await update_status(
                        self._step_status(target_channel.mention, 4, "Uploading to cloud storage..."), force=True
                    )
                    blob_name = f"archives/{datetime.now().strftime('%Y/%m')}/{output_base}.pdf"
                    gcs_url = await self.upload_to_gcs(pdf_file, gcs_bucket, blob_name)

                    if not gcs_url:
                        logger.warning("GCS upload failed — will fall back to Discord attachment if file is small enough.")
                        await message.channel.send(
                            "⚠️ Cloud storage upload failed. Continuing with Discord attachment if the file is small enough."
                        )
                    else:
                        logger.info(f"Uploaded to GCS: {gcs_url}")
                        await update_status(
                            self._step_status(target_channel.mention, 4, f"✅ Uploaded! Preparing Discord attachment..."),
                            force=True,
                        )

                # If GCS is unavailable and the file won't fit in Discord there's nothing to deliver
                if not gcs_url and file_size > DISCORD_LIMIT_BYTES:
                    logger.error("GCS upload failed and file is too large for Discord — cannot deliver archive.")
                    await update_status(
                        "❌ Archive failed: cloud upload failed and the file is too large for a Discord attachment.",
                        force=True,
                    )
                    return

                # If still too large for Discord, try more aggressive compression
                if file_size > DISCORD_LIMIT_BYTES:
                    logger.info("Still too large for Discord. Trying ebook compression...")
                    ebook_pdf = os.path.join(temp_dir, f"{output_base}_ebook.pdf")
                    if await compress_pdf(pdf_file, ebook_pdf, power=3):
                        if os.path.getsize(ebook_pdf) < file_size:
                            pdf_file = ebook_pdf
                            file_size = os.path.getsize(pdf_file)
                            
                    # If STILL too large, try /screen settings (72 dpi)
                    if file_size > DISCORD_LIMIT_BYTES:
                        logger.info("Still too large. Trying maximum compression...")
                        max_pdf = os.path.join(temp_dir, f"{output_base}_max.pdf")
                        if await compress_pdf(pdf_file, max_pdf, power=4):
                            if os.path.getsize(max_pdf) < file_size:
                                pdf_file = max_pdf
                                file_size = os.path.getsize(pdf_file)

                retention_days = int(os.environ.get("LOTSLARP_ARCHIVE_RETENTION_DAYS", "7"))
                deletion_date = datetime.now(timezone.utc) + timedelta(days=retention_days)

                gcs_line = (
                    f"🔗 **Cloud Storage Link:** {gcs_url}\n(Link expires in 7 days or is public depending on bucket settings)\n\n"
                    if gcs_url else
                    "⚠️ No cloud storage link available (upload failed or not configured).\n\n"
                )
                final_msg_content = (
                    f"📂 **Archive for {target_channel.mention} is complete!**\n\n"
                    f"This channel has been set to read-only.\n"
                    f"{gcs_line}"
                    f"⚠️ **Note:** This channel is scheduled to be automatically deleted in **{retention_days} days**."
                )
                
                sent_msg = None
                if file_size <= DISCORD_LIMIT_BYTES:
                    with open(pdf_file, "rb") as f:
                        discord_file = discord.File(f, filename=f"{channel_name}_archive.pdf")
                        sent_msg = await message.channel.send(content=final_msg_content, file=discord_file)
                else:
                    final_msg_content = "⚠️ **File too large for Discord attachment. Please use the link below.**\n\n" + final_msg_content
                    sent_msg = await message.channel.send(content=final_msg_content)

                await status_msg.delete()
                logger.info(f"Archive process finished for {target_channel.name}.")
                
                # SAVE TO FIRESTORE
                if sent_msg:
                    try:
                        doc_ref = self.db.collection('archived_channels').document(str(target_channel.id))
                        # hold_for_approval prevents auto-deletion by cleanup job
                        status = 'hold' if getattr(message, 'hold_for_approval', False) else 'pending'
                        doc_ref.set({
                            'guild_id': target_channel.guild.id,
                            'channel_name': target_channel.name,
                            'archived_at': datetime.now(timezone.utc),
                            'deletion_date': deletion_date,
                            'last_message_url': sent_msg.jump_url,
                            'gcs_url': gcs_url,
                            'status': status,
                        })
                        logger.info(f"Saved archive record for channel {target_channel.id} to Firestore.")
                    except Exception as e:
                        logger.error(f"Failed to save archive record to Firestore: {e}")

                # 4. Send to ST Archive Channel
                archive_channel_id_str = os.environ.get("LOTSLARP_ARCHIVE_CHANNEL_ID")
                if not archive_channel_id_str:
                    archive_channel_id_str = os.environ.get("LOTSLARP_BOT_REPORT_CHANNEL_ID")
                
                if archive_channel_id_str:
                    try:
                        archive_channel_id = int(archive_channel_id_str)
                        archive_channel = client.get_channel(archive_channel_id)
                        if archive_channel:
                             report_content = f"📦 **Archive Report**\n**Source:** {target_channel.guild.name} -> {target_channel.mention}\n**Date:** {datetime.now().strftime('%Y-%m-%d')}"
                             if gcs_url:
                                 report_content += f"\n**GCS Link:** {gcs_url}"
                             
                             if file_size <= DISCORD_LIMIT_BYTES:
                                 with open(pdf_file, "rb") as f:
                                    st_archive_file = discord.File(f, filename=f"{channel_name}_archive.pdf")
                                    await archive_channel.send(content=report_content, file=st_archive_file)
                             else:
                                 await archive_channel.send(content=report_content + "\n⚠️ *File too large for Discord attachment.*")
                             
                             logger.info(f"Archive report sent to ST Archive Channel ({archive_channel.name}).")
                        else:
                            logger.warning(f"Could not find ST Archive Channel with ID {archive_channel_id}")
                    except ValueError:
                        logger.error(f"Invalid LOTSLARP_ARCHIVE_CHANNEL_ID: {archive_channel_id_str}")
                    except Exception as e:
                        logger.error(f"Failed to send to ST Archive Channel: {e}")

            except Exception as e:
                logger.error(f"Failed to upload PDF: {e}", exc_info=True)
                try:
                    await status_msg.edit(content="❌ Failed to upload PDF (possibly due to size or connection). Check logs.")
                except:
                    pass

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

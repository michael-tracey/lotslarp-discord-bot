import os
import logging
import sqlite3
import pathlib
import discord
import asyncio
import importlib
import tracemalloc
import linecache
import re

from datetime import datetime
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import google.generativeai as genai
from google.cloud import firestore  # Add Firestore import
from modules import pdf_generator
from modules.utils import smart_chunk_message
from modules.channel_summarize import handle_share_interaction
from modules.summary_reminder import handle_remind_interaction
from modules.lore import LoreManager
from modules.monthly_summary import check_monthly_trigger
from modules.archive_cleanup import cleanup_old_archives

# --- Health Monitoring ---
def periodic_health_check():
    """Periodic health check to keep the container alive and monitor status."""
    logger.info("🔄 Periodic health check - Bot is alive and monitoring")

def connection_keepalive():
    """Keepalive function to prevent Cloud Run from scaling to zero."""
    logger.info("💓 Keepalive - Maintaining Cloud Run instance")

last_snapshot = None

def log_memory_usage():
    global last_snapshot
    
    if not tracemalloc.is_tracing():
        logger.warning("Tracemalloc is not running, can't log memory usage.")
        return
        
    current_snapshot = tracemalloc.take_snapshot()
    
    if last_snapshot:
        top_stats = current_snapshot.compare_to(last_snapshot, 'lineno')
        
        total_growth = sum(stat.size_diff for stat in top_stats)
        if total_growth > 0:
            logger.info(f"--- Memory Usage Growth Detected (Total: {total_growth / 1024:.2f} KiB) ---")
            for i, stat in enumerate(top_stats[:10], 1):
                frame = stat.traceback[0]
                logger.info(f"#{i}: {frame.filename}:{frame.lineno}: {stat.size_diff / 1024:.2f} KiB growth")
                try:
                    logger.info(f"    Line: {linecache.getline(frame.filename, frame.lineno).strip()}")
                except Exception:
                    logger.info("    (Could not retrieve line content)")
        else:
            logger.info("No significant memory growth since last check.")

    last_snapshot = current_snapshot


# --- End Memory Profiling ---

# Load environment variables from .env file
load_dotenv()

# --- HTTP Health Check Server Imports ---
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from http.server import HTTPServer
import threading

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
# --- End HTTP Health Check Server Imports ---

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

# Set specific loggers to reduce noise, but allow INFO/DEBUG for main bot activities
logging.getLogger('discord').setLevel(logging.INFO)  # Show INFO from discord.py
logging.getLogger('discord.gateway').setLevel(logging.INFO) # Show INFO from gateway for connection status
logging.getLogger('discord.client').setLevel(logging.INFO)  # Show INFO from client
logging.getLogger('discord.state').setLevel(logging.INFO)  # Show INFO from state
logging.getLogger('apscheduler').setLevel(logging.INFO)  # Reduce scheduler noise
logging.getLogger('apscheduler.executors.default').setLevel(logging.ERROR)  # Only errors from executors
logging.getLogger('apscheduler.scheduler').setLevel(logging.INFO)  # Allow scheduler info messages


# --- Health Check HTTP Server ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health' or self.path == '/': # Respond to / or /health
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"BotContainerHealthy") # Simple health response
            logger.info("Health check GET request successful.")
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"NotFound")
            logger.warning(f"Health check GET request to unknown path: {self.path}")

    def log_message(self, format, *args):
        # Quieten the HTTP server's logging or integrate with your main logger
        logger.debug("Health check server: %s" % (format % args))


def run_health_server(bot_client_for_check: discord.Client = None): # Optional: pass bot client
    port = int(os.environ.get("PORT", 8080))
    server_address = ('0.0.0.0', port) # Listen on all interfaces
    
    httpd = ThreadingHTTPServer(server_address, HealthCheckHandler)
    logger.info(f"Health check HTTP server starting on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Health check server received KeyboardInterrupt.")
    except Exception as e:
        logger.error(f"Health check server crashed: {e}", exc_info=True)
    finally:
        httpd.server_close()
        logger.info("Health check server stopped.")


async def process_command(client: discord.Client, message: discord.Message, command_map: dict):
    # ... (your existing process_command logic - no changes needed here for health checks)
    command_name_for_log = "unknown_command" 
    try:
        parts = message.content[1:].split()
        command_name = parts[0].lower() if parts else ""
        command_name_for_log = command_name

        logger.info(f"Processing command: '{command_name}' from {message.author.name}")
        logger.info(f"Checking command_map for '{command_name}'. Current registered commands: {list(command_map.keys())}")

        if command_name in command_map:
            command_instance = command_map[command_name]
            
            if asyncio.iscoroutinefunction(command_instance.run):
                result = await command_instance.run(client, message)
            else:
                result = command_instance.run(client, message)

            if result is None:
                logger.info(f"Command '{command_name}' returned None. No channel message needed.")
                return

            if isinstance(result, list):
                if not result:
                    logger.info(f"Command '{command_name}' returned an empty list of chunks.")
                    return
                for i, chunk in enumerate(result):
                    if chunk and str(chunk).strip():
                        await message.channel.send(str(chunk), suppress_embeds=True)
                        logger.info(f"Sent chunk {i+1}/{len(result)} for command '{command_name}'. Length: {len(str(chunk))}")
                        await asyncio.sleep(0.1) # Add a small delay to avoid rate limits
            
            elif isinstance(result, str):
                stripped_result = result.strip()
                if not stripped_result:
                    logger.info(f"Command '{command_name}' returned an empty string.")
                    return
                
                if len(stripped_result) > 1950: 
                    logger.warning(f"String from '{command_name}' exceeded 1950 chars ({len(stripped_result)}), re-chunking in discord_bot.py using smart_chunk_message.")
                    chunks = smart_chunk_message(stripped_result, 1950)
                    for i, chunk in enumerate(chunks):
                        await message.channel.send(chunk, suppress_embeds=True)
                        logger.info(f"Sent re-chunked part {i+1}/{len(chunks)}. Length: {len(chunk)}")
                        await asyncio.sleep(0.1) # Add a small delay to avoid rate limits
                else:
                    await message.channel.send(stripped_result, suppress_embeds=True)
            
            else: 
                logger.warning(f"Command '{command_name}' returned an unexpected type: {type(result)}. Converting to string.")
                try:
                    str_result = str(result).strip()
                    if not str_result:
                        logger.info(f"Command '{command_name}' (type {type(result)}) converted to an empty string.")
                        return

                    if len(str_result) > 1950:
                        logger.warning(f"Converted string from '{command_name}' (type {type(result)}) exceeded 1950 chars ({len(str_result)}), chunking.")
                        chunks = smart_chunk_message(str_result, 1950)
                        for i, chunk in enumerate(chunks):
                            await message.channel.send(chunk, suppress_embeds=True)
                            logger.info(f"Sent chunked part {i+1}/{len(chunks)} from converted type. Length: {len(chunk)}")
                            await asyncio.sleep(0.1) # Add a small delay to avoid rate limits
                    else:
                        await message.channel.send(str_result, suppress_embeds=True)
                except Exception as send_exc:
                    logger.error(f"Failed to send result of type {type(result)} for command '{command_name}': {send_exc}", exc_info=True)
                    await message.reply("**An error occurred trying to display the command's result.**", mention_author=False)
                    return
        else:
            logger.info(f"Command '{command_name}' not found in command_map.")

    except Exception as e:
        logger.error(f"Error processing command '{command_name_for_log}': {e}", exc_info=True)
        try:
            await message.reply("**An error occurred while processing the command.**", mention_author=False)
        except Exception as reply_exc:
            logger.error(f"Failed to send error reply to channel: {reply_exc}")


def get_app_db_path():
    db_name = os.environ.get("LOTSLARP_DISCORD_BOT_APP_DB", "huh.db")
    db_path = os.path.abspath(db_name)
    logger.info(f"Constructed absolute path for content DB: '{db_path}'")
    return os.path.abspath(db_path)


class MyClient(discord.Client):
    def __init__(self, command_map, summary_module, scheduler, status_command, voice_module=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.command_map = command_map
        self.summary_module = summary_module
        self.voice_module = voice_module
        self.scheduler = scheduler
        self.status_command = status_command
        self.summary_role_name = os.environ.get("LOTSLARP_DISCORD_BOT_SUMMARY_ROLE_NAME")
        try:
            channel_id_str = os.environ.get("LOTSLARP_DISCORD_BOT_DIGEST_CHANNEL_ID", "0")
            # Strip quotes and whitespace, then convert to int
            self.digest_channel_id = int(channel_id_str.strip().strip('"').strip("'"))
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid DIGEST_CHANNEL_ID value: '{os.environ.get('LOTSLARP_DISCORD_BOT_DIGEST_CHANNEL_ID')}'. Using 0 as default. Error: {e}")
            self.digest_channel_id = 0
            
        # New User Setup Configuration
        try:
            cat_id_str = os.environ.get("LOTSLARP_BOT_CREATE_NEW_USER_CATEGORY", "")
            self.new_user_category_id = int(cat_id_str.strip()) if cat_id_str.strip() else None
        except ValueError:
            logger.error(f"Invalid LOTSLARP_BOT_CREATE_NEW_USER_CATEGORY: {cat_id_str}")
            self.new_user_category_id = None
            
        self.new_user_message_template = os.environ.get("LOTSLARP_BOT_NEW_USER_MESSAGE_TEMPLATE", 
            "Welcome {user_mention}! :wave:\n\n"
            "This is your **personal channel** with the Storytellers. Use this space to:\n"
            "• Discuss character concepts\n"
            "• Ask rule questions\n"
            "• Chat privately with staff\n\n"
            "We'll rename this channel to your character's name once you're approved!\n\n"
            "(You can also email us at storytellers@lotslarp.org, but this channel is usually faster.)"
        )
        
        # Additional roles to add to the new user channel
        additional_roles_str = os.environ.get("LOTSLARP_BOT_NEW_USER_CHANNEL_ADDITIONAL_ROLES", "Tupperbox,Carl-bot")
        self.new_user_additional_roles = [r.strip() for r in additional_roles_str.split(",") if r.strip()]

        logger.info("MyClient initialized.")

    async def on_voice_state_update(self, member, before, after):
        logger.debug(f"Event: on_voice_state_update for {member.display_name}")
        if self.voice_module:
            await self.voice_module.on_voice_state_update(member, before, after)
        else:
            logger.warning("Voice module not loaded, ignoring voice state update.")

    async def create_intro_channel(self, member):
        """Helper to create the intro channel for a member."""
        if not self.new_user_category_id:
            return

        logger.info(f"Processing channel creation for member {member.name}...")
        guild = member.guild
        category = guild.get_channel(self.new_user_category_id)
        
        if not category or not isinstance(category, discord.CategoryChannel):
            logger.error(f"Target category ID {self.new_user_category_id} not found or is not a category.")
            return

        # Sanitize channel name
        # 1. Lowercase
        # 2. Spaces to hyphens
        # 3. Remove illegal chars (keep a-z, 0-9, -, _)
        # 4. Collapse multiple hyphens
        channel_name = member.name.lower().replace(" ", "-")
        channel_name = re.sub(r"[^a-z0-9\-_]", "", channel_name)
        channel_name = re.sub(r"-+", "-", channel_name).strip("-")
        
        # Fallback if name becomes empty
        if not channel_name:
            channel_name = f"user-{member.id}"

        # Create channel
        try:
            # Check if channel already exists in category
            existing_channel = discord.utils.get(category.text_channels, name=channel_name)
            if existing_channel:
                logger.info(f"Channel {channel_name} already exists. Skipping creation.")
                new_channel = existing_channel
            else:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    member: discord.PermissionOverwrite(read_messages=True),
                    guild.me: discord.PermissionOverwrite(read_messages=True)
                }
                
                # Add additional roles
                for role_name in self.new_user_additional_roles:
                    role = discord.utils.get(guild.roles, name=role_name)
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(read_messages=True)
                    else:
                        logger.warning(f"Role '{role_name}' not found in guild, skipping for channel creation.")

                new_channel = await guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    overwrites=overwrites,
                    reason=f"Setup channel for member {member.name}"
                )
                logger.info(f"Created channel {new_channel.name} (ID: {new_channel.id})")

                # Send First Message
                if self.new_user_message_template:
                    msg_content = self.new_user_message_template.replace('\\n', '\n').format(
                        user_mention=member.mention,
                        user_name=member.name,
                        channel_mention=new_channel.mention,
                        guild_name=guild.name
                    )
                    await new_channel.send(msg_content)
                    
        except Exception as e:
            logger.error(f"Failed to setup new user channel for {member.name}: {e}", exc_info=True)

    async def on_member_join(self, member):
        """
        Triggered when a member joins the guild.
        """
        logger.info(f"Member {member.name} joined guild {member.guild.name}. Checking for channel creation...")
        await self.create_intro_channel(member)

    async def on_member_update(self, before, after):
        """
        Monitor member updates to detect when a member completes screening (Apply to Join).
        Transition: before.pending=True -> after.pending=False
        """
        if not self.new_user_category_id:
            return

        # Check if the member transitioned from pending=True to pending=False
        if before.pending and not after.pending:
            logger.info(f"Member {after.name} completed screening! Ensuring channel exists...")
            await self.create_intro_channel(after)

    async def on_ready(self):
        # Set Discord logging levels after client is ready
        logging.getLogger('discord').setLevel(logging.WARNING)
        logging.getLogger('discord.gateway').setLevel(logging.ERROR)
        logging.getLogger('discord.client').setLevel(logging.WARNING)
        logging.getLogger('discord.state').setLevel(logging.WARNING)
        
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Bot is in {len(self.guilds)} guilds:")
        for guild in self.guilds:
            logger.info(f"  - Guild: {guild.name} (ID: {guild.id})")
        
        # Run startup checks now that the event loop is active
        await self.run_startup_checks()
        
        self.scheduler.start()
        logger.info("Scheduler started.")

    async def on_disconnect(self):
        logger.warning("Discord connection lost! Bot disconnected.")

    async def on_resumed(self):
        logger.info("Discord connection resumed successfully.")

    async def on_connect(self):
        logger.info("Discord connection established.")

    async def on_shard_disconnect(self, shard_id):
        logger.warning(f"Shard {shard_id} disconnected.")

    async def on_shard_resumed(self, shard_id):
        logger.info(f"Shard {shard_id} resumed.")

    async def run_startup_checks(self):
        """Runs health checks at startup and logs the results."""
        logger.info("--- Running Startup Health Checks ---")
        
        # 1. List available models
        logger.info("--- Listing available Gemini models ---")
        try:
            models_found = []
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    models_found.append(m.name)
            if models_found:
                for model_name in models_found:
                    logger.info(f"Model found: {model_name}")
            else:
                logger.warning("No models supporting 'generateContent' found.")
        except Exception as e:
            logger.error(f"Could not list models: {e}")
        logger.info("------------------------------------")

        # 2. Perform DB and AI tests
        if self.status_command:
            db_status = await self.status_command._test_db()
            ai_status = await self.status_command._test_ai()
            logger.info(f"Database Status: {db_status}")
            logger.info(f"Gemini AI Status: {ai_status}")
        else:
            logger.error("Status command not initialized, cannot run startup checks.")
        logger.info("--- Startup Health Checks Complete ---")

    async def on_message(self, message: discord.Message):
        if message.author == self.user:
            return
        
        # Log message details without printing the entire content
        if message.guild:
            logger.debug(f"Received message from Guild: {message.guild.name}, Channel: {message.channel.name}, Author: {message.author.name}")
        else:
            logger.debug(f"Received DM message from Author: {message.author.name}")

        # Cache message if it contains a mention of the summary role
        if self.summary_role_name and message.role_mentions:
            mentioned_role_names = [role.name for role in message.role_mentions]
            
            # --- Detailed Debugging Log ---
            logger.info("--- Role Mention Detected ---")
            logger.info(f"Message Content: {message.content}")
            logger.info(f"Target Role Name: '{self.summary_role_name}'")
            logger.info(f"message.role_mentions: {message.role_mentions}")
            logger.info(f"Mentioned Role Names: {mentioned_role_names}")
            # --- End Debugging Log ---

            if self.summary_role_name in mentioned_role_names:
                logger.info(f"SUCCESS: Found summary mention for role '{self.summary_role_name}' in message {message.id}")
                await self.summary_module.cache_message(message)
            else:
                logger.warning(f"FAILURE: Role mention(s) detected, but '{self.summary_role_name}' was not found in the mentioned roles.")
        
        if message.content.startswith("/"):
            await process_command(self, message, self.command_map)
        else:
            if message.guild:
                logger.debug(f"Ignoring non-command message from Guild: {message.guild.name}, Channel: {message.channel.name}, Author: {message.author.name}")
            else:
                logger.debug(f"Ignoring non-command DM message from Author: {message.author.name}")

    async def on_interaction(self, interaction: discord.Interaction):
        """Handles interactions such as button clicks."""
        if interaction.type == discord.InteractionType.component:
            custom_id = interaction.data.get('custom_id', '')
            if custom_id.startswith('share_summary:'):
                # We access firestore via the summary_module if it exists
                firestore_client = None
                if self.summary_module:
                    firestore_client = self.summary_module.db
                
                if firestore_client:
                    await handle_share_interaction(interaction, firestore_client)
                else:
                    await interaction.response.send_message("❌ Database connection unavailable.", ephemeral=True)
            elif custom_id.startswith('remind_summary:'):
                await handle_remind_interaction(interaction)


async def send_digest_pdf(client: discord.Client, summary_module, gemini_model, lore_manager=None, force=False):
    logger.info(f"Starting digest check... (Force: {force})")
    messages_data = await summary_module.get_messages_for_digest()
    
    should_send = False
    
    if not messages_data:
        logger.info("No messages to summarize. Skipping digest.")
        return

    if force:
        logger.info("Digest triggered manually via /digest-now (Force=True).")
        should_send = True
    else:
        # --- Digest Threshold Logic ---
        try:
            max_messages = int(os.environ.get("LOTSLARP_BOT_MAX_MESSAGES_BEFORE_DIGEST", 10))
            max_time_hours = int(os.environ.get("LOTSLARP_BOT_MAX_TIME_BEFORE_DIGEST", 72))
        except ValueError:
            logger.error("Invalid digest threshold environment variables. Using defaults (10 msgs, 72 hours).")
            max_messages = 10
            max_time_hours = 72

        # 1. Check Message Count
        if len(messages_data) >= max_messages:
            logger.info(f"Digest triggered: Message count ({len(messages_data)}) >= Threshold ({max_messages})")
            should_send = True
        
        # 2. Check Time Since First Message (Oldest)
        # messages_data is ordered by timestamp ascending, so index 0 is oldest.
        # Format: [..., ..., ..., ..., ..., ..., ..., ..., timestamp]
        elif len(messages_data) > 0:
            first_msg_timestamp = messages_data[0][8] # Index 8 is timestamp
            if first_msg_timestamp:
                # Ensure timestamp is offset-naive UTC or handle offsets. 
                # Firestore timestamps usually have tzinfo. discord.py creates tz-aware (UTC).
                # We'll use datetime.now(timezone.utc) if possible.
                now = datetime.now(first_msg_timestamp.tzinfo) if first_msg_timestamp.tzinfo else datetime.utcnow()
                
                time_diff = now - first_msg_timestamp
                hours_passed = time_diff.total_seconds() / 3600
                
                if hours_passed >= max_time_hours:
                    logger.info(f"Digest triggered: Time since oldest message ({hours_passed:.2f}h) >= Threshold ({max_time_hours}h)")
                    should_send = True
                else:
                    logger.info(f"Digest threshold not met. Messages: {len(messages_data)}/{max_messages}, Oldest: {hours_passed:.2f}h/{max_time_hours}h ago.")
            else:
                logger.warning("Oldest message has no timestamp. Skipping time check.")

    if not should_send:
        return

    logger.info("Generating and sending digest...")

    messages_for_pdf = []
    plain_text_for_summary = []
    message_ids_to_mark_sent = []
    total_message_length = 0
    unique_authors = set()
    
    for row in messages_data:
        # Deconstruct the list returned by the summary module
        # Expected format: [channel_id, guild_id, author_name, message_content, message_url, doc_id, author_display_name, channel_name, timestamp]
        channel_id = row[0]
        guild_id = row[1]
        author_name = row[2]
        message_content = row[3]
        message_url = row[4]
        msg_id = row[5] # This is now the Firestore document ID (string)
        author_display = row[6]
        channel_name_str = row[7]
        msg_timestamp = row[8]
        
        guild = client.get_guild(guild_id)
        channel = client.get_channel(channel_id)
        guild_name = guild.name if guild else "Unknown Server"
        channel_name = channel.name if channel else (channel_name_str or "Unknown Channel")
        
        # Human-readable timestamp
        ts_str = msg_timestamp.strftime('%m/%d %H:%M') if msg_timestamp else "??:??"

        messages_for_pdf.append({
            "guild_name": guild_name,
            "channel_name": channel_name,
            "author_name": author_name,
            "author_display_name": author_display,
            "message_content": message_content,
            "message_url": message_url,
            "timestamp": ts_str
        })
        plain_text_for_summary.append(f"[{ts_str}] Server: {guild_name}, Channel: {channel_name}, Author: {author_display or author_name}\n{message_content}\n")
        message_ids_to_mark_sent.append(msg_id)
        
        # Calculate statistics
        total_message_length += len(message_content)
        unique_authors.add(author_name)
    
    # Prepare message statistics
    # ... (stats logic unchanged)
    message_count = len(messages_data)
    avg_message_length = total_message_length // message_count if message_count > 0 else 0
    message_stats = [
        f"Total Messages: {message_count}",
        f"Unique Authors: {len(unique_authors)}",
        f"Average Message Length: {avg_message_length} characters",
        f"Total Content Length: {total_message_length} characters"
    ]

    executive_summary = ""
    if gemini_model:
        def _generate_summary_sync(prompt):
            try:
                # Use the synchronous method for running in a separate thread
                response = gemini_model.generate_content(prompt)
                logger.info("Successfully generated executive summary from Gemini.")
                return response.text
            except Exception as e:
                logger.error(f"Failed to generate summary from Gemini: {e}", exc_info=True)
                return "Error generating summary."

        try:
            # RAG Integration
            all_text = "\n".join(plain_text_for_summary)
            lore_context = ""
            if lore_manager:
                try:
                    lore_context = await lore_manager.get_relevant_lore(all_text)
                    if lore_context:
                        logger.info("Injected relevant lore into digest prompt.")
                except Exception as e:
                    logger.error(f"Error fetching lore for digest: {e}")

            default_prompt = "You are an AI assistant tasked with creating a high-level executive summary of Discord conversations. Analyze the following collection of messages and provide a concise summary. The summary should adhere to these rules: 1. Start with a one-sentence overview of the general topics discussed. 2. Use bullet points to highlight key decisions, action items, or significant points of interest. 3. Group related topics together under a common sub-heading if the conversation covers multiple distinct subjects. 4. Maintain a neutral, professional tone. 5. Do not invent or infer information that isn't present in the messages. 6. The summary should be no more than 4 paragraphs in total. Here are the messages to summarize:"
            prompt_instructions = os.environ.get("LOTSLARP_DISCORD_BOT_GEMINI_PROMPT", default_prompt)
            prompt = f"{prompt_instructions}\n{lore_context}\n" + all_text
            
            # Run the synchronous generation in a separate thread
            executive_summary = await asyncio.to_thread(_generate_summary_sync, prompt)

        except Exception as e:
            # This catches errors from the to_thread call itself, though the inner function handles its own.
            logger.error(f"An error occurred while trying to run summary generation in a thread: {e}", exc_info=True)
            executive_summary = "Error: Summary generation process failed."

    # Get cadence name for titles and create date range
    cadence_name = os.environ.get("LOTSLARP_DISCORD_BOT_DIGEST_CADENCE_NAME", "Daily")
    pdf_title = f"{cadence_name} Summary Digest"
    
    # Create appropriate date range based on cadence
    current_date = datetime.utcnow()
    if cadence_name.lower() == "daily":
        date_range = f"Day of {current_date.strftime('%B %d, %Y')}"
    elif cadence_name.lower() == "weekly":
        date_range = f"Week ending {current_date.strftime('%B %d, %Y')}"
    else:
        date_range = f"Period ending {current_date.strftime('%B %d, %Y')}"

    # Generate PDF in a separate thread to avoid blocking the event loop
    pdf_path = f"/tmp/digest_{current_date.strftime('%Y-%m-%d')}.pdf"
    pdf_success = await asyncio.to_thread(
        pdf_generator.create_digest_pdf,
        pdf_path, 
        executive_summary, 
        messages_for_pdf, 
        title=pdf_title,
        date_range=date_range,
        message_stats=message_stats
    )

    if not pdf_success:
        logger.error("Could not generate PDF, aborting digest send.")
        return

    # Send PDF to channel
    channel_id = client.digest_channel_id
    if not channel_id:
        logger.error("LOTSLARP_DISCORD_BOT_DIGEST_CHANNEL_ID not set. Cannot send PDF.")
        return

    channel = client.get_channel(channel_id)
    if not channel:
        logger.error(f"Cannot find channel with ID {channel_id}.")
        return

    try:
        # Build Message Index
        message_index = "\n**Message Index:**\n"
        for row in messages_data:
            # row: [channel_id, guild_id, author_name, message_content, message_url, doc_id, author_display_name, channel_name, timestamp]
            url_idx = row[4]
            author_display = row[6] or row[2] # Fallback to author_name if display name missing
            channel_name = row[7] or "Unknown Channel"
            ts_idx = row[8]
            ts_idx_str = ts_idx.strftime('%m/%d %H:%M') if ts_idx else "??:??"
            
            message_index += f"• `{ts_idx_str}` [#{channel_name}]({url_idx}) - {author_display}\n"

        # Prepare Discord message with summary, index, and statistics
        discord_message = f"**{pdf_title} - {date_range}**\n\n"
        
        discord_message += "**Storyteller Summary:**\n"
        discord_message += executive_summary + "\n"

        discord_message += message_index + "\n"

        discord_message += "**Message Statistics:**\n"
        for stat in message_stats:
            discord_message += f"• {stat}\n"
        
        # Use smart chunking
        chunks = smart_chunk_message(discord_message, 1950)

        with open(pdf_path, "rb") as f:
            pdf_file = discord.File(f, filename=os.path.basename(pdf_path))
            
            # Send chunks
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1:
                    # Last chunk gets the file
                    await channel.send(content=chunk, file=pdf_file)
                else:
                    await channel.send(content=chunk)
                    await asyncio.sleep(0.5)

        logger.info(f"Successfully sent PDF digest to channel {channel.name}.")
        # Mark messages as sent ONLY after successful sending
        await summary_module.mark_messages_as_sent(message_ids_to_mark_sent)
        logger.info(f"Marked {len(message_ids_to_mark_sent)} messages as sent.")
    except discord.errors.Forbidden:
        logger.error(f"Bot does not have permissions to send messages or files in channel {channel.name}.")
    except Exception as e:
        logger.error(f"Failed to send PDF digest: {e}", exc_info=True)
    finally:
        # Clean up the generated PDF file
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
            logger.info(f"Removed temporary PDF file: {pdf_path}")


async def run_stale_channels_job(client: discord.Client, summary_reminder_instance):
    """Job to run the automated stale channels scan."""
    output_channel = client.get_channel(summary_reminder_instance.output_channel_id)
    if output_channel:
        logger.info("Running scheduled stale channels scan...")
        await summary_reminder_instance.execute_auto_scan(client, output_channel)
    else:
        logger.error(f"Cannot run stale channels job: Output channel {summary_reminder_instance.output_channel_id} not found.")


def setup_bot():
    logger.info("Starting Discord bot core logic setup...")
    app_db_path = get_app_db_path()

    intents = discord.Intents.default()
    intents.message_content = True 
    intents.members = True 
    intents.guilds = True

    command_classes = {}
    module_names_to_load = ["throw", "huh", "summary", "pdf_generator", "lotslarp"]
    logger.info(f"Attempting to load command modules: {module_names_to_load}")
    for module_name_str in module_names_to_load:
        full_module_path = f"modules.{module_name_str}"
        logger.info(f"Loading module: {full_module_path}")
        try:
            module = importlib.import_module(full_module_path)
            logger.info(f"Successfully imported module object for {full_module_path}: {module}")
            
            # Capitalize snake_case to CamelCase for class name
            expected_class_name = ''.join(word.capitalize() for word in module_name_str.split('_'))

            logger.info(f"For module {module_name_str}, expecting class: {expected_class_name} (or 'Command')")

            found_class = None
            if hasattr(module, expected_class_name):
                logger.info(f"Found attribute '{expected_class_name}' in {module_name_str}.")
                potential_class = getattr(module, expected_class_name)
                if isinstance(potential_class, type):
                    command_classes[module_name_str] = potential_class
                    found_class = expected_class_name
                    logger.info(f"Successfully loaded and validated class '{expected_class_name}' from {full_module_path}.")
                else:
                    logger.warning(f"Attribute '{expected_class_name}' in {module_name_str} is not a class (type: {type(potential_class)}).")
            
            if not found_class and hasattr(module, "Command"): 
                logger.info(f"Did not find '{expected_class_name}', checking for generic 'Command' in {module_name_str}.")
                potential_class = getattr(module, "Command")
                if isinstance(potential_class, type):
                    command_classes[module_name_str] = potential_class
                    found_class = "Command"
                    logger.info(f"Successfully loaded and validated generic 'Command' class from {full_module_path}.")
                else:
                    logger.warning(f"Attribute 'Command' in {module_name_str} is not a class (type: {type(potential_class)}).")
            
            if not found_class:
                logger.warning(f"Module {full_module_path} loaded, but no suitable command class ('{expected_class_name}' or 'Command') found or validated.")

        except ImportError as ie:
            logger.error(f"ImportError when loading module {full_module_path}: {ie}", exc_info=True)
        except Exception as e:
            logger.error(f"An unexpected error occurred while loading module {full_module_path}: {e}", exc_info=True)

    if not command_classes:
        logger.error("CRITICAL: No command classes were loaded. Bot will not have commands.")
    else:
        logger.info(f"Finished loading command classes. Found: {list(command_classes.keys())}")

    gemini_api_key = os.environ.get("LOTSLARP_DISCORD_BOT_GEMINI_API_KEY")
    gemini_model_name = os.environ.get("LOTSLARP_DISCORD_BOT_GEMINI_MODEL", "gemini-pro") # Default to gemini-pro
    gemini_model = None
    if gemini_api_key:
        genai.configure(api_key=gemini_api_key)
        gemini_model = genai.GenerativeModel(gemini_model_name)
        logger.info(f"Gemini API key found and model '{gemini_model_name}' initialized.")
    else:
        logger.warning("LOTSLARP_DISCORD_BOT_GEMINI_API_KEY not found. Summary generation will be disabled.")

    # Initialize Firestore client
    try:
        firestore_client = firestore.Client()
        logger.info("Successfully initialized Firestore client.")
    except Exception as e:
        logger.critical(f"Failed to initialize Firestore client: {e}", exc_info=True)
        firestore_client = None

    # Initialize LoreManager
    lore_manager = None
    if firestore_client:
        lore_manager = LoreManager(firestore_client)
        # Prefetch cache in background? Or let it lazy load.
        # Lazy load is fine, but let's log it.
        logger.info("LoreManager initialized.")


    command_map_instances = {}
    summary_module_instance = None
    voice_module_instance = None
    status_command_instance = None
    summary_reminder_instance = None # To hold the instance for scheduling
    for name, Cls in command_classes.items():
        try:
            instance = None
            if name == "huh":
                instance = Cls(database_filename=get_app_db_path())
            elif name == "summary":
                if firestore_client:
                    summary_module_instance = Cls(db_client=firestore_client)
                else:
                    logger.error("Firestore client not available, cannot instantiate Voice module.")
                    continue
            elif name == "lotslarp":
                instance = Cls(
                    db_path=app_db_path, 
                    gemini_model=gemini_model,
                    firestore_client=firestore_client,
                    summary_module=summary_module_instance,
                    pdf_gen=pdf_generator,
                    lore_manager=lore_manager,
                    send_digest_callback=send_digest_pdf
                )
                # Expose the internal status handler for startup checks
                status_command_instance = instance.status_handler
                # Expose stale handler for scheduler
                summary_reminder_instance = instance.stale_handler
            elif name == "pdf_generator":
                continue # Not a command
            else:
                instance = Cls() 

            if instance:
                # Use the instance's `name` attribute if it exists, otherwise use the module name
                command_name = getattr(instance, 'name', name)
                command_map_instances[command_name] = instance
                logger.info(f"Successfully instantiated and mapped command: '{command_name}' (from module: {name})")
            else:
                logger.warning(f"Module '{name}' did not produce an instance.")

        except TypeError as te: # Catch specific TypeError for __init__
            logger.error(f"TypeError instantiating command {name} from class {Cls}: {te}. Check __init__ signature.", exc_info=True)
        except Exception as e:
            logger.error(f"Failed to instantiate command {name} from class {Cls}: {e}", exc_info=True)

    if not command_map_instances:
        logger.error("CRITICAL: No commands were successfully instantiated. Bot will not have commands.")
    else:
        logger.info(f"Bot setup complete. Registered commands: {list(command_map_instances.keys())}")
    
    # Create the client and scheduler
    scheduler = AsyncIOScheduler()
    client = MyClient(
        command_map=command_map_instances, 
        summary_module=summary_module_instance,
        voice_module=voice_module_instance, 
        scheduler=scheduler,
        status_command=status_command_instance,
        intents=intents
    )
    
    # Schedule jobs
    if summary_module_instance:
        # Cron schedule for checking digest thresholds (default hourly)
        cron_schedule = os.environ.get("LOTSLARP_DISCORD_BOT_DIGEST_CRON", "0 * * * *") 
        try:
            trigger = CronTrigger.from_crontab(cron_schedule, timezone="UTC")
            scheduler.add_job(send_digest_pdf, trigger=trigger, args=[client, summary_module_instance, gemini_model, lore_manager])
            logger.info(f"Scheduled digest check with cron schedule: '{cron_schedule}' UTC")
        except ValueError as e:
            logger.error(f"Invalid cron string '{cron_schedule}'. Defaulting to every hour. Error: {e}")
            scheduler.add_job(send_digest_pdf, 'interval', minutes=60, args=[client, summary_module_instance, gemini_model, lore_manager])

        scheduler.add_job(summary_module_instance.delete_old_messages, 'cron', hour=0)

        # Schedule Monthly Summary Check (Daily at 14:00 UTC)
        scheduler.add_job(check_monthly_trigger, 'cron', hour=14, args=[client, summary_module_instance, gemini_model, pdf_generator, lore_manager])
        logger.info("Scheduled monthly summary trigger check for daily at 14:00 UTC.")
    
    if voice_module_instance:
        scheduler.add_job(voice_module_instance.cleanup_old_logs, 'cron', hour=0)
        logger.info("Scheduled voice log cleanup for daily at 00:00.")
    
    # Schedule Archive Cleanup (Daily)
    scheduler.add_job(cleanup_old_archives, 'cron', hour=0, args=[client, firestore_client])
    logger.info("Scheduled stale archive channel cleanup for daily at 00:00.")
        
    # Schedule Stale Channels Scan
    if summary_reminder_instance:
        stale_cron = os.environ.get("LOTSLARP_BOT_STALE_CHANNELS_CRON")
        if stale_cron:
            try:
                trigger = CronTrigger.from_crontab(stale_cron, timezone="UTC")
                scheduler.add_job(run_stale_channels_job, trigger=trigger, args=[client, summary_reminder_instance])
                logger.info(f"Scheduled stale channels scan with cron schedule: '{stale_cron}' UTC")
            except ValueError as e:
                logger.error(f"Invalid stale channels cron string '{stale_cron}'. Job not scheduled. Error: {e}")
        else:
            logger.info("No cron schedule set for stale channels (LOTSLARP_BOT_STALE_CHANNELS_CRON). Skipping.")

    # Schedule health monitoring and keepalive jobs
    scheduler.add_job(periodic_health_check, 'interval', minutes=30)  # Health check every 30 minutes
    scheduler.add_job(connection_keepalive, 'interval', minutes=10)   # Keepalive every 10 minutes
    scheduler.add_job(log_memory_usage, 'interval', minutes=60)       # Reduced memory logging

    return client


async def main():
    logger.info("Application entry point reached.")
    
    # Start tracemalloc for memory profiling
    tracemalloc.start()
    logger.info("Tracemalloc started.")
    
    # Run the health check server in a separate thread
    health_server_thread = threading.Thread(target=run_health_server, daemon=True)
    health_server_thread.start()
    logger.info("Health check server thread initiated.")

    # Setup and connect the Discord client
    client = setup_bot()
    token = os.environ.get("LOTSLARP_DISCORD_BOT_DISCORD_TOKEN")
    if not token:
        logger.critical("LOTSLARP_DISCORD_BOT_DISCORD_TOKEN not found. Bot cannot start.")
        return

    # Retry logic for Discord connection
    max_retries = 3
    retry_delay = 30  # seconds
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Starting Discord client (attempt {attempt + 1}/{max_retries})")
            async with client:
                await client.start(token)
            break  # If we get here, connection was successful
        except discord.errors.LoginFailure:
            logger.critical("Login to Discord failed. Please check your token.", exc_info=True)
            break  # Don't retry login failures
        except Exception as e:
            logger.error(f"Discord client error (attempt {attempt + 1}/{max_retries}): {e}", exc_info=True)
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logger.critical("Max retries reached. Bot startup failed.")
        finally:
            logger.info("Discord client connection ended.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt. Shutting down.")
    except Exception as e:
        logger.critical(f"A critical error in the main asyncio loop: {e}", exc_info=True)
    finally:
        logger.info("Application main thread finished or bot logic exited.")

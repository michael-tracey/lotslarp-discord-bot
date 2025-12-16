import os
import logging
import sqlite3
import pathlib
import discord
import asyncio
import importlib
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import google.generativeai as genai
from modules import pdf_generator

# --- HTTP Health Check Server Imports ---
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
# --- End HTTP Health Check Server Imports ---

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)


# --- Health Check HTTP Server ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health' or self.path == '/': # Respond to / or /health
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"BotContainerHealthy") # Simple health response
            logger.debug("Health check GET request successful.")
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"NotFound")
            logger.debug(f"Health check GET request to unknown path: {self.path}")

    def log_message(self, format, *args):
        # Quieten the HTTP server's logging or integrate with your main logger
        logger.debug("%s - %s" % (self.address_string(), format % args))


def run_health_server(bot_client_for_check: discord.Client = None): # Optional: pass bot client
    port = int(os.environ.get("PORT", 8080))
    server_address = ('0.0.0.0', port) # Listen on all interfaces
    
    # If you want the health handler to check the bot's status:
    # You might need to make the handler a class factory or pass the client
    # For simplicity, HealthCheckHandler is kept basic here.
    # Example: You could define HealthCheckHandler inside run_health_server
    # and it could access bot_client_for_check if it's in scope or passed.

    httpd = HTTPServer(server_address, HealthCheckHandler)
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

        if command_name in command_map:
            command_instance = command_map[command_name]
            
            if asyncio.iscoroutinefunction(command_instance.run):
                result = await command_instance.run(message)
            else:
                result = command_instance.run(message)

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
            
            elif isinstance(result, str):
                stripped_result = result.strip()
                if not stripped_result:
                    logger.info(f"Command '{command_name}' returned an empty string.")
                    return
                
                if len(stripped_result) > 1950: 
                    logger.warning(f"String from '{command_name}' exceeded 1950 chars ({len(stripped_result)}), re-chunking in discord_bot.py.")
                    chunks = [stripped_result[i:i + 1950] for i in range(0, len(stripped_result), 1950)]
                    for i, chunk in enumerate(chunks):
                        await message.channel.send(chunk, suppress_embeds=True)
                        logger.info(f"Sent re-chunked part {i+1}/{len(chunks)}. Length: {len(chunk)}")
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
                        chunks = [str_result[i:i + 1950] for i in range(0, len(str_result), 1950)]
                        for i, chunk in enumerate(chunks):
                            await message.channel.send(chunk, suppress_embeds=True)
                            logger.info(f"Sent chunked part {i+1}/{len(chunks)} from converted type. Length: {len(chunk)}")
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
    def __init__(self, command_map, summary_module, scheduler, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.command_map = command_map
        self.summary_module = summary_module
        self.scheduler = scheduler
        self.summary_role_name = os.environ.get("LOTSLARP_DISCORD_BOT_SUMMARY_ROLE_NAME")
        self.digest_channel_id = int(os.environ.get("LOTSLARP_DISCORD_BOT_DIGEST_CHANNEL_ID", 0))
        logger.info("MyClient initialized.")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Bot is in {len(self.guilds)} guilds.")
        for guild in self.guilds:
            logger.info(f"- {guild.name} (ID: {guild.id})")
        self.scheduler.start()
        logger.info("Scheduler started.")

    async def on_message(self, message: discord.Message):
        if message.author == self.user:
            return

        # Cache message if it contains a mention of the summary role
        if self.summary_role_name and message.role_mentions:
            mentioned_role_names = [role.name for role in message.role_mentions]
            if self.summary_role_name in mentioned_role_names:
                logger.info(f"Found summary mention for role '{self.summary_role_name}' in message {message.id}")
                self.summary_module.cache_message(message)
        
        if message.content.startswith("/"):
            await process_command(self, message, self.command_map)


async def send_digest_pdf(client: discord.Client, summary_module, gemini_model):
    logger.info("Starting daily digest PDF process...")
    messages_data = summary_module.get_messages_for_digest()
    if not messages_data:
        logger.info("No messages to summarize. Skipping PDF generation.")
        return

    messages_for_pdf = []
    plain_text_for_summary = []
    message_ids_to_mark_sent = []
    for row in messages_data:
        channel_id, guild_id, author_name, message_content, message_url, msg_id = row
        guild = client.get_guild(guild_id)
        channel = client.get_channel(channel_id)
        guild_name = guild.name if guild else "Unknown Server"
        channel_name = channel.name if channel else "Unknown Channel"
        
        messages_for_pdf.append({
            "guild_name": guild_name,
            "channel_name": channel_name,
            "author_name": author_name,
            "message_content": message_content,
            "message_url": message_url,
        })
        plain_text_for_summary.append(f"Server: {guild_name}, Channel: {channel_name}, Author: {author_name}\n{message_content}\n")
        message_ids_to_mark_sent.append(msg_id)

    executive_summary = ""
    if gemini_model:
        try:
            prompt = "Please provide an executive summary of the following messages:\n\n" + "\n".join(plain_text_for_summary)
            response = await gemini_model.generate_content_async(prompt)
            executive_summary = response.text
            logger.info("Successfully generated executive summary from Gemini.")
        except Exception as e:
            logger.error(f"Failed to generate summary from Gemini: {e}", exc_info=True)
            executive_summary = "Error generating summary."

    # Generate PDF
    pdf_path = f"/tmp/digest_{datetime.utcnow().strftime('%Y-%m-%d')}.pdf"
    pdf_success = pdf_generator.create_digest_pdf(pdf_path, executive_summary, messages_for_pdf)

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
        with open(pdf_path, "rb") as f:
            pdf_file = discord.File(f, filename=os.path.basename(pdf_path))
            await channel.send(f"Daily Summary Digest - {datetime.utcnow().strftime('%Y-%m-%d')}", file=pdf_file)
        logger.info(f"Successfully sent PDF digest to channel {channel.name}.")
        # Mark messages as sent ONLY after successful sending
        summary_module.mark_messages_as_sent(message_ids_to_mark_sent)
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


def run_discord_bot_main_logic():
    logger.info("Starting Discord bot core logic setup...")
    app_db_path = get_app_db_path()

    intents = discord.Intents.default()
    intents.message_content = True 
    intents.members = True 
    intents.guilds = True

    command_classes = {}
    module_names_to_load = ["hello", "throw", "huh", "summary", "summary_digest", "pdf_generator"]
    logger.info(f"Attempting to load command modules: {module_names_to_load}")
    for module_name_str in module_names_to_load:
        full_module_path = f"modules.{module_name_str}"
        logger.info(f"Attempting to import module: {full_module_path}")
        try:
            module = importlib.import_module(full_module_path)
            logger.info(f"Successfully imported module object for {full_module_path}: {module}")
            
            expected_class_name = module_name_str.capitalize()
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
    gemini_model = None
    if gemini_api_key:
        genai.configure(api_key=gemini_api_key)
        gemini_model = genai.GenerativeModel('gemini-pro')
        logger.info("Gemini API key found and model initialized.")
    else:
        logger.warning("GEMINI_API_KEY not found. Summary generation will be disabled.")

    command_map_instances = {}
    summary_module_instance = None
    for name, Cls in command_classes.items():
        try:
            if name == "huh":
                command_map_instances[name] = Cls(database_filename=get_app_db_path())
            elif name == "summary":
                summary_module_instance = Cls(db_path=app_db_path)
            elif name == "summary_digest":
                command_map_instances[name] = Cls(summary_module=summary_module_instance, gemini_model=gemini_model)
            else:
                command_map_instances[name] = Cls() 
            logger.info(f"Successfully instantiated command: {name}")
        except TypeError as te: # Catch specific TypeError for __init__
            logger.error(f"TypeError instantiating command {name} from class {Cls}: {te}. Check __init__ signature.", exc_info=True)
        except Exception as e:
            logger.error(f"Failed to instantiate command {name} from class {Cls}: {e}", exc_info=True)

    if not command_map_instances:
        logger.error("CRITICAL: No commands were successfully instantiated. Bot will not have commands.")
        
    token = os.environ.get("LOTSLARP_DISCORD_BOT_DISCORD_TOKEN")
    if not token:
        logger.error("DISCORD_TOKEN not found. Bot cannot start main logic.")
        return

    scheduler = AsyncIOScheduler()
    client = MyClient(command_map=command_map_instances, summary_module=summary_module_instance, scheduler=scheduler, intents=intents)
    scheduler.add_job(send_digest_pdf, 'cron', hour=8, args=[client, summary_module_instance, gemini_model])
    scheduler.add_job(summary_module_instance.delete_old_messages, 'cron', hour=0)

    logger.info("Attempting to run Discord client...")
    try:
        client.run(token) 
    except discord.LoginFailure:
        logger.error("Discord Login Failed: Improper token has been passed.")
    except Exception as e:
        logger.error(f"An error occurred while running the Discord client: {e}", exc_info=True)
    logger.info("Discord client has stopped.")


async def run_diagnostics():
    """Runs diagnostics on the database and logs the number of entries."""
    logger.info("Running database diagnostics...")
    db_path = get_app_db_path()
    try:
        # File system diagnostics
        file_stats = os.stat(db_path)
        logger.info(f"Database file found at: {db_path}")
        logger.info(f"Database file size: {file_stats.st_size} bytes")
        logger.info(f"Database file permissions (st_mode): {oct(file_stats.st_mode)}")

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Query the 'entries' table
        cursor.execute("SELECT COUNT(*) FROM pages")
        count = cursor.fetchone()
        logger.info(f"Database page entries: {count}")

    except FileNotFoundError:
         logger.error(f"Database file not found at: {db_path}")
    except Exception as e:
        logger.error(f"Database operational error during diagnostics: {e}")
    finally:
        if 'conn' in locals() and conn:
             conn.close()

if __name__ == "__main__":
    logger.info("Application entry point (__main__) reached.")
    
    health_server_thread = threading.Thread(target=run_health_server, daemon=True)
    health_server_thread.start()
    logger.info("Health check server thread initiated.")

    try:
        # Run diagnostics after starting the health server but before the bot logic
        asyncio.run(run_diagnostics())
        logger.info("Calling run_discord_bot_main_logic().")
        run_discord_bot_main_logic()
    except Exception as main_bot_exc:
        logger.critical(f"run_discord_bot_main_logic() CRASHED: {main_bot_exc}", exc_info=True)
    
    logger.info("Application main thread finished or bot logic exited.")

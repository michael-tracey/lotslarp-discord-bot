import os
import logging
import sqlite3
import pathlib
import discord
import asyncio
import importlib
from datetime import datetime
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import google.generativeai as genai
from google.cloud import firestore  # Add Firestore import
from modules import pdf_generator

# Load environment variables from .env file
load_dotenv()

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
    def __init__(self, command_map, summary_module, scheduler, status_command, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.command_map = command_map
        self.summary_module = summary_module
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
        logger.info("MyClient initialized.")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Bot is in {len(self.guilds)} guilds:")
        for guild in self.guilds:
            logger.info(f"  - Guild: {guild.name} (ID: {guild.id})")
        
        # Run startup checks now that the event loop is active
        await self.run_startup_checks()
        
        self.scheduler.start()
        logger.info("Scheduler started.")

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
            if self.summary_role_name in mentioned_role_names:
                logger.info(f"Found summary mention for role '{self.summary_role_name}' in message {message.id}")
                self.summary_module.cache_message(message)
        
        if message.content.startswith("/"):
            await process_command(self, message, self.command_map)
        else:
            if message.guild:
                logger.debug(f"Ignoring non-command message from Guild: {message.guild.name}, Channel: {message.channel.name}, Author: {message.author.name}")
            else:
                logger.debug(f"Ignoring non-command DM message from Author: {message.author.name}")


async def send_digest_pdf(client: discord.Client, summary_module, gemini_model):
    logger.info("Starting daily digest PDF process...")
    messages_data = summary_module.get_messages_for_digest()
    if not messages_data:
        logger.info("No messages to summarize. Skipping PDF generation.")
        return

    messages_for_pdf = []
    plain_text_for_summary = []
    message_ids_to_mark_sent = []
    total_message_length = 0
    unique_authors = set()
    
    for row in messages_data:
        # Deconstruct the list returned by the summary module
        # Expected format: [channel_id, guild_id, author_name, message_content, message_url, doc_id]
        channel_id = row[0]
        guild_id = row[1]
        author_name = row[2]
        message_content = row[3]
        message_url = row[4]
        msg_id = row[5] # This is now the Firestore document ID (string)
        
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
        
        # Calculate statistics
        total_message_length += len(message_content)
        unique_authors.add(author_name)
    
    # Prepare message statistics
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
        try:
            default_prompt = "Please provide an executive summary of the following messages:\n\n"
            prompt_instructions = os.environ.get("LOTSLARP_DISCORD_BOT_GEMINI_PROMPT", default_prompt)
            prompt = f"{prompt_instructions}\n\n" + "\n".join(plain_text_for_summary)
            response = await gemini_model.generate_content_async(prompt)
            executive_summary = response.text
            logger.info("Successfully generated executive summary from Gemini.")
        except Exception as e:
            logger.error(f"Failed to generate summary from Gemini: {e}", exc_info=True)
            executive_summary = "Error generating summary."

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

    # Generate PDF
    pdf_path = f"/tmp/digest_{current_date.strftime('%Y-%m-%d')}.pdf"
    pdf_success = pdf_generator.create_digest_pdf(
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
        # Prepare Discord message with summary and statistics
        discord_message = f"**{pdf_title} - {date_range}**\n\n"
        discord_message += "**Message Statistics:**\n"
        for stat in message_stats:
            discord_message += f"• {stat}\n"
        discord_message += "\n**Storyteller Summary:**\n"
        
        # Truncate summary for Discord if too long
        if len(executive_summary) > 1200:
            discord_message += executive_summary[:1200] + "...\n\n*(Full summary available in attached PDF)*"
        else:
            discord_message += executive_summary

        with open(pdf_path, "rb") as f:
            pdf_file = discord.File(f, filename=os.path.basename(pdf_path))
            await channel.send(content=discord_message, file=pdf_file)
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


def setup_bot():
    logger.info("Starting Discord bot core logic setup...")
    app_db_path = get_app_db_path()

    intents = discord.Intents.default()
    intents.message_content = True 
    intents.members = True 
    intents.guilds = True

    command_classes = {}
    module_names_to_load = ["hello", "throw", "huh", "summary", "digest", "pdf_generator", "larpbot_status"]
    logger.info(f"Attempting to load command modules: {module_names_to_load}")
    for module_name_str in module_names_to_load:
        full_module_path = f"modules.{module_name_str}"
        logger.info(f"Attempting to import module: {full_module_path}")
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


    command_map_instances = {}
    summary_module_instance = None
    status_command_instance = None
    for name, Cls in command_classes.items():
        try:
            instance = None
            if name == "huh":
                instance = Cls(database_filename=get_app_db_path())
            elif name == "summary":
                if firestore_client:
                    summary_module_instance = Cls(db_client=firestore_client)
                else:
                    logger.error("Firestore client not available, cannot instantiate Summary module.")
                continue # This is not a command, so don't add to map
            elif name == "digest":
                instance = Cls(summary_module=summary_module_instance, gemini_model=gemini_model, pdf_gen=pdf_generator)
            elif name == "larpbot_status":
                status_command_instance = Cls(db_path=app_db_path, gemini_model=gemini_model)
                instance = status_command_instance
            elif name == "pdf_generator":
                continue # Not a command
            else:
                instance = Cls() 

            if instance:
                # Use the instance's `name` attribute if it exists, otherwise use the module name
                command_name = getattr(instance, 'name', name)
                command_map_instances[command_name] = instance
                logger.info(f"Successfully instantiated and mapped command: '{command_name}'")

        except TypeError as te: # Catch specific TypeError for __init__
            logger.error(f"TypeError instantiating command {name} from class {Cls}: {te}. Check __init__ signature.", exc_info=True)
        except Exception as e:
            logger.error(f"Failed to instantiate command {name} from class {Cls}: {e}", exc_info=True)

    if not command_map_instances:
        logger.error("CRITICAL: No commands were successfully instantiated. Bot will not have commands.")
    
    # Create the client and scheduler
    scheduler = AsyncIOScheduler()
    client = MyClient(
        command_map=command_map_instances, 
        summary_module=summary_module_instance, 
        scheduler=scheduler,
        status_command=status_command_instance,
        intents=intents
    )
    
    # Schedule jobs
    if summary_module_instance:
        cron_schedule = os.environ.get("LOTSLARP_DISCORD_BOT_DIGEST_CRON", "0 8 * * *") # Default to 8:00 AM UTC daily
        try:
            trigger = CronTrigger.from_crontab(cron_schedule, timezone="UTC")
            scheduler.add_job(send_digest_pdf, trigger=trigger, args=[client, summary_module_instance, gemini_model])
            logger.info(f"Scheduled daily digest with cron schedule: '{cron_schedule}' UTC")
        except ValueError as e:
            logger.error(f"Invalid cron string '{cron_schedule}'. Defaulting to every day at 8am. Error: {e}")
            scheduler.add_job(send_digest_pdf, 'cron', hour=8, args=[client, summary_module_instance, gemini_model])

        scheduler.add_job(summary_module_instance.delete_old_messages, 'cron', hour=0)

    return client


if __name__ == "__main__":
    logger.info("Application entry point (__main__) reached.")
    
    health_server_thread = threading.Thread(target=run_health_server, daemon=True)
    health_server_thread.start()
    logger.info("Health check server thread initiated.")

    try:
        # Setup bot and get client
        client = setup_bot()
        
        # Proceed with bot execution if token is present
        token = os.environ.get("LOTSLARP_DISCORD_BOT_DISCORD_TOKEN")
        if not token:
            logger.error("LOTSLARP_DISCORD_BOT_DISCORD_TOKEN not found. Bot cannot start.")
        else:
            logger.info("Attempting to run Discord client...")
            try:
                # Set discord.py logging to INFO
                discord_logger = logging.getLogger('discord')
                discord_logger.setLevel(logging.INFO)
                
                logger.debug("Calling client.run(token)...")
                client.run(token) 
                logger.debug("client.run(token) has exited.")

            except discord.errors.LoginFailure:
                logger.error("Login to Discord failed. Please check your token.", exc_info=True)
            except Exception as e:
                logger.error(f"An error occurred while running the client: {e}", exc_info=True)

    except Exception as main_exc:
        logger.critical(f"An unhandled exception occurred in the main execution block: {main_exc}", exc_info=True)
    
    logger.info("Application main thread finished or bot logic exited.")

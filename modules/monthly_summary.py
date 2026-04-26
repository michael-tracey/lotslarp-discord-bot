import os
import logging
import discord
import asyncio
from datetime import datetime, timedelta, timezone
from google.cloud import firestore
from modules.utils import smart_chunk_message, get_previous_game_date, get_date_of_weekday_in_month, compress_pdf, get_admin_roles

logger = logging.getLogger(__name__)

class MonthlySummary:
    def __init__(self, summary_module, gemini_model, pdf_gen, lore_manager=None):
        self.name = "summarize-month"
        self.summary_module = summary_module
        self.gemini_model = gemini_model
        self.pdf_gen = pdf_gen
        self.lore_manager = lore_manager
        self.admin_roles = get_admin_roles()
        
        try:
            # Check LOTSLARP_BOT_SUMMARY_CHANNEL_ID first, then REPORT, then DIGEST
            channel_id_str = os.environ.get("LOTSLARP_BOT_SUMMARY_CHANNEL_ID")
            if not channel_id_str:
                channel_id_str = os.environ.get("LOTSLARP_BOT_REPORT_CHANNEL_ID")
            if not channel_id_str:
                channel_id_str = os.environ.get("LOTSLARP_DISCORD_BOT_DIGEST_CHANNEL_ID", "0")
            
            self.digest_channel_id = int(channel_id_str.strip().strip('"').strip("'"))
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid DIGEST_CHANNEL_ID: {e}")
            self.digest_channel_id = 0

    async def run(self, client: discord.Client, message: discord.Message):
        """
        Manually triggers a monthly summary.
        Logic: Summarizes from "Last Game" until Now.
        Usage: /summarize-month
        """
        logger.info(f"Command started: /lotslarp report month by {message.author} in {message.channel}")

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

        try:
            await message.add_reaction("⏳")
        except (discord.Forbidden, discord.NotFound):
            pass

        # Configuration
        try:
            game_ordinal = int(os.environ.get("LOTSLARP_GAME_WEEK_ORDINAL", 1))
            game_weekday = int(os.environ.get("LOTSLARP_GAME_WEEKDAY", 5)) # Default Saturday (5)
        except ValueError:
            game_ordinal = 1
            game_weekday = 5

        # Range: Last Game -> Now
        end_date = datetime.now(timezone.utc)
        
        # Calculate Start Date (Last Game)
        # Note: get_previous_game_date returns a date object, need to convert to datetime
        last_game_date = get_previous_game_date(end_date.date(), ordinal=game_ordinal, weekday=game_weekday)
        start_date = datetime(
            last_game_date.year, 
            last_game_date.month, 
            last_game_date.day, 
            0, 0, 0, tzinfo=timezone.utc
        )
        
        logger.info(f"Calculated date range: {start_date} to {end_date}")
        logger.info(f"Target digest channel ID: {self.digest_channel_id}")

        try:
            result = await generate_and_send_summary(
                client=client,
                summary_module=self.summary_module,
                gemini_model=self.gemini_model,
                pdf_gen=self.pdf_gen,
                lore_manager=self.lore_manager,
                start_date=start_date,
                end_date=end_date,
                title="Monthly Game Cycle Summary (Manual)",
                channel_id=self.digest_channel_id
            )
            if result:
                try:
                    await message.add_reaction("✅")
                except (discord.Forbidden, discord.NotFound):
                    pass
                target_channel = client.get_channel(self.digest_channel_id)
                if target_channel and target_channel.id != message.channel.id:
                    await message.channel.send(f"✅ Monthly summary sent to {target_channel.mention}.")
                logger.info("Manual monthly summary completed successfully.")
            else:
                logger.warning("Manual monthly summary completed but returned False (likely no messages or configuration error).")
                try:
                    await message.add_reaction("✅")
                except (discord.Forbidden, discord.NotFound):
                    pass
        except Exception as e:
            logger.error(f"Manual monthly summary failed: {e}", exc_info=True)
            try:
                await message.add_reaction("❌")
            except (discord.Forbidden, discord.NotFound):
                pass
            await message.channel.send(f"**Error:** {str(e)}")


async def check_monthly_trigger(client, summary_module, gemini_model, pdf_gen, lore_manager):
    """
    Scheduled job to check if we are approaching the Game Day (default: Thursday before 1st Saturday).
    If so, sends a summary from the Previous Game until Today.
    """
    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()
    
    # Configuration
    try:
        game_ordinal = int(os.environ.get("LOTSLARP_GAME_WEEK_ORDINAL", 1))
        game_weekday = int(os.environ.get("LOTSLARP_GAME_WEEKDAY", 5)) # Default Saturday (5)
    except ValueError:
        game_ordinal = 1
        game_weekday = 5

    # Trigger Logic: 2 days before the Game
    # Calculate target trigger weekday
    trigger_weekday = (game_weekday - 2) % 7 
    
    # 1. Check if today is the trigger weekday
    if today.weekday() != trigger_weekday:
        logger.debug(f"Monthly Trigger: Today (weekday {today.weekday()}) is not trigger day ({trigger_weekday}). Skipping.")
        return

    # 2. Check if the upcoming Game Day (Today + 2 days) is the correct ordinal occurrence
    upcoming_game_date = today + timedelta(days=2)
    
    # Calculate the actual Game Date for this month to see if it matches our upcoming date
    try:
        actual_game_date = get_date_of_weekday_in_month(upcoming_game_date.year, upcoming_game_date.month, game_ordinal, game_weekday)
    except ValueError:
        logger.debug("Monthly Trigger: Could not calculate game date for this month. Skipping.")
        return

    if upcoming_game_date != actual_game_date:
        logger.debug(f"Monthly Trigger: Upcoming potential game date ({upcoming_game_date}) is not the configured game date ({actual_game_date}). Skipping.")
        return
    
    # It is the Trigger Day before the Game!
    logger.info("Monthly Trigger: It is 2 days before the Game. Initiating Summary.")

    # 3. Calculate Range
    # End Date: Now
    end_date = now_utc
    
    # Start Date: The PREVIOUS Game Date
    # Since we are currently *before* this month's game, get_previous_game_date should correctly return last month's game.
    last_game_date_obj = get_previous_game_date(today, ordinal=game_ordinal, weekday=game_weekday)
    
    # Convert date to datetime (UTC, start of day)
    start_date = datetime(
        last_game_date_obj.year, 
        last_game_date_obj.month, 
        last_game_date_obj.day, 
        0, 0, 0, tzinfo=timezone.utc
    )

    logger.info(f"Monthly Summary Range: {start_date} -> {end_date}")

    # 4. Get Channel ID
    try:
        channel_id_str = os.environ.get("LOTSLARP_DISCORD_BOT_DIGEST_CHANNEL_ID", "0")
        digest_channel_id = int(channel_id_str.strip().strip('"').strip("'"))
    except:
        digest_channel_id = 0

    if not digest_channel_id:
        logger.error("Digest channel ID not configured. Cannot send monthly summary.")
        return

    await generate_and_send_summary(
        client=client,
        summary_module=summary_module,
        gemini_model=gemini_model,
        pdf_gen=pdf_gen,
        lore_manager=lore_manager,
        start_date=start_date,
        end_date=end_date,
        title="Monthly Game Cycle Summary",
        channel_id=digest_channel_id
    )

async def store_monthly_summary(firestore_client, summary_text, start_date, end_date):
    """Stores the generated monthly summary in Firestore."""
    if not firestore_client:
        return

    # ID format: YYYY_MM (based on the end date/current report month)
    doc_id = end_date.strftime("%Y_%m")
    
    data = {
        'year': end_date.year,
        'month': end_date.month,
        'summary_text': summary_text,
        'start_date': start_date,
        'end_date': end_date,
        'created_at': datetime.now(timezone.utc)
    }
    
    try:
        await asyncio.to_thread(
            firestore_client.collection('monthly_summaries').document(doc_id).set, 
            data
        )
        logger.info(f"Stored monthly summary for {doc_id}.")
    except Exception as e:
        logger.error(f"Failed to store monthly summary: {e}")

async def get_recent_monthly_summaries(firestore_client, current_end_date):
    """Retrieves the N most recent monthly summaries before the current one."""
    if not firestore_client:
        return []
        
    try:
        # Get context limit from ENV
        try:
            limit = int(os.environ.get("LOTSLARP_MONTHLY_SUMMARY_CONTEXT_MONTHS", 3))
        except ValueError:
            limit = 3
            
        if limit <= 0:
            return []

        # Current report ID
        current_id = current_end_date.strftime("%Y_%m")

        # Query: Order by ID descending (newest first), exclude current if it exists (via logic or ID check)
        # We want summaries *before* this one.
        # Since ID is YYYY_MM, we can just query where ID < current_id order by ID desc
        
        # Note: ID comparison works for strings "YYYY_MM"
        col_ref = firestore_client.collection('monthly_summaries')
        
        # We need a synchronous wrapper for the query
        def _query_sync():
            # Current report ID
            current_id = current_end_date.strftime("%Y_%m")
            
            # Query for summaries where end_date < current_end_date
            # We order by end_date descending to get the most recent ones first
            q = col_ref.where(filter=firestore.FieldFilter('end_date', '<', current_end_date))\
                       .order_by('end_date', direction=firestore.Query.DESCENDING)\
                       .limit(limit)
            
            docs = q.stream()
            
            results = []
            for doc in docs:
                d = doc.to_dict()
                results.append(f"**Summary for {d.get('year')}-{d.get('month'):02d}:**\n{d.get('summary_text')}")
            
            # results are already descending (newest first). 
            # We reverse to provide them in chronological order to the AI.
            results.reverse()
            return results

        return await asyncio.to_thread(_query_sync)

    except Exception as e:
        logger.error(f"Failed to retrieve past summaries: {e}")
        return []


async def generate_and_send_summary(client, summary_module, gemini_model, pdf_gen, lore_manager, start_date, end_date, title, channel_id):
    logger.info(f"Generating summary '{title}' from {start_date} to {end_date}...")
    
    # Fetch messages
    messages_data = await summary_module.get_messages_in_range(start_date, end_date)
    
    if not messages_data:
        logger.warning(f"No messages found in the specified range ({start_date} to {end_date}). Aborting.")
        return False

    logger.info(f"Found {len(messages_data)} messages. Processing...")

    # Process messages for PDF and AI
    messages_for_pdf = []
    plain_text_for_summary = []
    total_message_length = 0
    unique_authors = set()

    for row in messages_data:
        # Expected format: [channel_id, guild_id, author_name, message_content, message_url, doc_id, author_display_name, channel_name, timestamp]
        # Note: timestamp in row[8] is likely a Firestore datetime
        
        channel_id_raw = row[0]
        guild_id = row[1]
        author_name = row[2]
        message_content = row[3]
        message_url = row[4]
        # row[5] is doc_id
        author_display = row[6]
        channel_name_str = row[7]
        msg_timestamp = row[8]
        
        # Ensure timestamp handling
        ts_str = msg_timestamp.strftime('%m/%d %H:%M') if msg_timestamp else "??:??"

        # Resolve Names if possible (though we likely rely on stored data)
        guild = client.get_guild(guild_id)
        channel = client.get_channel(channel_id_raw)
        guild_name = guild.name if guild else "Unknown Server"
        channel_name = channel.name if channel else (channel_name_str or "Unknown Channel")

        messages_for_pdf.append({
            "guild_name": guild_name,
            "channel_name": channel_name,
            "author_name": author_name,
            "author_display_name": author_display,
            "message_content": message_content,
            "message_url": message_url,
            "timestamp": ts_str
        })
        
        plain_text_for_summary.append(f"[{ts_str}] {channel_name} - {author_display or author_name}: {message_content}")
        
        total_message_length += len(message_content)
        unique_authors.add(author_name)

    # Statistics
    message_count = len(messages_data)
    avg_message_length = total_message_length // message_count if message_count > 0 else 0
    message_stats = [
        f"Total Messages: {message_count}",
        f"Unique Authors: {len(unique_authors)}",
        f"Average Message Length: {avg_message_length} characters",
        f"Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
    ]

    # AI Summary
    executive_summary = ""
    if gemini_model:
        logger.info("Generating AI summary...")
        def _generate_summary_sync(prompt):
            try:
                response = gemini_model.generate_content(prompt)
                return response.text
            except Exception as e:
                logger.error(f"Gemini error: {e}", exc_info=True)
                return "Error generating summary."

        try:
            all_text = "\n".join(plain_text_for_summary)
            lore_context = ""
            
            # Fetch Lore
            if lore_manager:
                try:
                    lore_context = await lore_manager.get_relevant_lore(all_text)
                except Exception as e:
                    logger.error(f"Lore error: {e}")

            # Fetch Previous Summaries Context
            past_context_str = ""
            try:
                past_summaries = await get_recent_monthly_summaries(summary_module.db, end_date)
                if past_summaries:
                    past_context_str = "\n\n*** PREVIOUS MONTHLY SUMMARIES (Context) ***\n" + "\n\n".join(past_summaries) + "\n\n"
                    logger.info(f"Injected {len(past_summaries)} past monthly summaries for context.")
            except Exception as e:
                logger.error(f"Error fetching past summaries context: {e}")

            default_prompt = "You are an AI assistant tasked with creating a comprehensive executive summary of Discord conversations from the past month. Analyze the following collection of messages and provide a detailed summary. The summary should adhere to these rules: 1. Start with a one-sentence overview of the general topics discussed. 2. Use bullet points to highlight key decisions, action items, or significant points of interest. 3. Group related topics together under a common sub-heading if the conversation covers multiple distinct subjects. 4. Maintain a neutral, professional tone. 5. Do not invent or infer information that isn't present in the messages. 6. The summary should be approximately 6-8 paragraphs in total to reflect the large volume of activity. Here are the messages to summarize:"
            prompt_instructions = os.environ.get("LOTSLARP_DISCORD_BOT_MONTHLY_PROMPT", default_prompt)
            
            # Combine Contexts
            # Order: Instructions -> Previous Summaries -> Lore -> Current Messages
            prompt = f"{prompt_instructions}\n{past_context_str}{lore_context}\n\n" + all_text
            
            executive_summary = await asyncio.to_thread(_generate_summary_sync, prompt)
            
            # Store the new summary
            if summary_module and summary_module.db and executive_summary and "Error:" not in executive_summary:
                await store_monthly_summary(summary_module.db, executive_summary, start_date, end_date)

        except Exception as e:
            logger.error(f"Summary thread error: {e}", exc_info=True)
            executive_summary = "Error: Summary generation process failed."
    else:
        logger.info("Gemini model not available. Skipping AI summary.")

    # Generate PDF
    logger.info("Generating PDF...")
    date_str = datetime.now().strftime('%Y-%m-%d')
    pdf_filename = f"monthly_summary_{date_str}.pdf"
    pdf_path = f"/tmp/{pdf_filename}"
    
    # Track all temporary files for cleanup
    temp_files = [pdf_path]
    
    date_range_str = f"{start_date.strftime('%B %d')} - {end_date.strftime('%B %d, %Y')}"

    pdf_success = await asyncio.to_thread(
        pdf_gen.create_digest_pdf, 
        pdf_path, 
        executive_summary, 
        messages_for_pdf, 
        title=title,
        date_range=date_range_str,
        message_stats=message_stats
    )

    if not pdf_success:
        logger.error("PDF generation failed.")
        return False

    # Send
    channel = client.get_channel(channel_id)
    if not channel:
        logger.error(f"Digest channel {channel_id} not found/accessible. Cannot send summary.")
        return False

    try:
        # Compress by default
        DISCORD_LIMIT_BYTES = 10 * 1024 * 1024
        logger.info(f"Optimizing monthly PDF size...")
        
        compressed_path = pdf_path.replace(".pdf", "_compressed.pdf")
        if await compress_pdf(pdf_path, compressed_path, power=2):
            temp_files.append(compressed_path)
            pdf_path = compressed_path
            # If still too large, try ebook
            if os.path.getsize(pdf_path) > DISCORD_LIMIT_BYTES:
                ebook_path = pdf_path.replace(".pdf", "_ebook.pdf")
                if await compress_pdf(pdf_path, ebook_path, power=3):
                    temp_files.append(ebook_path)
                    pdf_path = ebook_path
                    # If still too large, try max
                    if os.path.getsize(pdf_path) > DISCORD_LIMIT_BYTES:
                        max_path = pdf_path.replace(".pdf", "_max.pdf")
                        if await compress_pdf(pdf_path, max_path, power=4):
                            temp_files.append(max_path)
                            pdf_path = max_path

        file_size = os.path.getsize(pdf_path)
        
        logger.info(f"Sending summary to channel {channel.name} ({channel.id})...")
        discord_message = f"**{title}**\n\n"
        discord_message += f"**Period:** {date_range_str}\n\n"
        discord_message += "**Storyteller Recap:**\n"
        discord_message += executive_summary + "\n"
        
        if file_size > DISCORD_LIMIT_BYTES:
             discord_message += f"\n⚠️ **Note:** The PDF report is very large ({file_size/1024/1024:.2f} MB) and may fail to upload."

        chunks = smart_chunk_message(discord_message, 1950)

        with open(pdf_path, "rb") as f:
            pdf_file = discord.File(f, filename=pdf_filename)
            
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1:
                    await channel.send(content=chunk, file=pdf_file)
                else:
                    await channel.send(content=chunk)
                    await asyncio.sleep(0.5)
        
        logger.info(f"Monthly summary successfully sent to {channel.name}.")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send monthly summary: {e}", exc_info=True)
        return False
    finally:
        for tmp_file in temp_files:
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                    logger.info(f"Removed temporary PDF file: {tmp_file}")
                except Exception as e:
                    logger.error(f"Failed to remove temporary file {tmp_file}: {e}")
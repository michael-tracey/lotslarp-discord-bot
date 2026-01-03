import os
import logging
import discord
import asyncio
from datetime import datetime, timedelta, timezone
from modules.utils import smart_chunk_message

logger = logging.getLogger(__name__)

class MonthlySummary:
    def __init__(self, summary_module, gemini_model, pdf_gen, lore_manager=None):
        self.name = "summarize-month"
        self.summary_module = summary_module
        self.gemini_model = gemini_model
        self.pdf_gen = pdf_gen
        self.lore_manager = lore_manager
        self.admin_role_name = os.environ.get("LOTSLARP_BOT_ADMIN_USER", "@storytellers").strip("@")
        
        try:
            channel_id_str = os.environ.get("LOTSLARP_DISCORD_BOT_DIGEST_CHANNEL_ID", "0")
            self.digest_channel_id = int(channel_id_str.strip().strip('"').strip("'"))
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid DIGEST_CHANNEL_ID: {e}")
            self.digest_channel_id = 0

    async def run(self, client: discord.Client, message: discord.Message):
        """
        Manually triggers a monthly summary for the last 30 days.
        Usage: /summarize-month
        """
        # Check Permissions
        has_permission = False
        if isinstance(message.author, discord.Member):
            for role in message.author.roles:
                if role.name == self.admin_role_name:
                    has_permission = True
                    break
        
        if not has_permission:
            await message.channel.send("🚫 You do not have permission to run this command.")
            return

        await message.add_reaction("⏳")

        # Range: Last 30 days
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=30)
        
        try:
            await generate_and_send_summary(
                client=client,
                summary_module=self.summary_module,
                gemini_model=self.gemini_model,
                pdf_gen=self.pdf_gen,
                lore_manager=self.lore_manager,
                start_date=start_date,
                end_date=end_date,
                title="Manual 30-Day Summary",
                channel_id=self.digest_channel_id
            )
            await message.add_reaction("✅")
        except Exception as e:
            logger.error(f"Manual monthly summary failed: {e}", exc_info=True)
            await message.add_reaction("❌")
            await message.channel.send(f"**Error:** {str(e)}")


def get_first_saturday(year, month):
    """Returns a datetime.date object for the first Saturday of the specified month/year."""
    d = datetime(year, month, 1)
    while d.weekday() != 5:  # 5 is Saturday
        d += timedelta(days=1)
    return d.date()

async def check_monthly_trigger(client, summary_module, gemini_model, pdf_gen, lore_manager):
    """
    Scheduled job to check if today is the Thursday before the first Saturday of the month.
    If so, sends a summary from the First Saturday of the Previous Month until Today.
    """
    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()
    
    # 1. Check if today is Thursday (weekday 3)
    if today.weekday() != 3:
        logger.debug("Monthly Trigger: Not Thursday. Skipping.")
        return

    # 2. Check if the upcoming Saturday (Today + 2 days) is the 1st Saturday of the current month
    upcoming_saturday = today + timedelta(days=2)
    if upcoming_saturday.day > 7:
        logger.debug("Monthly Trigger: Upcoming Saturday is not the first Saturday. Skipping.")
        return
    
    # It is the Thursday before the first Saturday!
    logger.info("Monthly Trigger: It is the Thursday before the 1st Saturday. Initiating Summary.")

    # 3. Calculate Range
    # End Date: Now
    end_date = now_utc
    
    # Start Date: First Saturday of LAST Month
    # Find first day of current month, subtract 1 day to get into prev month
    first_of_this_month = today.replace(day=1)
    last_of_prev_month = first_of_this_month - timedelta(days=1)
    prev_month_year = last_of_prev_month.year
    prev_month_month = last_of_prev_month.month
    
    first_sat_prev_month_date = get_first_saturday(prev_month_year, prev_month_month)
    
    # Convert date to datetime (UTC, start of day)
    start_date = datetime(
        first_sat_prev_month_date.year, 
        first_sat_prev_month_date.month, 
        first_sat_prev_month_date.day, 
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


async def generate_and_send_summary(client, summary_module, gemini_model, pdf_gen, lore_manager, start_date, end_date, title, channel_id):
    logger.info(f"Generating summary '{title}' from {start_date} to {end_date}...")
    
    # Fetch messages
    messages_data = await summary_module.get_messages_in_range(start_date, end_date)
    
    if not messages_data:
        logger.info("No messages found in the specified range.")
        return

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
            if lore_manager:
                try:
                    lore_context = await lore_manager.get_relevant_lore(all_text)
                except Exception as e:
                    logger.error(f"Lore error: {e}")

            default_prompt = "Please provide a comprehensive monthly summary of these roleplay messages, highlighting major plot developments, character arcs, and key decisions."
            prompt_instructions = os.environ.get("LOTSLARP_DISCORD_BOT_MONTHLY_PROMPT", default_prompt)
            prompt = f"{prompt_instructions}\n{lore_context}\n\n" + all_text
            
            executive_summary = await asyncio.to_thread(_generate_summary_sync, prompt)
        except Exception as e:
            logger.error(f"Summary thread error: {e}", exc_info=True)
            executive_summary = "Error: Summary generation process failed."

    # Generate PDF
    date_str = datetime.now().strftime('%Y-%m-%d')
    pdf_filename = f"monthly_summary_{date_str}.pdf"
    pdf_path = f"/tmp/{pdf_filename}"
    
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
        return

    # Send
    channel = client.get_channel(channel_id)
    if not channel:
        logger.error(f"Digest channel {channel_id} not found.")
        return

    try:
        discord_message = f"**{title}**\n\n"
        discord_message += f"**Period:** {date_range_str}\n\n"
        discord_message += "**Storyteller Recap:**\n"
        discord_message += executive_summary + "\n"
        
        chunks = smart_chunk_message(discord_message, 1950)

        with open(pdf_path, "rb") as f:
            pdf_file = discord.File(f, filename=pdf_filename)
            
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1:
                    await channel.send(content=chunk, file=pdf_file)
                else:
                    await channel.send(content=chunk)
                    await asyncio.sleep(0.5)
        
        logger.info(f"Monthly summary sent to {channel.name}.")
        
    except Exception as e:
        logger.error(f"Failed to send monthly summary: {e}", exc_info=True)
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

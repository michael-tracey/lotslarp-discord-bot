import discord
import os
import asyncio
import logging
from datetime import datetime, timedelta
from modules import pdf_generator
from modules.utils import smart_chunk_message, compress_pdf

logger = logging.getLogger(__name__)

class Digest:
    def __init__(self, summary_module, gemini_model, pdf_gen, lore_manager=None):
        self.summary_module = summary_module
        self.gemini_model = gemini_model
        self.pdf_generator = pdf_gen
        self.lore_manager = lore_manager
        self.name = "digest"
        self.admin_role_name = os.environ.get("LOTSLARP_BOT_ADMIN_USER", "@storytellers").strip("@")

    async def run(self, client: discord.Client, message: discord.Message):
        logger.info(f"Command started: /digest by {message.author} in {message.channel}")

        # Check Permissions
        has_permission = False
        if isinstance(message.author, discord.Member):
            for role in message.author.roles:
                if role.name == self.admin_role_name:
                    has_permission = True
                    break
        
        if not has_permission:
            logger.warning(f"Permission denied for {message.author}")
            await message.channel.send("🚫 You do not have permission to run this command.")
            return

        parts = message.content.split()
        if len(parts) != 2 or parts[1].lower() not in ["day", "week", "month"]:
            await message.channel.send("Usage: /digest <day|week|month>")
            return

        timeframe = parts[1].lower()
        end_date = datetime.utcnow()
        if timeframe == "day":
            start_date = end_date - timedelta(days=1)
            date_range = f"Day of {start_date.strftime('%B %d, %Y')}"
        elif timeframe == "week":
            start_date = end_date - timedelta(weeks=1)
            date_range = f"Week of {start_date.strftime('%B %d')} - {end_date.strftime('%B %d, %Y')}"
        elif timeframe == "month":
            start_date = end_date - timedelta(days=30)
            date_range = f"Month of {start_date.strftime('%B %Y')}"
        
        logger.info(f"Generating digest for timeframe: {timeframe} ({start_date} - {end_date})")
        await message.channel.send(f"Generating summary digest for the last {timeframe}...", suppress_embeds=True)

        # get_messages_since returns [channel_id, guild_id, author_name, message_content, message_url, doc_id, author_display_name, channel_name, timestamp]
        messages_data = await self.summary_module.get_messages_since(start_date)
        if not messages_data:
            logger.info("No messages found for the specified timeframe.")
            await message.channel.send(f"No messages found for the last {timeframe}.")
            return

        logger.info(f"Found {len(messages_data)} messages. Processing...")

        messages_for_pdf = []
        plain_text_for_summary = []
        total_message_length = 0
        unique_authors = set()
        
        for row in messages_data:
            channel_id, guild_id, author_name, message_content, message_url, msg_id, author_display_name, channel_name, msg_timestamp = row
            guild = client.get_guild(guild_id)
            channel = client.get_channel(channel_id)
            guild_name = guild.name if guild else "Unknown Server"
            channel_name = channel_name or (channel.name if channel else "Unknown Channel")
            
            # Format timestamp
            ts_str = msg_timestamp.strftime('%m/%d %H:%M') if msg_timestamp else "??:??"

            messages_for_pdf.append({
                "guild_name": guild_name,
                "channel_name": channel_name,
                "author_name": author_name,
                "author_display_name": author_display_name,
                "message_content": message_content,
                "message_url": message_url,
                "timestamp": ts_str
            })
            plain_text_for_summary.append(f"[{ts_str}] Server: {guild_name}, Channel: {channel_name}, Author: {author_display_name or author_name}\n{message_content}\n")
            
            # Calculate statistics
            total_message_length += len(message_content)
            unique_authors.add(author_display_name or author_name)
        
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
        if self.gemini_model:
            logger.info("Generating AI summary...")
            try:
                # RAG Integration
                all_text = "\n".join(plain_text_for_summary)
                lore_context = ""
                if self.lore_manager:
                    try:
                        lore_context = await self.lore_manager.get_relevant_lore(all_text)
                    except Exception as e:
                        # Log error but continue
                        logger.error(f"Error fetching lore: {e}")

                default_prompt = f"Please provide an executive summary of the following messages from the last {timeframe}:\n\n"
                prompt_instructions = os.environ.get("LOTSLARP_DISCORD_BOT_GEMINI_PROMPT", default_prompt)
                prompt = f"{prompt_instructions}\n{lore_context}\n" + all_text
                response = await self.gemini_model.generate_content_async(prompt)
                executive_summary = response.text
            except Exception as e:
                logger.error(f"Error generating summary: {e}", exc_info=True)
                executive_summary = f"Error generating summary: {e}"
        else:
            logger.warning("Gemini model not configured. Skipping AI summary.")
            executive_summary = "Gemini API not configured. Cannot generate summary."

        # Generate PDF
        logger.info("Generating PDF...")
        pdf_title = f"{timeframe.capitalize()} Summary Digest"
        pdf_path = f"/tmp/summary_{timeframe}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
        pdf_success = self.pdf_generator.create_digest_pdf(
            pdf_path, 
            executive_summary, 
            messages_for_pdf, 
            title=pdf_title,
            date_range=date_range,
            message_stats=message_stats
        )

        if not pdf_success:
            logger.error("PDF generation failed.")
            await message.channel.send("An error occurred while generating the PDF report.")
            return

        # Build Message Index
        message_index = "\n**Message Index:**\n"
        for msg in messages_for_pdf:
            author = msg['author_display_name'] or msg['author_name']
            channel = msg['channel_name']
            url = msg['message_url']
            ts = msg.get('timestamp', '??:??')
            message_index += f"• `{ts}` [#{channel}]({url}) - {author}\n"

        # Prepare Discord message with summary
        discord_message = f"**{pdf_title} - {date_range}**\n\n"
        
        discord_message += "**Storyteller Summary:**\n"
        discord_message += executive_summary + "\n"

        discord_message += message_index + "\n"

        discord_message += "**Message Statistics:**\n"
        for stat in message_stats:
            discord_message += f"• {stat}\n"
        
        # Use smart chunking
        chunks = smart_chunk_message(discord_message, 1950)

        # Send PDF to channel with summary
        try:
            logger.info(f"Sending digest to {message.channel.name}...")
            
            # Compress by default
            DISCORD_LIMIT_BYTES = 10 * 1024 * 1024
            logger.info(f"Optimizing PDF size for {pdf_path}...")
            compressed_path = pdf_path.replace(".pdf", "_compressed.pdf")
            
            # Start with printer (300dpi)
            if await compress_pdf(pdf_path, compressed_path, power=2):
                pdf_path = compressed_path
                # If still too large, try ebook (150dpi)
                if os.path.getsize(pdf_path) > DISCORD_LIMIT_BYTES:
                    ebook_path = pdf_path.replace(".pdf", "_ebook.pdf")
                    if await compress_pdf(pdf_path, ebook_path, power=3):
                        pdf_path = ebook_path
                        # If still too large, try max (72dpi)
                        if os.path.getsize(pdf_path) > DISCORD_LIMIT_BYTES:
                            max_path = pdf_path.replace(".pdf", "_max.pdf")
                            if await compress_pdf(pdf_path, max_path, power=4):
                                pdf_path = max_path

            file_size = os.path.getsize(pdf_path)
            if file_size > DISCORD_LIMIT_BYTES:
                await message.channel.send(f"⚠️ The PDF report is very large ({file_size/1024/1024:.2f} MB) and may fail to upload.")

            with open(pdf_path, "rb") as f:
                pdf_file = discord.File(f, filename=os.path.basename(pdf_path))
                
                for i, chunk in enumerate(chunks):
                    if i == len(chunks) - 1:
                        await message.channel.send(chunk, file=pdf_file)
                    else:
                        await message.channel.send(chunk)
                        await asyncio.sleep(0.5)
            logger.info("Digest sent successfully.")
        except Exception as e:
            logger.error(f"Failed to send digest: {e}", exc_info=True)
            await message.channel.send(f"An error occurred while sending the PDF report: {e}")
        finally:
            # Clean up the generated PDF file
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        
        return None
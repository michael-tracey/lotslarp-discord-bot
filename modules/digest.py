import discord
import os
from datetime import datetime, timedelta
from modules import pdf_generator

class Digest:
    def __init__(self, summary_module, gemini_model, pdf_gen):
        self.summary_module = summary_module
        self.gemini_model = gemini_model
        self.pdf_generator = pdf_gen
        self.name = "digest"

    async def run(self, client: discord.Client, message: discord.Message):
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
        
        await message.channel.send(f"Generating summary digest for the last {timeframe}...", suppress_embeds=True)

        messages_data = await self.summary_module.get_messages_since(start_date)
        if not messages_data:
            await message.channel.send(f"No messages found for the last {timeframe}.")
            return

        messages_for_pdf = []
        plain_text_for_summary = []
        total_message_length = 0
        unique_authors = set()
        
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
        if self.gemini_model:
            try:
                default_prompt = f"Please provide an executive summary of the following messages from the last {timeframe}:\n\n"
                prompt_instructions = os.environ.get("LOTSLARP_DISCORD_BOT_GEMINI_PROMPT", default_prompt)
                prompt = f"{prompt_instructions}\n\n" + "\n".join(plain_text_for_summary)
                response = await self.gemini_model.generate_content_async(prompt)
                executive_summary = response.text
            except Exception as e:
                executive_summary = f"Error generating summary: {e}"
        else:
            executive_summary = "Gemini API not configured. Cannot generate summary."

        # Generate PDF
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
            await message.channel.send("An error occurred while generating the PDF report.")
            return

        # Prepare Discord message with summary
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

        # Send PDF to channel with summary
        try:
            with open(pdf_path, "rb") as f:
                pdf_file = discord.File(f, filename=os.path.basename(pdf_path))
                await message.channel.send(discord_message, file=pdf_file)
        except Exception as e:
            await message.channel.send(f"An error occurred while sending the PDF report: {e}")
        finally:
            # Clean up the generated PDF file
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        
        return None
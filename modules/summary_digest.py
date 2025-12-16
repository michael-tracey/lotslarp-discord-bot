import discord
import os
from datetime import datetime, timedelta
from modules import pdf_generator

class Summary_digest:
    def __init__(self, summary_module, gemini_model, pdf_gen):
        self.summary_module = summary_module
        self.gemini_model = gemini_model
        self.pdf_generator = pdf_gen
        self.name = "summary-digest"

    async def run(self, client: discord.Client, message: discord.Message):
        parts = message.content.split()
        if len(parts) != 2 or parts[1].lower() not in ["day", "week", "month"]:
            await message.channel.send("Usage: /summary-digest <day|week|month>")
            return

        timeframe = parts[1].lower()
        end_date = datetime.utcnow()
        if timeframe == "day":
            start_date = end_date - timedelta(days=1)
        elif timeframe == "week":
            start_date = end_date - timedelta(weeks=1)
        elif timeframe == "month":
            start_date = end_date - timedelta(days=30)
        
        await message.channel.send(f"Generating summary digest for the last {timeframe}...", suppress_embeds=True)

        messages_data = self.summary_module.get_messages_since(start_date)
        if not messages_data:
            await message.channel.send(f"No messages found for the last {timeframe}.")
            return

        messages_for_pdf = []
        plain_text_for_summary = []
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
        pdf_path = f"/tmp/summary_{timeframe}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
        pdf_success = self.pdf_generator.create_digest_pdf(pdf_path, executive_summary, messages_for_pdf)

        if not pdf_success:
            await message.channel.send("An error occurred while generating the PDF report.")
            return

        # Send PDF to channel
        try:
            with open(pdf_path, "rb") as f:
                pdf_file = discord.File(f, filename=os.path.basename(pdf_path))
                await message.channel.send(f"Summary Digest for the last {timeframe}:", file=pdf_file)
        except Exception as e:
            await message.channel.send(f"An error occurred while sending the PDF report: {e}")
        finally:
            # Clean up the generated PDF file
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        
        return None
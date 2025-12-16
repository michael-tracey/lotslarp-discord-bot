import discord
from datetime import datetime, timedelta

class Summary_digest:
    def __init__(self, summary_module, gemini_model):
        self.summary_module = summary_module
        self.gemini_model = gemini_model
        self.name = "summary-digest"

    async def run(self, message: discord.Message):
        parts = message.content.split()
        if len(parts) != 2 or parts[1].lower() not in ["day", "week", "month"]:
            return "Usage: /summary-digest <day|week|month>"

        timeframe = parts[1].lower()
        end_date = datetime.utcnow()
        if timeframe == "day":
            start_date = end_date - timedelta(days=1)
        elif timeframe == "week":
            start_date = end_date - timedelta(weeks=1)
        elif timeframe == "month":
            start_date = end_date - timedelta(days=30)
        
        messages = self.summary_module.get_messages_since(start_date)
        if not messages:
            return f"No messages found for the last {timeframe}."

        plain_text_for_summary = []
        for row in messages:
            _, _, _, author_name, message_content, _ = row
            plain_text_for_summary.append(f"Author: {author_name}\n{message_content}\n")

        if not self.gemini_model:
            return "Gemini API not configured. Cannot generate summary."

        try:
            prompt = f"Please provide an executive summary of the following messages from the last {timeframe}:\n\n" + "\n".join(plain_text_for_summary)
            response = await self.gemini_model.generate_content_async(prompt)
            return f"**Summary for the last {timeframe}:**\n{response.text}"
        except Exception as e:
            return f"Error generating summary: {e}"
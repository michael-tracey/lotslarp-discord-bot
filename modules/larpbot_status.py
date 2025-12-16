import discord
import sqlite3
import google.generativeai as genai

class LarpbotStatus:
    def __init__(self, db_path, gemini_model):
        self.name = "larpbot-status"
        self.db_path = db_path
        self.gemini_model = gemini_model

    async def _test_db(self):
        """Tests the database connection."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                if result and result[0] == 1:
                    return "✅ Connected"
                else:
                    return "❌ Connection failed (Query returned unexpected result)"
        except Exception as e:
            return f"❌ Connection failed: {e}"

    async def _test_ai(self):
        """Tests the Gemini API connection."""
        if not self.gemini_model:
            return "❌ Gemini model not configured"
        try:
            # Use a simple, low-cost prompt for the health check
            response = await self.gemini_model.generate_content_async("Say 'hello'", stream=False)
            if response.text and "hello" in response.text.lower():
                return f"✅ Connected (Model: {self.gemini_model.model_name})"
            else:
                return "❌ Connection failed (Unexpected response)"
        except Exception as e:
            return f"❌ Connection failed: {e}"

    async def run(self, message: discord.Message):
        """Runs the status checks and reports back."""
        await message.channel.send("Running bot status checks...", suppress_embeds=True)
        
        db_status = await self._test_db()
        ai_status = await self._test_ai()

        embed = discord.Embed(
            title="Larp-Bot Status Report",
            color=discord.Color.blue()
        )
        embed.add_field(name="Database Connection", value=db_status, inline=False)
        embed.add_field(name="Gemini AI Connection", value=ai_status, inline=False)
        
        return await message.channel.send(embed=embed)

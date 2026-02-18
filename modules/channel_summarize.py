import discord
import os
import logging
import asyncio
from datetime import datetime
from modules.utils import smart_chunk_message

logger = logging.getLogger(__name__)

async def handle_share_interaction(interaction: discord.Interaction, firestore_client):
    """
    Handles the 'Share to Channel' button click.
    Retrieves the summary from Firestore and posts it to the channel.
    """
    try:
        # custom_id format: "share_summary:<doc_id>"
        doc_id = interaction.data['custom_id'].split(':')[1]
        
        # Fetch summary data from Firestore
        doc_ref = firestore_client.collection('channel_summaries').document(doc_id)
        doc = await asyncio.to_thread(doc_ref.get)
        
        if not doc.exists:
            await interaction.response.send_message(
                "❌ **Summary Expired or Not Found**\n\n"
                "I'm sorry, but this summary is no longer available. To keep our database clean, "
                "we only store channel summaries temporarily (for up to 6 weeks). \n\n"
                "You can generate a new summary of this channel using `/summarize`.", 
                ephemeral=True
            )
            return

        data = doc.to_dict()
        summary_text = data.get('summary_text', '')
        summary_role_name = data.get('summary_role_name', '')
        # We use the channel where the button was clicked (interaction.channel) 
        # OR we could store target_channel_id if we want to force it to a specific channel.
        # The original logic posted to 'target_channel', which was the channel *being summarized*.
        # The button is currently in the 'summary output channel'.
        # We need to send to the 'target_channel_id' stored in DB.
        target_channel_id = data.get('target_channel_id')
        
        target_channel = interaction.client.get_channel(target_channel_id)
        if not target_channel:
             await interaction.response.send_message("❌ The target channel for this summary no longer exists.", ephemeral=True)
             return

        # Find the role to mention it properly
        mention_str = f"@{summary_role_name}"
        if target_channel.guild:
            role = discord.utils.get(target_channel.guild.roles, name=summary_role_name)
            if role:
                mention_str = role.mention

        # Chunk and send
        chunks = smart_chunk_message(summary_text, 1900)
        
        # Acknowledge interaction immediately to avoid timeout while sending
        await interaction.response.defer(ephemeral=True)
        
        sent_count = 0
        for chunk in chunks:
            message_content = f"(( {mention_str} {chunk} ))"
            await target_channel.send(message_content)
            await asyncio.sleep(0.5)
            sent_count += 1

        await interaction.followup.send(f"Summary shared to {target_channel.mention} ({sent_count} parts)!", ephemeral=True)
        
        # Optional: Disable button? 
        # Since it's persistent/database backed, we might want to let them click it again later?
        # If we want to disable it, we'd need to edit the message on the interaction.message.
        # For now, leaving it enabled allows re-sharing if needed.
        
    except Exception as e:
        logger.error(f"Error in handle_share_interaction: {e}", exc_info=True)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Failed to share summary: {e}", ephemeral=True)
            else:
                await interaction.followup.send(f"Failed to share summary: {e}", ephemeral=True)
        except:
            pass


class ChannelSummarize:
    def __init__(self, gemini_model, firestore_client, lore_manager=None):
        self.gemini_model = gemini_model
        self.firestore_client = firestore_client
        self.lore_manager = lore_manager
        self.name = "summarize"
        self.summary_role_name = os.environ.get("LOTSLARP_DISCORD_BOT_SUMMARY_ROLE_NAME")
        self.admin_role_name = os.environ.get("LOTSLARP_BOT_ADMIN_USER", "@storytellers").strip("@")
        
        # Get the summary output channel ID
        try:
            channel_id_str = os.environ.get("LOTSLARP_BOT_SUMMARY_CHANNEL_ID", "0")
            self.summary_channel_id = int(channel_id_str.strip().strip("'").strip("'"))
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid LOTSLARP_BOT_SUMMARY_CHANNEL_ID value: '{os.environ.get('LOTSLARP_BOT_SUMMARY_CHANNEL_ID')}'. Using 0 as default. Error: {e}")
            self.summary_channel_id = 0

    async def run(self, client: discord.Client, message: discord.Message):
        """
        Summarizes messages from a specified channel.
        Usage: /summarize <channel_id>
        """
        logger.info(f"Command started: /summarize by {message.author} in {message.channel}")

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
        
        if len(parts) != 2:
            return "Usage: /summarize <channel_id>"
        
        # Parse channel ID
        try:
            target_channel_id = int(parts[1].strip('<>#'))
        except ValueError:
            return "Invalid channel ID. Please provide a valid channel ID or mention."
        
        # Check if summary output channel is configured
        if not self.summary_channel_id:
            logger.error("Summary output channel not configured (LOTSLARP_BOT_SUMMARY_CHANNEL_ID).")
            return "Summary output channel is not configured. Please set LOTSLARP_BOT_SUMMARY_CHANNEL_ID."
        
        # Get the target channel (works across all guilds the bot has access to)
        target_channel = client.get_channel(target_channel_id)
        if not target_channel:
            logger.warning(f"Could not find target channel with ID {target_channel_id}")
            return f"Could not find channel with ID {target_channel_id}. Make sure the bot has access to it."
        
        # Get the summary output channel
        summary_channel = client.get_channel(self.summary_channel_id)
        if not summary_channel:
            logger.warning(f"Could not find summary output channel with ID {self.summary_channel_id}")
            return f"Could not find summary output channel with ID {self.summary_channel_id}."
        
        logger.info(f"Summarizing channel {target_channel.name} ({target_channel.id}) to {summary_channel.name}")

        # Check permissions
        if not target_channel.permissions_for(target_channel.guild.me).read_message_history:
            logger.warning(f"Bot missing read_message_history permission for {target_channel.name}")
            return f"Bot does not have permission to read message history in {target_channel.mention}."
        
        # Acknowledge the command (but don't post in the original channel)
        await message.add_reaction("⏳")
        
        try:
            # Fetch messages from the target channel
            messages_to_summarize = []
            last_summary_found = False
            
            # Read messages until we find a message with the summary role mention
            # Limit changed from 500 to 100 per request
            async for msg in target_channel.history(limit=100, oldest_first=False):
                # Check if this message mentions the summary role
                if self.summary_role_name and msg.role_mentions:
                    mentioned_role_names = [role.name for role in msg.role_mentions]
                    if self.summary_role_name in mentioned_role_names:
                        last_summary_found = True
                        break
                
                # Skip bot messages and empty messages
                if msg.author.bot or not msg.content.strip():
                    continue
                
                messages_to_summarize.append(msg)
            
            # Reverse to get chronological order
            messages_to_summarize.reverse()
            
            if not messages_to_summarize:
                logger.info("No messages found to summarize.")
                await message.add_reaction("❌")
                await summary_channel.send(
                    f"**Channel Summary Request**\n"
                    f"Channel: {target_channel.mention} ({target_channel.guild.name})\n"
                    f"Requested by: {message.author.mention}\n\n"
                    f"⚠️ No messages found to summarize (limit 100)."
                )
                return None
            
            # Build the text for AI summarization
            plain_text_for_summary = []
            for msg in messages_to_summarize:
                # Replace mentions with readable names
                content = msg.content
                for user in msg.mentions:
                    content = content.replace(f'<@{user.id}>', f'@{user.display_name}')
                for role in msg.role_mentions:
                    content = content.replace(f'<@&{role.id}>', f'@{role.name}')
                
                plain_text_for_summary.append(
                    f"[{msg.created_at.strftime('%Y-%m-%d %H:%M')}] {msg.author.display_name}: {content}"
                )
            
            # Generate AI summary
            summary_text = ""
            if self.gemini_model:
                logger.info(f"Generating AI summary for {len(messages_to_summarize)} messages...")
                def _generate_summary_sync(prompt_to_send):
                    try:
                        # Use the synchronous method for running in a separate thread
                        response = self.gemini_model.generate_content(prompt_to_send)
                        return response.text
                    except Exception as e:
                        logger.error(f"Failed to generate summary from Gemini: {e}", exc_info=True)
                        return f"Error generating summary: {e}"

                try:
                    # Get custom prompt or use default
                    default_prompt = (
                        "You are an AI assistant tasked with creating a high-level executive summary of Discord conversations. "
                        "Analyze the following collection of messages and provide a concise summary. The summary should adhere to these rules: "
                        "1. Start with a one-sentence overview of the general topics discussed. "
                        "2. Use bullet points to highlight key decisions, action items, or significant points of interest. "
                        "3. Group related topics together under a common sub-heading if the conversation covers multiple distinct subjects. "
                        "4. Maintain a neutral, professional tone. "
                        "5. Do not invent or infer information that isn't present in the messages. "
                        "6. The summary should be no more than 4 paragraphs in total. Here are the messages to summarize:"
                    )
                    
                    # RAG Integration
                    all_text = "\n".join(plain_text_for_summary)
                    lore_context = ""
                    if self.lore_manager:
                        try:
                            lore_context = await self.lore_manager.get_relevant_lore(all_text)
                            if lore_context:
                                logger.info("Injected relevant lore into channel summary prompt.")
                        except Exception as e:
                            logger.error(f"Error fetching lore for channel summary: {e}")

                    prompt_instructions = os.environ.get("LOTSLARP_DISCORD_BOT_CHANNEL_SUMMARY_PROMPT", default_prompt)
                    prompt = f"{prompt_instructions}\n{lore_context}\n" + all_text
                    
                    summary_text = await asyncio.to_thread(_generate_summary_sync, prompt)
                except Exception as e:
                    logger.error(f"An error occurred while trying to run summary generation in a thread: {e}", exc_info=True)
                    summary_text = "Error: Summary generation process failed."
            else:
                logger.warning("Gemini model not configured. Skipping AI summary.")
                summary_text = "Gemini API not configured. Cannot generate summary."
            
            # Prepare the summary message
            time_range = "since last summary" if last_summary_found else "from channel history"
            
            # Re-add Index as requested (using channel name as link text and author display name)
            message_index = "\n**Message Index:**\n"
            for msg in messages_to_summarize:
                ts_str = msg.created_at.strftime('%m/%d %H:%M')
                message_index += f"• `{ts_str}` [#{target_channel.name}]({msg.jump_url}) - {msg.author.display_name}\n"

            # Note: Index removed as requested. Added "Messages analyzed" prominently.
            full_response = (
                f"**📊 Channel Summary**\n"
                f"**Channel:** {target_channel.mention} (#{target_channel.name})\n"
                f"**Server:** {target_channel.guild.name}\n"
                f"**Requested by:** {message.author.mention}\n\n"
                f"**Summary:**\n{summary_text}\n"
                f"{message_index}\n"
                f"**Stats:**\n"
                f"**Messages analyzed:** {len(messages_to_summarize)} {time_range}\n"
                f"**Time range:** {messages_to_summarize[0].created_at.strftime('%Y-%m-%d %H:%M')} to {messages_to_summarize[-1].created_at.strftime('%Y-%m-%d %H:%M')} UTC"
            )
            
            # Use smart chunking
            chunks = smart_chunk_message(full_response, 1950)
            
            # Save Summary to Firestore
            doc_id = None
            if self.firestore_client:
                try:
                    data = {
                        'summary_text': summary_text,
                        'summary_role_name': self.summary_role_name,
                        'target_channel_id': target_channel.id,
                        'created_at': datetime.utcnow()
                    }
                    # Add to 'channel_summaries' collection
                    new_doc = await asyncio.to_thread(self.firestore_client.collection('channel_summaries').add, data)
                    doc_id = new_doc[1].id
                    logger.info(f"Saved channel summary to Firestore with ID: {doc_id}")
                except Exception as e:
                    logger.error(f"Failed to save summary to Firestore: {e}", exc_info=True)

            # Create View with Share Button (using Persistent ID)
            view = None
            if doc_id:
                view = discord.ui.View(timeout=None)
                # Custom ID format: share_summary:<doc_id>
                button = discord.ui.Button(label="Share to Channel", style=discord.ButtonStyle.primary, emoji="📢", custom_id=f"share_summary:{doc_id}")
                view.add_item(button)
            
            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1 and view:
                    # Attach view to the last chunk
                    await summary_channel.send(chunk, view=view)
                else:
                    await summary_channel.send(chunk)
            
            # Mark as complete
            await message.add_reaction("✅")
            logger.info(f"Successfully summarized {len(messages_to_summarize)} messages from {target_channel.name} ({target_channel.guild.name})")
            
        except discord.Forbidden:
            await message.add_reaction("❌")
            logger.warning(f"Forbidden access during summary generation for channel {target_channel_id}")
            return f"Bot does not have permission to access channel {target_channel_id}."
        except Exception as e:
            logger.error(f"Error summarizing channel: {e}", exc_info=True)
            await message.add_reaction("❌")
            await summary_channel.send(
                f"**Channel Summary Request Failed**\n"
                f"Channel: <#{target_channel_id}>\n"
                f"Requested by: {message.author.mention}\n\n"
                f"❌ Error: {str(e)}"
            )
        
        return None  # Don't send anything to the command channel
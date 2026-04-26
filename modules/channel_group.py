import os
import discord
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from google.cloud import firestore
from modules.utils import smart_chunk_message, get_admin_roles

logger = logging.getLogger(__name__)

class ChannelGroup:
    def __init__(self, gemini_model, firestore_client, lore_manager=None):
        self.gemini_model = gemini_model
        self.db = firestore_client
        self.lore_manager = lore_manager
        self.name = "group"
        self.admin_roles = get_admin_roles()

        # Get the summary output channel ID
        try:
            channel_id_str = os.environ.get("LOTSLARP_BOT_SUMMARY_CHANNEL_ID")
            if not channel_id_str:
                channel_id_str = os.environ.get("LOTSLARP_BOT_REPORT_CHANNEL_ID", "0")
            
            self.summary_channel_id = int(channel_id_str.strip().strip("'").strip('"'))
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid LOTSLARP_BOT_SUMMARY_CHANNEL_ID or REPORT_CHANNEL_ID: {e}")
            self.summary_channel_id = 0

    async def run(self, client: discord.Client, message: discord.Message):
        """
        Handles group-related commands.
        """
        # Check Permissions
        has_permission = False
        if isinstance(message.author, discord.Member):
            for role in message.author.roles:
                if role.name in self.admin_roles:
                    has_permission = True
                    break
        
        if not has_permission:
            await message.channel.send("🚫 You do not have permission to run this command.")
            return

        # Normalize content for parsing by ensuring spaces around mentions
        normalized_content = message.content.replace("<#", " <#")
        parts = normalized_content.split()
        
        # /lotslarp group ...
        if len(parts) < 3:
            await message.channel.send("""Usage:
`/lotslarp group list` - List all groups
`/lotslarp group <name> add <#channel>` - Add channel to a group
`/lotslarp group <name> remove <#channel>` - Remove channel from a group
`/lotslarp group <name> rename <new_name>` - Rename a group
`/lotslarp group <name> summarize` - Summarize the group (last 30 days)""")
            return

        subcommand = parts[2].lower()

        if subcommand == "list":
            await self.list_groups(client, message)
        else:
            # Check for /lotslarp group <name> <action> [args]
            # Special case: /lotslarp group add <#channel> -> Default group 'General'
            if subcommand == "add" and message.channel_mentions:
                await self.add_to_group(message, "General")
            elif subcommand == "summarize" and len(parts) == 3:
                await self.summarize_group(client, message, "General")
            elif len(parts) >= 4:
                group_name = parts[2]
                action = parts[3].lower()
                
                if action == "add":
                    await self.add_to_group(message, group_name)
                elif action == "remove":
                    await self.remove_from_group(message, group_name)
                elif action == "rename":
                    if len(parts) < 5:
                        await message.channel.send(f"Usage: `/lotslarp group {group_name} rename <new_name>`")
                    else:
                        new_name = " ".join(parts[4:])
                        await self.rename_group(message, group_name, new_name)
                elif action == "summarize":
                    await self.summarize_group(client, message, group_name)
                else:
                    await message.channel.send(f"Unknown action `{action}` for group `{group_name}`.")
            else:
                await message.channel.send("Invalid command format. Use `/lotslarp group list` for help.")

    async def list_groups(self, client, message):
        if not self.db:
            await message.channel.send("❌ Database unavailable.")
            return

        try:
            groups_ref = self.db.collection('channel_groups')
            docs = await asyncio.to_thread(groups_ref.get)
            
            if not docs:
                await message.channel.send("No channel groups found.")
                return

            # Collect and sort groups by name
            all_groups = []
            for doc in docs:
                data = doc.to_dict()
                name = data.get('name', doc.id)
                channels = data.get('channels', [])
                all_groups.append({'name': name, 'channels': channels})
            
            # Case-insensitive alphabetical sort
            all_groups.sort(key=lambda x: x['name'].lower())

            response = "**Channel Groups:**\n"
            for g in all_groups:
                # Resolve channel mentions and sort them alphabetically as well
                mentions = []
                for cid in g['channels']:
                    channel = client.get_channel(int(cid))
                    if channel:
                        mentions.append((channel.name.lower(), f"<#{cid}>"))
                    else:
                        mentions.append(("", f"<#{cid}>"))
                
                # Sort mentions by channel name
                mentions.sort(key=lambda x: x[0])
                mention_strings = [m[1] for m in mentions]
                
                response += f"• **{g['name']}**: {', '.join(mention_strings) if mention_strings else 'No channels'}\n"
            
            await message.channel.send(response)
        except Exception as e:
            logger.error(f"Error listing groups: {e}", exc_info=True)
            await message.channel.send(f"❌ Error listing groups: {e}")

    async def add_to_group(self, message, group_name):
        if not message.channel_mentions:
            await message.channel.send("Please mention the channel(s) you want to add.")
            return

        if not self.db:
            await message.channel.send("❌ Database unavailable.")
            return

        try:
            doc_id = group_name.lower().replace(" ", "_")
            doc_ref = self.db.collection('channel_groups').document(doc_id)
            
            doc = await asyncio.to_thread(doc_ref.get)
            if doc.exists:
                data = doc.to_dict()
                channels = set(data.get('channels', []))
                # Update name display to match casing if it exists
                actual_name = data.get('name', group_name)
            else:
                channels = set()
                actual_name = group_name
            
            added = []
            already_present = []
            for channel in message.channel_mentions:
                cid_str = str(channel.id)
                if cid_str not in channels:
                    channels.add(cid_str)
                    added.append(channel.mention)
                else:
                    already_present.append(channel.mention)
            
            if already_present:
                await message.channel.send(f"⚠️ **Note:** {', '.join(already_present)} is already in group `{actual_name}`.")

            if not added:
                return

            await asyncio.to_thread(doc_ref.set, {
                'name': actual_name,
                'channels': list(channels),
                'updated_at': datetime.now(timezone.utc)
            }, merge=True)
            
            await message.channel.send(f"✅ Added {', '.join(added)} to group `{actual_name}`.")
        except Exception as e:
            logger.error(f"Error adding to group: {e}", exc_info=True)
            await message.channel.send(f"❌ Error adding to group: {e}")

    async def remove_from_group(self, message, group_name):
        if not message.channel_mentions:
            await message.channel.send("Please mention the channel(s) you want to remove.")
            return

        if not self.db:
            await message.channel.send("❌ Database unavailable.")
            return

        try:
            doc_id = group_name.lower().replace(" ", "_")
            doc_ref = self.db.collection('channel_groups').document(doc_id)
            
            doc = await asyncio.to_thread(doc_ref.get)
            if not doc.exists:
                await message.channel.send(f"Group `{group_name}` does not exist.")
                return
            
            data = doc.to_dict()
            channels = set(data.get('channels', []))
            actual_name = data.get('name', group_name)
            
            removed = []
            for channel in message.channel_mentions:
                cid_str = str(channel.id)
                if cid_str in channels:
                    channels.remove(cid_str)
                    removed.append(channel.mention)
            
            if not removed:
                await message.channel.send(f"None of the mentioned channels were in group `{actual_name}`.")
                return

            if not channels:
                # Last channel removed, delete the group
                await asyncio.to_thread(doc_ref.delete)
                await message.channel.send(f"✅ Removed {', '.join(removed)} from group `{actual_name}`. Group is now empty and has been deleted.")
            else:
                await asyncio.to_thread(doc_ref.set, {
                    'channels': list(channels),
                    'updated_at': datetime.now(timezone.utc)
                }, merge=True)
                await message.channel.send(f"✅ Removed {', '.join(removed)} from group `{actual_name}`.")
        except Exception as e:
            logger.error(f"Error removing from group: {e}", exc_info=True)
            await message.channel.send(f"❌ Error removing from group: {e}")

    async def rename_group(self, message, old_group_name, new_name):
        if not self.db:
            await message.channel.send("❌ Database unavailable.")
            return

        try:
            old_doc_id = old_group_name.lower().replace(" ", "_")
            new_doc_id = new_name.lower().replace(" ", "_")
            
            old_doc_ref = self.db.collection('channel_groups').document(old_doc_id)
            old_doc = await asyncio.to_thread(old_doc_ref.get)
            
            if not old_doc.exists:
                await message.channel.send(f"Group `{old_group_name}` does not exist.")
                return
            
            data = old_doc.to_dict()
            
            # Check if new name already exists
            new_doc_ref = self.db.collection('channel_groups').document(new_doc_id)
            if new_doc_id != old_doc_id:
                new_doc = await asyncio.to_thread(new_doc_ref.get)
                if new_doc.exists:
                    await message.channel.send(f"❌ A group with name `{new_name}` already exists.")
                    return

            # Update data
            data['name'] = new_name
            data['updated_at'] = datetime.now(timezone.utc)
            
            # Write new doc
            await asyncio.to_thread(new_doc_ref.set, data)
            
            # Delete old doc if IDs differ
            if new_doc_id != old_doc_id:
                await asyncio.to_thread(old_doc_ref.delete)
                
            await message.channel.send(f"✅ Group `{old_group_name}` has been renamed to `{new_name}`.")
        except Exception as e:
            logger.error(f"Error renaming group: {e}", exc_info=True)
            await message.channel.send(f"❌ Error renaming group: {e}")

    async def summarize_group(self, client, message, group_name):
        if not self.db:
            await message.channel.send("❌ Database unavailable.")
            return

        doc_id = group_name.lower().replace(" ", "_")
        doc_ref = self.db.collection('channel_groups').document(doc_id)
        doc = await asyncio.to_thread(doc_ref.get)
        
        if not doc.exists:
            await message.channel.send(f"Group `{group_name}` does not exist.")
            return
        
        data = doc.to_dict()
        channel_ids = data.get('channels', [])
        actual_name = data.get('name', group_name)
        
        if not channel_ids:
            await message.channel.send(f"Group `{actual_name}` has no channels.")
            return

        await message.channel.send(f"⏳ Gathering history for group `{actual_name}` ({len(channel_ids)} channels) for the last 30 days... This may take a moment.")
        
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        
        # Dictionary to group logs by a base name
        # We store: { base_name: { 'all_channels': [names], 'logs': [(name, msgs)] } }
        grouped_data = {}
        
        for cid in channel_ids:
            try:
                channel = client.get_channel(int(cid))
                if not channel:
                    try:
                        channel = await client.fetch_channel(int(cid))
                    except Exception as e:
                        logger.warning(f"Could not fetch channel {cid}: {e}")
                        continue
                
                # Determine base name for grouping
                base_name = channel.name.replace("-and-friends", "").lower()
                if base_name not in grouped_data:
                    grouped_data[base_name] = {'all_channels': [], 'logs': []}
                
                grouped_data[base_name]['all_channels'].append(channel.name)

                if not channel.permissions_for(channel.guild.me).read_message_history:
                    continue
                
                messages = []
                async for msg in channel.history(limit=1000, after=thirty_days_ago, oldest_first=True):
                    if msg.author.bot or not msg.content.strip():
                        continue
                    
                    content = msg.content
                    for user in msg.mentions:
                        content = content.replace(f'<@{user.id}>', f'@{user.display_name}')
                    for role in msg.role_mentions:
                        content = content.replace(f'<@&{role.id}>', f'@{role.name}')
                    
                    messages.append(f"[{msg.created_at.strftime('%Y-%m-%d %H:%M')}] {msg.author.display_name}: {content}")
                
                if messages:
                    grouped_data[base_name]['logs'].append((channel.name, messages))
            except Exception as e:
                logger.error(f"Error processing channel {cid}: {e}")

        # Filter out groups with zero messages total
        active_groups = {k: v for k, v in grouped_data.items() if v['logs']}

        if not active_groups:
            await message.channel.send(f"No recent activity found in any of the channels in group `{actual_name}`.")
            return

        group_context = []
        channels_processed = len(active_groups)
        
        for base_name, data in active_groups.items():
            merged_content = ""
            # Show ALL channels in this subgroup in the header
            channel_headers = [f"#{name}" for name in sorted(data['all_channels'])]
            merged_content += f"--- Channels: {', '.join(channel_headers)} ---\n"
            
            for name, msgs in data['logs']:
                merged_content += f"\n[Logs for #{name}]\n" + "\n".join(msgs)
            group_context.append(merged_content)

        # AI Summarization
        if self.gemini_model:
            await message.channel.send(f"🪄 Generating group report for `{actual_name}`...")
            
            def _generate_summary_sync(prompt_to_send):
                try:
                    response = self.gemini_model.generate_content(prompt_to_send)
                    return response.text
                except Exception as e:
                    logger.error(f"Failed to generate summary from Gemini: {e}", exc_info=True)
                    return f"Error generating summary: {e}"

            try:
                all_text = "\n\n".join(group_context)
                
                lore_context = ""
                if self.lore_manager:
                    try:
                        lore_context = await self.lore_manager.get_relevant_lore(all_text[:8000])
                    except Exception as e:
                        logger.error(f"Error fetching lore for group summary: {e}")

                # Dynamic length guidance based on the number of processed channels
                if channels_processed <= 2:
                    length_instruction = "For EACH active channel group, provide approximately 3 detailed paragraphs summarizing the events."
                elif channels_processed <= 4:
                    length_instruction = "For EACH active channel group, provide approximately 2 detailed paragraphs summarizing the events."
                else:
                    length_instruction = "For EACH active channel group, provide 1 concise paragraph followed by a list of bullet points for key highlights."

                prompt = f"""You are an AI Storyteller assistant for a LARP community. You are providing a group summary for multiple Discord channels over the last 30 days.

YOUR TASK:
1. Start with a clear, bold header: # 📊 Group Summary: {actual_name}
2. Provide a general overview paragraph summarizing the high-level themes and major events across all these channels.
3. {length_instruction}
4. Use clear Markdown subheaders for each channel group (e.g., ## 📍 #channel-name).
5. If a channel had no activity, just mention that briefly under its subheader.
6. Maintain a professional, narrative, and immersive tone.
7. Integrate any relevant lore context provided to make the summary more accurate to the world.

Lore Context:
{lore_context}

Logs:
{all_text}"""
                
                summary_text = await asyncio.to_thread(_generate_summary_sync, prompt)
                
                # Determine output channel
                target_output_channel = None
                if self.summary_channel_id:
                    target_output_channel = client.get_channel(self.summary_channel_id)
                
                if not target_output_channel:
                    target_output_channel = message.channel
                    if self.summary_channel_id:
                         await message.channel.send(f"⚠️ Configured summary channel not found. Sending summary here instead.")

                chunks = smart_chunk_message(summary_text, 1950)
                for chunk in chunks:
                    await target_output_channel.send(chunk)
                
                await message.add_reaction("✅")
                if target_output_channel.id != message.channel.id:
                    await message.channel.send(f"✅ Group summary for `{actual_name}` sent to {target_output_channel.mention}.")
            except Exception as e:
                logger.error(f"An error occurred during group summary generation: {e}", exc_info=True)
                await message.channel.send(f"❌ Error: Group summary generation failed. ({e})")
        else:
            await message.channel.send("❌ Gemini API not configured. Cannot generate summary.")

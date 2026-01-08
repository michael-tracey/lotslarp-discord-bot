import os
import discord
import logging
from datetime import datetime, timezone
from google.cloud import firestore
from modules.utils import smart_chunk_message

logger = logging.getLogger(__name__)

async def cleanup_old_archives(client: discord.Client, firestore_client):
    """
    Queries Firestore for 'pending' archive channels.
    Checks deletion_date. If passed, deletes the channel and updates DB.
    Generates a report to LOTSLARP_BOT_SUMMARY_CHANNEL_ID.
    """
    if not firestore_client:
        logger.error("Firestore client not available. Skipping archive cleanup.")
        return

    logger.info("Starting archive cleanup check (using Firestore)...")
    
    deleted_channels_info = []
    pending_deletion_info = []
    
    try:
        # Query for all pending archives
        docs = firestore_client.collection('archived_channels').where('status', '==', 'pending').stream()
        
        for doc in docs:
            data = doc.to_dict()
            channel_id = int(doc.id)
            deletion_date = data.get('deletion_date')
            guild_id = data.get('guild_id')
            channel_name = data.get('channel_name', 'Unknown')
            jump_url = data.get('last_message_url', '')
            
            if not deletion_date:
                logger.warning(f"Document {doc.id} missing deletion_date.")
                continue
            
            # Ensure deletion_date is timezone-aware (UTC)
            if deletion_date.tzinfo is None:
                deletion_date = deletion_date.replace(tzinfo=timezone.utc)
            
            now = datetime.now(timezone.utc)
            
            if now >= deletion_date:
                # Time to delete
                try:
                    channel = client.get_channel(channel_id)
                    if channel:
                        await channel.delete(reason="Stale Archive Cleanup")
                        logger.info(f"Deleted channel {channel_name} ({channel_id}).")
                        
                        # Update Firestore
                        doc.reference.update({'status': 'deleted'})
                        
                        guild_name = channel.guild.name if channel.guild else "Unknown Server"
                        deleted_channels_info.append(f"• **{guild_name}** -> `#{channel_name}`")
                    else:
                        logger.warning(f"Channel {channel_id} not found (already deleted?). Marking as deleted in DB.")
                        doc.reference.update({'status': 'deleted'})
                        deleted_channels_info.append(f"• **Unknown Server** -> `#{channel_name}` (Already gone)")
                        
                except discord.Forbidden:
                    logger.error(f"Permission denied deleting channel {channel_id}.")
                    # Don't update status, retry next time? Or log error in report.
                except Exception as e:
                    logger.error(f"Error deleting channel {channel_id}: {e}")
            else:
                # Still pending
                time_left = deletion_date - now
                days_left = time_left.days
                
                # Fetch guild name for report if possible
                guild_name = "Unknown Server"
                if guild_id:
                    guild = client.get_guild(guild_id)
                    if guild:
                        guild_name = guild.name
                
                if jump_url:
                    # The whole label is now the link, satisfying the "no intro text" and "no Jump to Archive text" request
                    pending_info = f"• `{days_left} days left`: [{guild_name} -> #{channel_name}]({jump_url})"
                else:
                    pending_info = f"• `{days_left} days left`: **{guild_name}** -> `#{channel_name}`"
                
                pending_deletion_info.append(pending_info)

    except Exception as e:
        logger.error(f"Error querying Firestore for archives: {e}", exc_info=True)
        return

    logger.info(f"Archive cleanup complete. Processed {len(deleted_channels_info)} deletions.")

    # --- Generate Report ---
    summary_channel_id_str = os.environ.get("LOTSLARP_BOT_SUMMARY_CHANNEL_ID")
    if not summary_channel_id_str:
        logger.warning("LOTSLARP_BOT_SUMMARY_CHANNEL_ID not set. Skipping cleanup report.")
        return

    try:
        summary_channel = client.get_channel(int(summary_channel_id_str))
        if not summary_channel:
             logger.warning(f"Could not find summary channel with ID {summary_channel_id_str}.")
             return
        
        report_content = f"**🗑️ Daily Archive Cleanup Report - {datetime.now().strftime('%Y-%m-%d')}**\n\n"
        
        if deleted_channels_info:
            report_content += "**Deleted Channels:**\n" + "\n".join(deleted_channels_info) + "\n\n"
        else:
            report_content += "**Deleted Channels:**\n(None)\n\n"
            
        if pending_deletion_info:
            report_content += "**Pending Deletion:**\n" + "\n".join(pending_deletion_info)
        else:
            report_content += "**Pending Deletion:**\n(None)"

        chunks = smart_chunk_message(report_content)
        for chunk in chunks:
            await summary_channel.send(chunk)
            
    except ValueError:
        logger.error("Invalid LOTSLARP_BOT_SUMMARY_CHANNEL_ID format.")
    except Exception as e:
        logger.error(f"Failed to send cleanup report: {e}")

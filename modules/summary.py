import datetime
import logging
import discord
import asyncio # Added this import
from google.cloud.firestore_v1.base_client import BaseClient
from google.cloud.firestore_v1 import FieldFilter

class Summary:
    def __init__(self, db_client: BaseClient):
        self.db = db_client
        self.collection_ref = self.db.collection('summary_messages')
        logging.info("Summary module initialized with Firestore client.")

    async def cache_message(self, message: discord.Message):
        """
        Caches a message as a new document in Firestore, enriching it with metadata
        and replacing mention IDs with readable names.
        """
        await asyncio.to_thread(self._cache_message_sync, message)

    def _cache_message_sync(self, message: discord.Message):
        doc_ref = self.collection_ref.document(str(message.id))

        # Start with original content
        processed_content = message.content

        # Replace user mentions (<@123...>) with their display names (@username)
        for user in message.mentions:
            processed_content = processed_content.replace(f'<@{user.id}>', f'@{user.display_name}')

        # Replace role mentions (<@&123...>) with the role name (@rolename)
        for role in message.role_mentions:
            processed_content = processed_content.replace(f'<@&{role.id}>', f'@{role.name}')
        
        # Check if the channel is a thread and get parent info
        parent_channel_id = None
        parent_channel_name = None
        if isinstance(message.channel, discord.Thread):
            parent_channel_id = message.channel.parent_id
            parent_channel_name = message.channel.parent.name if message.channel.parent else None

        # Build the data document
        doc_data = {
            'message_id': message.id,
            'channel_id': message.channel.id,
            'channel_name': message.channel.name,
            'parent_channel_id': parent_channel_id,
            'parent_channel_name': parent_channel_name,
            'guild_id': message.guild.id,
            'guild_name': message.guild.name,
            'author_id': message.author.id,
            'author_name': message.author.name,
            'author_display_name': message.author.display_name,
            'message_content': processed_content, # Store the processed content
            'message_url': message.jump_url,
            'timestamp': message.created_at, # Use original message timestamp
            'cached_at': datetime.datetime.utcnow(), # Keep a record of when we cached it
            'sent_date': None,
            'is_reply': message.reference is not None,
            'attachments': [att.url for att in message.attachments]
        }
        
        doc_ref.set(doc_data)
        logging.info(f"Cached and enriched message {message.id} to Firestore.")

    async def get_messages_for_digest(self):
        """Fetches all unsent messages, ordered by timestamp."""
        return await asyncio.to_thread(self._get_messages_for_digest_sync)

    def _get_messages_for_digest_sync(self):
        query = self.collection_ref.where(filter=FieldFilter('sent_date', '==', None)).order_by('timestamp')
        docs = query.stream()
        
        # Firestore documents need to be converted to a format that the calling function expects.
        # The original code returned a list of tuples from fetchall(). We will return a list of dicts.
        # The calling function `send_digest_pdf` accesses by index, so we'll adapt it.
        # Expected format: (channel_id, guild_id, author_name, message_content, message_url, id)
        
        messages = []
        for doc in docs:
            data = doc.to_dict()
            messages.append([
                data.get('channel_id'),
                data.get('guild_id'),
                data.get('author_name'),
                data.get('message_content'),
                data.get('message_url'),
                doc.id,
                data.get('author_display_name'),
                data.get('channel_name'),
                data.get('timestamp')
            ])
        return messages

    async def get_messages_since(self, start_date):
        """Fetches all messages since a given start date."""
        return await asyncio.to_thread(self._get_messages_since_sync, start_date)

    def _get_messages_since_sync(self, start_date):
        query = self.collection_ref.where(filter=FieldFilter('timestamp', '>=', start_date)).order_by('timestamp')
        docs = query.stream()
        
        messages = []
        for doc in docs:
            data = doc.to_dict()
            messages.append([
                data.get('channel_id'),
                data.get('guild_id'),
                data.get('author_name'),
                data.get('message_content'),
                data.get('message_url'),
                doc.id,
                data.get('author_display_name'),
                data.get('channel_name')
            ])
        return messages

    async def mark_messages_as_sent(self, message_ids):
        """Marks a list of messages as sent by setting their sent_date in a batch."""
        if not message_ids:
            return
        await asyncio.to_thread(self._mark_messages_as_sent_sync, message_ids)

    def _mark_messages_as_sent_sync(self, message_ids):
        batch = self.db.batch()
        sent_time = datetime.datetime.utcnow()
        
        for msg_id in message_ids:
            doc_ref = self.collection_ref.document(str(msg_id))
            batch.update(doc_ref, {'sent_date': sent_time})
            
        batch.commit()
        logging.info(f"Marked {len(message_ids)} messages as sent in Firestore.")

    def _delete_collection_in_batches(self, query, batch_size):
        """Helper to delete documents from a query in batches."""
        docs = query.limit(batch_size).stream()
        deleted = 0

        while True:
            batch = self.db.batch()
            doc_count_in_batch = 0
            for doc in docs:
                batch.delete(doc.reference)
                doc_count_in_batch += 1
            
            if doc_count_in_batch == 0:
                break

            batch.commit()
            deleted += doc_count_in_batch
            
            # Fetch the next batch
            docs = query.limit(batch_size).stream()

        return deleted

    async def clear_all_messages(self):
        """Deletes all documents from the summary_messages collection."""
        await asyncio.to_thread(self._clear_all_messages_sync)

    def _clear_all_messages_sync(self):
        logging.warning("Clearing all messages from the Firestore summary_messages collection.")
        query = self.collection_ref
        deleted_count = self._delete_collection_in_batches(query, 100)
        logging.info(f"Cleared {deleted_count} messages from Firestore.")

    async def delete_old_messages(self):
        """Deletes messages and summaries older than six weeks."""
        await asyncio.to_thread(self._delete_old_messages_sync)

    def _delete_old_messages_sync(self):
        six_weeks_ago = datetime.datetime.utcnow() - datetime.timedelta(weeks=6)
        
        # 1. Clean up summary_messages
        logging.info(f"Deleting messages older than {six_weeks_ago} from summary_messages...")
        query_messages = self.collection_ref.where(filter=FieldFilter('timestamp', '<', six_weeks_ago))
        deleted_messages = self._delete_collection_in_batches(query_messages, 100)
        
        # 2. Clean up channel_summaries
        logging.info(f"Deleting summaries older than {six_weeks_ago} from channel_summaries...")
        summaries_ref = self.db.collection('channel_summaries')
        query_summaries = summaries_ref.where(filter=FieldFilter('created_at', '<', six_weeks_ago))
        deleted_summaries = self._delete_collection_in_batches(query_summaries, 100)
        
        if deleted_messages > 0 or deleted_summaries > 0:
            logging.info(f"Cleanup complete. Deleted {deleted_messages} messages and {deleted_summaries} summaries.")
        else:
            logging.info("No old data found to delete.")

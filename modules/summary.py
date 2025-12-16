import datetime
import logging
import discord
from google.cloud.firestore_v1.base_client import BaseClient

class Summary:
    def __init__(self, db_client: BaseClient):
        self.db = db_client
        self.collection_ref = self.db.collection('summary_messages')
        logging.info("Summary module initialized with Firestore client.")

    def cache_message(self, message: discord.Message):
        """
        Caches a message as a new document in Firestore, enriching it with metadata
        and replacing mention IDs with readable names.
        """
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

    def get_messages_for_digest(self):
        """Fetches all unsent messages, ordered by timestamp."""
        query = self.collection_ref.where('sent_date', '==', None).order_by('timestamp')
        docs = query.stream()
        
        # Firestore documents need to be converted to a format that the calling function expects.
        # The original code returned a list of tuples from fetchall(). We will return a list of dicts.
        # The calling function `send_digest_pdf` accesses by index, so we'll adapt it.
        # Expected format: (channel_id, guild_id, author_name, message_content, message_url, id)
        
        messages = []
        for doc in docs:
            data = doc.to_dict()
            # The original code used the DB's autoincrement ID. Here, we use the Firestore document ID (which is the message_id string)
            messages.append([
                data.get('channel_id'),
                data.get('guild_id'),
                data.get('author_name'),
                data.get('message_content'),
                data.get('message_url'),
                doc.id  # Use the document ID (string)
            ])
        return messages

    def get_messages_since(self, start_date):
        """Fetches all messages since a given start date."""
        query = self.collection_ref.where('timestamp', '>=', start_date).order_by('timestamp')
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
                doc.id
            ])
        return messages

    def mark_messages_as_sent(self, message_ids):
        """Marks a list of messages as sent by setting their sent_date in a batch."""
        if not message_ids:
            return
        
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

    def clear_all_messages(self):
        """Deletes all documents from the summary_messages collection."""
        logging.warning("Clearing all messages from the Firestore summary_messages collection.")
        query = self.collection_ref
        deleted_count = self._delete_collection_in_batches(query, 100)
        logging.info(f"Cleared {deleted_count} messages from Firestore.")

    def delete_old_messages(self):
        """Deletes messages older than six weeks."""
        six_weeks_ago = datetime.datetime.utcnow() - datetime.timedelta(weeks=6)
        logging.info(f"Deleting messages older than {six_weeks_ago}...")
        
        query = self.collection_ref.where('timestamp', '<', six_weeks_ago)
        deleted_count = self._delete_collection_in_batches(query, 100)
        
        if deleted_count > 0:
            logging.info(f"Deleted {deleted_count} old messages from Firestore.")
        else:
            logging.info("No old messages found to delete.")

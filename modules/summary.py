import sqlite3
import datetime

class Summary:
    def __init__(self, db_path):
        self.db_path = db_path
        self._create_table()

    def _create_table(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS summary_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    author_id INTEGER NOT NULL,
                    author_name TEXT NOT NULL,
                    message_content TEXT NOT NULL,
                    message_url TEXT NOT NULL,
                    timestamp DATETIME NOT NULL
                )
            ''')
            # Add sent_date column if it doesn't exist
            cursor.execute("PRAGMA table_info(summary_messages)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'sent_date' not in columns:
                cursor.execute('ALTER TABLE summary_messages ADD COLUMN sent_date DATETIME')
            conn.commit()

    def cache_message(self, message):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO summary_messages (message_id, channel_id, guild_id, author_id, author_name, message_content, message_url, timestamp, sent_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                message.id,
                message.channel.id,
                message.guild.id,
                message.author.id,
                message.author.name,
                message.content,
                message.jump_url,
                datetime.datetime.utcnow(),
                None
            ))
            conn.commit()

    def get_messages_for_digest(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT channel_id, guild_id, author_name, message_content, message_url, id FROM summary_messages WHERE sent_date IS NULL ORDER BY timestamp ASC')
            return cursor.fetchall()

    def get_messages_since(self, start_date):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT channel_id, guild_id, author_name, message_content, message_url, id FROM summary_messages WHERE timestamp >= ? ORDER BY timestamp ASC', (start_date,))
            return cursor.fetchall()

    def mark_messages_as_sent(self, message_ids):
        if not message_ids:
            return
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            placeholders = ','.join('?' for _ in message_ids)
            cursor.execute(f'UPDATE summary_messages SET sent_date = ? WHERE id IN ({placeholders})', (datetime.datetime.utcnow(), *message_ids))
            conn.commit()

    def clear_all_messages(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM summary_messages')
            conn.commit()

    def delete_old_messages(self):
        six_weeks_ago = datetime.datetime.utcnow() - datetime.timedelta(weeks=6)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM summary_messages WHERE timestamp < ?', (six_weeks_ago,))
            conn.commit()

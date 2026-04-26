import logging
import asyncio
from google.cloud import firestore
import re

logger = logging.getLogger(__name__)

class LoreManager:
    def __init__(self, firestore_client):
        self.db = firestore_client
        self.cache_lock = asyncio.Lock()
        self.keyword_map = {}  # keyword -> set(doc_ids)
        self.doc_cache = {}    # doc_id -> formatted entry string
        self._titles = []      # sorted list of all titles (for autocomplete)
        self.last_refresh = None
        self._initialized = False

    async def _refresh_cache(self):
        """Fetches all glossary entries and rebuilds the in-memory keyword map."""
        async with self.cache_lock:
            try:
                logger.info("Refreshing Lore Glossary cache...")
                collection_ref = self.db.collection('lore_glossary')
                docs = await asyncio.to_thread(lambda: list(collection_ref.stream()))

                new_keyword_map = {}
                new_doc_cache = {}
                new_titles = []

                for doc in docs:
                    data = doc.to_dict()
                    content = data.get('content', '')
                    title = data.get('title', '')
                    keywords = data.get('keywords', [])

                    entry_text = f"**{title}**: {content}"
                    new_doc_cache[doc.id] = entry_text
                    if title:
                        new_titles.append(title)

                    for kw in keywords:
                        kw_lower = kw.lower().strip()
                        if kw_lower:
                            if kw_lower not in new_keyword_map:
                                new_keyword_map[kw_lower] = set()
                            new_keyword_map[kw_lower].add(doc.id)

                self.keyword_map = new_keyword_map
                self.doc_cache = new_doc_cache
                self._titles = sorted(new_titles, key=str.lower)
                self._initialized = True
                logger.info(f"Lore Glossary refreshed. Loaded {len(self.doc_cache)} entries and {len(self.keyword_map)} keywords.")
            except Exception as e:
                logger.error(f"Failed to refresh Lore Glossary: {e}", exc_info=True)

    async def _invalidate_cache(self) -> None:
        """Clears in-memory cache; next access will re-fetch from Firestore."""
        async with self.cache_lock:
            self.keyword_map = {}
            self.doc_cache = {}
            self._titles = []
            self._initialized = False

    # ── Read helpers ──────────────────────────────────────────────────────────

    async def get_titles(self) -> list:
        """Returns a sorted list of all entry titles (used for autocomplete)."""
        if not self._initialized:
            await self._refresh_cache()
        return list(self._titles)

    async def list_entries(self) -> list:
        """Returns all lore entries as a list of dicts, sorted by title."""
        try:
            docs = await asyncio.to_thread(
                lambda: list(self.db.collection('lore_glossary').stream())
            )
            entries = [
                {
                    'id': doc.id,
                    'title': doc.to_dict().get('title', ''),
                    'content': doc.to_dict().get('content', ''),
                    'keywords': doc.to_dict().get('keywords', []),
                }
                for doc in docs
            ]
            return sorted(entries, key=lambda e: e['title'].lower())
        except Exception as e:
            logger.error(f"Failed to list lore entries: {e}")
            return []

    async def _find_doc_by_title(self, title: str):
        """Returns (doc_ref, data) for the entry matching title, or (None, None)."""
        title_stripped = title.strip()
        try:
            # Exact match first (uses index)
            query = self.db.collection('lore_glossary').where('title', '==', title_stripped)
            docs = await asyncio.to_thread(lambda: list(query.stream()))
            if docs:
                return docs[0].reference, docs[0].to_dict()
            # Case-insensitive fallback
            all_docs = await asyncio.to_thread(
                lambda: list(self.db.collection('lore_glossary').stream())
            )
            for doc in all_docs:
                data = doc.to_dict()
                if data.get('title', '').lower() == title_stripped.lower():
                    return doc.reference, data
        except Exception as e:
            logger.error(f"Error finding lore entry '{title}': {e}")
        return None, None

    # ── Write helpers ─────────────────────────────────────────────────────────

    async def add_entry(self, title: str, content: str, keywords: list) -> bool:
        """Creates a new lore entry. Returns True on success."""
        try:
            data = {
                'title': title.strip(),
                'content': content.strip(),
                'keywords': [k.lower().strip() for k in keywords if k.strip()],
            }
            await asyncio.to_thread(lambda: self.db.collection('lore_glossary').add(data))
            await self._invalidate_cache()
            logger.info(f"Lore entry added: '{title}'")
            return True
        except Exception as e:
            logger.error(f"Failed to add lore entry '{title}': {e}")
            return False

    async def update_entry(self, title: str, content: str, keywords: list = None) -> bool:
        """Updates an existing entry by title. Returns True on success, False if not found."""
        ref, _ = await self._find_doc_by_title(title)
        if ref is None:
            return False
        try:
            updates = {'content': content.strip()}
            if keywords is not None:
                updates['keywords'] = [k.lower().strip() for k in keywords if k.strip()]
            await asyncio.to_thread(lambda: ref.update(updates))
            await self._invalidate_cache()
            logger.info(f"Lore entry updated: '{title}'")
            return True
        except Exception as e:
            logger.error(f"Failed to update lore entry '{title}': {e}")
            return False

    async def remove_entry(self, title: str) -> bool:
        """Deletes an entry by title. Returns True on success, False if not found."""
        ref, _ = await self._find_doc_by_title(title)
        if ref is None:
            return False
        try:
            await asyncio.to_thread(lambda: ref.delete())
            await self._invalidate_cache()
            logger.info(f"Lore entry removed: '{title}'")
            return True
        except Exception as e:
            logger.error(f"Failed to remove lore entry '{title}': {e}")
            return False

    # ── RAG lookup ────────────────────────────────────────────────────────────

    async def get_relevant_lore(self, text: str) -> str:
        """
        Scans the input text for known keywords and returns a formatted string 
        of relevant lore entries.
        """
        if not self._initialized:
            await self._refresh_cache()

        # Tokenize input text (simplified)
        # We split by non-alphanumeric to find words
        # We also want to check for multi-word keywords if possible.
        # For simplicity/efficiency, we'll check if our known keywords exist in the text.
        # To avoid O(N*M) where N=text length and M=num keywords, we can do a pass.
        
        # Lowercase the text for matching
        text_lower = text.lower()
        
        matched_doc_ids = set()
        matched_keywords = []

        for kw, doc_ids in self.keyword_map.items():
            if kw in text_lower:
                matched_doc_ids.update(doc_ids)
                matched_keywords.append(kw)

        if not matched_doc_ids:
            return ""

        logger.info(f"RAG Match Found! Keywords: {', '.join(matched_keywords)}. Found {len(matched_doc_ids)} unique lore entries.")

        # Retrieve content
        lore_entries = []
        for doc_id in matched_doc_ids:
            if doc_id in self.doc_cache:
                lore_entries.append(self.doc_cache[doc_id])
        
        if not lore_entries:
            return ""

        header = "\n\n*** RELEVANT GAME WORLD KNOWLEDGE ***\nUse this information to better understand the context of the messages.\n"
        return header + "\n".join(lore_entries) + "\n\n"

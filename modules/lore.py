import logging
import asyncio
from google.cloud import firestore
import re

logger = logging.getLogger(__name__)

class LoreManager:
    def __init__(self, firestore_client):
        self.db = firestore_client
        self.cache_lock = asyncio.Lock()
        self.keyword_map = {} # Map of keyword -> set(doc_ids)
        self.doc_cache = {}   # Map of doc_id -> content string
        self.last_refresh = None
        self._initialized = False

    async def _refresh_cache(self):
        """Fetches all glossary entries and builds the keyword map."""
        async with self.cache_lock:
            try:
                logger.info("Refreshing Lore Glossary cache...")
                collection_ref = self.db.collection('lore_glossary')
                docs = await asyncio.to_thread(lambda: list(collection_ref.stream()))
                
                new_keyword_map = {}
                new_doc_cache = {}

                for doc in docs:
                    data = doc.to_dict()
                    content = data.get('content', '')
                    title = data.get('title', '')
                    keywords = data.get('keywords', [])
                    
                    # Format the entry for injection
                    entry_text = f"**{title}**: {content}"
                    new_doc_cache[doc.id] = entry_text

                    for kw in keywords:
                        kw_lower = kw.lower().strip()
                        if kw_lower:
                            if kw_lower not in new_keyword_map:
                                new_keyword_map[kw_lower] = set()
                            new_keyword_map[kw_lower].add(doc.id)
                
                self.keyword_map = new_keyword_map
                self.doc_cache = new_doc_cache
                self._initialized = True
                logger.info(f"Lore Glossary refreshed. Loaded {len(self.doc_cache)} entries and {len(self.keyword_map)} keywords.")
            except Exception as e:
                logger.error(f"Failed to refresh Lore Glossary: {e}", exc_info=True)

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

        logger.info(f"RAG Match Found! Keywords: {', '.join(matched_keywords)}")

        # Retrieve content
        lore_entries = []
        for doc_id in matched_doc_ids:
            if doc_id in self.doc_cache:
                lore_entries.append(self.doc_cache[doc_id])
        
        if not lore_entries:
            return ""

        header = "\n\n*** RELEVANT GAME WORLD KNOWLEDGE ***\nUse this information to better understand the context of the messages.\n"
        return header + "\n".join(lore_entries) + "\n\n"

import logging
import sqlite3
import asyncio
from jinja2 import Environment, FileSystemLoader
import discord

logger = logging.getLogger(__name__)

# A simple list of common stop words.
STOP_WORDS = set([
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "he",
    "in", "is", "it", "its", "of", "on", "that", "the", "to", "was", "were",
    "will", "with", "what", "when", "where", "who", "whom", "why", "how",
    "i", "you", "me", "my", "mine", "your", "yours", "he", "him", "his", "she",
    "her", "hers", "it", "its", "we", "us", "our", "ours", "they", "them",
    "their", "theirs", "this", "these", "those"
])


class Huh:
    def __init__(self, database_filename: str = "huh.db"): # Must accept database_filename
        self.db_name = database_filename
        # self.template_env = Environment(loader=FileSystemLoader("templates")) # If you had this, ensure it's also correct or removed if not used
        logger.info(f"Huh command instance initialized with DB: {self.db_name}")
    
    # ... rest of the Huh class (async def run, _format_page_content, etc.)


    async def run(self, client: discord.Client, message: discord.Message):
        logger.info(f"Command started: /huh by {message.author} in {message.channel}")

        parts = message.content.split()
        if len(parts) < 2:
            return "Please provide a title to search for."
        title_search = " ".join(parts[1:])
        
        result, suggestions = await asyncio.to_thread(self._search_database, title_search)

        if result:
            logger.info(f"Huh: Found exact match for '{title_search}'")
            return self._format_page_content(result)
        elif suggestions:
            logger.info(f"Huh: No exact match for '{title_search}', found {len(suggestions)} suggestions")
            unique_suggestions = list(set(suggestions))
            unique_suggestions = [s for s in unique_suggestions if s.lower() != title_search.lower()]
            unique_suggestions.sort(key=lambda s: (len(s), s.lower()))
            top_suggestions = unique_suggestions[:10]

            if len(top_suggestions) == 1:
                suggested_title = top_suggestions[0]
                result, _ = await asyncio.to_thread(self._search_database, suggested_title)
                if result:
                    did_you_mean_message = f"Did you mean: **{suggested_title}**?\n\n"
                    return did_you_mean_message + self._format_page_content(result)
                else:
                    await message.delete()
                    dm_message = f"I found a suggestion '{suggested_title}', but couldn't retrieve its content."
                    await message.author.send(dm_message)
                    return None
            elif len(top_suggestions) > 1:
                await message.delete()
                suggestions_str = "\n".join([f"- {s}" for s in top_suggestions])
                dm_message = (
                    f"No exact match found for '{title_search}'. Did you mean one of these?\n\n"
                    f"{suggestions_str}\n\n"
                    f"You can refine your search by replying here in this DM (e.g., `/huh [new search term]`)."
                )
                await message.author.send(dm_message)
                return None
            else:
                await message.delete()
                dm_message = f"Sorry, I couldn't find any other relevant suggestions matching '{title_search}'."
                await message.author.send(dm_message)
                return None
        else:
            logger.info(f"Huh: No matches or suggestions for '{title_search}'")
            await message.delete()
            dm_message = f"Sorry, I couldn't find any content matching the significant terms in: '{title_search}'."
            await message.author.send(dm_message)
            return None

    def _search_database(self, title_search):

        try:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row
            with conn:
                cursor = conn.cursor()
                cursor.execute("SELECT title, breadcrumbs, markdown_content, url, is_power, power_level, power_cost FROM pages WHERE LOWER(title) = LOWER(?)", (title_search,))
                result = cursor.fetchone()

                if result:
                    return result, None
                else:
                    search_words_tokenized = title_search.lower().split()
                    filtered_search_words = [word for word in search_words_tokenized if word not in STOP_WORDS]

                    if not filtered_search_words:
                        return None, []

                    conditions = " AND ".join(["LOWER(title) LIKE LOWER(?)"] * len(filtered_search_words))
                    suggestions_query = f"SELECT title FROM pages WHERE {conditions}"
                    query_params = [f"%{word}%" for word in filtered_search_words]
                    
                    cursor.execute(suggestions_query, query_params)
                    suggestions = [row['title'] for row in cursor.fetchall()]
                    return None, suggestions
        except Exception as e:
            logger.exception(f"Error during database operation or processing for '{title_search}': {e}")
            return None, None


    def _format_page_content(self, page_data: sqlite3.Row): # Return type can be str or list[str]
        """Helper function to format the page content for display."""
        page_title = page_data['title']
        breadcrumbs = page_data['breadcrumbs']
        content = page_data['markdown_content']
        url = page_data['url']
        is_power = page_data['is_power']
        power_level = page_data['power_level']
        power_cost = page_data['power_cost']

        header = f"# {page_title}\n"
        if breadcrumbs: 
            header += f"**{breadcrumbs}**\n"
        
        if url and not url.startswith('files/'): 
            share_link = f"[BNS SRD]({url})\n\n"
            header += share_link

        if is_power:
            power_info = f"**Power Level:** {power_level if power_level is not None else 'N/A'}"
            if power_cost: 
                power_info += f" **Cost:** {power_cost}"
            header += power_info + "\n"
        
        page_content_str = "" # Initialize to empty string
        if content: 
            page_content_str = str(content).replace("_Share Link_", "") # Ensure content is string

            if not is_power:
                powers_header_text = "## POWERS"
                powers_index = page_content_str.find(powers_header_text)
                if powers_index != -1:
                    content_before_powers = page_content_str[:powers_index]
                    
                    conn_powers = sqlite3.connect(self.db_name)
                    conn_powers.row_factory = sqlite3.Row
                    cursor_powers = conn_powers.cursor()
                    
                    powers_query_str = """
                        SELECT title, power_level, power_cost FROM pages
                        WHERE category = 'Discipline Power'
                        AND parent_discipline_title = ?
                        AND LOWER(title) != LOWER(?)
                        ORDER BY CAST(power_level AS INTEGER), title 
                    """ 
                    cursor_powers.execute(powers_query_str, (page_title, page_title))
                    powers_data = cursor_powers.fetchall()
                    conn_powers.close()

                    if powers_data:
                        temp_powers_list = []
                        for p_row in powers_data:
                            title_str = p_row['title']
                            level_str = f"Level {p_row['power_level'] if p_row['power_level'] is not None else 'N/A'}"
                            cost_str = ""
                            if p_row['power_cost']:
                                cost_str = f", Cost {p_row['power_cost']}"
                            temp_powers_list.append(f"- {title_str} ({level_str}{cost_str})")
                        powers_list_str = "\n".join(temp_powers_list)
                        page_content_str = f"{content_before_powers}{powers_header_text}\n{powers_list_str}"
                    else:
                        page_content_str = f"{content_before_powers}{powers_header_text}\nNone"
                    
                    page_content_str += "\n\n_You may /huh any individual powers in the list above._"
            
            page_content_str = self._clean_and_format_content(page_content_str)
        
        full_response = (header + "\n" + page_content_str if page_content_str else header).strip()


        if len(full_response) > 1950: # Use a conservative limit like 1950

            chunks = []
            current_chunk = ""
            
            # Try to split by paragraphs first
            paragraphs = full_response.split('\n\n')
            for i, paragraph in enumerate(paragraphs):
                if len(current_chunk) + len(paragraph) + (2 if current_chunk else 0) > 1950:
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = paragraph
                else:
                    current_chunk += ('\n\n' if current_chunk else '') + paragraph
            if current_chunk: # Add the last processed chunk
                chunks.append(current_chunk)

            # If any chunk is still too large, try splitting by lines
            final_chunks_pass1 = []
            needs_hard_split = False
            for chunk_pass1 in chunks:
                if len(chunk_pass1) > 1950:
                    needs_hard_split = True
                    current_line_chunk = ""
                    for line in chunk_pass1.split('\n'):
                        if len(current_line_chunk) + len(line) + (1 if current_line_chunk else 0) > 1950:
                            if current_line_chunk:
                                final_chunks_pass1.append(current_line_chunk)
                            current_line_chunk = line
                        else:
                            current_line_chunk += ('\n' if current_line_chunk else '') + line
                    if current_line_chunk: # Add last processed line chunk
                        final_chunks_pass1.append(current_line_chunk)
                else:
                    final_chunks_pass1.append(chunk_pass1)
            
            if not needs_hard_split:

                return final_chunks_pass1

            # Final pass: hard split any remaining oversized chunks
            final_chunks_pass2 = []
            for chunk_pass2 in final_chunks_pass1:
                if len(chunk_pass2) > 1950:
                    for i_split in range(0, len(chunk_pass2), 1950):
                        final_chunks_pass2.append(chunk_pass2[i_split:i_split + 1950])
                else:
                    final_chunks_pass2.append(chunk_pass2)

            return final_chunks_pass2
            
        return full_response

    def _find_next_header(self, content_text, start_index):
        # This helper might not be used if "## POWERS" is reliably found
        next_header_index = -1
        for header_prefix in ["## ", "### ", "#### ", "##### ", "###### "]:
            next_h = content_text.find(header_prefix, start_index)
            if next_h != -1 and (next_header_index == -1 or next_h < next_header_index):
                next_header_index = next_h
        return next_header_index

    def _clean_and_format_content(self, content_text):
        if not isinstance(content_text, str): # Ensure it's a string
            content_text = str(content_text)
            
        replacements = [(" \n", "\n"), (" #\n", "\n#"), (" ##\n", "\n##"), (" ###\n", "\n###")]
        for old, new in replacements:
            content_text = content_text.replace(old, new)
        # This part for ensuring headers are on new lines might need refinement
        # For now, just basic cleaning
        
        while "\n\n\n" in content_text:
            content_text = content_text.replace("\n\n\n", "\n\n")
        return content_text.strip()

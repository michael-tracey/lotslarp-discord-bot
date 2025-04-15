import logging
import sqlite3
from jinja2 import Environment, FileSystemLoader

logging.basicConfig(level=logging.INFO)

class Huh:
    def __init__(self):
        self.template_env = Environment(loader=FileSystemLoader("templates"))

    def run(self, message):
        logging.info(f"processins message in huh: {message}")
        parts = message.content.split()
        if len(parts) < 2:
            return "Please provide a title to search for."
        title = " ".join(parts[1:])
        logging.info(f"Looking up content for title: {title}")

        try:
            conn = sqlite3.connect("vamp_wiki_content.db")
            with conn:
                cursor = conn.cursor()
                cursor.execute("SELECT title, breadcrumbs, markdown_content, url, is_power, power_level, power_cost FROM pages WHERE LOWER(title) = LOWER(?)", (title,))
                result = cursor.fetchone()

                if result:
                    page_title, breadcrumbs, content, url, is_power, power_level, power_cost = result
                    header = f"# {page_title}\n**{breadcrumbs}**\n"                    
                    if not url.startswith('files/'):
                        share_link = f"[BNS SRD]({url})\n\n"
                        header += share_link

                    if is_power:
                        power_info = f"**Power Level:** {power_level}"
                        power_info += f" **Cost:** {power_cost}" if power_cost else ""
                        header += power_info + "\n"

                    # Process "Powers" section
                    powers_header = "## POWERS"
                    powers_index = content.find(powers_header)
                    if powers_index != -1:
                        # Extract content before "Powers"
                        content_before_powers = content[:powers_index]

                        # Find the end of the "Powers" section (next header or end of content)
                        next_header_index = find_next_header(content, powers_index + len(powers_header))
                        if next_header_index == -1:
                            next_header_index = len(content)

                        if not is_power:
                            powers_query = """SELECT title, power_level, power_cost FROM pages
                                            WHERE category = 'Discipline Power'
                                            AND parent_discipline_title = ?
                                            AND LOWER(title) != LOWER(?)
                                            ORDER BY power_level
                        """
                            # Extract powers from the database and format them
                            cursor.execute(powers_query, (page_title, page_title))
                            powers = cursor.fetchall()

                            if powers:
                                powers_list = "\n".join([f"- {p[0]} (Level {p[1]}{', Cost ' + str(p[2]) if p[2] else ''})" for p in powers])
                                content = f"{content_before_powers}{powers_header}\n{powers_list}"
                            else:
                                content = f"{content_before_powers}{powers_header}\nNone"

                            content += "\n\n_You may /huh any individual powers in the list above._"

                    content = content.replace("_Share Link_", "")

                    # Consolidate whitespace and ensure headers are at the start of lines
                    content = clean_and_format_content(content)

                    # Replace multiple blank lines with a single blank line, and return.
                    while "\n\n\n" in content:
                        content = content.replace("\n\n\n", "\n\n")
                    return header + content
                else:
                    # If no exact match, search for similar titles
                    suggestions = []
                    for word in title.split():
                        cursor.execute("SELECT title FROM pages WHERE LOWER(title) LIKE LOWER(?)", (f"%{word}%",))
                        suggestions.extend([row[0] for row in cursor.fetchall()])

                    # Remove duplicates, the original title, and consolidate
                    if suggestions:
                        suggestions = list(set(suggestions))
                        suggestions = [s for s in suggestions if s.lower() != title]
                        suggestions_str = "\n".join(f"- {suggestion}" for suggestion in suggestions)
                    else:
                        suggestions_str = ""  # Empty string if no suggestions

                    # Return suggestions or no match message
                    if suggestions_str:
                        return f"No exact match found for '{title}'.\n\nSimilar titles include:\n{suggestions_str}"
                    else:
                        return f"No content found for title: '{title}'"


        except Exception as e:
            logging.exception(f"Error during database operation: {e}")
            return "An error occurred while processing the command."

def find_next_header(content, start_index):
    """Finds the index of the next header in the content."""
    next_header_index = -1
    for header_prefix in ["## ", "### ", "#### ", "##### ", "###### "]:
        next_h = content.find(header_prefix, start_index)
        if next_h != -1 and (next_header_index == -1 or next_h < next_header_index):
            next_header_index = next_h
    return next_header_index

def clean_and_format_content(content):
    """Cleans whitespace and ensures headers start on new lines."""
    replacements = [(" \n", "\n"), (" #\n", "\n#"), (" ##\n", "\n##"), (" ###\n", "\n###")]
    for old, new in replacements:
        content = content.replace(old, new)
    for prefix in ["\n#", "\n##", "\n###"]:
        content = content.replace(prefix, prefix)
    return content
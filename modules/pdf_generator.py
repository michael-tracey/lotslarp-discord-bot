from fpdf import FPDF
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'Discord Summary Digest', 0, 1, 'C')
        self.set_font('Arial', '', 8)
        self.cell(0, 10, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}", 0, 1, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, title):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, title, 0, 1, 'L')
        self.ln(5)

    def chapter_body(self, body):
        self.set_font('Arial', '', 12)
        self.multi_cell(0, 10, body)
        self.ln()

    def add_summary_section(self, summary_text):
        self.add_page()
        self.chapter_title('Executive Summary')
        self.chapter_body(summary_text)

    def add_messages_section(self, messages):
        self.add_page()
        self.chapter_title('Message Details')
        
        current_guild = ""
        current_channel = ""

        for message in messages:
            guild_name = message.get('guild_name', 'Unknown Server')
            channel_name = message.get('channel_name', 'Unknown Channel')

            if guild_name != current_guild:
                self.set_font('Arial', 'B', 12)
                self.cell(0, 10, f"Server: {guild_name}", 0, 1, 'L')
                self.ln(2)
                current_guild = guild_name
                current_channel = "" # Reset channel when server changes

            if channel_name != current_channel:
                self.set_font('Arial', 'I', 11)
                self.cell(0, 10, f"  Channel: {channel_name}", 0, 1, 'L')
                self.ln(1)
                current_channel = channel_name
            
            self.set_font('Arial', '', 10)
            author = message.get('author_name', 'Unknown Author')
            content = message.get('message_content', '[no content]')
            # FPDF uses latin-1 encoding by default, so we need to encode properly
            content = content.encode('latin-1', 'replace').decode('latin-1')
            author = author.encode('latin-1', 'replace').decode('latin-1')

            self.multi_cell(0, 5, f"    Author: {author}\n    Message: {content}\n")
            self.ln(2)

def create_digest_pdf(file_path, executive_summary, messages):
    """
    Generates a PDF digest.

    Args:
        file_path (str): The full path to save the PDF file.
        executive_summary (str): The AI-generated summary text.
        messages (list): A list of message dictionaries.
    """
    try:
        pdf = PDF()
        
        # Add summary
        pdf.add_summary_section(executive_summary)
        
        # Add detailed messages
        pdf.add_messages_section(messages)
        
        pdf.output(file_path)
        logger.info(f"Successfully created PDF digest at {file_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to create PDF digest: {e}", exc_info=True)
        return False

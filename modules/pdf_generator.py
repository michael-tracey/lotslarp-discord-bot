from fpdf import FPDF
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.background_color = (40, 40, 40)
        self.text_color = (220, 220, 220)
        self.link_color = (100, 150, 255)
        self.header_color = (255, 255, 255)

    def add_page(self, orientation='', format='', same=False):
        super().add_page(orientation, format, same)
        self.set_fill_color(*self.background_color)
        self.rect(0, 0, self.w, self.h, 'F')
        self.set_text_color(*self.text_color)

    def header(self):
        self.set_text_color(*self.header_color)
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'Discord Summary Digest', 0, 1, 'C')
        self.set_text_color(*self.text_color)
        self.set_font('Arial', '', 8)
        self.cell(0, 10, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}", 0, 1, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(*self.text_color)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, title):
        self.set_font('Arial', 'B', 14)
        self.set_text_color(*self.header_color)
        self.cell(0, 10, title, 0, 1, 'L')
        self.set_text_color(*self.text_color)
        self.ln(5)

    def chapter_body(self, body):
        self.set_font('Arial', '', 12)
        # Ensure body is properly encoded for FPDF's latin-1 internal encoding
        safe_body = body.encode('latin-1', 'replace').decode('latin-1')
        self.multi_cell(0, 10, safe_body)
        self.ln()

    def add_summary_section(self, summary_text):
        self.add_page()
        self.chapter_title('Executive Summary')
        self.chapter_body(summary_text)

    def add_messages_section(self, messages):
        self.add_page()
        self.chapter_title('Message Details')
        
        for message in messages:
            guild_name = message.get('guild_name', 'Unknown Server')
            channel_name = message.get('channel_name', 'Unknown Channel')
            author = message.get('author_name', 'Unknown Author')
            content = message.get('message_content', '[no content]')
            url = message.get('message_url', '')

            # --- Create clickable link section ---
            self.set_font('Arial', 'B', 11)
            self.set_text_color(*self.link_color)
            link_text = f"Server: {guild_name} > Channel: {channel_name} (by {author})"
            # Encode text for FPDF's internal encoding
            safe_link_text = link_text.encode('latin-1', 'replace').decode('latin-1')
            self.cell(0, 6, safe_link_text, 0, 1, 'L', link=url)
            self.set_text_color(*self.text_color)
            
            # --- Add message content ---
            self.set_font('Arial', '', 10)
            safe_content = content.encode('latin-1', 'replace').decode('latin-1')
            self.multi_cell(0, 5, " " * 5 + safe_content) # Indent content
            self.ln(4)

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

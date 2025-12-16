from fpdf import FPDF
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class PDF(FPDF):
    def __init__(self, *args, title='Discord Summary Digest', **kwargs):
        super().__init__(*args, **kwargs)
        self.title = title
        # A more refined dark theme palette
        self.background_color = (35, 39, 42)
        self.text_color = (220, 221, 222)
        self.header_color = (114, 137, 218) # Discord's "Blurple"
        self.link_color = (0, 176, 240)
        self.line_color = (88, 101, 111)

    def add_page(self, orientation='', format='', same=False):
        super().add_page(orientation, format, same)
        self.set_fill_color(self.background_color[0], self.background_color[1], self.background_color[2])
        self.rect(0, 0, self.w, self.h, 'F')
        self.set_text_color(self.text_color[0], self.text_color[1], self.text_color[2])

    def header(self):
        self.set_text_color(self.header_color[0], self.header_color[1], self.header_color[2])
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, self.title, 0, 1, 'C')
        self.set_text_color(self.text_color[0], self.text_color[1], self.text_color[2])
        self.set_font('Arial', '', 9)
        self.cell(0, 8, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}", 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(self.text_color[0], self.text_color[1], self.text_color[2])
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, title):
        self.set_font('Arial', 'B', 14)
        self.set_text_color(self.header_color[0], self.header_color[1], self.header_color[2])
        self.cell(0, 6, title, 0, 1, 'L')
        self.set_draw_color(self.line_color[0], self.line_color[1], self.line_color[2])
        self.line(self.get_x(), self.get_y(), self.get_x() + self.w - self.l_margin - self.r_margin, self.get_y())
        self.ln(7)

    def chapter_body(self, body):
        self.set_font('Arial', '', 11)
        self.set_text_color(self.text_color[0], self.text_color[1], self.text_color[2])
        safe_body = body.encode('latin-1', 'replace').decode('latin-1')
        self.multi_cell(0, 6, safe_body)
        self.ln()

    def add_summary_section(self, summary_text):
        self.add_page()
        self.chapter_title('Executive Summary')
        self.chapter_body(summary_text)

    def add_messages_section(self, messages):
        self.add_page()
        self.chapter_title('Message Details')
        
        for i, message in enumerate(messages):
            guild_name = message.get('guild_name', 'Unknown Server')
            channel_name = message.get('channel_name', 'Unknown Channel')
            author = message.get('author_name', 'Unknown Author')
            content = message.get('message_content', '[no content]')
            url = message.get('message_url', '')

            # --- Create clickable link section ---
            self.set_font('Arial', 'B', 10)
            self.set_text_color(self.link_color[0], self.link_color[1], self.link_color[2])
            link_text = f"Server: {guild_name} > #{channel_name} (by {author})"
            safe_link_text = link_text.encode('latin-1', 'replace').decode('latin-1')
            self.cell(0, 5, safe_link_text, 0, 1, 'L', link=url)
            
            # --- Add message content ---
            self.set_text_color(self.text_color[0], self.text_color[1], self.text_color[2])
            self.set_font('Arial', '', 10)
            safe_content = content.encode('latin-1', 'replace').decode('latin-1')
            self.multi_cell(0, 5, " " * 3 + safe_content) # Indent content
            self.ln(2)

            # Add a separator line between messages, but not after the last one
            if i < len(messages) - 1:
                self.set_draw_color(self.line_color[0], self.line_color[1], self.line_color[2])
                self.line(self.get_x(), self.get_y(), self.get_x() + self.w - self.l_margin - self.r_margin, self.get_y())
                self.ln(4)

def create_digest_pdf(file_path, executive_summary, messages, title="Discord Summary Digest"):
    """
    Generates a PDF digest.

    Args:
        file_path (str): The full path to save the PDF file.
        executive_summary (str): The AI-generated summary text.
        messages (list): A list of message dictionaries.
        title (str): The title for the PDF document.
    """
    try:
        pdf = PDF(title=title)
        
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

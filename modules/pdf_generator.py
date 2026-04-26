from fpdf import FPDF
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def safe_encode_text(text):
    """Safely encode text for PDF generation, replacing problematic Unicode characters."""
    if not text:
        return ""
    # Replace common Unicode characters that cause issues
    replacements = {
        '•': '-',  # bullet point
        '–': '-',  # en dash
        '—': '--', # em dash
        '"': '"',  # left double quote
        '"': '"',  # right double quote
        ''': "'",  # left single quote
        ''': "'",  # right single quote
        '…': '...' # ellipsis
    }
    
    safe_text = text
    for unicode_char, replacement in replacements.items():
        safe_text = safe_text.replace(unicode_char, replacement)
    
    # Encode to latin-1 with replacement for any remaining problematic characters
    return safe_text.encode('latin-1', 'replace').decode('latin-1')

class PDF(FPDF):
    def __init__(self, *args, title='Discord Summary Digest', date_range='', **kwargs):
        super().__init__(*args, **kwargs)
        self.title = title
        self.date_range = date_range
        # Light theme palette for better readability
        self.palette_bg = (255, 255, 255)  # White background
        self.palette_text = (33, 37, 41)  # Dark text for readability
        self.palette_header = (114, 137, 218) # Discord's "Blurple"
        self.palette_link = (0, 123, 191)  # Darker blue for links
        self.palette_line = (108, 117, 125)  # Medium gray for lines

    def add_page(self, orientation='', format='', same=False):
        super().add_page(orientation, format, same)
        self.set_fill_color(*self.palette_bg)
        self.rect(0, 0, self.w, self.h, 'F')
        self.set_text_color(*self.palette_text)

    def header(self):
        self.set_text_color(*self.palette_header)
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, safe_encode_text(self.title), 0, 1, 'C')
        
        # Add date range if provided
        if self.date_range:
            self.set_text_color(*self.palette_text)
            self.set_font('Arial', 'B', 11)
            self.cell(0, 8, safe_encode_text(self.date_range), 0, 1, 'C')
        
        self.set_text_color(*self.palette_text)
        self.set_font('Arial', '', 9)
        self.cell(0, 8, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}", 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(*self.palette_text)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, title):
        self.set_font('Arial', 'B', 14)
        self.set_text_color(*self.palette_header)
        self.cell(0, 6, safe_encode_text(title), 0, 1, 'L')
        self.set_draw_color(*self.palette_line)
        self.line(self.get_x(), self.get_y(), self.get_x() + self.w - self.l_margin - self.r_margin, self.get_y())
        self.ln(7)

    def chapter_body(self, body):
        self.set_font('Arial', '', 11)
        self.set_text_color(*self.palette_text)
        safe_body = safe_encode_text(body)
        self.multi_cell(0, 6, safe_body)
        self.ln()

    def add_summary_section(self, summary_text, message_stats=None):
        self.add_page()
        self.chapter_title('Storyteller Summary')
        
        # Add message statistics if provided
        if message_stats:
            self.set_font('Arial', 'B', 10)
            self.set_text_color(*self.palette_text)
            self.cell(0, 6, 'Message Statistics:', 0, 1, 'L')
            self.set_font('Arial', '', 10)
            for stat_line in message_stats:
                # Use a simple dash instead of bullet character to avoid encoding issues
                safe_stat_line = safe_encode_text(stat_line)
                self.cell(0, 5, f"- {safe_stat_line}", 0, 1, 'L')
            self.ln(5)
        
        self.chapter_body(summary_text)

    def add_messages_section(self, messages):
        # Don't add a new page - continue on the same page
        self.chapter_title('Message Details')
        
        for i, message in enumerate(messages):
            guild_name = message.get('guild_name', 'Unknown Server')
            channel_name = message.get('channel_name', 'Unknown Channel')
            author = message.get('author_name', 'Unknown Author')
            content = message.get('message_content', '[no content]')
            url = message.get('message_url', '')

            # --- Create clickable link section ---
            self.set_font('Arial', 'B', 10)
            self.set_text_color(*self.palette_link)
            link_text = f"Server: {guild_name} > #{channel_name} (by {author})"
            safe_link_text = safe_encode_text(link_text)
            self.cell(0, 5, safe_link_text, 0, 1, 'L', link=url)
            
            # --- Add message content ---
            self.set_text_color(*self.palette_text)
            self.set_font('Arial', '', 10)
            safe_content = safe_encode_text(content)
            self.multi_cell(0, 5, " " * 3 + safe_content) # Indent content
            self.ln(2)

            # Add a separator line between messages, but not after the last one
            if i < len(messages) - 1:
                self.set_draw_color(*self.palette_line)
                self.line(self.get_x(), self.get_y(), self.get_x() + self.w - self.l_margin - self.r_margin, self.get_y())
                self.ln(4)


def create_digest_pdf(file_path, executive_summary, messages, title="Discord Summary Digest", date_range="", message_stats=None):
    """
    Generates a PDF digest.

    Args:
        file_path (str): The full path to save the PDF file.
        executive_summary (str): The AI-generated summary text.
        messages (list): A list of message dictionaries.
        title (str): The title for the PDF document.
        date_range (str): The date range for the report.
        message_stats (list): List of message statistics strings.
    """
    try:
        pdf = PDF(title=title, date_range=date_range)
        
        # Add summary with statistics
        pdf.add_summary_section(executive_summary, message_stats)
        
        # Add detailed messages (no page break)
        pdf.add_messages_section(messages)
        
        pdf.output(file_path)
        logger.info(f"Successfully created PDF digest at {file_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to create PDF digest: {e}", exc_info=True)
        return False

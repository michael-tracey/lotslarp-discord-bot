def smart_chunk_message(text: str, limit: int = 1950) -> list[str]:
    """
    Splits a long message into chunks that respect Discord's character limit.
    It tries to split by paragraphs (\n\n), then by lines (\n), and finally
    hard splits if necessary, to avoid breaking words or formatting where possible.
    """
    if not text:
        return []

    if len(text) <= limit:
        return [text]

    chunks = []
    current_chunk = ""

    # 1. Try to split by paragraphs
    paragraphs = text.split('\n\n')
    for paragraph in paragraphs:
        # Check if adding this paragraph (plus separator) exceeds limit
        added_len = len(paragraph) + (2 if current_chunk else 0) # 2 for '\n\n'
        
        if len(current_chunk) + added_len > limit:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = paragraph
        else:
            current_chunk += ('\n\n' if current_chunk else '') + paragraph
    
    if current_chunk:
        chunks.append(current_chunk)

    # 2. If any chunk is still too large, split by lines
    final_chunks_pass1 = []
    for chunk in chunks:
        if len(chunk) > limit:
            current_line_chunk = ""
            lines = chunk.split('\n')
            for line in lines:
                added_len = len(line) + (1 if current_line_chunk else 0) # 1 for '\n'
                
                if len(current_line_chunk) + added_len > limit:
                    if current_line_chunk:
                        final_chunks_pass1.append(current_line_chunk)
                    current_line_chunk = line
                else:
                    current_line_chunk += ('\n' if current_line_chunk else '') + line
            
            if current_line_chunk:
                final_chunks_pass1.append(current_line_chunk)
        else:
            final_chunks_pass1.append(chunk)

    # 3. Final pass: hard split any remaining oversized chunks (rare, but possible for huge code blocks or gibberish)
    final_chunks_pass2 = []
    for chunk in final_chunks_pass1:
        if len(chunk) > limit:
            for i in range(0, len(chunk), limit):
                final_chunks_pass2.append(chunk[i:i + limit])
        else:
            final_chunks_pass2.append(chunk)

    return final_chunks_pass2

from datetime import date, timedelta
import calendar

def get_date_of_weekday_in_month(year: int, month: int, ordinal: int, weekday: int) -> date:
    """
    Finds the date of the nth (ordinal) occurrence of a specific weekday in a month.
    
    Args:
        year: The year.
        month: The month (1-12).
        ordinal: The nth occurrence (e.g., 1 for 1st, 2 for 2nd). 
                 Supports -1 for the last occurrence.
        weekday: The day of the week (0=Monday, 6=Sunday).
    
    Returns:
        datetime.date object of the specified day.
    """
    if ordinal == -1:
        # Find the last occurrence
        # Start from the last day of the month
        last_day_num = calendar.monthrange(year, month)[1]
        d = date(year, month, last_day_num)
        while d.weekday() != weekday:
            d -= timedelta(days=1)
        return d
    
    # Start from the 1st of the month
    d = date(year, month, 1)
    # Advance to the first occurrence of the weekday
    while d.weekday() != weekday:
        d += timedelta(days=1)
    
    # Advance by (ordinal - 1) weeks
    d += timedelta(weeks=ordinal - 1)
    
    # Check if we spilled over to the next month (invalid ordinal for this month)
    if d.month != month:
         raise ValueError(f"There is no {ordinal}-th weekday {weekday} in month {month}/{year}")
         
    return d

def get_previous_game_date(current_date: date, ordinal: int = 1, weekday: int = 5) -> date:
    """
    Calculates the date of the "last game".
    
    Logic:
    - Determine the game date for the current month.
    - If current_date > current_month_game_date, return current_month_game_date.
    - Else, return the game date for the previous month.
    """
    try:
        current_month_game = get_date_of_weekday_in_month(current_date.year, current_date.month, ordinal, weekday)
    except ValueError:
        # Fallback if calculation fails (e.g. 5th Saturday in a month with only 4)
        # Treat as if "game hasn't happened yet" this month?
        # Let's assume valid config for now, or default to previous month.
        current_month_game = current_date + timedelta(days=1) # Force fallback

    if current_date > current_month_game:
        return current_month_game
    else:
        # Get previous month
        first = current_date.replace(day=1)
        last_month = first - timedelta(days=1)
        return get_date_of_weekday_in_month(last_month.year, last_month.month, ordinal, weekday)


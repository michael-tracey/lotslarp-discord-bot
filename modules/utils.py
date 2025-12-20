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

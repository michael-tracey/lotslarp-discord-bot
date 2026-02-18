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

import os
import subprocess
import asyncio
import logging

logger = logging.getLogger(__name__)

async def compress_pdf(input_path: str, output_path: str, power: int = 2) -> bool:
    """
    Compresses a PDF using Ghostscript.
    
    Args:
        input_path: Path to the source PDF.
        output_path: Path where the compressed PDF should be saved.
        power: Compression power (0-4):
               0: default (low compression, high quality)
               1: prepress (high quality, 300 dpi)
               2: printer (good quality, 300 dpi)
               3: ebook (medium quality, 150 dpi)
               4: screen (low quality, 72 dpi)
    
    Returns:
        bool: True if compression was successful, False otherwise.
    """
    settings = {
        0: "/default",
        1: "/prepress",
        2: "/printer",
        3: "/ebook",
        4: "/screen"
    }
    
    pdf_setting = settings.get(power, "/printer")
    
    gs_command = [
        "gs",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        f"-dPDFSETTINGS={pdf_setting}",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        f"-sOutputFile={output_path}",
        input_path
    ]
    
    logger.info(f"Compressing PDF {input_path} to {output_path} using {pdf_setting} settings...")
    
    try:
        process = await asyncio.create_subprocess_exec(
            *gs_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            original_size = os.path.getsize(input_path)
            new_size = os.path.getsize(output_path)
            reduction = (original_size - new_size) / original_size * 100
            logger.info(f"PDF compression successful. Size reduced from {original_size/1024/1024:.2f}MB to {new_size/1024/1024:.2f}MB ({reduction:.1f}% reduction).")
            return True
        else:
            logger.error(f"Ghostscript failed with exit code {process.returncode}")
            logger.error(f"GS STDERR: {stderr.decode()}")
            return False
    except Exception as e:
        logger.error(f"Error during PDF compression: {e}", exc_info=True)
        return False

class JobQueue:
    """A queue that limits concurrency and allows waiters to track their position."""
    def __init__(self, max_concurrent=2):
        self.max_concurrent = max_concurrent
        self.active_count = 0
        self.waiters = []  # List of (asyncio.Future, asyncio.Event)
        self._change_event = asyncio.Event()

    async def run_task(self, task_func, *args, update_callback=None, **kwargs):
        """
        Runs a task through the queue.
        
        Args:
            task_func: The coroutine function to run.
            update_callback: Optional async function that takes (position) as an argument.
            *args, **kwargs: Arguments for task_func.
        """
        logger.info(f"JobQueue: New task submitted. Active: {self.active_count}/{self.max_concurrent}, Waiters: {len(self.waiters)}")
        
        # If we have space and nobody is waiting, go immediately
        if self.active_count < self.max_concurrent and not self.waiters:
            self.active_count += 1
            logger.info(f"JobQueue: Fast-path. Starting task immediately. New active count: {self.active_count}")
            try:
                return await task_func(*args, **kwargs)
            finally:
                self._release()

        # Otherwise, get in line
        my_future = asyncio.get_event_loop().create_future()
        self.waiters.append(my_future)
        self._notify_change()
        
        pos = len(self.waiters)
        logger.info(f"JobQueue: Task queued at position {pos}. Active: {self.active_count}")

        try:
            last_pos = pos
            if update_callback:
                await update_callback(last_pos)

            while not my_future.done():
                logger.info(f"JobQueue: Waiter (pos {last_pos}) waiting for turn or change event...")
                # Wait for our turn OR for the queue to change
                change_waiter = asyncio.create_task(self._change_event.wait())
                done, pending = await asyncio.wait(
                    [my_future, change_waiter],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                for t in pending:
                    t.cancel()

                if my_future.done():
                    logger.info("JobQueue: Waiter's turn has arrived!")
                    break
                
                # The queue moved, update our position
                self._change_event.clear()
                try:
                    new_pos = self.waiters.index(my_future) + 1
                    if new_pos != last_pos:
                        logger.info(f"JobQueue: Waiter position updated: {last_pos} -> {new_pos}")
                        last_pos = new_pos
                        if update_callback:
                            await update_callback(last_pos)
                except ValueError:
                    # We might have been popped and set_result called, but loop hasn't hit my_future.done()
                    logger.info("JobQueue: Waiter no longer in waiters list, assuming turn is coming.")
            
            logger.info(f"JobQueue: Waiter starting task. Active: {self.active_count}")
            return await task_func(*args, **kwargs)
        finally:
            if my_future in self.waiters:
                self.waiters.remove(my_future)
                self._notify_change()
            self._release()

    def _release(self):
        """Called when a task finishes to let the next one in."""
        self.active_count -= 1
        self._maybe_start_next()

    def _maybe_start_next(self):
        """Starts the next task in the queue if space is available."""
        while self.active_count < self.max_concurrent and self.waiters:
            self.active_count += 1
            next_waiter = self.waiters.pop(0)
            if not next_waiter.done():
                next_waiter.set_result(True)
            self._notify_change()

    def _notify_change(self):
        """Notifies all waiters that the queue has changed."""
        self._change_event.set()
        # We don't clear it immediately, waiters will clear it after they see it

    @property
    def waiting_count(self):
        return len(self.waiters)

# Shared instance for archiver to ensure cross-module/cross-instance coordination
shared_archive_queue = None

def get_shared_archive_queue(max_concurrent=2):
    global shared_archive_queue
    if shared_archive_queue is None:
        shared_archive_queue = JobQueue(max_concurrent=max_concurrent)
    return shared_archive_queue

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


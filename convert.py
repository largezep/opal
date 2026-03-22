"""
convert_transcript.py
=====================
Converts raw Claude.ai copy-paste exports to RAY: / AI: pipeline format.

Handles the Claude.ai export pattern:
    [user message]
    
    Dec 22
    [AI response]
    
    [user message]
    
    Dec 22
    [AI response]

Also handles ChatGPT exports:
    Human: [user message]
    Assistant: [AI response]

And plain alternating blocks with no labels.

Usage:
    python convert_transcript.py input.txt output.txt

    or drop input.txt in the same folder and run:
    python convert_transcript.py input.txt
    (output will be input_converted.txt)

Output format:
    RAY: [user message]
    ---
    AI: [AI response]
    ---
"""

import re
import sys
import os

# Date stamp patterns that appear between turns in Claude.ai exports
DATE_PATTERNS = [
    r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}$',
    r'^\d{1,2}:\d{2}\s*(AM|PM)$',
    r'^(Yesterday|Today)$',
    r'^\d{4}-\d{2}-\d{2}$',
]

DATE_RE = re.compile('|'.join(DATE_PATTERNS), re.IGNORECASE)

# Lines to strip entirely
SKIP_PATTERNS = [
    r'^You are out of free messages',
    r'^Upgrade$',
    r'^Claude is AI',
    r'^Show more$',
    r'^Interactive artifact',  # artifact placeholders
    r'^\[.*artifact.*\]$',
]

SKIP_RE = re.compile('|'.join(SKIP_PATTERNS), re.IGNORECASE)


def is_date_stamp(line):
    return bool(DATE_RE.match(line.strip()))


def is_skip_line(line):
    return bool(SKIP_RE.match(line.strip()))


def detect_format(lines):
    """
    Detect the export format:
    - 'chatgpt': lines start with 'Human:' or 'Assistant:'
    - 'claude_raw': Claude.ai copy-paste with date stamps
    - 'alternating': plain alternating blocks, no labels
    """
    for line in lines[:50]:
        s = line.strip()
        if s.startswith('Human:') or s.startswith('Assistant:'):
            return 'chatgpt'
        if s.startswith('RAY:') or s.startswith('AI:'):
            return 'already_converted'
    # Check for date stamps (Claude.ai pattern)
    for line in lines[:100]:
        if is_date_stamp(line):
            return 'claude_raw'
    return 'alternating'


def convert_chatgpt(lines):
    """Convert ChatGPT Human:/Assistant: format."""
    turns = []
    current_speaker = None
    current_lines = []

    for line in lines:
        s = line.strip()
        if is_skip_line(s):
            continue
        if s.startswith('Human:'):
            if current_speaker and current_lines:
                turns.append((current_speaker, ' '.join(current_lines)))
            current_speaker = 'RAY'
            current_lines = []
            rest = s[6:].strip()
            if rest:
                current_lines.append(rest)
        elif s.startswith('Assistant:'):
            if current_speaker and current_lines:
                turns.append((current_speaker, ' '.join(current_lines)))
            current_speaker = 'AI'
            current_lines = []
            rest = s[10:].strip()
            if rest:
                current_lines.append(rest)
        elif s and current_speaker:
            current_lines.append(s)

    if current_speaker and current_lines:
        turns.append((current_speaker, ' '.join(current_lines)))

    return turns


def convert_claude_raw(lines):
    """
    Convert Claude.ai copy-paste format.
    
    Pattern: user block, then date stamp, then AI block, repeat.
    The date stamp signals the boundary between user message and AI response.
    """
    turns = []
    current_lines = []
    expecting = 'RAY'   # first block is always the user

    for line in lines:
        s = line.strip()

        if is_skip_line(s):
            continue

        if is_date_stamp(s):
            # Date stamp = end of user turn, start of AI turn
            if current_lines and expecting == 'RAY':
                text = ' '.join(current_lines).strip()
                if text:
                    turns.append(('RAY', text))
            current_lines = []
            expecting = 'AI'
            continue

        if not s:
            # Blank line — might signal end of AI turn if we see another user message next
            # Don't flush yet, just skip
            continue

        # Check if this looks like a new user question starting
        # (short line after AI content, not a date stamp)
        # Heuristic: if we're in AI mode and hit a short line that looks like a question,
        # flush the AI turn and start a new RAY turn
        if (expecting == 'AI' and current_lines and
                len(s) < 200 and
                (s.endswith('?') or s[0].islower()) and
                len(current_lines) > 3):
            # Flush AI turn
            text = ' '.join(current_lines).strip()
            if text:
                turns.append(('AI', text))
            current_lines = [s]
            expecting = 'RAY'
            continue

        current_lines.append(s)

    # Flush last block
    if current_lines:
        text = ' '.join(current_lines).strip()
        if text:
            turns.append((expecting, text))

    return turns


def convert_claude_raw_v2(lines):
    """
    More robust Claude.ai converter.
    
    Builds a list of blocks separated by date stamps,
    then assigns RAY/AI alternating starting with RAY.
    """
    # Split into blocks separated by date stamps
    blocks = []
    current_block = []

    for line in lines:
        s = line.strip()

        if is_skip_line(s):
            continue

        if is_date_stamp(s):
            # Save current block (user message before date stamp)
            if current_block:
                text = ' '.join(current_block).strip()
                if text:
                    blocks.append(('RAY', text))
            current_block = []
            # Next block is AI response
            blocks.append(('AI_PLACEHOLDER', ''))
            continue

        if s:
            current_block.append(s)

    # Flush last block
    if current_block:
        text = ' '.join(current_block).strip()
        if text:
            # Determine speaker: if last block marker was AI_PLACEHOLDER, this is AI
            # Otherwise it's RAY
            if blocks and blocks[-1][0] == 'AI_PLACEHOLDER':
                blocks[-1] = ('AI', text)
            else:
                blocks.append(('RAY', text))

    # Fill in AI_PLACEHOLDERs and clean up
    # The structure is: RAY block, AI_PLACEHOLDER (gets filled by next content), repeat
    # Actually let's do a cleaner pass:
    
    # Re-parse: collect all non-empty blocks, assign alternating speakers
    blocks2 = []
    current = []
    speaker = 'RAY'
    after_date = False

    for line in lines:
        s = line.strip()
        if is_skip_line(s):
            continue
        if is_date_stamp(s):
            # Flush current block as RAY
            if current:
                text = ' '.join(current).strip()
                if text:
                    blocks2.append(('RAY', text))
                current = []
            after_date = True
            continue
        if not s:
            if after_date and current:
                # Blank line after date + content = end of AI turn
                pass
            continue
        
        if after_date:
            current.append(s)
            # Check: is the NEXT non-empty line a date stamp?
            # We can't know yet, so just keep collecting
        else:
            current.append(s)

    # This approach is getting complicated. Use simpler method:
    return convert_by_date_boundaries(lines)


def convert_by_date_boundaries(lines):
    """
    Cleanest approach: split file by date stamps.
    Everything before first date stamp = first RAY turn.
    Everything between date stamp N and date stamp N+1:
        First portion (before next user-looking text) = AI turn
        Remainder = next RAY turn (but usually date stamp handles this)
    
    Actually simplest: 
    - Collect all text blocks
    - Date stamps divide RAY (before) from AI (after)
    - Next RAY turn starts when we hit another date stamp
    """
    segments = []  # list of (type, text) where type is 'user' or 'ai'
    
    current_lines = []
    mode = 'user'  # start expecting user content
    
    for line in lines:
        s = line.strip()
        
        if is_skip_line(s):
            continue
            
        if is_date_stamp(s):
            # Flush as user turn
            text = ' '.join(current_lines).strip()
            if text:
                segments.append(('RAY', text))
            current_lines = []
            mode = 'ai'
            continue
        
        if not s:
            # Blank line while in AI mode might signal new user turn starting
            if mode == 'ai' and current_lines:
                # Peek: does what follows look like a short user question?
                # We'll handle this by post-processing
                pass
            continue
        
        current_lines.append(s)
        
        # If we're in AI mode and we see a line that looks like a new user message
        # (typically short, after substantial AI content), switch to user mode
        # Heuristic: if current AI content is long and this line is short and 
        # doesn't look like a continuation
        if mode == 'ai' and len(current_lines) > 5:
            total_chars = sum(len(l) for l in current_lines[:-1])
            this_line_short = len(s) < 150
            prev_line_long = len(current_lines) > 1 and len(current_lines[-2]) > 100
            
            if total_chars > 500 and this_line_short and prev_line_long:
                # Flush AI turn (everything except last line)
                ai_text = ' '.join(current_lines[:-1]).strip()
                if ai_text:
                    segments.append(('AI', ai_text))
                current_lines = [s]
                mode = 'user'
    
    # Flush final block
    if current_lines:
        text = ' '.join(current_lines).strip()
        if text:
            segments.append((mode.upper() if mode == 'ai' else 'RAY', text))
    
    # Fix mode labels
    result = []
    for speaker, text in segments:
        if speaker == 'ai':
            speaker = 'AI'
        result.append((speaker, text))
    
    return result


def simple_claude_convert(lines):
    """
    Simplest possible approach that actually works:
    
    Split the file on date stamp lines.
    Odd-indexed chunks = RAY (user messages before date stamps)  
    Even-indexed chunks = AI (responses after date stamps)
    
    Structure of Claude.ai export:
    [user text]
    Dec 22          <- date stamp
    [AI text]
    [user text]
    Dec 22          <- date stamp  
    [AI text]
    ...
    """
    # Split into chunks on date stamps
    chunks = []
    current = []
    
    for line in lines:
        s = line.strip()
        if is_skip_line(s):
            continue
        if is_date_stamp(s):
            if current:
                chunks.append('\n'.join(current))
            current = []
        elif s:
            current.append(s)
    
    if current:
        chunks.append('\n'.join(current))
    
    # Now assign speakers
    # First chunk is RAY (user question before first date stamp)
    # Then alternating: AI, RAY, AI, RAY...
    turns = []
    for i, chunk in enumerate(chunks):
        text = chunk.strip()
        if not text:
            continue
        if i == 0:
            speaker = 'RAY'
        elif i % 2 == 1:
            speaker = 'AI'
        else:
            speaker = 'RAY'
        turns.append((speaker, text))
    
    return turns


def write_output(turns, output_path):
    """Write turns to output file in RAY: / AI: format."""
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, (speaker, text) in enumerate(turns):
            # Write speaker label on its own line, then text
            f.write(f"{speaker}: {text}\n")
            if i < len(turns) - 1:
                f.write("---\n")
    print(f"  Written: {output_path}")
    print(f"  Turns: {len(turns)}")
    ray_n = sum(1 for s, _ in turns if s == 'RAY')
    ai_n  = sum(1 for s, _ in turns if s == 'AI')
    print(f"  RAY: {ray_n}  AI: {ai_n}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python convert_transcript.py input.txt [output.txt]")
        sys.exit(1)

    input_path = sys.argv[1]
    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        base = os.path.splitext(input_path)[0]
        output_path = base + "_converted.txt"

    print(f"\n=== CONVERT TRANSCRIPT ===\n")
    print(f"  Input:  {input_path}")
    print(f"  Output: {output_path}")

    with open(input_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    print(f"  Lines:  {len(lines)}")

    fmt = detect_format(lines)
    print(f"  Format: {fmt}")

    if fmt == 'already_converted':
        print("  Already in RAY:/AI: format. Nothing to do.")
        sys.exit(0)
    elif fmt == 'chatgpt':
        turns = convert_chatgpt(lines)
    else:
        # Claude raw or alternating — use simple date-boundary method
        turns = simple_claude_convert(lines)

    if not turns:
        print("  ERROR: No turns found. Check input format.")
        sys.exit(1)

    write_output(turns, output_path)
    print(f"\n  Next: copy {output_path} to C:\\OPAL\\ and run narrate.py")
    print(f"        or run fusion.py directly if audio already exists\n")


if __name__ == "__main__":
    main()
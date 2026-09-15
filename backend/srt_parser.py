import re
from typing import List, Dict, Any

def time_to_seconds(time_str: str) -> float:
    """Converts HH:MM:SS,mmm or MM:SS,mmm string to float seconds."""
    time_str = time_str.strip().replace(',', '.')
    parts = time_str.split(':')
    if len(parts) == 3:
        h, m, s = parts
        return float(h) * 3600 + float(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return float(m) * 60 + float(s)
    return 0.0

def seconds_to_timestamp(seconds: float) -> str:
    """Converts float seconds into readable MM:SS or HH:MM:SS string."""
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def parse_srt(srt_content: str) -> List[Dict[str, Any]]:
    """
    Parses full SRT text into structured block list:
    [{ id, start_sec, end_sec, start_fmt, end_fmt, text }]
    """
    blocks = []
    # Split blocks by double linebreaks or blank lines
    raw_blocks = re.split(r'\n\s*\n', srt_content.strip())
    
    for raw in raw_blocks:
        lines = [line.strip() for line in raw.split('\n') if line.strip()]
        if len(lines) >= 2:
            # First line might be index or timecode
            timecode_line = ""
            text_lines = []
            
            if '-->' in lines[0]:
                timecode_line = lines[0]
                text_lines = lines[1:]
            elif len(lines) >= 3 and '-->' in lines[1]:
                timecode_line = lines[1]
                text_lines = lines[2:]
            else:
                continue
            
            # Parse start and end time
            times = timecode_line.split('-->')
            if len(times) == 2:
                start_sec = time_to_seconds(times[0])
                end_sec = time_to_seconds(times[1])
                raw_text = " ".join(text_lines)
                
                # Remove common transcription service watermarks and website ads
                clean_text = re.sub(r'\(Transcribed by [^\)]+\)', '', raw_text, flags=re.IGNORECASE)
                clean_text = re.sub(r'Go Unlimited to remove this message\.?', '', clean_text, flags=re.IGNORECASE)
                clean_text = re.sub(r'Subtitles by [^\.]+', '', clean_text, flags=re.IGNORECASE)
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                
                if clean_text:
                    blocks.append({
                        "start_sec": start_sec,
                        "end_sec": end_sec,
                        "start_fmt": seconds_to_timestamp(start_sec),
                        "end_fmt": seconds_to_timestamp(end_sec),
                        "text": clean_text
                    })
                
    return blocks

from translator import translate_chunks_parallel

def create_chunks(parsed_blocks: List[Dict[str, Any]], target_word_count: int = 250, overlap_blocks: int = 2) -> List[Dict[str, Any]]:
    """
    Groups subtitle blocks into dynamic context chunks while maintaining exact timestamp bounds.
    Auto-translates non-English transcript chunks to English for cross-lingual search and Q&A.
    """
    chunks = []
    if not parsed_blocks:
        return chunks
        
    i = 0
    while i < len(parsed_blocks):
        current_words = 0
        chunk_blocks = []
        
        j = i
        while j < len(parsed_blocks) and current_words < target_word_count:
            block = parsed_blocks[j]
            chunk_blocks.append(block)
            words_in_block = len(block['text'].split())
            current_words += words_in_block
            j += 1
            
        if chunk_blocks:
            combined_text = " ".join([b['text'] for b in chunk_blocks])
            start_sec = chunk_blocks[0]['start_sec']
            end_sec = chunk_blocks[-1]['end_sec']
            start_fmt = chunk_blocks[0]['start_fmt']
            end_fmt = chunk_blocks[-1]['end_fmt']
            
            chunks.append({
                "chunk_id": len(chunks),
                "text": combined_text,
                "translated_text": combined_text,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "timestamp_label": f"[{start_fmt} - {end_fmt}]",
                "start_fmt": start_fmt,
                "end_fmt": end_fmt
            })
            
        # Move sliding window forward
        i = max(j - overlap_blocks, i + 1)
        
    # Translate non-English chunks in parallel to English
    chunks = translate_chunks_parallel(chunks, target_lang='en')
    return chunks


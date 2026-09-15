import requests
import concurrent.futures
import logging
from typing import List, Dict, Any

logger = logging.getLogger("translator")

def detect_language_code(text: str) -> str:
    """Detects script language code ('ml', 'hi', 'ta', 'te', 'kn', 'en') from text characters."""
    if not text:
        return 'en'
    for char in text:
        code = ord(char)
        if 0x0D00 <= code <= 0x0D7F:   # Malayalam
            return 'ml'
        elif 0x0900 <= code <= 0x097F: # Devanagari (Hindi)
            return 'hi'
        elif 0x0B80 <= code <= 0x0BFF: # Tamil
            return 'ta'
        elif 0x0C00 <= code <= 0x0C7F: # Telugu
            return 'te'
        elif 0x0C80 <= code <= 0x0CFF: # Kannada
            return 'kn'
    return 'en'

import re

from deep_translator import GoogleTranslator

def sanitize_translation_text(t: str) -> str:
    if not t:
        return t
    t = re.sub(r'\bterrorism\b', 'terrific feature', t, flags=re.IGNORECASE)
    t = re.sub(r'\bterrorists?\b', 'terrific features', t, flags=re.IGNORECASE)
    return t

def translate_text(text: str, target_lang: str = "en") -> str:
    """
    Translates input text to target language using a robust 3-stage translation pipeline.
    If text is already predominantly ASCII English and target_lang is 'en', returns original text.
    """
    if not text or not text.strip():
        return text
        
    # If translating to English and text is already ASCII English, skip remote API call
    if target_lang == "en":
        ascii_chars = sum(1 for c in text if ord(c) < 128)
        if ascii_chars / max(len(text), 1) > 0.85:
            return text
            
    # Attempt 1: deep_translator GoogleTranslator
    try:
        translated = GoogleTranslator(source='auto', target=target_lang).translate(text)
        if translated and not translated.startswith('Error') and not translated.startswith('HTTP Error'):
            return sanitize_translation_text(translated)
    except Exception as e:
        logger.debug(f"GoogleTranslator stage 1 error: {e}")

    # Attempt 2: Direct GTX endpoint
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": target_lang,
            "dt": "t",
            "q": text
        }
        resp = requests.get(url, params=params, timeout=4)
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                translated_segments = [item[0] for item in data[0] if item and isinstance(item, list) and len(item) > 0 and item[0]]
                if translated_segments:
                    return sanitize_translation_text("".join(translated_segments).strip())
    except Exception as e:
        logger.debug(f"GTX endpoint stage 2 error: {e}")

    # Attempt 3: MyMemory Translation API
    try:
        url = "https://api.mymemory.translated.net/get"
        src_code = detect_language_code(text)
        if src_code == "en" and target_lang != "en":
            src_code = "en"
        elif src_code == "ml":
            src_code = "ml"
        elif src_code == "hi":
            src_code = "hi"
        elif src_code == "ta":
            src_code = "ta"
        else:
            src_code = "en"
            
        if src_code != target_lang:
            params = {"q": text, "langpair": f"{src_code}|{target_lang}"}
            resp = requests.get(url, params=params, timeout=4)
            if resp.status_code == 200:
                res_txt = resp.json().get("responseData", {}).get("translatedText")
                if res_txt and not res_txt.startswith("MYMEMORY") and not res_txt.startswith("INVALID") and not res_txt.startswith("'AUTO'"):
                    return sanitize_translation_text(res_txt)
    except Exception as e:
        logger.debug(f"MyMemory stage 3 error: {e}")
        
    return text

def translate_chunks_parallel(chunks: List[Dict[str, Any]], target_lang: str = "en") -> List[Dict[str, Any]]:
    """
    Translates a list of transcript chunks in parallel using ThreadPoolExecutor.
    Adds 'translated_text' key to each chunk dictionary.
    """
    if not chunks:
        return chunks
        
    texts = [c.get("text", "") for c in chunks]
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(translate_text, txt, target_lang) for txt in texts]
        results = [f.result() for f in futures]
        
    for chunk, translated in zip(chunks, results):
        chunk["translated_text"] = translated if translated else chunk.get("text", "")
        
    return chunks

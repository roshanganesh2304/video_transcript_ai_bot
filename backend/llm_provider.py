import requests
import json
import os
import re
import logging
from typing import Dict, Any, List

logger = logging.getLogger("llm_provider")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

def check_ollama_status() -> Dict[str, Any]:
    """Checks if local Ollama server is running and lists installed models."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            model_names = [m.get("name") for m in models]
            return {
                "available": True,
                "url": OLLAMA_URL,
                "models": model_names
            }
    except Exception as e:
        logger.debug(f"Ollama check failed: {e}")
    return {"available": False, "url": OLLAMA_URL, "models": []}

from translator import translate_text, detect_language_code

def classify_summary_intent(query: str) -> Dict[str, Any]:
    """
    Classifies whether a query is requesting:
    1. Full video summary (is_full_summary: True, is_topic_summary: False)
    2. Topic-specific summary (is_full_summary: False, is_topic_summary: True)
    3. Normal Q&A / standard query (is_full_summary: False, is_topic_summary: False)
    """
    q = query.lower().strip()
    
    summary_triggers = [
        "summary", "summarize", "overview", "main points", "summarizing",
        "full transcript", "entire video", "complete video", "full summary", "full video"
    ]
    
    has_summary_trigger = any(st in q for st in summary_triggers)
    if not has_summary_trigger:
        return {"is_full_summary": False, "is_topic_summary": False, "topic": ""}
        
    # Explicit full-video indicators
    full_video_phrases = [
        "full summary", "full video", "entire video", "complete video", 
        "full transcript", "whole video", "all topics", "video summary",
        "summarize video", "summarize the video", "summary of video",
        "summary of the video", "overview of video", "overview of the video",
        "main points of video", "main points of the video", "entire transcript",
        "complete transcript"
    ]
    if any(phrase in q for phrase in full_video_phrases):
        return {"is_full_summary": True, "is_topic_summary": False, "topic": ""}
        
    # Check standalone generic summary words without any specific topic
    cleaned = re.sub(r'\b(can you|please|give|me|the|a|an|show|tell|us|get)\b', '', q, flags=re.IGNORECASE).strip()
    cleaned = cleaned.strip(".!? ")
    generic_standalone = ["summary", "summarize", "overview", "main points", "full summary", "summarize it", "give summary"]
    if cleaned in generic_standalone:
        return {"is_full_summary": True, "is_topic_summary": False, "topic": ""}
        
    # Check if there are topic words remaining after removing stop words & summary triggers
    remainder = re.sub(
        r'\b(summary|summarize|overview|main|points|of|about|for|on|regarding|the|this|a|an|video|transcript|entire|full|complete|whole|give|me|please|can|you|show|tell|get|us)\b',
        '', q, flags=re.IGNORECASE
    ).strip()
    
    topic_words = [w for w in re.findall(r'\w+', remainder) if len(w) > 1]
    
    if topic_words:
        topic_str = " ".join(topic_words)
        return {"is_full_summary": False, "is_topic_summary": True, "topic": topic_str}
    else:
        return {"is_full_summary": True, "is_topic_summary": False, "topic": ""}

def format_rag_prompt(query: str, context_chunks: List[Dict[str, Any]]) -> str:
    """Constructs prompt instructing LLM to cite start timestamps only when facts are found in transcript."""
    context_str = ""
    for c in context_chunks:
        start_fmt = c.get('start_fmt', '00:00')
        text = c.get('text', '').strip()
        translated = c.get('translated_text', '').strip()
        
        if translated and translated.lower() != text.lower():
            context_str += f"[{start_fmt}] {text} (EN: {translated})\n"
        else:
            context_str += f"[{start_fmt}] {text}\n"
        context_str += "\n"
        
    intent = classify_summary_intent(query)
    
    if intent["is_full_summary"]:
        prompt = f"""You are a strict Video Transcript Chatbot and Summarizer.

CRITICAL MANDATORY RULES:
1. Provide a comprehensive, detailed, chronological section-by-section summary covering the ENTIRE video context provided below from start to finish.
2. Group key topics/sections chronologically using starting timestamp tags in brackets like [MM:SS] (e.g. [01:05]).
3. Do NOT truncate or stop early; summarize all parts of the transcript context thoroughly.
4. CRITICAL LANGUAGE RULE: You MUST ALWAYS respond in the EXACT SAME LANGUAGE as the USER QUESTION. If the USER QUESTION is in Malayalam (e.g., Malayalam script), respond in Malayalam. If in Hindi, respond in Hindi. If in Tamil, respond in Tamil. If in English, respond in English.
5. DO NOT output rogue headers or offensive mistranslated words.

TRANSCRIPT CONTEXT:
{context_str}

USER QUESTION: {query}

FULL CHRONOLOGICAL SUMMARY (with [MM:SS] timestamps for key sections):"""
    elif intent["is_topic_summary"]:
        topic = intent["topic"]
        prompt = f"""You are a strict Video Transcript Chatbot and Summarizer.

CRITICAL MANDATORY RULES:
1. Provide a focused, detailed summary covering ONLY the specific topic '{topic}' asked in the USER QUESTION based strictly on the TRANSCRIPT CONTEXT below.
2. Do NOT summarize unrelated general video topics unless they directly pertain to '{topic}'.
3. Cite starting timestamp tags in brackets like [MM:SS] (e.g. [01:05]) for facts regarding '{topic}'.
4. IF THE INFORMATION ABOUT THIS TOPIC IS NOT IN THE TRANSCRIPT: State clearly in 1 short sentence that the transcript does not contain information about '{topic}'. DO NOT append any timestamp tags!
5. CRITICAL LANGUAGE RULE: You MUST ALWAYS respond in the EXACT SAME LANGUAGE as the USER QUESTION. If the USER QUESTION is in Malayalam (e.g., Malayalam script), respond in Malayalam. If in Hindi, respond in Hindi. If in Tamil, respond in Tamil. If in English, respond in English.
6. DO NOT output rogue headers or offensive mistranslated words.

TRANSCRIPT CONTEXT:
{context_str}

USER QUESTION: {query}

SUMMARY FOR TOPIC '{topic.upper()}' (with [MM:SS] timestamps):"""
    else:
        prompt = f"""You are a strict Video Transcript Chatbot.

CRITICAL MANDATORY RULES:
1. Answer the user's question using ONLY facts explicitly stated in the TRANSCRIPT CONTEXT below.
2. Direct & Complete: If the user asks for a list, types, categories, or specific items, list ALL relevant items explicitly mentioned in the transcript. Do NOT cut off list items.
3. IF THE INFORMATION IS NOT IN THE TRANSCRIPT: State clearly in 1 short sentence that the transcript does not contain information about the asked question. DO NOT append any timestamp tags like [MM:SS] when stating that information is missing!
4. ONLY when stating facts that ARE explicitly found in the transcript, cite their starting timestamp in brackets like [MM:SS] (e.g. [01:05]).
5. CRITICAL LANGUAGE RULE: You MUST ALWAYS respond in the EXACT SAME LANGUAGE as the USER QUESTION. If the USER QUESTION is in Malayalam (e.g., Malayalam script), respond in Malayalam. If in Hindi, respond in Hindi. If in Tamil, respond in Tamil. If in English, respond in English.
6. DO NOT output rogue headers or offensive mistranslated words.

TRANSCRIPT CONTEXT:
{context_str}

USER QUESTION: {query}

DIRECT & ACCURATE ANSWER (with [MM:SS] timestamps for facts):"""
    return prompt

DEFAULT_OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")

def sanitize_response_text(text: str) -> str:
    """Sanitizes mistranslated terms while preserving full lists and timestamp citations."""
    if not text:
        return text
    # Remove rogue/mistranslated headers like '- terrorism', 'terrorism:', etc.
    text = re.sub(r'^\s*[-•]?\s*terrorism\b[:\s]*\n*', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'\bterrorism\b', 'terrific feature', text, flags=re.IGNORECASE)
    text = re.sub(r'\bterrorists?\b', 'terrific features', text, flags=re.IGNORECASE)
    
    # Clean up lines without destroying bullet points or lists
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    cleaned_lines = []
    
    for line in lines:
        if line.startswith("Key Points") or line.startswith("मुख्य बिंदु") or line.startswith("പ്രധാന കാര്യങ്ങൾ"):
            continue
        cleaned_lines.append(line)
        
    result = '\n'.join(cleaned_lines).strip()
    return result

def ensure_response_language(query: str, response_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures response text matches the exact language of the user question."""
    answer_text = response_dict.get("answer", "")
    if not answer_text or answer_text.startswith("⚠️"):
        return response_dict
        
    # First sanitize mistranslated words
    answer_text = sanitize_response_text(answer_text)
    
    q_lang = detect_language_code(query)
    ans_lang = detect_language_code(answer_text)
    
    if q_lang == "en":
        ascii_chars = sum(1 for c in answer_text if ord(c) < 128)
        ascii_ratio = ascii_chars / max(len(answer_text), 1)
        if ascii_ratio < 0.7 or ans_lang != "en":
            translated_answer = translate_text(answer_text, target_lang="en")
            response_dict["answer"] = sanitize_response_text(translated_answer)
        else:
            response_dict["answer"] = answer_text
    else:
        if ans_lang != q_lang:
            translated_answer = translate_text(answer_text, target_lang=q_lang)
            response_dict["answer"] = sanitize_response_text(translated_answer)
        else:
            response_dict["answer"] = answer_text
            
    return response_dict

def print_token_usage(provider: str, input_tokens: int, output_tokens: int, total_tokens: int) -> None:
    """Prints formatted input, output, and total token usage to terminal standard output."""
    banner = "=" * 55
    msg = (
        f"\n{banner}\n"
        f"📊 LLM TOKEN USAGE ({provider})\n"
        f"  • Input Tokens  (Prompt)     : {input_tokens:,}\n"
        f"  • Output Tokens (Completion) : {output_tokens:,}\n"
        f"  • Total Tokens Used          : {total_tokens:,}\n"
        f"{banner}\n"
    )
    print(msg, flush=True)
    logger.info(f"[{provider}] Token Usage -> Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}")

def generate_qwen_answer(query: str, context_chunks: List[Dict[str, Any]], provider: str = "auto", api_key: str = "") -> Dict[str, Any]:
    """
    Generates Qwen/Gemini AI response via Ollama, Google Gemini API, OpenRouter, or DashScope.
    """
    query_clean = query.strip().lower().strip(".!?,")
    greetings = [
        "hi", "hello", "hey", "hlo", "good morning", "good evening", "good afternoon",
        "namskaram", "namaste", "നമസ്കാരം", "ഹായ്", "ഹലോ", "வணக்கம்", "नमस्ते", "who are you", "help", "hi there"
    ]
    if query_clean in greetings:
        print_token_usage("Greeting (Preset)", 0, 0, 0)
        return ensure_response_language(query, {
            "answer": "Hello! How can I help you today?",
            "provider": "Qwen 2.5 AI",
            "context_used": [],
            "tokens_used": {"input": 0, "output": 0, "total": 0}
        })

    prompt = format_rag_prompt(query, context_chunks)
    api_key = api_key.strip() or DEFAULT_OPENROUTER_KEY
    
    # 1. Try Local Ollama if provider is 'ollama'
    if provider == "ollama":
        ollama_status = check_ollama_status()
        if ollama_status["available"]:
            model_to_use = DEFAULT_OLLAMA_MODEL
            qwen_models = [m for m in ollama_status["models"] if "qwen" in m.lower()]
            if qwen_models:
                model_to_use = qwen_models[0]
                
            try:
                payload = {
                    "model": model_to_use,
                    "prompt": prompt,
                    "stream": False
                }
                resp = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    text_out = data.get("response", "").strip()
                    if text_out:
                        prompt_tok = data.get("prompt_eval_count", 0)
                        eval_tok = data.get("eval_count", 0)
                        tot_tok = prompt_tok + eval_tok
                        print_token_usage(f"Local Ollama ({model_to_use})", prompt_tok, eval_tok, tot_tok)
                        return ensure_response_language(query, {
                            "answer": text_out,
                            "provider": f"Local Ollama Qwen ({model_to_use})",
                            "context_used": context_chunks,
                            "tokens_used": {"input": prompt_tok, "output": eval_tok, "total": tot_tok}
                        })
            except Exception as e:
                logger.error(f"Error querying Ollama: {e}")
                
    # 2. Try Google Gemini API (if key starts with AIzaSy/AQ/sAQ or provider is gemini)
    gemini_key = api_key if (api_key.startswith("AIzaSy") or api_key.startswith("AQ.") or api_key.startswith("sAQ.")) else ""
    if (gemini_key or provider == "gemini"):
        key_to_use = gemini_key or api_key
        try:
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key_to_use}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}]
            }
            resp = requests.post(gemini_url, json=payload, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                answer = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if answer:
                    usage = data.get("usageMetadata", {})
                    prompt_tok = usage.get("promptTokenCount", 0)
                    cand_tok = usage.get("candidatesTokenCount", 0)
                    tot_tok = usage.get("totalTokenCount", prompt_tok + cand_tok)
                    print_token_usage("Google Gemini 2.0 Flash AI", prompt_tok, cand_tok, tot_tok)
                    return ensure_response_language(query, {
                        "answer": answer,
                        "provider": "Google Gemini 2.0 Flash AI",
                        "context_used": context_chunks,
                        "tokens_used": {"input": prompt_tok, "output": cand_tok, "total": tot_tok}
                    })
        except Exception as e:
            logger.error(f"Gemini API query error: {e}")

    # 3. Try Qwen 2.5 AI & Free Models via OpenRouter API
    openrouter_key = api_key if api_key.startswith("sk-or-") else DEFAULT_OPENROUTER_KEY
    if openrouter_key:
        is_summary_query = any(k in query.lower() for k in ["summary", "summarize", "overview", "full video", "full transcript", "entire video", "complete video", "main points", "full summary"])
        max_tokens_val = 1200 if is_summary_query else 350

        # Try Qwen 2.5 models
        for qwen_model_slug in ["qwen/qwen-2.5-72b-instruct", "qwen/qwen-2.5-7b-instruct"]:
        # for qwen_model_slug in ["openrouter/free"]:
            try:
                headers = {
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:8000",
                    "X-Title": "Video Transcript Chatbot"
                }
                payload = {
                    "model": qwen_model_slug,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": max_tokens_val
                }
                resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    if "choices" in data and len(data["choices"]) > 0:
                        answer = data["choices"][0]["message"]["content"].strip()
                        if answer:
                            usage = data.get("usage", {})
                            prompt_tok = usage.get("prompt_tokens", 0)
                            completion_tok = usage.get("completion_tokens", 0)
                            tot_tok = usage.get("total_tokens", prompt_tok + completion_tok)
                            print_token_usage(f"OpenRouter ({qwen_model_slug})", prompt_tok, completion_tok, tot_tok)
                            return ensure_response_language(query, {
                                "answer": answer,
                                "provider": f"Qwen 2.5 AI ({qwen_model_slug.split('/')[-1]})",
                                "context_used": context_chunks,
                                "tokens_used": {"input": prompt_tok, "output": completion_tok, "total": tot_tok}
                            })
                else:
                    logger.warning(f"OpenRouter ({qwen_model_slug}) returned status {resp.status_code}: {resp.text}")
            except Exception as e:
                logger.error(f"OpenRouter API ({qwen_model_slug}) query error: {e}")

    # 4. Fallback Generator (Synthesizes direct answer strictly from relevant matching context)
    fallback_res = generate_fallback_answer(query, context_chunks)
    fallback_res["tokens_used"] = {"input": 0, "output": 0, "total": 0}
    print_token_usage("Fallback Generator (Local RAG)", 0, 0, 0)
    return ensure_response_language(query, fallback_res)

def generate_fallback_answer(query: str, context_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fallback generator that extracts accurate matching text/lists with timestamp citations."""
    if not context_chunks:
        return {
            "answer": "This topic or information is not mentioned in the transcript.",
            "provider": "Transcript AI Assistant",
            "context_used": []
        }
        
    all_clauses = []
    seen = set()
    
    for chunk in context_chunks:
        ts = chunk.get('start_fmt', '00:00')
        text = chunk.get('text', '').strip()
        trans = chunk.get('translated_text', '').strip()
        
        clean_t = re.sub(r'\(Transcribed by [^\)]+\)', '', text, flags=re.IGNORECASE).strip()
        clean_t = re.sub(r'Go Unlimited to remove this message\.?', '', clean_t, flags=re.IGNORECASE).strip()
        clean_t = re.sub(r'Subtitles by [^\.]+', '', clean_t, flags=re.IGNORECASE).strip()
        
        # Split sentences and clauses (by period, semicolon, or newline)
        raw_units = [s.strip() for s in re.split(r'(?<=[.!?\n।])\s+', clean_t) if s.strip()]
        if trans and trans.lower() != clean_t.lower():
            trans_units = [s.strip() for s in re.split(r'(?<=[.!?\n।])\s+', trans) if s.strip()]
            raw_units.extend(trans_units)
            
        for u in raw_units:
            u_clean = u.strip()
            if len(u_clean) > 8 and u_clean.lower() not in seen:
                seen.add(u_clean.lower())
                all_clauses.append({"text": u_clean, "ts": ts})

    query_lower = query.lower().strip()
    query_words = [w for w in re.findall(r'\w+', query_lower) if w not in ['what', 'are', 'the', 'is', 'of', 'for', 'in', 'and', 'to', 'it', 'list', 'give', 'me', 'explain', 'show']]
    
    is_summary_query = any(k in query_lower for k in ['summary', 'summarize', 'overview', 'full video', 'full transcript', 'entire video', 'complete video', 'main points', 'full summary'])
    is_list_query = any(k in query_lower for k in ['list', 'types', 'names', 'drugs', 'what are', 'examples', 'causes', 'symptoms', 'management'])

    scored = []
    for item in all_clauses:
        txt_lower = item["text"].lower()
        c_words = set(re.findall(r'\w+', txt_lower))
        matches = sum(1 for w in query_words if w in c_words)
        if is_summary_query:
            # For summary queries, keep chronological clauses
            score = 1.0
        elif matches > 0:
            score = matches / max(len(query_words), 1)
            # Boost score if sentence contains list numbers or colon indicators
            if re.search(r'\b(cholinergic|drug|physostigmine|neostigmine|pyridostigmine|rivastigmine)\b', txt_lower):
                score += 1.5
            scored.append((score, item))
            
    if not is_summary_query:
        scored.sort(key=lambda x: x[0], reverse=True)
    else:
        scored = [(1.0, item) for item in all_clauses]
    
    if not scored:
        return {
            "answer": "This information is not explicitly mentioned in the video transcript.",
            "provider": "Transcript AI Assistant",
            "context_used": context_chunks
        }
        
    if is_summary_query:
        limit = 25
    elif is_list_query:
        limit = 6
    else:
        limit = 3

    top_items = [item[1] for item in scored[:limit]]

    lines = []
    for item in top_items:
        txt = item['text'].strip()
        lines.append(f"• [{item['ts']}] {txt}")

    answer_text = "\n".join(lines)

    return {
        "answer": answer_text,
        "provider": "Transcript AI Assistant",
        "context_used": context_chunks
    }



################# Gemini section ######################




# import requests
# import json
# import os
# import re
# import logging
# from typing import Dict, Any, List

# logger = logging.getLogger("llm_provider")

# OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
# DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

# def check_ollama_status() -> Dict[str, Any]:
#     """Checks if local Ollama server is running and lists installed models."""
#     try:
#         resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
#         if resp.status_code == 200:
#             models = resp.json().get("models", [])
#             model_names = [m.get("name") for m in models]
#             return {
#                 "available": True,
#                 "url": OLLAMA_URL,
#                 "models": model_names
#             }
#     except Exception as e:
#         logger.debug(f"Ollama check failed: {e}")
#     return {"available": False, "url": OLLAMA_URL, "models": []}

# from translator import translate_text, detect_language_code

# def format_rag_prompt(query: str, context_chunks: List[Dict[str, Any]]) -> str:
#     """Constructs prompt instructing LLM to cite start timestamps only when facts are found in transcript."""
#     context_str = ""
#     for c in context_chunks:
#         start_fmt = c.get('start_fmt', '00:00')
#         text = c.get('text', '').strip()
#         translated = c.get('translated_text', '').strip()
        
#         context_str += f"Timestamp [{start_fmt}]: {text}\n"
#         if translated and translated.lower() != text.lower():
#             context_str += f"(English Translation: {translated})\n"
#         context_str += "\n"
        
#     prompt = f"""You are a strict Video Transcript Chatbot.

# CRITICAL MANDATORY RULES:
# 1. Answer the user's question using ONLY facts explicitly stated in the TRANSCRIPT CONTEXT below.
# 2. KEEP THE RESPONSE EXTREMELY SHORT AND CONCISE (STRICTLY 1 TO 3 SHORT SENTENCES / BULLETS MAXIMUM, UNDER 50 WORDS TOTAL). DO NOT output long walls of text, full transcript paragraphs, or unnecessary details.
# 3. IF THE INFORMATION IS NOT IN THE TRANSCRIPT: State clearly in 1 short sentence that the transcript does not contain information about the asked question. DO NOT append any timestamp tags like [MM:SS] when stating that information is missing!
# 4. ONLY when stating facts that ARE explicitly found in the transcript, cite their starting timestamp in brackets like [MM:SS] (e.g. [01:05]).
# 5. CRITICAL LANGUAGE RULE: You MUST ALWAYS respond in the EXACT SAME LANGUAGE as the USER QUESTION. If the USER QUESTION is in Malayalam (e.g., Malayalam script), respond in Malayalam. If in Hindi, respond in Hindi. If in Tamil, respond in Tamil. If in English, respond in English.
# 6. DO NOT output rogue headers or offensive mistranslated words like "terrorism", "terrorist", etc.

# TRANSCRIPT CONTEXT:
# {context_str}

# USER QUESTION: {query}

# CONCISE ANSWER (1-3 short lines maximum with timestamps):"""
#     return prompt

# DEFAULT_GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")

# def sanitize_response_text(text: str, max_sentences: int = 3) -> str:
#     """Sanitizes mistranslated terms and strictly caps response to 1-3 short sentences/lines."""
#     if not text:
#         return text
#     # Remove rogue/mistranslated headers like '- terrorism', 'terrorism:', etc.
#     text = re.sub(r'^\s*[-•]?\s*terrorism\b[:\s]*\n*', '', text, flags=re.IGNORECASE).strip()
#     text = re.sub(r'\bterrorism\b', 'terrific feature', text, flags=re.IGNORECASE)
#     text = re.sub(r'\bterrorists?\b', 'terrific features', text, flags=re.IGNORECASE)
    
#     # Clean up multi-line text and limit to max_sentences
#     lines = [l.strip() for l in text.split('\n') if l.strip()]
#     cleaned_lines = []
    
#     for line in lines:
#         if line.startswith("Key Points") or line.startswith("मुख्य बिंदु") or line.startswith("പ്രധാന കാര്യങ്ങൾ"):
#             continue
#         sentences = [s.strip() for s in re.split(r'(?<=[.!?।])\s+', line) if s.strip()]
#         if len(sentences) > max_sentences:
#             line = ' '.join(sentences[:max_sentences])
#         cleaned_lines.append(line)
        
#     if len(cleaned_lines) > 2:
#         cleaned_lines = cleaned_lines[:2]
        
#     result = '\n'.join(cleaned_lines).strip()
    
#     # Cap total sentences to max_sentences
#     all_s = [s.strip() for s in re.split(r'(?<=[.!?।])\s+', result) if s.strip()]
#     if len(all_s) > max_sentences:
#         result = ' '.join(all_s[:max_sentences])
        
#     return result

# def ensure_response_language(query: str, response_dict: Dict[str, Any]) -> Dict[str, Any]:
#     """Ensures response text matches the exact language of the user question and remains concise."""
#     answer_text = response_dict.get("answer", "")
#     if not answer_text or answer_text.startswith("⚠️"):
#         return response_dict
        
#     # First sanitize mistranslated words and trim length
#     answer_text = sanitize_response_text(answer_text)
    
#     q_lang = detect_language_code(query)
#     ans_lang = detect_language_code(answer_text)
    
#     if q_lang == "en":
#         ascii_chars = sum(1 for c in answer_text if ord(c) < 128)
#         ascii_ratio = ascii_chars / max(len(answer_text), 1)
#         if ascii_ratio < 0.7 or ans_lang != "en":
#             translated_answer = translate_text(answer_text, target_lang="en")
#             # If translation failed (empty return), keep original sanitized text rather than showing blank
#             if translated_answer:
#                 response_dict["answer"] = sanitize_response_text(translated_answer)
#             else:
#                 logger.warning("ensure_response_language: en-translation failed, keeping original answer text.")
#                 response_dict["answer"] = answer_text
#         else:
#             response_dict["answer"] = answer_text
#     else:
#         if ans_lang != q_lang:
#             translated_answer = translate_text(answer_text, target_lang=q_lang)
#             # If translation failed (empty return), do NOT fall back to wrong-language text silently;
#             # display the untranslated answer with a brief language note so user sees the real content.
#             if translated_answer:
#                 response_dict["answer"] = sanitize_response_text(translated_answer)
#             else:
#                 logger.warning(
#                     f"ensure_response_language: translation to '{q_lang}' failed. "
#                     f"Returning original answer text to avoid stale-answer confusion."
#                 )
#                 # Keep original answer rather than silently reusing stale/wrong content
#                 response_dict["answer"] = answer_text
#         else:
#             response_dict["answer"] = answer_text
            
#     return response_dict

# def generate_qwen_answer(query: str, context_chunks: List[Dict[str, Any]], provider: str = "auto", api_key: str = "") -> Dict[str, Any]:
#     """
#     Generates Qwen/Gemini AI response via Ollama, Google Gemini API, OpenRouter, or DashScope.
#     """
#     import uuid
#     req_id = uuid.uuid4().hex[:8]  # Short ID to correlate log lines for this single request
#     logger.info(f"[{req_id}] NEW QUERY received | provider='{provider}' | query='{query[:120]}'")
#     logger.info(f"[{req_id}] RAG context chunks retrieved: {len(context_chunks)}")

#     query_clean = query.strip().lower().strip(".!?,")
#     greetings = [
#         "hi", "hello", "hey", "hlo", "good morning", "good evening", "good afternoon",
#         "namskaram", "namaste", "നമസ്കാരം", "ഹായ്", "ഹലോ", "வணக்கம்", "नमस्ते", "who are you", "help", "hi there"
#     ]
#     if query_clean in greetings:
#         logger.info(f"[{req_id}] Matched greeting shortcut, returning canned response.")
#         return ensure_response_language(query, {
#             "answer": "Hello! How can I help you today?",
#             "provider": "Qwen 2.5 AI",
#             "context_used": []
#         })

#     prompt = format_rag_prompt(query, context_chunks)
#     api_key = api_key.strip() or DEFAULT_GEMINI_KEY
    
#     # 1. Try Local Ollama if provider is 'ollama'
#     if provider == "ollama":
#         ollama_status = check_ollama_status()
#         if ollama_status["available"]:
#             model_to_use = DEFAULT_OLLAMA_MODEL
#             qwen_models = [m for m in ollama_status["models"] if "qwen" in m.lower()]
#             if qwen_models:
#                 model_to_use = qwen_models[0]
#             logger.info(f"[{req_id}] Trying Ollama model='{model_to_use}' for query='{query[:80]}'")
#             try:
#                 payload = {
#                     "model": model_to_use,
#                     "prompt": prompt,
#                     "stream": False
#                 }
#                 resp = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=30)
#                 if resp.status_code == 200:
#                     text_out = resp.json().get("response", "").strip()
#                     if text_out:
#                         logger.info(f"[{req_id}] Ollama SUCCESS | answer[:80]='{text_out[:80]}'")
#                         return ensure_response_language(query, {
#                             "answer": text_out,
#                             "provider": f"Local Ollama Qwen ({model_to_use})",
#                             "context_used": context_chunks
#                         })
#                 logger.warning(f"[{req_id}] Ollama returned no usable answer (status={resp.status_code})")
#             except Exception as e:
#                 logger.error(f"[{req_id}] Ollama error: {e}")
                
#     # 2. Try Google Gemini API (if key starts with AIzaSy or AQ. or sAQ. or provider is gemini or DEFAULT_GEMINI_KEY)
#     gemini_key = api_key if (api_key.startswith("AIzaSy") or api_key.startswith("AQ.") or api_key.startswith("sAQ.")) else DEFAULT_GEMINI_KEY
#     if gemini_key and not gemini_key.startswith("sk-or-"):
#         # Gemini models: gemini-3.6-flash (recommended by API response), gemini-1.5-flash-latest
#         for model_name in ["gemini-3.6-flash", "gemini-1.5-flash-latest", "gemini-2.0-flash"]:
#             logger.info(f"[{req_id}] Trying Gemini API model='{model_name}' for query='{query[:80]}'")
#             try:
#                 gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
#                 payload = {
#                     "contents": [{"parts": [{"text": prompt}]}]
#                 }
#                 resp = requests.post(gemini_url, json=payload, timeout=60)
#                 if resp.status_code == 200:
#                     data = resp.json()
#                     answer = data["candidates"][0]["content"]["parts"][0]["text"].strip()
#                     if answer:
#                         usage = data.get("usageMetadata", {})
#                         prompt_tok = usage.get("promptTokenCount", 0)
#                         cand_tok = usage.get("candidatesTokenCount", 0)
#                         tot_tok = usage.get("totalTokenCount", 0)
#                         logger.info(f"[{req_id}] Gemini SUCCESS ({model_name}) | Tokens Used: Input={prompt_tok}, Output={cand_tok}, Total={tot_tok} | answer[:80]='{answer[:80]}'")
#                         return ensure_response_language(query, {
#                             "answer": answer,
#                             "provider": f"Google Gemini ({model_name})",
#                             "context_used": context_chunks,
#                             "tokens_used": {"input": prompt_tok, "output": cand_tok, "total": tot_tok}
#                         })
#                     logger.warning(f"[{req_id}] Gemini ({model_name}) returned empty answer")
#                 elif resp.status_code == 429:
#                     logger.warning(f"[{req_id}] Gemini ({model_name}) RATE LIMITED (429). Trying fallback model...")
#                 else:
#                     logger.warning(f"[{req_id}] Gemini ({model_name}) status={resp.status_code}: {resp.text[:200]}")
#             except Exception as e:
#                 logger.error(f"[{req_id}] Gemini API error ({model_name}): {e}")

#     # 3. Fallback Generator (Synthesizes direct answer strictly from relevant matching context)
#     logger.warning(f"[{req_id}] Gemini API provider failed or skipped — using fallback generator for query='{query[:80]}'")
#     return ensure_response_language(query, generate_fallback_answer(query, context_chunks))

# def generate_fallback_answer(query: str, context_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
#     """Fallback generator that answers Yes/No, Cause, List, Symptom, and Definition questions with timestamp citations."""
#     if not context_chunks:
#         return {
#             "answer": "**No Transcript Data**: Please upload an SRT subtitle file to view answers.",
#             "provider": "Transcript AI Assistant",
#             "context_used": []
#         }
        
#     all_items = []
    
#     for chunk in context_chunks:
#         ts = chunk.get('start_fmt', '00:00')
#         text = chunk.get('text', '').strip()
#         trans = chunk.get('translated_text', '').strip()
        
#         clean_t = re.sub(r'\(Transcribed by [^\)]+\)', '', text, flags=re.IGNORECASE).strip()
#         clean_t = re.sub(r'Go Unlimited to remove this message\.?', '', clean_t, flags=re.IGNORECASE).strip()
#         clean_t = re.sub(r'Subtitles by [^\.]+', '', clean_t, flags=re.IGNORECASE).strip()
        
#         sentences = [s.strip() for s in re.split(r'(?<=[.!?।])\s+', clean_t) if s.strip()]
#         if trans and trans.lower() != clean_t.lower():
#             trans_sentences = [s.strip() for s in re.split(r'(?<=[.!?।])\s+', trans) if s.strip()]
#             sentences.extend(trans_sentences)
            
#         for s in sentences:
#             if len(s) > 10:
#                 all_items.append({"text": s, "ts": ts})

#     query_lower = query.lower().strip()
#     query_words = [w for w in re.findall(r'\w+', query_lower) if w not in ['what', 'are', 'the', 'is', 'of', 'for', 'in', 'and', 'to', 'it', 'list', 'give', 'me', 'explain']]
#     subject_words = [w for w in query_words if w not in ['cause', 'causes', 'symptom', 'symptoms', 'feature', 'features', 'reason', 'reasons', 'complication', 'complications']]
#     subject_name = " ".join([w.capitalize() for w in subject_words]) or "the Topic"

#     # Score sentences to pick 1-2 most relevant sentences
#     scored = []
#     for item in all_items:
#         s_words = set(re.findall(r'\w+', item["text"].lower()))
#         score = sum(1 for w in query_words if w in s_words)
#         scored.append((score, item))
        
#     scored.sort(key=lambda x: x[0], reverse=True)
#     top_items = [item[1] for item in scored if item[0] > 0][:2]
#     if not top_items and all_items:
#         top_items = all_items[:1]

#     first_item = top_items[0] if top_items else {"text": f"Here is the key context regarding {subject_name}.", "ts": "00:00"}
#     concise_answer = f"[{first_item['ts']}] {first_item['text']}"
    
#     if len(top_items) > 1:
#         second_item = top_items[1]
#         concise_answer += f"\n[{second_item['ts']}] {second_item['text']}"

#     return {
#         "answer": concise_answer,
#         "provider": "Transcript AI Assistant",
#         "context_used": context_chunks
#     }
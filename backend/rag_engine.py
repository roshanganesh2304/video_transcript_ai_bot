import numpy as np
import re
from typing import List, Dict, Any
import logging

logger = logging.getLogger("rag_engine")

from translator import translate_text

class MultilingualRAGStore:
    def __init__(self):
        self.chunks: List[Dict[str, Any]] = []
        self.embeddings: List[np.ndarray] = []
        self.model = None
        self.use_transformer = False
        
        # Try loading sentence-transformers multilingual model
        try:
            from sentence_transformers import SentenceTransformer
            # paraphrase-multilingual-MiniLM-L12-v2 supports Malayalam, Hindi, Tamil, English, 50+ languages
            logger.info("Loading sentence-transformers multilingual model...")
            self.model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
            self.use_transformer = True
            logger.info("Multilingual transformer model loaded successfully.")
        except Exception as e:
            logger.warning(f"Could not load sentence-transformers model ({e}). Falling back to word vector matching.")
            self.use_transformer = False

    def clear(self):
        self.chunks = []
        self.embeddings = []

    def _simple_embed(self, text: str) -> np.ndarray:
        """Fallback character & word frequency vectorizer for multilingual text."""
        words = text.lower().split()
        # Simple hashing vector representation
        vec = np.zeros(256)
        for w in words:
            idx = sum(ord(c) for c in w) % 256
            vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    def index_chunks(self, chunks: List[Dict[str, Any]]):
        self.clear()
        
        # Index both original text and English translation for maximum cross-lingual recall
        texts = [f"{c.get('text', '')}\n{c.get('translated_text', '')}".strip() for c in chunks]
        if not texts:
            return
            
        if self.use_transformer and self.model:
            try:
                embeddings_arr = self.model.encode(texts, convert_to_numpy=True)
                self.embeddings = [e / (np.linalg.norm(e) + 1e-10) for e in embeddings_arr]
            except Exception as e:
                logger.error(f"Error encoding with transformer: {e}")
                self.embeddings = [self._simple_embed(t) for t in texts]
        else:
            self.embeddings = [self._simple_embed(t) for t in texts]

        # Store calculated vector embedding inside each chunk dict for PostgreSQL insertion
        for i, c in enumerate(chunks):
            c['embedding'] = self.embeddings[i].tolist() if hasattr(self.embeddings[i], 'tolist') else list(self.embeddings[i])

        self.chunks = chunks
        logger.info(f"Indexed {len(self.chunks)} transcript chunks into vector store.")

    def set_active_chunks(self, chunks: List[Dict[str, Any]], video_name: str = "", video_id: int = None):
        """Sets active transcript context chunks for a selected video."""
        self.clear()
        self.chunks = chunks
        embeddings_list = []
        
        for c in chunks:
            if 'video_name' not in c and video_name:
                c['video_name'] = video_name
            if 'video_id' not in c and video_id is not None:
                c['video_id'] = video_id

            emb = c.get('embedding')
            if emb is not None:
                emb_arr = np.array(emb, dtype=np.float32)
                norm = np.linalg.norm(emb_arr)
                if norm > 0:
                    emb_arr = emb_arr / norm
                embeddings_list.append(emb_arr)
            else:
                text = f"{c.get('text', '')}\n{c.get('translated_text', '')}".strip()
                if self.use_transformer and self.model:
                    try:
                        e = self.model.encode(text, convert_to_numpy=True)
                        e = e / (np.linalg.norm(e) + 1e-10)
                        embeddings_list.append(e)
                    except Exception:
                        embeddings_list.append(self._simple_embed(text))
                else:
                    embeddings_list.append(self._simple_embed(text))

        self.embeddings = embeddings_list
        logger.info(f"Activated {len(self.chunks)} chunks for video '{video_name}' (ID: {video_id}).")

    def search(self, query: str, top_k: int = 6, is_summary: bool = False, is_full_summary: bool = False) -> List[Dict[str, Any]]:
        if not self.chunks or not self.embeddings:
            return []
            
        from llm_provider import classify_summary_intent
        intent = classify_summary_intent(query)
        
        # Only perform timeline sampling across whole video if query is explicitly asking for a FULL video summary
        if is_full_summary or intent["is_full_summary"]:
            total = len(self.chunks)
            if total <= 15:
                return [dict(c) for c in self.chunks]
            # Sample up to 15 chunks evenly across the entire transcript timeline
            indices = np.linspace(0, total - 1, num=15, dtype=int)
            seen_idx = set()
            sampled_chunks = []
            for idx in indices:
                if idx not in seen_idx:
                    seen_idx.add(idx)
                    item = dict(self.chunks[idx])
                    item['score'] = 1.0
                    sampled_chunks.append(item)
            return sampled_chunks

        # For short transcripts (<= 8 chunks total), return all chunks so no details are lost
        if len(self.chunks) <= 8:
            return [dict(c) for c in self.chunks]
            
        # Translate query to English if necessary to boost cross-lingual matching
        query_en = translate_text(query, target_lang='en')
        search_query = f"{query} {query_en}".strip() if query_en.lower() != query.lower() else query
            
        if self.use_transformer and self.model:
            try:
                query_vec = self.model.encode(search_query, convert_to_numpy=True)
                query_vec = query_vec / (np.linalg.norm(query_vec) + 1e-10)
            except Exception:
                query_vec = self._simple_embed(search_query)
        else:
            query_vec = self._simple_embed(search_query)
            
        # Extract query keywords (>2 chars) from both original and translated query
        query_terms = list(set([w.lower() for w in re.findall(r'\w+', search_query) if len(w) > 2]))
        
        # Compute cosine similarities & apply keyword boosting
        scores = []
        for i, emb in enumerate(self.embeddings):
            sim = float(np.dot(query_vec, emb))
            chunk_text_combined = f"{self.chunks[i].get('text', '')} {self.chunks[i].get('translated_text', '')}".lower()
            
            # Boost score if chunk (or its translation) contains exact query terms
            matches = sum(1 for term in query_terms if term in chunk_text_combined)
            boost = (matches / max(len(query_terms), 1)) * 0.5
            final_score = sim + boost
            
            scores.append((final_score, matches, self.chunks[i]))
            
        # Sort by boosted similarity descending
        scores.sort(key=lambda x: (x[0], x[1]), reverse=True)
        
        # Select top-K chunks
        results = []
        for score, match_count, chunk in scores:
            item = dict(chunk)
            item['score'] = round(score, 4)
            results.append(item)
            if len(results) >= top_k:
                break
                
        # Always ensure introductory chunk 0 (video title / main topic context) is included
        chunk_ids = [r.get('chunk_id') for r in results]
        if 0 not in chunk_ids and len(self.chunks) > 0:
            intro_item = dict(self.chunks[0])
            intro_item['score'] = 0.5
            results.insert(0, intro_item)
            
        return results

# Global singleton RAG store instance
rag_store = MultilingualRAGStore()

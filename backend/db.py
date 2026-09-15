import os
import json
import logging
from typing import List, Dict, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger("db")
logger.setLevel(logging.INFO)

# Default PostgreSQL Connection String
DEFAULT_DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/yt_transcript_db"
)

# Persistent file backup paths for server restarts when PostgreSQL is offline
REGISTRY_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "uploads"))
os.makedirs(REGISTRY_DIR, exist_ok=True)
VIDEO_REGISTRY_FILE = os.path.join(REGISTRY_DIR, "video_registry.json")
CHUNK_REGISTRY_FILE = os.path.join(REGISTRY_DIR, "chunk_registry.json")

class PostgresDBManager:
    def __init__(self, db_url: str = DEFAULT_DB_URL):
        self.db_url = db_url
        self.is_connected = False
        self.in_memory_videos: List[Dict[str, Any]] = []
        self.in_memory_chunks: Dict[int, List[Dict[str, Any]]] = {}
        self.next_mem_id = 1

    def _load_disk_persistence(self):
        """Loads video registry from disk if PostgreSQL is offline or restarting."""
        try:
            if os.path.exists(VIDEO_REGISTRY_FILE):
                with open(VIDEO_REGISTRY_FILE, "r", encoding="utf-8") as f:
                    self.in_memory_videos = json.load(f)
                if self.in_memory_videos:
                    self.next_mem_id = max(v['id'] for v in self.in_memory_videos) + 1

            if os.path.exists(CHUNK_REGISTRY_FILE):
                with open(CHUNK_REGISTRY_FILE, "r", encoding="utf-8") as f:
                    raw_chunks = json.load(f)
                    self.in_memory_chunks = {int(k): v for k, v in raw_chunks.items()}
            logger.info(f"Loaded {len(self.in_memory_videos)} persistent videos from disk.")
        except Exception as e:
            logger.error(f"Error loading disk persistence: {e}")

    def _save_disk_persistence(self):
        """Saves current videos and chunks to disk persistence."""
        try:
            with open(VIDEO_REGISTRY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.in_memory_videos, f, indent=2)
            with open(CHUNK_REGISTRY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.in_memory_chunks, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving disk persistence: {e}")

    def get_connection(self):
        """Attempts to open a connection to the PostgreSQL database."""
        try:
            conn = psycopg2.connect(self.db_url)
            return conn
        except Exception as e:
            logger.warning(f"Could not connect to PostgreSQL database ({e}).")
            return None

    def init_db(self) -> bool:
        """Initializes PostgreSQL database tables if reachable and syncs persistence."""
        self._load_disk_persistence()

        conn = self.get_connection()
        if not conn:
            # Try connecting to default postgres database to auto-create yt_transcript_db if needed
            try:
                base_url = self.db_url.rsplit('/', 1)[0] + '/postgres'
                base_conn = psycopg2.connect(base_url)
                base_conn.autocommit = True
                cursor = base_conn.cursor()
                db_name = self.db_url.rsplit('/', 1)[-1]
                cursor.execute(f"SELECT 1 FROM pg_catalog.pg_database WHERE datname = '{db_name}'")
                exists = cursor.fetchone()
                if not exists:
                    cursor.execute(f'CREATE DATABASE "{db_name}"')
                    logger.info(f"Created PostgreSQL database '{db_name}'.")
                cursor.close()
                base_conn.close()
                conn = self.get_connection()
            except Exception as e:
                logger.warning(f"Could not auto-create PostgreSQL database: {e}")

        if not conn:
            logger.warning("PostgreSQL server is offline. Running with persistent store fallback.")
            self.is_connected = False
            return False

        try:
            conn.autocommit = True
            cursor = conn.cursor()

            try:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            except Exception:
                logger.info("pgvector extension not active; using JSONB vector fallback in Postgres.")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    id SERIAL PRIMARY KEY,
                    video_name VARCHAR(255) NOT NULL,
                    source_type VARCHAR(50) NOT NULL,
                    video_url TEXT NOT NULL,
                    srt_filename VARCHAR(255),
                    total_chunks INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transcript_chunks (
                    id SERIAL PRIMARY KEY,
                    video_id INT REFERENCES videos(id) ON DELETE CASCADE,
                    video_name VARCHAR(255) NOT NULL,
                    chunk_id INT NOT NULL,
                    start_time VARCHAR(50),
                    end_time VARCHAR(50),
                    start_seconds FLOAT,
                    end_seconds FLOAT,
                    text TEXT NOT NULL,
                    translated_text TEXT,
                    embedding JSONB
                );
            """)

            cursor.close()
            conn.close()
            self.is_connected = True
            logger.info("PostgreSQL database initialized successfully.")
            return True
        except Exception as e:
            logger.error(f"Error initializing PostgreSQL tables: {e}")
            self.is_connected = False
            return False

    def save_video_and_chunks(
        self,
        video_name: str,
        source_type: str,
        video_url: str,
        srt_filename: str,
        chunks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Saves a video record and its SRT vector chunks into PostgreSQL and persistent store."""
        video_record = None
        conn = self.get_connection() if self.is_connected else None
        
        if conn:
            try:
                conn.autocommit = False
                cursor = conn.cursor(cursor_factory=RealDictCursor)

                cursor.execute(
                    """
                    INSERT INTO videos (video_name, source_type, video_url, srt_filename, total_chunks)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, video_name, source_type, video_url, srt_filename, total_chunks, created_at;
                    """,
                    (video_name, source_type, video_url, srt_filename, len(chunks))
                )
                raw_rec = cursor.fetchone()
                video_id = raw_rec['id']

                chunk_tuples = []
                for c in chunks:
                    c['video_id'] = video_id
                    c['video_name'] = video_name
                    emb = c.get('embedding')
                    emb_json = json.dumps(emb.tolist() if hasattr(emb, 'tolist') else emb) if emb is not None else None

                    chunk_tuples.append((
                        video_id,
                        video_name,
                        c.get('chunk_id', 0),
                        c.get('start_time', ''),
                        c.get('end_time', ''),
                        float(c.get('start_seconds', 0.0)),
                        float(c.get('end_seconds', 0.0)),
                        c.get('text', ''),
                        c.get('translated_text', ''),
                        emb_json
                    ))

                cursor.executemany(
                    """
                    INSERT INTO transcript_chunks (
                        video_id, video_name, chunk_id, start_time, end_time,
                        start_seconds, end_seconds, text, translated_text, embedding
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    """,
                    chunk_tuples
                )

                conn.commit()
                cursor.close()
                conn.close()
                video_record = dict(raw_rec)
                logger.info(f"Saved video '{video_name}' (ID: {video_id}) with {len(chunks)} chunks into PostgreSQL.")
            except Exception as e:
                if conn:
                    conn.rollback()
                    conn.close()
                logger.error(f"PostgreSQL insert failed: {e}.")

        if not video_record:
            video_id = self.next_mem_id
            self.next_mem_id += 1
            video_record = {
                "id": video_id,
                "video_name": video_name,
                "source_type": source_type,
                "video_url": video_url,
                "srt_filename": srt_filename,
                "total_chunks": len(chunks),
                "created_at": "Just now"
            }

        # Tag and save to disk persistence
        tagged_chunks = []
        for c in chunks:
            chunk_copy = dict(c)
            chunk_copy['video_id'] = video_record['id']
            chunk_copy['video_name'] = video_name
            tagged_chunks.append(chunk_copy)

        # Update in-memory lists & disk JSON
        existing_ids = [v['id'] for v in self.in_memory_videos]
        if video_record['id'] not in existing_ids:
            self.in_memory_videos.append(video_record)
        self.in_memory_chunks[video_record['id']] = tagged_chunks
        self._save_disk_persistence()

        return video_record

    def get_all_videos(self) -> List[Dict[str, Any]]:
        """Fetches all video records from PostgreSQL or persistent store."""
        conn = self.get_connection() if self.is_connected else None
        if conn:
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("SELECT * FROM videos ORDER BY id DESC;")
                records = cursor.fetchall()
                cursor.close()
                conn.close()
                if records:
                    return [dict(r) for r in records]
            except Exception as e:
                logger.error(f"Failed to fetch videos from PostgreSQL: {e}")

        return list(reversed(self.in_memory_videos))

    def get_video_by_id(self, video_id: int) -> Optional[Dict[str, Any]]:
        """Fetches video details by ID."""
        conn = self.get_connection() if self.is_connected else None
        if conn:
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute("SELECT * FROM videos WHERE id = %s;", (video_id,))
                record = cursor.fetchone()
                cursor.close()
                conn.close()
                if record:
                    return dict(record)
            except Exception as e:
                logger.error(f"Failed to fetch video {video_id} from PostgreSQL: {e}")

        for v in self.in_memory_videos:
            if v['id'] == video_id:
                return v
        return None

    def get_chunks_by_video_id(self, video_id: int) -> List[Dict[str, Any]]:
        """Fetches all SRT vector chunks for a specific video."""
        conn = self.get_connection() if self.is_connected else None
        if conn:
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute(
                    "SELECT * FROM transcript_chunks WHERE video_id = %s ORDER BY chunk_id ASC;",
                    (video_id,)
                )
                records = cursor.fetchall()
                cursor.close()
                conn.close()

                if records:
                    chunks = []
                    for r in records:
                        item = dict(r)
                        if item.get('embedding') and isinstance(item['embedding'], str):
                            try:
                                item['embedding'] = json.loads(item['embedding'])
                            except Exception:
                                pass
                        chunks.append(item)
                    return chunks
            except Exception as e:
                logger.error(f"Failed to fetch chunks for video {video_id} from PostgreSQL: {e}")

        return self.in_memory_chunks.get(video_id, [])

    def update_video(self, video_id: int, new_name: str, new_url: str = "") -> Optional[Dict[str, Any]]:
        """Updates video title and URL in PostgreSQL and persistent store."""
        updated = None
        conn = self.get_connection() if self.is_connected else None
        source_type = None
        if new_url:
            source_type = "youtube" if ("youtube.com" in new_url or "youtu.be" in new_url) else "local"

        if conn:
            try:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                if new_url:
                    cursor.execute(
                        "UPDATE videos SET video_name = %s, video_url = %s, source_type = %s WHERE id = %s RETURNING *;",
                        (new_name, new_url, source_type, video_id)
                    )
                else:
                    cursor.execute(
                        "UPDATE videos SET video_name = %s WHERE id = %s RETURNING *;",
                        (new_name, video_id)
                    )
                record = cursor.fetchone()
                conn.commit()
                cursor.close()
                conn.close()
                if record:
                    updated = dict(record)
            except Exception as e:
                logger.error(f"Failed to update video {video_id} in PostgreSQL: {e}")

        # Update in-memory & disk persistence
        for v in self.in_memory_videos:
            if v['id'] == video_id:
                v['video_name'] = new_name
                if new_url:
                    v['video_url'] = new_url
                    v['source_type'] = source_type
                if not updated:
                    updated = v

        if video_id in self.in_memory_chunks:
            for c in self.in_memory_chunks[video_id]:
                c['video_name'] = new_name

        self._save_disk_persistence()
        return updated

    def delete_video(self, video_id: int) -> bool:
        """Deletes a video and its SRT chunks from PostgreSQL and persistent store."""
        conn = self.get_connection() if self.is_connected else None
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM videos WHERE id = %s;", (video_id,))
                conn.commit()
                cursor.close()
                conn.close()
            except Exception as e:
                logger.error(f"Failed to delete video {video_id} from PostgreSQL: {e}")

        self.in_memory_videos = [v for v in self.in_memory_videos if v['id'] != video_id]
        if video_id in self.in_memory_chunks:
            del self.in_memory_chunks[video_id]
        self._save_disk_persistence()
        return True

# Singleton PostgreSQL Database Manager
db_manager = PostgresDBManager()

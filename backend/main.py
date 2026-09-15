from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
import shutil
import uvicorn
from typing import Optional

from srt_parser import parse_srt, create_chunks
from rag_engine import rag_store
from llm_provider import generate_qwen_answer, check_ollama_status
from db import db_manager

app = FastAPI(title="Video Transcript Chatbot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Upload directory paths
UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "uploads", "videos"))
SRT_UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "uploads", "srt"))
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(SRT_UPLOAD_DIR, exist_ok=True)

class QueryRequest(BaseModel):
    query: str
    provider: str = "auto"
    api_key: str = ""

class OpenTextEditRequest(BaseModel):
    filename: str = ""

# Track currently active video ID
active_video_id: Optional[int] = None
active_video_name: str = ""

@app.on_event("startup")
def startup_event():
    """Initializes PostgreSQL database and seeds initial sample video if store is empty."""
    global active_video_id, active_video_name
    db_manager.init_db()
    
    # Check if any videos exist; if not, seed sample_malayalam.srt
    videos = db_manager.get_all_videos()
    if not videos:
        sample_srt_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sample_data", "sample_malayalam.srt"))
        if os.path.exists(sample_srt_path):
            try:
                with open(sample_srt_path, "r", encoding="utf-8") as f:
                    srt_text = f.read()
                parsed = parse_srt(srt_text)
                if parsed:
                    chunks = create_chunks(parsed, target_word_count=200, overlap_blocks=2)
                    rag_store.index_chunks(chunks)
                    rec = db_manager.save_video_and_chunks(
                        video_name="Sample Malayalam Video",
                        source_type="youtube",
                        video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                        srt_filename="sample_malayalam.srt",
                        chunks=chunks
                    )
                    active_video_id = rec.get("id")
                    active_video_name = rec.get("video_name")
            except Exception as e:
                print(f"Error seeding initial sample video: {e}")
    else:
        # Load the latest video as active default
        latest = videos[0]
        v_chunks = db_manager.get_chunks_by_video_id(latest['id'])
        if v_chunks:
            rag_store.set_active_chunks(v_chunks, video_name=latest['video_name'], video_id=latest['id'])
            active_video_id = latest['id']
            active_video_name = latest['video_name']

@app.get("/api/status")
def get_status():
    ollama_info = check_ollama_status()
    return {
        "status": "online",
        "postgres_connected": db_manager.is_connected,
        "active_video_id": active_video_id,
        "active_video_name": active_video_name,
        "indexed_chunks": len(rag_store.chunks),
        "ollama": ollama_info,
        "transformer_active": rag_store.use_transformer
    }

@app.get("/api/videos")
def list_videos():
    """Returns all stored videos from PostgreSQL."""
    videos = db_manager.get_all_videos()
    return {"videos": videos, "active_video_id": active_video_id}

@app.get("/api/videos/{video_id}")
def get_video_detail(video_id: int):
    """Returns details and chunks for a given video ID."""
    video = db_manager.get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")
    chunks = db_manager.get_chunks_by_video_id(video_id)
    return {"video": video, "chunks": chunks}

@app.post("/api/select-video/{video_id}")
def select_video(video_id: int):
    """Activates a video's transcript vector chunks in the RAG store for chat queries."""
    global active_video_id, active_video_name
    video = db_manager.get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")
        
    chunks = db_manager.get_chunks_by_video_id(video_id)
    rag_store.set_active_chunks(chunks, video_name=video['video_name'], video_id=video_id)
    
    active_video_id = video_id
    active_video_name = video['video_name']
    
    return {
        "success": True,
        "video": video,
        "total_chunks": len(chunks)
    }

class EditVideoRequest(BaseModel):
    video_name: str
    video_url: Optional[str] = ""

@app.put("/api/videos/{video_id}")
def edit_video(video_id: int, req: EditVideoRequest):
    """Edits video title and optional URL."""
    global active_video_id, active_video_name
    if not req.video_name.strip():
        raise HTTPException(status_code=400, detail="Video title cannot be empty.")
    
    updated = db_manager.update_video(video_id, req.video_name.strip(), req.video_url.strip())
    if not updated:
        raise HTTPException(status_code=404, detail="Video not found.")
        
    if active_video_id == video_id:
        active_video_name = req.video_name.strip()
        
    return {"success": True, "video": updated}

@app.delete("/api/videos/{video_id}")
def delete_video(video_id: int):
    """Deletes a video and its SRT chunks from PostgreSQL database."""
    global active_video_id, active_video_name
    video = db_manager.get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")
        
    success = db_manager.delete_video(video_id)
    if active_video_id == video_id:
        active_video_id = None
        active_video_name = ""
        rag_store.clear()
        
    return {"success": success, "message": f"Video '{video['video_name']}' deleted."}

@app.post("/api/admin/upload")
async def admin_upload_video_srt(
    video_name: str = Form(...),
    source_type: str = Form("local"), # "local" or "youtube"
    video_url: str = Form(""),
    video_file: Optional[UploadFile] = File(None),
    srt_file: UploadFile = File(...)
):
    """
    Admin endpoint: Uploads video file (or Youtube URL) and SRT file,
    chunks the SRT with video_name attached, computes vector embeddings,
    stores in PostgreSQL, and sets active context.
    """
    global active_video_id, active_video_name
    try:
        final_video_url = video_url.strip()
        
        # Save video file if provided for local source
        if source_type == "local" and video_file and video_file.filename:
            safe_video_name = "".join(c for c in video_file.filename if c.isalnum() or c in (".", "_", "-")).strip()
            save_path = os.path.join(UPLOAD_DIR, safe_video_name)
            with open(save_path, "wb") as buffer:
                shutil.copyfileobj(video_file.file, buffer)
            final_video_url = f"/uploads/videos/{safe_video_name}"
            
        if not final_video_url:
            final_video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

        # Read and parse SRT file
        content_bytes = await srt_file.read()
        srt_text = content_bytes.decode("utf-8", errors="ignore")
        
        parsed_blocks = parse_srt(srt_text)
        if not parsed_blocks:
            raise HTTPException(status_code=400, detail="Failed to parse SRT file. Check file format.")
            
        # Save SRT file locally
        safe_srt_filename = "".join(c for c in srt_file.filename if c.isalnum() or c in (".", "_", "-")).strip()
        if not safe_srt_filename.endswith(".srt"):
            safe_srt_filename += ".srt"
        srt_save_path = os.path.join(SRT_UPLOAD_DIR, safe_srt_filename)
        with open(srt_save_path, "w", encoding="utf-8") as f:
            f.write(srt_text)

        # Create chunks and generate vector embeddings
        chunks = create_chunks(parsed_blocks, target_word_count=200, overlap_blocks=2)
        
        # Compute embeddings via rag_store
        rag_store.index_chunks(chunks)

        # Save to PostgreSQL DB
        video_rec = db_manager.save_video_and_chunks(
            video_name=video_name.strip(),
            source_type=source_type,
            video_url=final_video_url,
            srt_filename=safe_srt_filename,
            chunks=chunks
        )

        active_video_id = video_rec['id']
        active_video_name = video_rec['video_name']

        return {
            "success": True,
            "video": video_rec,
            "total_blocks": len(parsed_blocks),
            "total_chunks": len(chunks),
            "sample_chunks": chunks[:3]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Admin Upload Failed: {str(e)}")

# Backwards compatibility endpoints
@app.post("/api/upload-video")
async def upload_video(video_file: UploadFile = File(...)):
    try:
        safe_filename = "".join(c for c in video_file.filename if c.isalnum() or c in (".", "_", "-")).strip()
        save_path = os.path.join(UPLOAD_DIR, safe_filename)
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(video_file.file, buffer)
        return {"success": True, "filename": safe_filename, "url": f"/uploads/videos/{safe_filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload-srt")
async def upload_srt(video_url: str = Form(""), file: UploadFile = File(...)):
    try:
        content_bytes = await file.read()
        srt_text = content_bytes.decode("utf-8", errors="ignore")
        parsed_blocks = parse_srt(srt_text)
        if not parsed_blocks:
            raise HTTPException(status_code=400, detail="Failed to parse SRT file.")
            
        safe_srt_filename = "".join(c for c in file.filename if c.isalnum() or c in (".", "_", "-")).strip()
        if not safe_srt_filename.endswith(".srt"):
            safe_srt_filename += ".srt"
        srt_save_path = os.path.join(SRT_UPLOAD_DIR, safe_srt_filename)
        with open(srt_save_path, "w", encoding="utf-8") as f:
            f.write(srt_text)

        chunks = create_chunks(parsed_blocks, target_word_count=200, overlap_blocks=2)
        rag_store.index_chunks(chunks)
        
        # Save to DB
        v_name = safe_srt_filename.replace(".srt", "").replace("_", " ").title()
        v_rec = db_manager.save_video_and_chunks(
            video_name=v_name,
            source_type="youtube" if ("youtube" in video_url or "youtu.be" in video_url) else "local",
            video_url=video_url or "/uploads/videos/sample.mp4",
            srt_filename=safe_srt_filename,
            chunks=chunks
        )
        global active_video_id, active_video_name
        active_video_id = v_rec['id']
        active_video_name = v_rec['video_name']
        
        return {
            "success": True,
            "filename": safe_srt_filename,
            "video_url": video_url,
            "total_blocks": len(parsed_blocks),
            "total_chunks": len(chunks)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/open-srt-textedit")
def open_srt_in_textedit(req: OpenTextEditRequest):
    """Opens the uploaded SRT file in macOS TextEdit."""
    filename = req.filename.strip()
    srt_path = ""
    
    if filename:
        safe_filename = "".join(c for c in filename if c.isalnum() or c in (".", "_", "-")).strip()
        candidate = os.path.join(SRT_UPLOAD_DIR, safe_filename)
        if os.path.exists(candidate):
            srt_path = candidate
        else:
            sample_candidate = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sample_data", safe_filename))
            if os.path.exists(sample_candidate):
                srt_path = sample_candidate

    if not srt_path:
        all_srts = [os.path.join(SRT_UPLOAD_DIR, f) for f in os.listdir(SRT_UPLOAD_DIR) if f.endswith(".srt")]
        sample_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sample_data"))
        if os.path.exists(sample_dir):
            all_srts.extend([os.path.join(sample_dir, f) for f in os.listdir(sample_dir) if f.endswith(".srt")])
            
        if not all_srts:
            raise HTTPException(status_code=404, detail="No SRT file found to open.")
        srt_path = max(all_srts, key=os.path.getmtime)
        
    try:
        import subprocess
        subprocess.Popen(["open", "-a", "TextEdit", srt_path])
        return {"success": True, "filename": os.path.basename(srt_path), "path": srt_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to launch TextEdit: {str(e)}")

@app.post("/api/query")
def query_transcript(req: QueryRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
        
    if not rag_store.chunks:
        return {
            "answer": "⚠️ No video transcript selected yet. Please select a video from the list on the Home page or upload one in the Admin Panel!",
            "provider": "System",
            "timestamps": []
        }
        
    from llm_provider import classify_summary_intent
    intent = classify_summary_intent(req.query)
    
    if intent["is_full_summary"]:
        top_k = 15
        top_chunks = rag_store.search(req.query, top_k=top_k, is_full_summary=True)
    elif intent["is_topic_summary"]:
        top_k = 5
        top_chunks = rag_store.search(req.query, top_k=top_k, is_full_summary=False)
    else:
        top_k = 4
        top_chunks = rag_store.search(req.query, top_k=top_k, is_full_summary=False)
    
    result = generate_qwen_answer(
        query=req.query,
        context_chunks=top_chunks,
        provider=req.provider,
        api_key=req.api_key
    )
    
    return result

# Serve static uploads
uploads_static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "uploads"))
app.mount("/uploads", StaticFiles(directory=uploads_static_dir), name="uploads")

# Serve static frontend files
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

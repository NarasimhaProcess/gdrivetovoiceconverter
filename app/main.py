"""
FastAPI Server for Google Drive to Voice Converter.
Provides REST and SSE endpoints for Drive file browsing, credential management,
voice conversion with tempo-sync, and direct language-folder Drive upload.
"""

import os
import json
import uuid
import shutil
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.config import (
    BASE_DIR, STORAGE_DIR, TEMP_DIR, OUTPUT_DIR,
    load_gdrive_credentials, save_gdrive_credentials
)
from app.languages import LANGUAGES, get_languages_list, get_language_folder_name
from app.gdrive_service import GDriveManager
from app.voice_converter import VideoVoiceConverter, get_media_duration

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("gdrive_voice_converter")

app = FastAPI(title="Google Drive to Voice Converter")

# Mount static and templates
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# In-memory jobs tracking
jobs: Dict[str, Dict[str, Any]] = {}
job_events: Dict[str, asyncio.Queue] = {}

def get_drive_manager() -> GDriveManager:
    return GDriveManager()

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/status")
async def get_status():
    """Check credentials and connection to Google Drive."""
    try:
        manager = get_drive_manager()
        status = manager.get_status()
        status["has_env_key"] = bool(os.environ.get("GDRIVE_CREDENTIALS"))
        return status
    except Exception as e:
        return {
            "connected": False,
            "error": str(e),
            "has_env_key": bool(os.environ.get("GDRIVE_CREDENTIALS")),
            "type": None,
            "email": None
        }

@app.post("/api/credentials")
async def update_credentials(
    credentials_file: Optional[UploadFile] = File(None),
    credentials_json: Optional[str] = Form(None)
):
    """Save credentials from uploaded JSON file or pasted JSON text."""
    data = None
    if credentials_file:
        content = await credentials_file.read()
        try:
            data = json.loads(content.decode("utf-8"))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON in uploaded file: {e}")
    elif credentials_json:
        try:
            data = json.loads(credentials_json)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON string: {e}")
    else:
        raise HTTPException(status_code=400, detail="No credentials provided.")

    saved_path = save_gdrive_credentials(data)
    manager = GDriveManager(creds_dict=data)
    status = manager.get_status()

    return {
        "success": True,
        "saved_path": saved_path,
        "status": status
    }

@app.get("/api/languages")
async def list_languages():
    """Returns available Indian languages and Professional English."""
    return {
        "languages": get_languages_list()
    }

@app.get("/api/drive/files")
async def list_drive_files(folder_id: Optional[str] = None, q: Optional[str] = None):
    """Lists video files and folders from Google Drive."""
    manager = get_drive_manager()
    try:
        data = manager.list_files_and_folders(folder_id=folder_id, search_query=q)
        return data
    except Exception as e:
        logger.error(f"Error listing Drive files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def update_job_progress(job_id: str, progress: int, message: str, **kwargs):
    if job_id in jobs:
        jobs[job_id]["progress"] = progress
        jobs[job_id]["message"] = message
        for k, v in kwargs.items():
            jobs[job_id][k] = v
        # Notify SSE queue
        if job_id in job_events:
            event_data = {
                "progress": progress,
                "message": message,
                **{k: v for k, v in kwargs.items() if isinstance(v, (str, int, float, bool, dict, list))}
            }
            try:
                job_events[job_id].put_nowait(event_data)
            except asyncio.QueueFull:
                pass

def process_conversion_task(job_id: str, options: Dict[str, Any]):
    """Background worker for video download, voice dubbing, tempo match, and drive upload."""
    job_work_dir = TEMP_DIR / job_id
    job_work_dir.mkdir(parents=True, exist_ok=True)

    try:
        drive_file_id = options.get("drive_file_id")
        uploaded_video_path = options.get("local_video_path")
        target_lang = options.get("target_lang", "hi")
        voice_id = options.get("voice_id")
        match_duration = options.get("match_duration", True)
        duck_original_audio = options.get("duck_original_audio", False)
        background_volume = options.get("background_volume", 0.15)
        dest_folder_mode = options.get("dest_folder_mode", "same_as_source")
        file_name = options.get("file_name", "video.mp4")
        parent_folder_id = options.get("parent_folder_id")

        manager = get_drive_manager()
        video_local_path = None

        # Step 1: Obtain video file
        if drive_file_id:
            update_job_progress(job_id, 5, "Connecting to Google Drive to download video...")
            dest_video = job_work_dir / f"input_{file_name}"
            video_local_path = manager.download_file(
                drive_file_id,
                dest_video,
                progress_callback=lambda pct, msg: update_job_progress(job_id, pct, msg)
            )
            # Retrieve parent folder ID of source video if same_as_source mode
            if not parent_folder_id and dest_folder_mode == "same_as_source":
                try:
                    meta = manager.get_file_metadata(drive_file_id)
                    parents = meta.get("parents", [])
                    if parents:
                        parent_folder_id = parents[0]
                except Exception as e:
                    logger.warning(f"Could not get parent folder ID: {e}")
        elif uploaded_video_path and Path(uploaded_video_path).exists():
            video_local_path = Path(uploaded_video_path)
            update_job_progress(job_id, 25, "Local video file ready for conversion...")
        else:
            raise ValueError("No video file provided.")

        jobs[job_id]["input_video_path"] = str(video_local_path)

        # Step 2: Convert voice & match video
        converter = VideoVoiceConverter(job_work_dir)
        conv_result = converter.convert_video_voice(
            video_path=video_local_path,
            target_lang=target_lang,
            voice_id=voice_id,
            match_duration=match_duration,
            duck_original_audio=duck_original_audio,
            background_volume=background_volume,
            progress_callback=lambda pct, msg: update_job_progress(job_id, pct, msg)
        )

        output_video_path = conv_result["output_video_path"]
        jobs[job_id]["converted_video_path"] = str(output_video_path)
        jobs[job_id]["original_transcript"] = conv_result["original_transcript"]
        jobs[job_id]["translated_transcript"] = conv_result["translated_transcript"]

        # Step 3: Save to permanent output storage
        lang_folder_name = get_language_folder_name(target_lang)
        base_name, ext = os.path.splitext(file_name)
        if not ext:
            ext = ".mp4"
        out_filename = f"{base_name}_{lang_folder_name}{ext}"

        final_local_file = OUTPUT_DIR / f"{job_id}_{out_filename}"
        shutil.copy2(output_video_path, final_local_file)
        jobs[job_id]["final_local_file"] = str(final_local_file)
        jobs[job_id]["final_filename"] = out_filename

        # Step 4: Google Drive Upload directly to Language Folder
        drive_uploaded = False
        upload_response = {}
        folder_link = ""
        drive_warning = None

        try:
            update_job_progress(job_id, 82, "Preparing Google Drive target language folder...")
            # Determine parent folder for target language folder
            target_parent = parent_folder_id if (dest_folder_mode == "same_as_source" and parent_folder_id) else None

            # Create or find language folder in Google Drive
            drive_lang_folder = manager.get_or_create_language_folder(
                language_folder_name=lang_folder_name,
                parent_folder_id=target_parent
            )
            folder_id = drive_lang_folder.get("id")
            folder_link = drive_lang_folder.get("webViewLink", "")
            jobs[job_id]["drive_folder_id"] = folder_id
            jobs[job_id]["drive_folder_name"] = lang_folder_name
            jobs[job_id]["drive_folder_link"] = folder_link

            # Upload file to the language folder
            upload_response = manager.upload_file(
                local_path=output_video_path,
                filename=out_filename,
                folder_id=folder_id,
                mime_type="video/mp4",
                progress_callback=lambda pct, msg: update_job_progress(job_id, pct, msg)
            )
            drive_uploaded = True
        except Exception as drive_err:
            logger.warning(f"Google Drive upload skipped or failed: {drive_err}")
            err_str = str(drive_err)
            if "storageQuota" in err_str or "storage quota" in err_str:
                drive_warning = (
                    "Google Drive limitation: Service Accounts have 0 MB personal storage quota and cannot upload files directly to personal @gmail.com accounts without a Google Workspace Shared Drive or OAuth. "
                    "Your converted video is ready to download and watch below!"
                )
            else:
                drive_warning = f"Drive upload notice: {drive_err}"

        if drive_uploaded:
            finish_msg = "Voice conversion and direct Drive export complete!"
        else:
            finish_msg = "Voice conversion complete! Converted video ready to download below."

        update_job_progress(
            job_id,
            100,
            finish_msg,
            status="completed",
            drive_file_id=upload_response.get("id"),
            drive_file_link=upload_response.get("webViewLink"),
            drive_folder_link=folder_link,
            drive_folder_name=lang_folder_name,
            drive_warning=drive_warning,
            filename=out_filename
        )

    except Exception as e:
        logger.exception(f"Job {job_id} failed: {e}")
        update_job_progress(job_id, 0, f"Error: {str(e)}", status="failed", error=str(e))


@app.post("/api/convert")
async def start_conversion(
    background_tasks: BackgroundTasks,
    drive_file_id: Optional[str] = Form(None),
    file_name: Optional[str] = Form("video.mp4"),
    parent_folder_id: Optional[str] = Form(None),
    target_lang: str = Form("hi"),
    voice_id: Optional[str] = Form(None),
    match_duration: bool = Form(True),
    duck_original_audio: bool = Form(False),
    background_volume: float = Form(0.15),
    dest_folder_mode: str = Form("same_as_source"),
    upload_file: Optional[UploadFile] = File(None)
):
    """Starts asynchronous conversion and returns job_id."""
    job_id = str(uuid.uuid4())[:8]
    local_video_path = None

    if upload_file and upload_file.filename:
        file_name = upload_file.filename
        job_temp = TEMP_DIR / job_id
        job_temp.mkdir(parents=True, exist_ok=True)
        local_video_path = job_temp / file_name
        with open(local_video_path, "wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)

    if not drive_file_id and not local_video_path:
        raise HTTPException(status_code=400, detail="Please select a video from Google Drive or upload a video file.")

    jobs[job_id] = {
        "job_id": job_id,
        "status": "processing",
        "progress": 2,
        "message": "Initializing voice conversion pipeline...",
        "file_name": file_name,
        "target_lang": target_lang,
        "voice_id": voice_id
    }
    job_events[job_id] = asyncio.Queue(maxsize=50)

    options = {
        "drive_file_id": drive_file_id,
        "local_video_path": str(local_video_path) if local_video_path else None,
        "file_name": file_name,
        "parent_folder_id": parent_folder_id,
        "target_lang": target_lang,
        "voice_id": voice_id,
        "match_duration": match_duration,
        "duck_original_audio": duck_original_audio,
        "background_volume": background_volume,
        "dest_folder_mode": dest_folder_mode
    }

    background_tasks.add_task(process_conversion_task, job_id, options)

    return {"job_id": job_id, "status": "processing"}


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Poll job status."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.get("/api/jobs/{job_id}/stream")
async def stream_job_progress(job_id: str):
    """Server-Sent Events stream for real-time progress updates."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        q = job_events.get(job_id)
        # Send current initial state
        initial_data = json.dumps(jobs[job_id])
        yield f"data: {initial_data}\n\n"

        while True:
            if jobs.get(job_id, {}).get("status") in ("completed", "failed"):
                final_data = json.dumps(jobs[job_id])
                yield f"data: {final_data}\n\n"
                break

            if q:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=2.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat
                    yield f": ping\n\n"
            else:
                await asyncio.sleep(1.0)
                yield f"data: {json.dumps(jobs.get(job_id, {}))}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/preview/{job_id}/original")
async def preview_original_video(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    p = jobs[job_id].get("input_video_path")
    if not p or not Path(p).exists():
        raise HTTPException(status_code=404, detail="Original video file not available")
    return FileResponse(p, media_type="video/mp4")


@app.get("/api/preview/{job_id}/converted")
async def preview_converted_video(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    p = jobs[job_id].get("converted_video_path") or jobs[job_id].get("final_local_file")
    if not p or not Path(p).exists():
        raise HTTPException(status_code=404, detail="Converted video file not available")
    return FileResponse(p, media_type="video/mp4")


@app.get("/api/download/{job_id}")
async def download_converted_file(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    p = jobs[job_id].get("final_local_file") or jobs[job_id].get("converted_video_path")
    if not p or not Path(p).exists():
        raise HTTPException(status_code=404, detail="Output file not found")
    filename = jobs[job_id].get("final_filename", "converted_video.mp4")
    return FileResponse(p, media_type="video/mp4", filename=filename)

"""
FastAPI Server for Google Drive to Voice Converter.
Provides REST and SSE endpoints for Drive file browsing, credential management,
voice conversion with tempo-sync, and direct language-folder Drive upload.
"""

import os
import json
import uuid
import shutil
import zipfile
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

import py7zr

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

from app.config import (
    BASE_DIR, STORAGE_DIR, TEMP_DIR, OUTPUT_DIR,
    MAX_UPLOAD_SIZE_BYTES, MAX_UPLOAD_SIZE_MB, MAX_UPLOAD_SIZE_GB,
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

@app.get("/api/config")
async def get_app_config():
    """Returns application configuration including max file size limits."""
    return {
        "max_upload_size_bytes": MAX_UPLOAD_SIZE_BYTES,
        "max_upload_size_mb": MAX_UPLOAD_SIZE_MB,
        "max_upload_size_gb": MAX_UPLOAD_SIZE_GB
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

@app.get("/api/drive/download/{file_id}")
async def download_drive_file(file_id: str):
    """Directly download a file from Google Drive to the browser without needing to open Google Drive."""
    manager = get_drive_manager()
    try:
        meta = manager.get_file_metadata(file_id)
        file_name = meta.get("name", f"video_{file_id}.mp4")
        mime_type = meta.get("mimeType", "video/mp4")
        temp_file = TEMP_DIR / "downloads" / f"{file_id}_{file_name}"
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        if not temp_file.exists() or temp_file.stat().st_size == 0:
            manager.download_file(file_id, temp_file)
        return FileResponse(
            temp_file,
            media_type=mime_type,
            filename=file_name
        )
    except Exception as e:
        logger.error(f"Error directly downloading Drive file {file_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".flv", ".wmv", ".m4v"}
ARCHIVE_EXTENSIONS = {".zip", ".7z"}

def extract_archive(archive_path: Path, extract_dir: Path) -> Tuple[Path, Optional[str]]:
    """
    Safely extracts a .zip or .7z archive.
    Returns (primary_video_path, optional_custom_script_text).
    """
    extract_dir.mkdir(parents=True, exist_ok=True)
    ext = archive_path.suffix.lower()

    if ext == ".zip":
        with zipfile.ZipFile(archive_path, 'r') as zf:
            for member in zf.infolist():
                dest = (extract_dir / member.filename).resolve()
                if not str(dest).startswith(str(extract_dir.resolve())):
                    raise HTTPException(status_code=400, detail="Invalid archive: path traversal detected.")
            zf.extractall(extract_dir)
    elif ext == ".7z":
        with py7zr.SevenZipFile(archive_path, mode='r') as z:
            z.extractall(extract_dir)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported archive format: {ext}")

    video_files = []
    for p in extract_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
            video_files.append(p)

    if not video_files:
        raise HTTPException(
            status_code=400,
            detail="No supported video files (.mp4, .mkv, .mov, .webm, .avi) found inside the archive."
        )

    # Pick largest video file as the primary video
    video_files.sort(key=lambda f: f.stat().st_size, reverse=True)
    primary_video = video_files[0]

    # Check for custom transcript or script text file
    custom_script = None
    for p in extract_dir.rglob("*.txt"):
        if p.is_file() and ("transcript" in p.name.lower() or "script" in p.name.lower()):
            try:
                custom_script = p.read_text(encoding="utf-8", errors="ignore").strip()
                logger.info(f"Loaded custom script from archive: {p.name}")
                break
            except Exception:
                pass

    return primary_video, custom_script


def create_dubbing_package(job_id: str, fmt: str = "zip") -> Path:
    """
    Creates a ZIP or 7-Zip package containing:
    - Converted MP4 video
    - Isolated Neural Voiceover Track (MP3/WAV)
    - Original & Translated Transcripts (.txt)
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    converted_video = job.get("final_local_file") or job.get("converted_video_path")
    if not converted_video or not Path(converted_video).exists():
        raise HTTPException(status_code=404, detail="Converted video file not found")

    target_lang = job.get("target_lang", "hi")
    lang_name = LANGUAGES.get(target_lang, {}).get("name", target_lang)
    final_filename = job.get("final_filename", "converted_video.mp4")
    stem = Path(final_filename).stem

    package_dir = TEMP_DIR / job_id / "package"
    package_dir.mkdir(parents=True, exist_ok=True)

    # 1. Video
    pkg_video = package_dir / Path(converted_video).name
    if not pkg_video.exists():
        shutil.copy2(converted_video, pkg_video)

    # 2. Voice audio
    voice_path = job.get("final_voice_file") or job.get("voice_audio_path")
    if voice_path and Path(voice_path).exists():
        voice_ext = Path(voice_path).suffix or ".mp3"
        pkg_audio = package_dir / f"{stem}_voiceover{voice_ext}"
        if not pkg_audio.exists():
            shutil.copy2(voice_path, pkg_audio)

    # 3. Transcripts
    orig_text = job.get("original_transcript", "")
    trans_text = job.get("translated_transcript", "")
    pkg_transcript = package_dir / f"{stem}_transcripts.txt"
    pkg_transcript.write_text(
        f"===========================================================\n"
        f"  DriveVoice AI - Video Dubbing Kit\n"
        f"  File: {final_filename}\n"
        f"  Target Language: {lang_name} ({target_lang})\n"
        f"===========================================================\n\n"
        f"--- ORIGINAL DETECTED SPEECH ---\n"
        f"{orig_text}\n\n"
        f"--- TRANSLATED & DUBBED SPEECH ({lang_name}) ---\n"
        f"{trans_text}\n",
        encoding="utf-8"
    )

    # 4. Generate Archive
    if fmt == "zip":
        archive_path = OUTPUT_DIR / f"{job_id}_{stem}_dubbing_package.zip"
        if not archive_path.exists() or archive_path.stat().st_size == 0:
            with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                for item in package_dir.iterdir():
                    if item.is_file():
                        zf.write(item, arcname=item.name)
        return archive_path

    elif fmt == "7z":
        archive_path = OUTPUT_DIR / f"{job_id}_{stem}_dubbing_package.7z"
        if not archive_path.exists() or archive_path.stat().st_size == 0:
            with py7zr.SevenZipFile(archive_path, mode='w') as z:
                for item in package_dir.iterdir():
                    if item.is_file():
                        z.write(item, arcname=item.name)
        return archive_path

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}")


def update_job_progress(job_id: str, progress: int, message: str, **kwargs):
    if job_id in jobs:
        jobs[job_id]["progress"] = progress
        jobs[job_id]["message"] = message
        for k, v in kwargs.items():
            jobs[job_id][k] = v
        # Notify SSE queue
        if job_id in job_events:
            event_data = {
                "job_id": job_id,
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

        # Ensure faststart on input video so browser previews can stream and seek instantly without resets
        fast_input = job_work_dir / f"fast_{Path(video_local_path).name}"
        try:
            cmd = ["ffmpeg", "-y", "-i", str(video_local_path), "-c", "copy", "-movflags", "+faststart", str(fast_input)]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            if fast_input.exists() and fast_input.stat().st_size > 0:
                video_local_path = fast_input
        except Exception as e:
            logger.debug(f"Input faststart optimization note: {e}")

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
            custom_transcript=options.get("custom_script"),
            source_lang=options.get("source_lang", "auto"),
            voice_mode=options.get("voice_mode", "preset"),
            clone_source=options.get("clone_source", "upload"),
            clone_audio_path=Path(options["clone_audio_path"]) if options.get("clone_audio_path") else None,
            clone_engine=options.get("clone_engine", "acoustic"),
            elevenlabs_api_key=options.get("elevenlabs_api_key") or os.environ.get("ELEVENLABS_API_KEY"),
            progress_callback=lambda pct, msg: update_job_progress(job_id, pct, msg)
        )

        output_video_path = conv_result["output_video_path"]
        voice_audio_path = conv_result.get("voice_audio_path")
        jobs[job_id]["converted_video_path"] = str(output_video_path)
        jobs[job_id]["voice_audio_path"] = str(voice_audio_path) if voice_audio_path else ""
        jobs[job_id]["original_transcript"] = conv_result["original_transcript"]
        jobs[job_id]["translated_transcript"] = conv_result["translated_transcript"]
        jobs[job_id]["voice_mode"] = conv_result.get("voice_mode", "preset")
        jobs[job_id]["clone_profile"] = conv_result.get("clone_profile")

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

        if voice_audio_path and Path(voice_audio_path).exists():
            final_voice_file = OUTPUT_DIR / f"{job_id}_{base_name}_voiceover_{lang_folder_name}{Path(voice_audio_path).suffix}"
            shutil.copy2(voice_audio_path, final_voice_file)
            jobs[job_id]["final_voice_file"] = str(final_voice_file)

        # Step 4: Google Drive Upload directly to Language Folder or Direct Download
        if dest_folder_mode == "direct_download":
            logger.info(f"Direct download selected for job {job_id}. Skipping Google Drive upload.")
            update_job_progress(
                job_id,
                100,
                "Voice conversion complete! Converted video is ready for direct download.",
                status="completed",
                dest_folder_mode="direct_download",
                filename=out_filename
            )
        else:
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
                dest_folder_mode=dest_folder_mode,
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
    dest_folder_mode: str = Form("direct_download"),
    source_lang: Optional[str] = Form("auto"),
    voice_mode: str = Form("preset"),
    clone_source: str = Form("upload"),
    clone_engine: str = Form("acoustic"),
    elevenlabs_api_key: Optional[str] = Form(None),
    upload_file: Optional[UploadFile] = File(None),
    clone_file: Optional[UploadFile] = File(None)
):
    """Starts asynchronous conversion and returns job_id."""
    job_id = str(uuid.uuid4())[:8]
    local_video_path = None
    job_temp = TEMP_DIR / job_id
    job_temp.mkdir(parents=True, exist_ok=True)

    # Handle reference voice audio upload for cloning
    clone_audio_path = None
    if clone_file and clone_file.filename:
        raw_clone_name = clone_file.filename
        clone_audio_path = job_temp / f"ref_clone_{raw_clone_name}"
        with open(clone_audio_path, "wb") as c_buf:
            while chunk := await clone_file.read(1024 * 1024):
                c_buf.write(chunk)
        logger.info(f"Saved uploaded reference voice sample: {clone_audio_path}")

    custom_script = None
    if upload_file and upload_file.filename:
        raw_name = upload_file.filename
        uploaded_path = job_temp / raw_name
        
        # Stream file in 1MB chunks to disk without loading entire 2GB file into memory
        bytes_written = 0
        CHUNK_SIZE = 1024 * 1024  # 1 MB chunk
        with open(uploaded_path, "wb") as buffer:
            while chunk := await upload_file.read(CHUNK_SIZE):
                bytes_written += len(chunk)
                if bytes_written > MAX_UPLOAD_SIZE_BYTES:
                    buffer.close()
                    uploaded_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"Uploaded file exceeds maximum allowed size of {MAX_UPLOAD_SIZE_GB:.1f} GB ({MAX_UPLOAD_SIZE_MB} MB)."
                    )
                buffer.write(chunk)

        # Automatically extract .zip or .7z archives
        if uploaded_path.suffix.lower() in ARCHIVE_EXTENSIONS:
            unpacked_dir = job_temp / "unpacked"
            local_video_path, custom_script = extract_archive(uploaded_path, unpacked_dir)
            file_name = local_video_path.name
            logger.info(f"Unpacked {raw_name} -> found primary video {file_name}")
        else:
            local_video_path = uploaded_path
            file_name = raw_name

    if not drive_file_id and not local_video_path:
        raise HTTPException(status_code=400, detail="Please select a video from Google Drive or upload a video file.")

    jobs[job_id] = {
        "job_id": job_id,
        "status": "processing",
        "progress": 2,
        "message": "Initializing voice conversion pipeline...",
        "file_name": file_name,
        "target_lang": target_lang,
        "voice_id": voice_id,
        "voice_mode": voice_mode
    }
    job_events[job_id] = asyncio.Queue(maxsize=50)

    options = {
        "drive_file_id": drive_file_id,
        "local_video_path": str(local_video_path) if local_video_path else None,
        "file_name": file_name,
        "parent_folder_id": parent_folder_id,
        "target_lang": target_lang,
        "source_lang": source_lang or "auto",
        "voice_id": voice_id,
        "match_duration": match_duration,
        "duck_original_audio": duck_original_audio,
        "background_volume": background_volume,
        "dest_folder_mode": dest_folder_mode,
        "custom_script": custom_script,
        "voice_mode": voice_mode,
        "clone_source": clone_source,
        "clone_audio_path": str(clone_audio_path) if clone_audio_path else None,
        "clone_engine": clone_engine,
        "elevenlabs_api_key": elevenlabs_api_key
    }

    background_tasks.add_task(process_conversion_task, job_id, options)

    return {"job_id": job_id, "status": "processing"}


@app.post("/api/clone/analyze")
async def analyze_clone_sample(sample_file: UploadFile = File(...)):
    """Uploads an audio sample and returns the analyzed acoustic profile (pitch, gender, duration)."""
    temp_sample = TEMP_DIR / f"test_sample_{uuid.uuid4().hex[:6]}_{sample_file.filename}"
    try:
        with open(temp_sample, "wb") as bf:
            while chunk := await sample_file.read(1024 * 1024):
                bf.write(chunk)
        from app.voice_cloner import analyze_reference_voice
        prof = analyze_reference_voice(temp_sample)
        return {
            "success": True,
            "filename": sample_file.filename,
            "duration": round(prof.duration_sec, 1),
            "f0": round(prof.f0, 1),
            "gender": prof.gender,
            "pitch_scale": round(prof.pitch_scale, 2)
        }
    except Exception as e:
        logger.error(f"Sample analysis failed: {e}")
        return {"success": False, "error": str(e)}
    finally:
        temp_sample.unlink(missing_ok=True)


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
    return FileResponse(p, media_type="video/mp4", content_disposition_type="inline")


@app.get("/api/preview/{job_id}/converted")
async def preview_converted_video(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    p = jobs[job_id].get("converted_video_path") or jobs[job_id].get("final_local_file")
    if not p or not Path(p).exists():
        raise HTTPException(status_code=404, detail="Converted video file not available")
    return FileResponse(p, media_type="video/mp4", content_disposition_type="inline")


@app.get("/api/download/{job_id}")
async def download_converted_file(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    p = jobs[job_id].get("final_local_file") or jobs[job_id].get("converted_video_path")
    if not p or not Path(p).exists():
        raise HTTPException(status_code=404, detail="Output file not found")
    filename = jobs[job_id].get("final_filename", "converted_video.mp4")
    return FileResponse(p, media_type="video/mp4", filename=filename)


@app.get("/api/download/{job_id}/zip")
async def download_package_zip(job_id: str):
    """Downloads the complete dubbing package (video, voice audio, transcripts) as a ZIP archive."""
    archive_path = create_dubbing_package(job_id, fmt="zip")
    filename = archive_path.name
    if "_" in filename:
        filename = filename.split("_", 1)[1]
    return FileResponse(archive_path, media_type="application/zip", filename=filename)


@app.get("/api/download/{job_id}/7z")
async def download_package_7z(job_id: str):
    """Downloads the complete dubbing package as a 7-Zip (.7z) archive."""
    archive_path = create_dubbing_package(job_id, fmt="7z")
    filename = archive_path.name
    if "_" in filename:
        filename = filename.split("_", 1)[1]
    return FileResponse(archive_path, media_type="application/x-7z-compressed", filename=filename)

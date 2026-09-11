"""
Google Drive Service Manager.
Handles authentication, listing video files, downloading, folder creation, and uploading.
"""

import io
import os
import logging
from typing import Dict, Any, List, Optional, Tuple, Callable
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials

from app.config import load_gdrive_credentials

logger = logging.getLogger("gdrive_voice_converter")

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly"
]

VIDEO_MIME_TYPES = [
    "video/mp4",
    "video/webm",
    "video/x-matroska",
    "video/quicktime",
    "video/x-msvideo",
    "video/mpeg",
    "video/3gpp"
]

class GDriveManager:
    def __init__(self, creds_dict: Optional[Dict[str, Any]] = None):
        self.creds_dict = creds_dict or load_gdrive_credentials()
        self._service = None
        self._auth_info = None

    def get_service(self):
        if self._service is not None:
            return self._service

        if not self.creds_dict:
            self.creds_dict = load_gdrive_credentials()

        if not self.creds_dict:
            raise ValueError("Google Drive credentials not found. Please configure GDRIVE_CREDENTIALS or upload credentials.json.")

        try:
            # Check type of credentials
            creds_type = self.creds_dict.get("type")
            if creds_type == "service_account":
                credentials = service_account.Credentials.from_service_account_info(
                    self.creds_dict,
                    scopes=SCOPES
                )
                self._auth_info = {
                    "type": "service_account",
                    "email": self.creds_dict.get("client_email"),
                    "project_id": self.creds_dict.get("project_id")
                }
            elif "installed" in self.creds_dict or "web" in self.creds_dict or "client_id" in self.creds_dict:
                # OAuth2 client format or token format
                if "token" in self.creds_dict:
                    credentials = Credentials.from_authorized_user_info(self.creds_dict, scopes=SCOPES)
                else:
                    credentials = Credentials.from_authorized_user_info(self.creds_dict.get("installed", self.creds_dict.get("web", self.creds_dict)), scopes=SCOPES)
                self._auth_info = {
                    "type": "oauth2_user",
                    "email": self.creds_dict.get("client_email", "OAuth User"),
                    "project_id": self.creds_dict.get("project_id", "")
                }
            else:
                # Attempt service account parsing as default fallback
                credentials = service_account.Credentials.from_service_account_info(
                    self.creds_dict,
                    scopes=SCOPES
                )
                self._auth_info = {
                    "type": "service_account",
                    "email": self.creds_dict.get("client_email", "Unknown"),
                    "project_id": self.creds_dict.get("project_id", "")
                }

            self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)
            return self._service
        except Exception as e:
            logger.error(f"Failed to initialize Google Drive service: {e}")
            raise

    def get_status(self) -> Dict[str, Any]:
        """Returns connection status, account email, and drive info."""
        try:
            service = self.get_service()
            about = service.about().get(fields="user,storageQuota").execute()
            user_info = about.get("user", {})
            quota = about.get("storageQuota", {})
            
            email = self._auth_info.get("email") if self._auth_info else user_info.get("emailAddress")
            if not email:
                email = user_info.get("emailAddress", "Connected")

            return {
                "connected": True,
                "type": self._auth_info.get("type", "unknown") if self._auth_info else "service_account",
                "email": email,
                "display_name": user_info.get("displayName", "Google Drive User"),
                "project_id": self._auth_info.get("project_id") if self._auth_info else "",
                "storage_used": quota.get("usage", "0"),
                "storage_limit": quota.get("limit", "0")
            }
        except Exception as e:
            return {
                "connected": False,
                "error": str(e),
                "type": None,
                "email": None
            }

    def list_files_and_folders(self, folder_id: Optional[str] = None, search_query: Optional[str] = None) -> Dict[str, Any]:
        """
        Lists folders and video files in the specified folder (or all accessible files if root).
        """
        service = self.get_service()
        
        query_parts = ["trashed = false"]

        if folder_id:
            query_parts.append(f"'{folder_id}' in parents")

        if search_query and search_query.strip():
            escaped = search_query.replace("'", "\\'")
            query_parts.append(f"name contains '{escaped}'")

        # Include folders AND video files
        mime_clause = " or ".join([f"mimeType = '{m}'" for m in VIDEO_MIME_TYPES])
        type_filter = f"(mimeType = 'application/vnd.google-apps.folder' or {mime_clause} or mimeType contains 'video/')"
        query_parts.append(type_filter)

        q = " and ".join(query_parts)
        logger.info(f"Drive search query: {q}")

        results = service.files().list(
            q=q,
            pageSize=100,
            fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink, thumbnailLink, parents, iconLink)",
            orderBy="folder, name"
        ).execute()

        items = results.get("files", [])
        folders = []
        videos = []

        for item in items:
            is_folder = item.get("mimeType") == "application/vnd.google-apps.folder"
            formatted = {
                "id": item.get("id"),
                "name": item.get("name"),
                "mimeType": item.get("mimeType"),
                "size": int(item.get("size", 0)) if item.get("size") else 0,
                "modifiedTime": item.get("modifiedTime"),
                "webViewLink": item.get("webViewLink"),
                "thumbnailLink": item.get("thumbnailLink"),
                "parents": item.get("parents", []),
                "is_folder": is_folder
            }
            if is_folder:
                folders.append(formatted)
            else:
                videos.append(formatted)

        # Also get current folder name if folder_id is given
        current_folder_name = "Root / Shared with Me"
        parent_id = None
        if folder_id:
            try:
                meta = service.files().get(fileId=folder_id, fields="name, parents").execute()
                current_folder_name = meta.get("name", "Folder")
                parent_parents = meta.get("parents", [])
                if parent_parents:
                    parent_id = parent_parents[0]
            except Exception:
                pass

        return {
            "current_folder_id": folder_id,
            "current_folder_name": current_folder_name,
            "parent_folder_id": parent_id,
            "folders": folders,
            "videos": videos,
            "total_count": len(items)
        }

    def get_file_metadata(self, file_id: str) -> Dict[str, Any]:
        service = self.get_service()
        return service.files().get(
            fileId=file_id,
            fields="id, name, mimeType, size, modifiedTime, webViewLink, thumbnailLink, parents"
        ).execute()

    def download_file(self, file_id: str, dest_path: Path, progress_callback: Optional[Callable[[int, str], None]] = None) -> Path:
        """
        Downloads a file from Google Drive to local destination with progress updates.
        """
        service = self.get_service()
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if progress_callback:
            progress_callback(5, "Requesting file stream from Google Drive...")

        request = service.files().get_media(fileId=file_id)
        with io.FileIO(str(dest_path), "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024 * 5) # 5MB chunks
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status and progress_callback:
                    pct = int(status.progress() * 100)
                    # Scale download phase to 5% - 25% of overall pipeline
                    progress_callback(5 + int(pct * 0.20), f"Downloading from Drive: {pct}%")

        if progress_callback:
            progress_callback(25, "Download from Google Drive complete.")

        return dest_path

    def get_or_create_language_folder(self, language_folder_name: str, parent_folder_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Finds or creates a folder in Google Drive for the target language.
        If parent_folder_id is given, places the folder inside it; otherwise in root.
        """
        service = self.get_service()

        query_parts = [
            f"name = '{language_folder_name}'",
            "mimeType = 'application/vnd.google-apps.folder'",
            "trashed = false"
        ]
        if parent_folder_id:
            query_parts.append(f"'{parent_folder_id}' in parents")

        q = " and ".join(query_parts)
        results = service.files().list(
            q=q,
            spaces="drive",
            fields="files(id, name, webViewLink)"
        ).execute()

        files = results.get("files", [])
        if files:
            logger.info(f"Found existing Drive folder: {files[0]}")
            return files[0]

        # Create new folder
        folder_metadata = {
            "name": language_folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }
        if parent_folder_id:
            folder_metadata["parents"] = [parent_folder_id]

        folder = service.files().create(
            body=folder_metadata,
            fields="id, name, webViewLink"
        ).execute()
        logger.info(f"Created new Drive folder: {folder}")
        return folder

    def upload_file(self, local_path: Path, filename: str, folder_id: Optional[str] = None, mime_type: str = "video/mp4", progress_callback: Optional[Callable[[int, str], None]] = None) -> Dict[str, Any]:
        """
        Uploads a video to Google Drive inside the target language folder.
        """
        service = self.get_service()
        file_metadata = {
            "name": filename,
        }
        if folder_id:
            file_metadata["parents"] = [folder_id]

        media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True, chunksize=1024 * 1024 * 5)
        request = service.files().create(body=file_metadata, media_body=media, fields="id, name, webViewLink, webContentLink, size")

        if progress_callback:
            progress_callback(85, "Uploading converted video to Google Drive...")

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status and progress_callback:
                pct = int(status.progress() * 100)
                # Scale upload phase from 85% to 98%
                progress_callback(85 + int(pct * 0.13), f"Uploading to Drive: {pct}%")

        if progress_callback:
            progress_callback(100, "Successfully saved converted video to Google Drive!")

        return response

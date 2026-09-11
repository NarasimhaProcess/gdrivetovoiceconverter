import os
import json
import base64
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger("gdrive_voice_converter")

BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = BASE_DIR
STORAGE_DIR = BASE_DIR / "storage"
TEMP_DIR = STORAGE_DIR / "temp"
OUTPUT_DIR = STORAGE_DIR / "output"

for d in [STORAGE_DIR, TEMP_DIR, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

CREDENTIAL_CANDIDATES = [
    WORKSPACE_DIR / "credentials.json",
    WORKSPACE_DIR / "gdrive_credentials.json",
    WORKSPACE_DIR / "service_account.json",
    Path.home() / ".credentials" / "gdrive.json",
    Path("/workspaces/.codespaces/shared/gdrive_credentials.json"),
]

def load_gdrive_credentials() -> Optional[Dict[str, Any]]:
    """
    Attempts to load Google Drive credentials from:
    1. GDRIVE_CREDENTIALS environment variable (JSON string, base64 string, or file path)
    2. Local workspace files (credentials.json, gdrive_credentials.json, etc.)
    3. Codespaces secret files if mounted
    """
    env_creds = os.environ.get("GDRIVE_CREDENTIALS")
    if env_creds:
        env_creds = env_creds.strip()
        # Case 1: Raw JSON string
        if env_creds.startswith("{") and env_creds.endswith("}"):
            try:
                data = json.loads(env_creds)
                logger.info("Loaded credentials from GDRIVE_CREDENTIALS env var (JSON string)")
                return data
            except Exception as e:
                logger.error(f"Failed to parse GDRIVE_CREDENTIALS JSON: {e}")

        # Case 2: File path
        if os.path.exists(env_creds):
            try:
                with open(env_creds, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    logger.info(f"Loaded credentials from file path in GDRIVE_CREDENTIALS: {env_creds}")
                    return data
            except Exception as e:
                logger.error(f"Failed to read file from GDRIVE_CREDENTIALS path: {e}")

        # Case 3: Base64 encoded JSON
        try:
            decoded = base64.b64decode(env_creds).decode("utf-8")
            if decoded.startswith("{") and decoded.endswith("}"):
                data = json.loads(decoded)
                logger.info("Loaded credentials from GDRIVE_CREDENTIALS env var (base64 encoded)")
                return data
        except Exception:
            pass

    # Search local candidate files
    for path in CREDENTIAL_CANDIDATES:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    logger.info(f"Loaded credentials from file: {path}")
                    return data
            except Exception as e:
                logger.error(f"Error loading candidate credentials from {path}: {e}")

    return None

def save_gdrive_credentials(creds_dict: Dict[str, Any]) -> str:
    """
    Saves credentials to credentials.json in workspace and updates environment variable.
    """
    target_path = WORKSPACE_DIR / "credentials.json"
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(creds_dict, f, indent=2)
    os.environ["GDRIVE_CREDENTIALS"] = str(target_path)
    logger.info(f"Saved credentials to {target_path}")
    return str(target_path)

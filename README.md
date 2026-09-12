# Google Drive to Voice Converter & Video Dubbing Studio 🎙️🎬

An automated AI-powered video dubbing and translation studio integrated with **Google Drive**. 
It extracts audio from video files stored in Google Drive (or local upload), transcribes the speech, translates it into **Indian languages** or **Professional English**, generates expressive neural voiceovers with natural prosody, synchronizes the voice duration to match the original video speed, and uploads the dubbed video **directly back to Google Drive inside a language-specific folder** (e.g. `Drive / Hindi/video_Hindi.mp4`).

---

## 🌟 Key Features

- **Direct Download & Google Drive Export Options**:
  - **⚡ Direct Download Only**: Convert videos and download MP4s directly to your device without requiring Google Drive uploads or permissions (bypasses Service Account 0 MB personal quota restrictions).
  - **Drive File Explorer Direct Download**: Download any video directly from your Google Drive files list with 1-click without opening the Drive website.
  - **Direct Google Drive Integration**:
    - Connects using `GDRIVE_CREDENTIALS` (GitHub Secret, Codespaces environment variable, or `credentials.json`).
    - Interactive Drive Explorer: browse folders, preview video files, and search.
    - Automatic language folder creation on Google Drive (e.g., `Hindi/`, `Telugu/`, `Tamil/`, `Professional_English_Indian/`).
    - Chunked resumable upload directly back to Google Drive with direct web links to view the file and folder.
- **Indian Languages & Professional English Support**:
  - **Indian Languages**: Hindi (हिन्दी), Telugu (తెలుగు), Tamil (தமிழ்), Kannada (ಕನ್ನಡ), Malayalam (മലയാളം), Bengali (বাংলা), Marathi (मराठी), Gujarati (ગુજરાતી), Punjabi (ਪੰਜਾਬੀ), Urdu (اردو).
  - **Professional English**: Indian Accent (Neerja / Prabhat), US Accent (Jenny / Guy / Aria / Christopher), British UK Accent (Sonia / Ryan).
- **🎙️ AI & Acoustic Voice Cloning Studio (NEW)**:
  - **Upload Voice Sample**: Clone from any audio file (.wav, .mp3, .m4a, 10s–60s) with live audio preview and automatic pitch ($F_0$) & gender detection.
  - **Auto-Clone from Video**: Automatically isolates and clones the speaker's vocal characteristics directly from the source video (0 extra files needed).
  - **Live Microphone Recording**: Record voice directly in your browser with a 1-click 15-second recorder.
  - **Built-in 100% Free Acoustic Cloner**: High-resolution pitch retuning, formant shifting, and parametric EQ morphing with zero external dependencies.
  - **ElevenLabs AI Generative Clone**: Optional support for ElevenLabs instant voice cloning API.
- **Voice-to-Video Synchronization**:
  - **Tempo Alignment**: Automatically matches speech speed to video duration using FFmpeg `atempo` filters so dubbing syncs with scene timing.
  - **Smart Audio Ducking**: Option to retain original background music and ambient sound at a subtle volume while layering the clear converted voice over top.
- **Real-Time Interactive UI**:
  - Live progress tracking via Server-Sent Events (SSE) with step-by-step pipeline indicators.
  - Live side-by-side video preview players (Original Video vs Converted Video).
  - Download converted MP4 directly or open in Google Drive.

---

## 💻 System Prerequisites

### 1. Hardware Requirements
| Component | Minimum Specification | Recommended Specification |
| :--- | :--- | :--- |
| **Processor (CPU)** | Dual-Core (x86_64 or ARM64) | 4 Cores or higher |
| **RAM (Memory)** | 2 GB | 4 GB - 8 GB (for faster video muxing) |
| **Disk Storage** | 1.5 GB free space | 5 GB+ (depends on video file sizes) |
| **Network** | Active Internet connection (for Google Drive API, STT & Neural TTS) | Broadband connection |

### 2. Software Requirements
- **Python**: Version `3.9` to `3.14` (Python `3.10` or `3.12` recommended)
- **Git**: To clone the repository
- **FFmpeg**: For audio stream extraction, tempo matching, and MP4 remuxing (can be installed via OS package manager or auto-configured by `static-ffmpeg`)

### 3. OS-Specific Setup Commands

#### 🐧 Ubuntu / Debian / Raspberry Pi OS:
```bash
sudo apt update
sudo apt install -y python3 python3-pip git ffmpeg
```

#### 🎩 Fedora / Red Hat / CentOS:
```bash
sudo dnf install -y python3 python3-pip git ffmpeg
```

#### 🏹 Arch Linux:
```bash
sudo pacman -S python python-pip git ffmpeg
```

#### 🪟 Windows:
1. Install **Python 3.10+** from [python.org](https://www.python.org/downloads/) *(make sure to check **"Add python.exe to PATH"** during setup)*.
2. Install **Git for Windows** from [git-scm.com](https://git-scm.com).
3. *(Optional)* FFmpeg will be automatically fetched on first run by `static-ffmpeg`.

#### 🍎 macOS:
```bash
brew install python git ffmpeg
```

---

## 🚀 Quick Start for Any Client or Collaborator

### Opening in GitHub Codespaces (1-Click)
1. On GitHub, click the green **<> Code** button ➔ **Codespaces** tab ➔ **Create codespace on main**.
2. When the terminal opens, run just **ONE command**:
   ```bash
   ./run.sh
   ```
   *(This script automatically installs all required dependencies, configures FFmpeg, and launches the application on port 8000!)*
3. A popup will appear: **"Open in Browser"**. Click it to use the studio!

---

### If Running Locally on Any Machine
```bash
# 1. Clone repository
git clone https://github.com/NarasimhaProcess/gdrivetovoiceconverter.git
cd gdrivetovoiceconverter

# 2. Run startup script (auto-installs requirements and starts)
./run.sh
```
Open your browser at `http://localhost:8000`.

---

### How to Make the URL Public (So Clients Can Share It)
Inside GitHub Codespaces terminal:
```bash
gh codespace ports visibility 8000:public -c "$CODESPACE_NAME"
```
Or right-click Port **8000** in the **Ports** tab and choose **Port Visibility ➔ Public**.

---

## 📦 Large File Upload & Download Configuration (Up to 2 GB)

The studio is pre-configured to process files up to **2 GB** out of the box:
- **Streaming Upload**: Videos are streamed directly to disk in 1 MB chunks, preventing memory overflow.
- **Real-Time Progress**: The UI shows live byte-level upload progress (`MB transferred / Total MB`).
- **High-Speed Drive Transfer**: Google Drive download and upload chunk sizes are set to 32 MB.
- **Zero Video Re-encoding Loss**: FFmpeg remuxes converted audio via `-c:v copy` in seconds.

To customize the limit, set the `MAX_UPLOAD_SIZE_GB` environment variable:
```bash
export MAX_UPLOAD_SIZE_GB=4.0   # Increase to 4 GB
./run.sh
```

---

## 🔑 Google Drive Credentials (`GDRIVE_CREDENTIALS`)

The application supports 3 flexible methods to supply your Google Drive credentials:

### Method 1: GitHub / Codespaces Secret (Recommended)
1. In your GitHub repository, go to **Settings** > **Secrets and variables** > **Codespaces** (or **Actions**).
2. Click **New repository secret**.
3. Name: `GDRIVE_CREDENTIALS`
4. Secret: Paste the full JSON content of your Google Service Account key file.
5. If the Codespace was created before adding the secret, you can reload or export it in your terminal:
   ```bash
   export GDRIVE_CREDENTIALS='{"type": "service_account", ...}'
   ```

### Method 2: Local File in Workspace
Place your Google Service Account JSON file in the project root as:
```
credentials.json
```
*(This file is gitignored to keep your credentials private.)*

### Method 3: Direct Web UI Upload / Paste
1. Open the web interface.
2. Click the ⚙️ **Settings** icon in the top right.
3. Upload your `credentials.json` or paste the JSON text directly into the modal and click **Save & Connect**.

---

## 📌 Important: Sharing Google Drive Folders with Service Account

When using a Google Cloud Service Account:
1. Open the Web UI — the green status pill at the top shows your service account email (e.g., `my-service-account@project.iam.gserviceaccount.com`).
2. In your Google Drive (in your browser):
   - Right-click the folder containing your videos (or create a new folder).
   - Click **Share** > Add the service account email > Set permission to **Editor** > Click **Send**.
3. In the Web UI, click the **Refresh** button in the Drive Explorer. Your folders and videos will immediately appear!

---

## 🛠️ Architecture & Pipeline

```
[Google Drive Video]
        │
        ▼ (Download via Drive v3 API)
[FFmpeg Audio Extraction] (16kHz PCM WAV)
        │
        ▼
[Speech Recognition (STT)]
        │
        ▼
[Language Translation] (Indian Languages & Professional English)
        │
        ▼
[Neural Speech Synthesis (TTS)] (Edge Neural TTS / gTTS fallback)
        │
        ▼
[Tempo & Duration Matching] (FFmpeg atempo filter sync)
        │
        ▼
[Remuxing with Original Video] (FFmpeg stream copy - zero video loss)
        │
        ▼
[Direct Google Drive Upload] (Save to `<Language>` folder)
        │
        ▼
[Interactive Side-by-Side Video Preview & Drive Links]
```

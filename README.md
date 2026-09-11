# Google Drive to Voice Converter & Video Dubbing Studio 🎙️🎬

An automated AI-powered video dubbing and translation studio integrated with **Google Drive**. 
It extracts audio from video files stored in Google Drive (or local upload), transcribes the speech, translates it into **Indian languages** or **Professional English**, generates expressive neural voiceovers with natural prosody, synchronizes the voice duration to match the original video speed, and uploads the dubbed video **directly back to Google Drive inside a language-specific folder** (e.g. `Drive / Hindi/video_Hindi.mp4`).

---

## 🌟 Key Features

- **Direct Google Drive Integration**:
  - Connects using `GDRIVE_CREDENTIALS` (GitHub Secret, Codespaces environment variable, or `credentials.json`).
  - Interactive Drive Explorer: browse folders, preview video files, and search.
  - Automatic language folder creation on Google Drive (e.g., `Hindi/`, `Telugu/`, `Tamil/`, `Professional_English_Indian/`).
  - Chunked resumable upload directly back to Google Drive with direct web links to view the file and folder.
- **Indian Languages & Professional English Support**:
  - **Indian Languages**: Hindi (हिन्दी), Telugu (తెలుగు), Tamil (தமிழ்), Kannada (ಕನ್ನಡ), Malayalam (മലയാളം), Bengali (বাংলা), Marathi (मराठी), Gujarati (ગુજરાતી), Punjabi (ਪੰਜਾਬੀ), Urdu (اردو).
  - **Professional English**: Indian Accent (Neerja / Prabhat), US Accent (Jenny / Guy / Aria / Christopher), British UK Accent (Sonia / Ryan).
- **Voice-to-Video Synchronization**:
  - **Tempo Alignment**: Automatically matches speech speed to video duration using FFmpeg `atempo` filters so dubbing syncs with scene timing.
  - **Smart Audio Ducking**: Option to retain original background music and ambient sound at a subtle volume while layering the clear converted voice over top.
- **Real-Time Interactive UI**:
  - Live progress tracking via Server-Sent Events (SSE) with step-by-step pipeline indicators.
  - Live side-by-side video preview players (Original Video vs Converted Video).
  - Download converted MP4 locally or open directly in Google Drive.

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

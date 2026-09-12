// State management
let currentFolderId = null;
let currentFolderPath = [{ id: null, name: "Root Drive" }];
let selectedVideo = null; // { type: 'drive'|'local', id, name, size, parentId, fileObj }
let languagesData = [];
let activeJobId = null;
let eventSource = null;
let maxUploadSizeBytes = 2 * 1024 * 1024 * 1024; // 2 GB default

// Voice Cloning state
let currentVoiceMode = 'preset'; // 'preset' or 'clone'
let currentCloneSource = 'upload'; // 'upload', 'original_video', 'record'
let currentCloneEngine = 'acoustic'; // 'acoustic' or 'elevenlabs'
let cloneFileObj = null; // File or Blob for reference voice
let mediaRecorder = null;
let recordedAudioChunks = [];
let recordTimerInterval = null;
let recordSecondsLeft = 15;

document.addEventListener("DOMContentLoaded", () => {
    loadConfig();
    checkDriveStatus();
    loadLanguages();
    onFolderModeChange();
    loadApiKeyLocal();
});

async function loadConfig() {
    try {
        const resp = await fetch("/api/config");
        if (resp.ok) {
            const data = await resp.json();
            if (data.max_upload_size_bytes) {
                maxUploadSizeBytes = data.max_upload_size_bytes;
            }
        }
    } catch (_) {}
}

// 1. Google Drive Status & Connection
async function checkDriveStatus() {
    const container = document.getElementById("drive-status-container");
    const notice = document.getElementById("service-account-notice");
    const saEmail = document.getElementById("sa-email-display");

    try {
        const resp = await fetch("/api/status");
        const data = await resp.json();

        if (data.connected) {
            container.className = "flex items-center px-3 py-1.5 rounded-full text-xs font-medium border border-emerald-500/40 bg-emerald-950/40 text-emerald-300";
            container.innerHTML = `
                <span class="w-2 h-2 rounded-full bg-emerald-400 mr-2"></span>
                <span class="truncate max-w-xs font-mono">${data.email || 'Drive Connected'}</span>
            `;

            if (data.type === "service_account" && data.email) {
                notice.classList.remove("hidden");
                saEmail.textContent = data.email;
            } else {
                notice.classList.add("hidden");
            }

            // Load Drive root files
            loadDriveFiles(null);
        } else {
            container.className = "flex items-center px-3 py-1.5 rounded-full text-xs font-medium border border-amber-500/40 bg-amber-950/40 text-amber-300 cursor-pointer";
            container.innerHTML = `
                <span class="w-2 h-2 rounded-full bg-amber-400 mr-2"></span>
                <span>Drive Optional (Click to Setup)</span>
            `;
            container.onclick = openCredentialsModal;

            document.getElementById("drive-files-container").innerHTML = `
                <div class="p-8 text-center space-y-3">
                    <div class="w-10 h-10 rounded-full bg-slate-800 text-indigo-400 mx-auto flex items-center justify-center">
                        <i data-lucide="cloud-off" class="w-5 h-5"></i>
                    </div>
                    <p class="text-xs font-medium text-slate-200">Google Drive is optional and not connected</p>
                    <p class="text-[11px] text-slate-400 max-w-sm mx-auto">You can use <strong>Direct Video Dubbing & Download</strong> without Google Drive by uploading your video directly!</p>
                    <div class="flex items-center justify-center gap-2 pt-2">
                        <button onclick="switchSourceTab('upload')" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium rounded-xl shadow transition flex items-center space-x-1.5">
                            <i data-lucide="upload" class="w-3.5 h-3.5"></i>
                            <span>Use Local Video Upload</span>
                        </button>
                        <button onclick="openCredentialsModal()" class="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium rounded-xl border border-slate-700 transition">
                            Setup Drive
                        </button>
                    </div>
                </div>
            `;
            // If Drive is not connected, default to local upload tab
            switchSourceTab('upload');
            lucide.createIcons();
        }
    } catch (err) {
        console.error("Failed to check status:", err);
    }
}

// 2. Load Languages & Voices
async function loadLanguages() {
    try {
        const resp = await fetch("/api/languages");
        const data = await resp.json();
        languagesData = data.languages || [];

        const select = document.getElementById("language-select");
        select.innerHTML = "";

        // Groups: Indian Languages and Professional English
        const englishGroup = document.createElement("optgroup");
        englishGroup.label = "Professional English";

        const indianGroup = document.createElement("optgroup");
        indianGroup.label = "Indian Languages";

        languagesData.forEach(lang => {
            const opt = document.createElement("option");
            opt.value = lang.code;
            opt.textContent = `${lang.name} (${lang.native_name})`;
            if (lang.category === "English") {
                englishGroup.appendChild(opt);
            } else {
                indianGroup.appendChild(opt);
            }
        });

        select.appendChild(indianGroup);
        select.appendChild(englishGroup);

        // Select Hindi by default or first available
        select.value = "hi";
        onLanguageChange();
    } catch (err) {
        console.error("Failed to load languages:", err);
    }
}

function onLanguageChange() {
    const langCode = document.getElementById("language-select").value;
    const lang = languagesData.find(l => l.code === langCode);
    const voiceSelect = document.getElementById("voice-select");
    voiceSelect.innerHTML = "";

    if (lang && lang.voices) {
        lang.voices.forEach(voice => {
            const opt = document.createElement("option");
            opt.value = voice.id;
            opt.textContent = `${voice.name} • ${voice.gender}`;
            if (voice.id === lang.default_voice) {
                opt.selected = true;
            }
            voiceSelect.appendChild(opt);
        });
    }
}

// 3. Drive File Explorer
async function loadDriveFiles(folderId = null, searchQuery = "") {
    const container = document.getElementById("drive-files-container");
    container.innerHTML = `
        <div class="p-8 text-center text-slate-500 text-xs">
            <i data-lucide="loader" class="w-5 h-5 animate-spin mx-auto mb-2 text-indigo-400"></i>
            Loading files from Google Drive...
        </div>
    `;
    lucide.createIcons();

    try {
        let url = `/api/drive/files`;
        const params = new URLSearchParams();
        if (folderId) params.append("folder_id", folderId);
        if (searchQuery) params.append("q", searchQuery);
        if (params.toString()) url += `?${params.toString()}`;

        const resp = await fetch(url);
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || "Failed to load files");
        }
        const data = await resp.json();

        currentFolderId = data.current_folder_id;
        renderBreadcrumbs(data.current_folder_name, folderId);
        renderDriveList(data.folders, data.videos);
    } catch (err) {
        container.innerHTML = `
            <div class="p-6 text-center text-xs text-red-400">
                <i data-lucide="alert-circle" class="w-5 h-5 mx-auto mb-2"></i>
                <p>Could not load files: ${err.message}</p>
                <p class="text-slate-500 text-[11px] mt-1">Make sure you have shared your Google Drive folders with the Service Account email.</p>
            </div>
        `;
        lucide.createIcons();
    }
}

function renderBreadcrumbs(currentName, folderId) {
    const breadcrumbs = document.getElementById("drive-breadcrumbs");
    breadcrumbs.innerHTML = `
        <button onclick="navigateToFolder(null, 'Root Drive')" class="hover:text-indigo-300 flex items-center font-medium">
            <i data-lucide="hard-drive" class="w-3.5 h-3.5 mr-1"></i> Root Drive
        </button>
    `;
    if (folderId) {
        breadcrumbs.innerHTML += `
            <span class="text-slate-600">/</span>
            <span class="text-slate-200 font-medium truncate max-w-xs">${currentName || 'Folder'}</span>
        `;
    }
    lucide.createIcons();
}

function navigateToFolder(folderId, name = "") {
    loadDriveFiles(folderId);
}

function searchDriveFiles() {
    const q = document.getElementById("drive-search-input").value;
    loadDriveFiles(currentFolderId, q);
}

function refreshDriveFiles() {
    document.getElementById("drive-search-input").value = "";
    loadDriveFiles(currentFolderId);
}

function formatBytes(bytes, decimals = 1) {
    if (!+bytes) return '0 B';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
}

function renderDriveList(folders, videos) {
    const container = document.getElementById("drive-files-container");
    container.innerHTML = "";

    if (folders.length === 0 && videos.length === 0) {
        container.innerHTML = `
            <div class="p-8 text-center text-slate-500 text-xs">
                <i data-lucide="folder-open" class="w-8 h-8 text-slate-600 mx-auto mb-2"></i>
                <p>No video files or folders found here.</p>
                <p class="text-slate-600 text-[11px] mt-1">Upload a video in Google Drive and share the folder with your service account email, or switch to "Local Upload" tab above.</p>
            </div>
        `;
        lucide.createIcons();
        return;
    }

    // Render Folders
    folders.forEach(folder => {
        const item = document.createElement("div");
        item.className = "flex items-center justify-between p-3 hover:bg-slate-900/80 transition cursor-pointer group";
        item.innerHTML = `
            <div class="flex items-center space-x-3 overflow-hidden">
                <div class="w-8 h-8 rounded-lg bg-amber-500/10 text-amber-400 flex items-center justify-center flex-shrink-0">
                    <i data-lucide="folder" class="w-4 h-4"></i>
                </div>
                <span class="text-xs font-medium text-slate-200 truncate group-hover:text-indigo-300 transition">${folder.name}</span>
            </div>
            <span class="text-[10px] text-slate-500">Folder</span>
        `;
        item.onclick = () => navigateToFolder(folder.id, folder.name);
        container.appendChild(item);
    });

    // Render Video Files
    currentVideos = videos;
    videos.forEach(video => {
        const item = document.createElement("div");
        const isSelected = selectedVideo && selectedVideo.id === video.id;
        item.className = `flex items-center justify-between p-3 hover:bg-slate-900/80 transition cursor-pointer group ${isSelected ? 'bg-indigo-950/40 border-l-2 border-indigo-500' : ''}`;
        
        item.innerHTML = `
            <div class="flex items-center space-x-3 overflow-hidden flex-1" onclick="selectDriveVideoById('${video.id}')">
                <div class="w-8 h-8 rounded-lg bg-indigo-500/10 text-indigo-400 flex items-center justify-center flex-shrink-0">
                    <i data-lucide="film" class="w-4 h-4"></i>
                </div>
                <div class="overflow-hidden">
                    <h5 class="text-xs font-medium text-slate-200 truncate group-hover:text-indigo-300 transition">${video.name}</h5>
                    <span class="text-[10px] text-slate-500">${formatBytes(video.size)}</span>
                </div>
            </div>
            <div class="flex items-center space-x-2 flex-shrink-0 ml-3">
                <a href="/api/drive/download/${video.id}" download="${video.name}" onclick="event.stopPropagation()" class="px-2.5 py-1.5 rounded-lg text-slate-300 bg-slate-800 hover:bg-slate-700 hover:text-white transition flex items-center space-x-1 text-xs border border-slate-700" title="Download video file directly without opening Google Drive">
                    <i data-lucide="download" class="w-3.5 h-3.5"></i>
                    <span class="hidden sm:inline text-[11px] font-medium">Download</span>
                </a>
                <button onclick="selectDriveVideoById('${video.id}'); event.stopPropagation();" class="px-3 py-1.5 rounded-lg text-xs font-medium transition ${isSelected ? 'bg-indigo-600 text-white shadow' : 'bg-slate-800 hover:bg-indigo-600 hover:text-white text-slate-300'}">
                    ${isSelected ? 'Selected' : 'Select'}
                </button>
            </div>
        `;
        container.appendChild(item);
    });

    lucide.createIcons();
}

function selectDriveVideoById(videoId) {
    const video = (currentVideos || []).find(v => v.id === videoId);
    if (video) {
        selectDriveVideo(video);
    }
}

function selectDriveVideo(video) {
    selectedVideo = {
        type: 'drive',
        id: video.id,
        name: video.name,
        size: video.size,
        parentId: currentFolderId,
        fileObj: null
    };

    updateSelectedVideoCard();
    // Re-render list to highlight
    const q = document.getElementById("drive-search-input").value;
    loadDriveFiles(currentFolderId, q);
}

function handleLocalFileSelect(input) {
    if (!input.files || input.files.length === 0) return;
    const file = input.files[0];

    if (file.size > maxUploadSizeBytes) {
        alert(`Selected file is too large (${formatBytes(file.size)}). Maximum supported file size is ${formatBytes(maxUploadSizeBytes)}.`);
        input.value = "";
        return;
    }

    selectedVideo = {
        type: 'local',
        id: null,
        name: file.name,
        size: file.size,
        parentId: null,
        fileObj: file
    };
    updateSelectedVideoCard();
}

function updateSelectedVideoCard() {
    const card = document.getElementById("selected-video-card");
    const nameEl = document.getElementById("selected-video-name");
    const detailsEl = document.getElementById("selected-video-details");
    const convertBtn = document.getElementById("start-convert-btn");

    if (selectedVideo) {
        card.classList.remove("hidden");
        nameEl.textContent = selectedVideo.name;
        const isArchive = selectedVideo.name.endsWith('.zip') || selectedVideo.name.endsWith('.7z');
        const typeLabel = selectedVideo.type === 'drive' ? 'Google Drive' : (isArchive ? 'Archive Package' : 'Local File');
        detailsEl.textContent = `${typeLabel} • ${formatBytes(selectedVideo.size)}`;
        convertBtn.disabled = false;
    } else {
        card.classList.add("hidden");
        convertBtn.disabled = true;
    }
}

function clearSelectedVideo() {
    selectedVideo = null;
    document.getElementById("local-video-input").value = "";
    updateSelectedVideoCard();
    loadDriveFiles(currentFolderId);
}

function onFolderModeChange() {
    const mode = document.querySelector('input[name="folder_mode"]:checked')?.value || 'direct_download';
    const btnText = document.getElementById("convert-btn-text");
    const btnIcon = document.getElementById("convert-btn-icon");
    const stepLabel = document.getElementById("step-upload-label");
    const stepIcon = document.getElementById("step-upload-icon");

    const directContainer = document.getElementById("mode-direct-container");
    const sourceContainer = document.getElementById("mode-source-container");
    const rootContainer = document.getElementById("mode-root-container");

    if (directContainer) {
        directContainer.className = mode === 'direct_download' 
            ? "flex items-start space-x-2.5 p-3 rounded-xl border border-indigo-500/60 bg-indigo-950/40 cursor-pointer transition"
            : "flex items-start space-x-2.5 p-3 rounded-xl border border-slate-800 bg-slate-950/40 cursor-pointer hover:border-indigo-500/50 transition";
    }
    if (sourceContainer) {
        sourceContainer.className = mode === 'same_as_source' 
            ? "flex items-start space-x-2.5 p-3 rounded-xl border border-indigo-500/60 bg-indigo-950/40 cursor-pointer transition"
            : "flex items-start space-x-2.5 p-3 rounded-xl border border-slate-800 bg-slate-950/40 cursor-pointer hover:border-indigo-500/50 transition";
    }
    if (rootContainer) {
        rootContainer.className = mode === 'root' 
            ? "flex items-start space-x-2.5 p-3 rounded-xl border border-indigo-500/60 bg-indigo-950/40 cursor-pointer transition"
            : "flex items-start space-x-2.5 p-3 rounded-xl border border-slate-800 bg-slate-950/40 cursor-pointer hover:border-indigo-500/50 transition";
    }

    if (mode === "direct_download") {
        if (btnText) btnText.textContent = "Convert Voice & Direct Download";
        if (btnIcon) btnIcon.setAttribute("data-lucide", "download");
        if (stepLabel) stepLabel.textContent = "4. Direct Download Ready";
        if (stepIcon) stepIcon.setAttribute("data-lucide", "download");
    } else {
        if (btnText) btnText.textContent = "Convert Voice & Save to Drive";
        if (btnIcon) btnIcon.setAttribute("data-lucide", "sparkles");
        if (stepLabel) stepLabel.textContent = "4. Save to Drive Folder";
        if (stepIcon) stepIcon.setAttribute("data-lucide", "cloud-upload");
    }
    lucide.createIcons();
}

function switchSourceTab(tab) {
    const driveTab = document.getElementById("drive-tab-content");
    const uploadTab = document.getElementById("upload-tab-content");
    const tabDriveBtn = document.getElementById("tab-drive-btn");
    const tabUploadBtn = document.getElementById("tab-upload-btn");

    if (tab === 'drive') {
        driveTab.classList.remove("hidden");
        uploadTab.classList.add("hidden");
        tabDriveBtn.className = "px-3 py-1.5 rounded-lg bg-indigo-600 text-white shadow transition flex items-center space-x-1.5";
        tabUploadBtn.className = "px-3 py-1.5 rounded-lg text-slate-400 hover:text-slate-200 transition flex items-center space-x-1.5";
    } else {
        driveTab.classList.add("hidden");
        uploadTab.classList.remove("hidden");
        tabUploadBtn.className = "px-3 py-1.5 rounded-lg bg-indigo-600 text-white shadow transition flex items-center space-x-1.5";
        tabDriveBtn.className = "px-3 py-1.5 rounded-lg text-slate-400 hover:text-slate-200 transition flex items-center space-x-1.5";

        // Auto-select direct download when on local upload tab
        const directRadio = document.getElementById("folder-mode-direct");
        if (directRadio) {
            directRadio.checked = true;
            onFolderModeChange();
        }
    }
}

// --- Voice Cloning Handlers ---
function switchVoiceMode(mode) {
    currentVoiceMode = mode;
    const presetBtn = document.getElementById("voice-mode-preset-btn");
    const cloneBtn = document.getElementById("voice-mode-clone-btn");
    const presetContainer = document.getElementById("voice-preset-container");
    const cloneContainer = document.getElementById("voice-clone-container");
    const convertBtnText = document.getElementById("convert-btn-text");

    if (mode === 'clone') {
        presetBtn.className = "px-3 py-1 rounded-lg text-slate-400 hover:text-slate-200 transition flex items-center space-x-1";
        cloneBtn.className = "px-3 py-1 rounded-lg bg-indigo-600 text-white shadow transition flex items-center space-x-1";
        presetContainer.classList.add("hidden");
        cloneContainer.classList.remove("hidden");
        if (convertBtnText) {
            convertBtnText.textContent = "Clone Voice & Direct Download";
        }
    } else {
        cloneBtn.className = "px-3 py-1 rounded-lg text-slate-400 hover:text-slate-200 transition flex items-center space-x-1";
        presetBtn.className = "px-3 py-1 rounded-lg bg-indigo-600 text-white shadow transition flex items-center space-x-1";
        presetContainer.classList.remove("hidden");
        cloneContainer.classList.add("hidden");
        if (convertBtnText) {
            convertBtnText.textContent = "Convert Voice & Direct Download";
        }
    }
    lucide.createIcons();
}

function switchCloneSource(src) {
    currentCloneSource = src;
    const uploadBtn = document.getElementById("clone-src-upload-btn");
    const videoBtn = document.getElementById("clone-src-video-btn");
    const recordBtn = document.getElementById("clone-src-record-btn");

    const uploadSection = document.getElementById("clone-upload-section");
    const videoSection = document.getElementById("clone-video-section");
    const recordSection = document.getElementById("clone-record-section");

    const inactiveClass = "p-2 rounded-lg text-xs font-medium bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-200 flex flex-col items-center justify-center text-center transition";
    const activeClass = "p-2 rounded-lg text-xs font-medium bg-indigo-600/30 border border-indigo-500 text-white flex flex-col items-center justify-center text-center transition";

    uploadBtn.className = src === 'upload' ? activeClass : inactiveClass;
    videoBtn.className = src === 'original_video' ? activeClass : inactiveClass;
    recordBtn.className = src === 'record' ? activeClass : inactiveClass;

    uploadSection.classList.toggle("hidden", src !== 'upload');
    videoSection.classList.toggle("hidden", src !== 'original_video');
    recordSection.classList.toggle("hidden", src !== 'record');

    lucide.createIcons();
}

function onCloneFileSelected(event) {
    const file = event.target.files[0];
    if (!file) return;
    cloneFileObj = file;

    const prompt = document.getElementById("clone-upload-prompt");
    if (prompt) prompt.textContent = `Selected: ${file.name} (${formatBytes(file.size)})`;

    mountAudioPreview(file, file.name);
    analyzeAudioSample(file);
}

function mountAudioPreview(blobOrFile, name) {
    const previewBox = document.getElementById("clone-preview-box");
    const player = document.getElementById("clone-audio-player");
    const nameLabel = document.getElementById("clone-sample-name");
    const badge = document.getElementById("clone-sample-badge");

    const url = URL.createObjectURL(blobOrFile);
    player.src = url;
    nameLabel.textContent = name;
    badge.textContent = "Analyzing...";
    badge.className = "px-2 py-0.5 rounded text-[10px] bg-amber-500/20 text-amber-300 font-mono";
    previewBox.classList.remove("hidden");
}

async function analyzeAudioSample(file) {
    const formData = new FormData();
    formData.append("sample_file", file);

    const statF0 = document.getElementById("stat-f0");
    const statGender = document.getElementById("stat-gender");
    const statDuration = document.getElementById("stat-duration");
    const badge = document.getElementById("clone-sample-badge");

    try {
        const resp = await fetch("/api/clone/analyze", {
            method: "POST",
            body: formData
        });
        if (resp.ok) {
            const data = await resp.json();
            if (data.success) {
                statF0.textContent = `${data.f0} Hz`;
                statGender.textContent = data.gender.charAt(0).toUpperCase() + data.gender.slice(1);
                statDuration.textContent = `${data.duration}s`;
                badge.textContent = "✓ Voice Ready";
                badge.className = "px-2 py-0.5 rounded text-[10px] bg-emerald-500/20 text-emerald-300 font-mono";
                return;
            }
        }
    } catch (_) {}

    badge.textContent = "Ready";
    badge.className = "px-2 py-0.5 rounded text-[10px] bg-indigo-500/20 text-indigo-300 font-mono";
}

function onCloneEngineChange() {
    const select = document.getElementById("clone-engine-select");
    const keyContainer = document.getElementById("elevenlabs-key-container");
    currentCloneEngine = select.value;
    keyContainer.classList.toggle("hidden", currentCloneEngine !== "elevenlabs");
}

function saveApiKeyLocal() {
    const input = document.getElementById("elevenlabs-api-key-input");
    if (input) {
        localStorage.setItem("elevenlabs_api_key", input.value.trim());
    }
}

function loadApiKeyLocal() {
    const saved = localStorage.getItem("elevenlabs_api_key");
    const input = document.getElementById("elevenlabs-api-key-input");
    if (saved && input) {
        input.value = saved;
    }
}

async function toggleMicRecording() {
    const btn = document.getElementById("record-mic-btn");
    const btnText = document.getElementById("record-mic-text");
    const status = document.getElementById("record-status");

    if (mediaRecorder && mediaRecorder.state === "recording") {
        mediaRecorder.stop();
        clearInterval(recordTimerInterval);
        return;
    }

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        recordedAudioChunks = [];
        mediaRecorder = new MediaRecorder(stream);

        mediaRecorder.ondataavailable = (e) => {
            if (e.data && e.data.size > 0) {
                recordedAudioChunks.push(e.data);
            }
        };

        mediaRecorder.onstop = () => {
            stream.getTracks().forEach(t => t.stop());
            const mime = mediaRecorder.mimeType || "audio/webm";
            const ext = mime.includes("ogg") ? "ogg" : (mime.includes("wav") ? "wav" : "webm");
            const audioBlob = new Blob(recordedAudioChunks, { type: mime });
            const recordedFile = new File([audioBlob], `recorded_voice_${Date.now()}.${ext}`, { type: mime });
            cloneFileObj = recordedFile;

            btn.className = "px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold flex items-center space-x-1.5 shadow transition";
            btnText.textContent = "Re-record Voice";
            status.textContent = `Recorded voice sample successfully!`;

            mountAudioPreview(recordedFile, "live_recording.wav");
            analyzeAudioSample(recordedFile);
        };

        mediaRecorder.start();
        recordSecondsLeft = 15;
        btn.className = "px-4 py-2 rounded-xl bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold flex items-center space-x-1.5 shadow transition animate-pulse";
        btnText.textContent = `Recording (${recordSecondsLeft}s left) - Click to Stop`;
        status.textContent = "Speak clearly into your microphone...";

        recordTimerInterval = setInterval(() => {
            recordSecondsLeft--;
            if (recordSecondsLeft <= 0) {
                clearInterval(recordTimerInterval);
                if (mediaRecorder && mediaRecorder.state === "recording") {
                    mediaRecorder.stop();
                }
            } else {
                btnText.textContent = `Recording (${recordSecondsLeft}s left) - Click to Stop`;
            }
        }, 1000);

    } catch (err) {
        alert("Microphone access error: " + err.message);
    }
}

// 4. Start Conversion
async function startConversion() {
    if (!selectedVideo) return;

    const convertBtn = document.getElementById("start-convert-btn");
    convertBtn.disabled = true;

    const progressCard = document.getElementById("conversion-progress-card");
    const completionCard = document.getElementById("completion-card");
    progressCard.classList.remove("hidden");
    completionCard.classList.add("hidden");

    // Scroll to progress
    progressCard.scrollIntoView({ behavior: "smooth" });

    // Validate Voice Cloning parameters
    if (currentVoiceMode === "clone") {
        if (currentCloneSource === "upload" && !cloneFileObj) {
            alert("Please upload an audio sample or choose 'From Video' to clone from the input video.");
            convertBtn.disabled = false;
            progressCard.classList.add("hidden");
            return;
        }
        if (currentCloneSource === "record" && !cloneFileObj) {
            alert("Please record your voice sample first or select 'From Video'.");
            convertBtn.disabled = false;
            progressCard.classList.add("hidden");
            return;
        }
    }

    // Gather parameters
    const sourceLang = document.getElementById("source-language-select")?.value || "auto";
    const targetLang = document.getElementById("language-select").value;
    const voiceId = document.getElementById("voice-select").value;
    const matchDuration = document.getElementById("match-duration-toggle").checked;
    const ducking = document.getElementById("ducking-toggle").checked;
    const folderMode = document.querySelector('input[name="folder_mode"]:checked').value;

    const formData = new FormData();
    formData.append("source_lang", sourceLang);
    formData.append("target_lang", targetLang);
    formData.append("voice_id", voiceId);
    formData.append("match_duration", matchDuration);
    formData.append("duck_original_audio", ducking);
    formData.append("dest_folder_mode", folderMode);

    // Voice Cloning form fields
    formData.append("voice_mode", currentVoiceMode);
    formData.append("clone_source", currentCloneSource);
    formData.append("clone_engine", document.getElementById("clone-engine-select")?.value || "acoustic");
    const elevenKey = document.getElementById("elevenlabs-api-key-input")?.value?.trim();
    if (elevenKey) {
        formData.append("elevenlabs_api_key", elevenKey);
    }
    if (currentVoiceMode === "clone" && cloneFileObj) {
        formData.append("clone_file", cloneFileObj, cloneFileObj.name || "reference_voice.wav");
    }

    if (selectedVideo.type === 'drive') {
        formData.append("drive_file_id", selectedVideo.id);
        formData.append("file_name", selectedVideo.name);
        if (selectedVideo.parentId) {
            formData.append("parent_folder_id", selectedVideo.parentId);
        }
    } else if (selectedVideo.type === 'local' && selectedVideo.fileObj) {
        formData.append("upload_file", selectedVideo.fileObj);
        formData.append("file_name", selectedVideo.name);
    }

    if (selectedVideo.type === 'local' && selectedVideo.fileObj) {
        updateProgressUI(1, "Starting video upload to server...");
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/convert", true);

        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
                const uploadPct = Math.round((e.loaded / e.total) * 100);
                const loadedStr = formatBytes(e.loaded);
                const totalStr = formatBytes(e.total);
                const mappedProgress = Math.max(1, Math.min(20, Math.round(uploadPct * 0.20)));
                updateProgressUI(mappedProgress, `Uploading video to server: ${uploadPct}% (${loadedStr} / ${totalStr})...`);
            }
        };

        xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    const data = JSON.parse(xhr.responseText);
                    activeJobId = data.job_id;
                    listenToJobProgress(activeJobId);
                } catch (parseErr) {
                    alert("Unexpected server response format: " + parseErr.message);
                    convertBtn.disabled = false;
                    progressCard.classList.add("hidden");
                }
            } else {
                let errMsg = "Upload failed";
                try {
                    const err = JSON.parse(xhr.responseText);
                    errMsg = err.detail || errMsg;
                } catch (_) {}
                alert("Error starting conversion: " + errMsg);
                convertBtn.disabled = false;
                progressCard.classList.add("hidden");
            }
        };

        xhr.onerror = () => {
            alert("Network error occurred during video upload. Please check your connection.");
            convertBtn.disabled = false;
            progressCard.classList.add("hidden");
        };

        xhr.send(formData);
        return;
    }

    try {
        updateProgressUI(2, "Initializing conversion pipeline...");
        const resp = await fetch("/api/convert", {
            method: "POST",
            body: formData
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || "Failed to initiate conversion");
        }

        const data = await resp.json();
        activeJobId = data.job_id;

        // Listen for progress via SSE
        listenToJobProgress(activeJobId);

    } catch (err) {
        alert("Error starting conversion: " + err.message);
        convertBtn.disabled = false;
        progressCard.classList.add("hidden");
    }
}

// 5. SSE Progress Listener
function listenToJobProgress(jobId) {
    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource(`/api/jobs/${jobId}/stream`);

    eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleJobUpdate(data);
        } catch (e) {
            console.error("SSE parse error:", e);
        }
    };

    eventSource.onerror = () => {
        console.warn("SSE connection interrupted, falling back to polling...");
        eventSource.close();
        fallbackPollJob(jobId);
    };
}

async function fallbackPollJob(jobId) {
    const interval = setInterval(async () => {
        try {
            const resp = await fetch(`/api/jobs/${jobId}`);
            if (resp.ok) {
                const data = await resp.json();
                handleJobUpdate(data);
                if (data.status === "completed" || data.status === "failed") {
                    clearInterval(interval);
                }
            }
        } catch (e) {
            console.error("Polling error:", e);
        }
    }, 2000);
}

function handleJobUpdate(data) {
    const pct = data.progress || 0;
    const msg = data.message || "Processing...";

    updateProgressUI(pct, msg);

    // Update transcripts if available
    if (data.original_transcript || data.translated_transcript) {
        document.getElementById("live-transcripts-box").classList.remove("hidden");
        document.getElementById("transcript-orig").textContent = data.original_transcript || "...";
        document.getElementById("transcript-translated").textContent = data.translated_transcript || "...";
    }

    if (data.status === "completed") {
        if (eventSource) eventSource.close();
        showCompletion(data);
    } else if (data.status === "failed") {
        if (eventSource) eventSource.close();
        alert("Conversion failed: " + (data.error || "Unknown error"));
        document.getElementById("start-convert-btn").disabled = false;
    }
}

function updateProgressUI(pct, msg) {
    document.getElementById("progress-pct-badge").textContent = `${pct}%`;
    document.getElementById("progress-status-text").textContent = msg;
    document.getElementById("progress-bar-fill").style.width = `${pct}%`;

    // Highlight active pipeline steps
    const stepDownload = document.getElementById("step-download");
    const stepStt = document.getElementById("step-stt");
    const stepTts = document.getElementById("step-tts");
    const stepUpload = document.getElementById("step-upload");

    stepDownload.className = pct >= 25 ? "step-complete p-2.5 rounded-lg border text-xs flex items-center space-x-2" : (pct >= 5 ? "step-active p-2.5 rounded-lg border text-xs flex items-center space-x-2" : "p-2.5 rounded-lg bg-slate-950/60 border border-slate-800 text-slate-400 flex items-center space-x-2");
    stepStt.className = pct >= 60 ? "step-complete p-2.5 rounded-lg border text-xs flex items-center space-x-2" : (pct >= 28 ? "step-active p-2.5 rounded-lg border text-xs flex items-center space-x-2" : "p-2.5 rounded-lg bg-slate-950/60 border border-slate-800 text-slate-400 flex items-center space-x-2");
    stepTts.className = pct >= 80 ? "step-complete p-2.5 rounded-lg border text-xs flex items-center space-x-2" : (pct >= 60 ? "step-active p-2.5 rounded-lg border text-xs flex items-center space-x-2" : "p-2.5 rounded-lg bg-slate-950/60 border border-slate-800 text-slate-400 flex items-center space-x-2");
    stepUpload.className = pct >= 100 ? "step-complete p-2.5 rounded-lg border text-xs flex items-center space-x-2" : (pct >= 82 ? "step-active p-2.5 rounded-lg border text-xs flex items-center space-x-2" : "p-2.5 rounded-lg bg-slate-950/60 border border-slate-800 text-slate-400 flex items-center space-x-2");

    // Dynamic label for Step 3 if cloning
    if (currentVoiceMode === "clone") {
        const ttsLabel = stepTts.querySelector("span");
        if (ttsLabel) {
            ttsLabel.textContent = pct >= 80 ? "3. Voice Cloned & Remuxed" : "3. Clone Voice & Remux";
        }
    }
}

function showCompletion(data) {
    document.getElementById("start-convert-btn").disabled = false;
    const completionCard = document.getElementById("completion-card");
    completionCard.classList.remove("hidden");
    completionCard.scrollIntoView({ behavior: "smooth" });

    const mode = document.querySelector('input[name="folder_mode"]:checked')?.value;
    const isDirect = mode === "direct_download" || data.dest_folder_mode === "direct_download" || !data.drive_file_id;
    const isClone = data.voice_mode === "clone" || currentVoiceMode === "clone";

    // Drive Warning / Storage Quota Notice
    const warningEl = document.getElementById("drive-warning-alert");
    const warningText = document.getElementById("drive-warning-text");
    const titleEl = document.getElementById("completion-title");
    const subtitleEl = document.getElementById("completion-subtitle");

    if (data.drive_warning && !isDirect) {
        warningEl.classList.remove("hidden");
        warningText.textContent = data.drive_warning;
        titleEl.textContent = isClone ? "🎙️ Voice Cloning Complete! (Ready to Download)" : "Voice Dubbing Complete! (Ready to Download)";
        subtitleEl.textContent = "Your video has been converted with synchronized voice. See details below.";
    } else {
        warningEl.classList.add("hidden");
        if (isClone) {
            titleEl.textContent = isDirect ? "🎉 Voice Cloning & Dubbing Complete!" : "🎙️ Voice Cloning & Drive Export Complete!";
            subtitleEl.textContent = isDirect ? "Your video has been dubbed with the cloned voice and is ready for direct download." : "Your video has been dubbed with the cloned voice and uploaded to Google Drive.";
        } else {
            if (isDirect) {
                titleEl.textContent = "🎉 Voice Dubbing Complete!";
                subtitleEl.textContent = "Your converted video with synchronized voice is ready for direct download.";
            } else {
                titleEl.textContent = "Voice Dubbing & Drive Export Complete!";
                subtitleEl.textContent = "Your video has been converted and uploaded directly to your Google Drive folder.";
            }
        }
    }

    // Voice Clone Badge
    const cloneBadge = document.getElementById("completion-clone-badge");
    const cloneStats = document.getElementById("completion-clone-stats");
    if (cloneBadge) {
        if (isClone && data.clone_profile) {
            cloneBadge.classList.remove("hidden");
            if (cloneStats) {
                cloneStats.textContent = `Pitch: ${data.clone_profile.f0}Hz • Voice Gender: ${data.clone_profile.gender.toUpperCase()} • Shift Factor: ${data.clone_profile.pitch_scale}x`;
            }
        } else if (isClone) {
            cloneBadge.classList.remove("hidden");
            if (cloneStats) cloneStats.textContent = "Acoustic Tone & Formant Matched";
        } else {
            cloneBadge.classList.add("hidden");
        }
    }

    // Buttons
    const btnFolder = document.getElementById("btn-open-drive-folder");
    const btnFile = document.getElementById("btn-open-drive-file");
    const btnDownload = document.getElementById("btn-download-local");
    const btnZip = document.getElementById("btn-download-zip");
    const btn7z = document.getElementById("btn-download-7z");
    const folderLabel = document.getElementById("label-open-folder");

    const jobId = data.job_id || activeJobId;

    if (data.drive_folder_link && !isDirect) {
        btnFolder.href = data.drive_folder_link;
        btnFolder.classList.remove("hidden");
        folderLabel.textContent = `Open "${data.drive_folder_name}" in Drive`;
    } else {
        btnFolder.classList.add("hidden");
    }

    if (data.drive_file_link && !isDirect) {
        btnFile.href = data.drive_file_link;
        btnFile.classList.remove("hidden");
    } else {
        btnFile.classList.add("hidden");
    }

    if (btnDownload) {
        btnDownload.href = `/api/download/${jobId}`;
        btnDownload.setAttribute("download", data.filename || "converted_video.mp4");
    }

    if (btnZip) {
        btnZip.href = `/api/download/${jobId}/zip`;
    }

    if (btn7z) {
        btn7z.href = `/api/download/${jobId}/7z`;
    }

    // Mount players
    const origPlayer = document.getElementById("player-original");
    const convPlayer = document.getElementById("player-converted");
    origPlayer.src = `/api/preview/${jobId}/original`;
    convPlayer.src = `/api/preview/${jobId}/converted`;

    const langName = document.getElementById("language-select").selectedOptions[0]?.text || "Selected Language";
    document.getElementById("label-converted-preview").textContent = `Converted Video (${langName})`;
}

// 6. Credentials Modal Management
function openCredentialsModal() {
    document.getElementById("credentials-modal").classList.remove("hidden");
}

function closeCredentialsModal() {
    document.getElementById("credentials-modal").classList.add("hidden");
}

async function submitCredentials() {
    const fileInput = document.getElementById("modal-file-input");
    const jsonText = document.getElementById("modal-json-text").value;
    const feedback = document.getElementById("modal-feedback");

    feedback.className = "text-xs p-3 rounded-lg bg-indigo-950/60 border border-indigo-500/40 text-indigo-200 block";
    feedback.textContent = "Validating and saving credentials...";

    const formData = new FormData();
    if (fileInput.files && fileInput.files.length > 0) {
        formData.append("credentials_file", fileInput.files[0]);
    } else if (jsonText && jsonText.trim()) {
        formData.append("credentials_json", jsonText.trim());
    } else {
        feedback.className = "text-xs p-3 rounded-lg bg-red-950/60 border border-red-500/40 text-red-200 block";
        feedback.textContent = "Please select a JSON file or paste JSON content.";
        return;
    }

    try {
        const resp = await fetch("/api/credentials", {
            method: "POST",
            body: formData
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || "Failed to save credentials");
        }

        const data = await resp.json();
        feedback.className = "text-xs p-3 rounded-lg bg-emerald-950/60 border border-emerald-500/40 text-emerald-200 block";
        feedback.textContent = "Google Drive connected successfully!";

        setTimeout(() => {
            closeCredentialsModal();
            checkDriveStatus();
        }, 1200);

    } catch (err) {
        feedback.className = "text-xs p-3 rounded-lg bg-red-950/60 border border-red-500/40 text-red-200 block";
        feedback.textContent = err.message;
    }
}

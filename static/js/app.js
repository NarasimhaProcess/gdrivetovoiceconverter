// State management
let currentFolderId = null;
let currentFolderPath = [{ id: null, name: "Root Drive" }];
let selectedVideo = null; // { type: 'drive'|'local', id, name, size, parentId, fileObj }
let languagesData = [];
let activeJobId = null;
let eventSource = null;

document.addEventListener("DOMContentLoaded", () => {
    checkDriveStatus();
    loadLanguages();
});

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
                <span>Drive Not Connected (Click to Setup)</span>
            `;
            container.onclick = openCredentialsModal;

            document.getElementById("drive-files-container").innerHTML = `
                <div class="p-8 text-center space-y-3">
                    <div class="w-10 h-10 rounded-full bg-amber-950/60 text-amber-400 mx-auto flex items-center justify-center">
                        <i data-lucide="key" class="w-5 h-5"></i>
                    </div>
                    <p class="text-xs text-slate-300">Google Drive credentials not detected.</p>
                    <button onclick="openCredentialsModal()" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium rounded-xl shadow transition">
                        Connect Google Drive (Upload / Paste Credentials)
                    </button>
                </div>
            `;
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
    videos.forEach(video => {
        const item = document.createElement("div");
        const isSelected = selectedVideo && selectedVideo.id === video.id;
        item.className = `flex items-center justify-between p-3 hover:bg-slate-900/80 transition cursor-pointer group ${isSelected ? 'bg-indigo-950/40 border-l-2 border-indigo-500' : ''}`;
        
        item.innerHTML = `
            <div class="flex items-center space-x-3 overflow-hidden">
                <div class="w-8 h-8 rounded-lg bg-indigo-500/10 text-indigo-400 flex items-center justify-center flex-shrink-0">
                    <i data-lucide="film" class="w-4 h-4"></i>
                </div>
                <div class="overflow-hidden">
                    <h5 class="text-xs font-medium text-slate-200 truncate group-hover:text-indigo-300 transition">${video.name}</h5>
                    <span class="text-[10px] text-slate-500">${formatBytes(video.size)}</span>
                </div>
            </div>
            <button class="px-3 py-1 rounded-lg text-xs font-medium transition ${isSelected ? 'bg-indigo-600 text-white' : 'bg-slate-800 hover:bg-indigo-600 hover:text-white text-slate-300'}">
                ${isSelected ? 'Selected' : 'Select'}
            </button>
        `;
        item.onclick = () => selectDriveVideo(video);
        container.appendChild(item);
    });

    lucide.createIcons();
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
        detailsEl.textContent = `${selectedVideo.type === 'drive' ? 'Google Drive' : 'Local File'} • ${formatBytes(selectedVideo.size)}`;
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

    // Gather parameters
    const targetLang = document.getElementById("language-select").value;
    const voiceId = document.getElementById("voice-select").value;
    const matchDuration = document.getElementById("match-duration-toggle").checked;
    const ducking = document.getElementById("ducking-toggle").checked;
    const folderMode = document.querySelector('input[name="folder_mode"]:checked').value;

    const formData = new FormData();
    formData.append("target_lang", targetLang);
    formData.append("voice_id", voiceId);
    formData.append("match_duration", matchDuration);
    formData.append("duck_original_audio", ducking);
    formData.append("dest_folder_mode", folderMode);

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
}

function showCompletion(data) {
    document.getElementById("start-convert-btn").disabled = false;
    const completionCard = document.getElementById("completion-card");
    completionCard.classList.remove("hidden");
    completionCard.scrollIntoView({ behavior: "smooth" });

    // Drive Warning / Storage Quota Notice
    const warningEl = document.getElementById("drive-warning-alert");
    const warningText = document.getElementById("drive-warning-text");
    const titleEl = document.getElementById("completion-title");
    const subtitleEl = document.getElementById("completion-subtitle");

    if (data.drive_warning) {
        warningEl.classList.remove("hidden");
        warningText.textContent = data.drive_warning;
        titleEl.textContent = "Voice Dubbing Complete! (Ready to Download)";
        subtitleEl.textContent = "Your video has been converted with synchronized voice. See details below.";
    } else {
        warningEl.classList.add("hidden");
        titleEl.textContent = "Voice Dubbing & Drive Export Complete!";
        subtitleEl.textContent = "Your video has been converted and uploaded directly to your Google Drive folder.";
    }

    // Buttons
    const btnFolder = document.getElementById("btn-open-drive-folder");
    const btnFile = document.getElementById("btn-open-drive-file");
    const btnDownload = document.getElementById("btn-download-local");
    const folderLabel = document.getElementById("label-open-folder");

    if (data.drive_folder_link) {
        btnFolder.href = data.drive_folder_link;
        btnFolder.classList.remove("hidden");
        folderLabel.textContent = `Open "${data.drive_folder_name}" in Drive`;
    } else {
        btnFolder.classList.add("hidden");
    }

    if (data.drive_file_link) {
        btnFile.href = data.drive_file_link;
        btnFile.classList.remove("hidden");
    } else {
        btnFile.classList.add("hidden");
    }

    btnDownload.href = `/api/download/${data.job_id}`;

    // Mount players
    const origPlayer = document.getElementById("player-original");
    const convPlayer = document.getElementById("player-converted");
    origPlayer.src = `/api/preview/${data.job_id}/original`;
    convPlayer.src = `/api/preview/${data.job_id}/converted`;

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

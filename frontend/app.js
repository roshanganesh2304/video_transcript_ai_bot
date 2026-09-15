let player = null;
let currentVideoId = "dQw4w9WgXcQ";
let activeSourceMode = "youtube"; // "youtube" or "local"
let currentActiveVideoId = null;
let lastUploadedSrtFilename = "sample_malayalam.srt";
let adminSourceMode = "local"; // "local" or "youtube"

// Initialize YouTube IFrame API
function onYouTubeIframeAPIReady() {
    player = new YT.Player('player', {
        height: '100%',
        width: '100%',
        videoId: currentVideoId,
        playerVars: {
            'playsinline': 1,
            'autoplay': 0,
            'controls': 1
        },
        events: {
            'onReady': onPlayerReady
        }
    });
}

function onPlayerReady(event) {
    if (activeSourceMode === "youtube") {
        const placeholder = document.getElementById('video-placeholder');
        if (placeholder) placeholder.style.display = 'none';
    }
}

function extractYouTubeId(url) {
    if (!url) return null;
    const regExp = /^.*(youtu.be\/|v\/|u\/\w\/|embed\/|watch\?v=|\&v=)([^#\&\?]*).*/;
    const match = url.match(regExp);
    return (match && match[2].length === 11) ? match[2] : null;
}

function loadYouTubeVideo(videoUrl) {
    if (!videoUrl) return;
    activeSourceMode = "youtube";

    const localPlayer = document.getElementById('local-player');
    if (localPlayer) {
        localPlayer.pause();
        localPlayer.style.display = 'none';
    }

    const ytContainer = document.getElementById('player');
    if (ytContainer) {
        ytContainer.style.display = 'block';
    }

    const videoId = extractYouTubeId(videoUrl) || "dQw4w9WgXcQ";
    currentVideoId = videoId;

    const placeholder = document.getElementById('video-placeholder');
    if (placeholder) placeholder.style.display = 'none';

    try {
        if (player && typeof player.loadVideoById === 'function') {
            player.loadVideoById(videoId);
            return;
        }
    } catch (e) {
        console.warn("YouTube API loadVideoById warning:", e);
    }

    if (ytContainer) {
        ytContainer.innerHTML = `<iframe id="yt-embed-iframe" src="https://www.youtube.com/embed/${videoId}?enablejsapi=1&autoplay=1" width="100%" height="100%" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>`;
    }
}

function loadLocalVideo(videoUrl) {
    if (!videoUrl) return;
    activeSourceMode = "local";

    const ytContainer = document.getElementById('player');
    if (ytContainer) ytContainer.style.display = 'none';

    const localPlayer = document.getElementById('local-player');
    if (localPlayer) {
        localPlayer.style.display = 'block';
        localPlayer.src = videoUrl;
        localPlayer.load();
        localPlayer.play().catch(() => { });
    }

    const placeholder = document.getElementById('video-placeholder');
    if (placeholder) placeholder.style.display = 'none';
}

// Global timestamp seek handler
window.onTimestampClick = function (seconds) {
    if (activeSourceMode === "local") {
        const localPlayer = document.getElementById('local-player');
        if (localPlayer) {
            localPlayer.currentTime = seconds;
            localPlayer.play().catch(() => { });
        }
    } else {
        if (player && typeof player.seekTo === 'function') {
            player.seekTo(seconds, true);
            player.playVideo();
        } else {
            const iframe = document.getElementById('yt-embed-iframe') || document.querySelector('#player iframe');
            if (iframe && iframe.contentWindow) {
                iframe.contentWindow.postMessage(JSON.stringify({
                    'event': 'command',
                    'func': 'seekTo',
                    'args': [seconds, true]
                }), '*');
                iframe.contentWindow.postMessage(JSON.stringify({
                    'event': 'command',
                    'func': 'playVideo',
                    'args': []
                }), '*');
            }
        }
    }
};

function parseTimeToSeconds(timeStr) {
    const parts = timeStr.split(':').map(Number);
    if (parts.length === 3) {
        return parts[0] * 3600 + parts[1] * 60 + parts[2];
    } else if (parts.length === 2) {
        return parts[0] * 60 + parts[1];
    }
    return 0;
}

function formatMarkdown(text) {
    if (!text) return '';
    let html = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/^\s*[-•]\s+(.*$)/gim, '<div class="ai-bullet-item"><span class="bullet-dot">•</span> <span>$1</span></div>');
    html = html.replace(/\n\n/g, '<div class="spacer"></div>');
    html = html.replace(/\n/g, '<br>');
    return html;
}

function renderTimestampPills(text) {
    let formatted = formatMarkdown(text);
    const regex = /\[(\d{2}:\d{2}(?::\d{2})?)\]/g;
    return formatted.replace(regex, (match, p1) => {
        const seconds = parseTimeToSeconds(p1);
        return `<span class="timestamp-pill" onclick="window.onTimestampClick(${seconds})">⏱️ ${p1}</span>`;
    });
}

function scrollToBottom(container) {
    if (!container) return;
    setTimeout(() => {
        try {
            container.scrollTo({
                top: container.scrollHeight,
                behavior: 'smooth'
            });
        } catch (e) {
            container.scrollTop = container.scrollHeight;
        }
    }, 30);
}

function appendUserMessage(text) {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;
    const div = document.createElement('div');
    div.className = 'message user-msg';
    div.innerHTML = `
        <div class="msg-avatar">👤</div>
        <div class="msg-body">${escapeHtml(text)}</div>
    `;
    chatMessages.appendChild(div);
    scrollToBottom(chatMessages);
}

function appendBotLoadingMessage() {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return null;
    const div = document.createElement('div');
    div.className = 'message bot-msg';
    div.innerHTML = `
        <div class="msg-avatar">🤖</div>
        <div class="msg-body">
            <div class="gemini-yt-loader">
                <div class="loader-spark-head">
                    <span class="spark-icon">✨</span>
                    <span class="loader-status-text">Thinking & searching transcript...</span>
                    <div class="pulse-dots">
                        <span class="dot dot-1"></span>
                        <span class="dot dot-2"></span>
                        <span class="dot dot-3"></span>
                    </div>
                </div>
                <div class="shimmer-container">
                    <div class="shimmer-line line-1"></div>
                    <div class="shimmer-line line-2"></div>
                    <div class="shimmer-line line-3"></div>
                </div>
            </div>
        </div>
    `;
    chatMessages.appendChild(div);
    scrollToBottom(chatMessages);
    return div;
}

function appendSystemMessage(htmlText) {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;
    const div = document.createElement('div');
    div.className = 'message system-msg';
    div.innerHTML = `
        <div class="msg-avatar">ℹ️</div>
        <div class="msg-body">${htmlText}</div>
    `;
    chatMessages.appendChild(div);
    scrollToBottom(chatMessages);
}

function escapeHtml(text) {
    if (!text) return '';
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

// Get video thumbnail URL based on video source
function getVideoThumbnail(video) {
    const ytId = extractYouTubeId(video.video_url);
    if (ytId) {
        return `https://img.youtube.com/vi/${ytId}/hqdefault.jpg`;
    }
    // Default gradient poster banner for local uploaded videos
    return null;
}

// Fetch Video List from PostgreSQL Database & Render UI Cards
async function loadVideoList() {
    try {
        const res = await fetch('/api/videos');
        const data = await res.json();
        const videos = data.videos || [];
        currentActiveVideoId = data.active_video_id;

        // Render Home Gallery Cards
        const listContainer = document.getElementById('video-list-container');
        const badgeCount = document.getElementById('video-count-badge');
        if (badgeCount) badgeCount.innerText = `${videos.length} Videos`;

        if (videos.length === 0) {
            listContainer.innerHTML = `
                <div class="empty-video-state">
                    <p>📂 No videos stored in database yet.</p>
                    <button type="button" class="btn-goto-admin" onclick="switchNavView('admin')">Go to Admin Panel to Add Videos</button>
                </div>
            `;
        } else {
            listContainer.innerHTML = videos.map(v => {
                const isLocal = (v.source_type === "local");
                const sourceBadge = isLocal ? `<span class="badge-source local">📁 Local</span>` : `<span class="badge-source yt">🌐 YouTube</span>`;
                const thumbUrl = getVideoThumbnail(v);

                const thumbHtml = thumbUrl ? `
                    <div class="card-thumb-wrapper">
                        <img src="${thumbUrl}" alt="${escapeHtml(v.video_name)}" class="card-thumb-img" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';"/>
                        <div class="card-thumb-fallback" style="display:none;">
                            <span class="fallback-icon">🎬</span>
                        </div>
                        <div class="thumb-play-overlay">
                            <div class="play-btn-circle">▶</div>
                        </div>
                    </div>
                ` : `
                    <div class="card-thumb-wrapper local-gradient">
                        <div class="local-thumb-content">
                            <span class="local-cam-icon">🎬</span>
                            <span class="local-filename">${escapeHtml(v.srt_filename || 'video')}</span>
                        </div>
                        <div class="thumb-play-overlay">
                            <div class="play-btn-circle">▶</div>
                        </div>
                    </div>
                `;

                return `
                    <div class="video-card-item" onclick="selectVideo(${v.id})">
                        ${thumbHtml}
                        <div class="card-details">
                            <div class="card-details-top">
                                ${sourceBadge}
                                <span class="chunk-badge">🧩 ${v.total_chunks || 0} Chunks</span>
                            </div>
                            <h3 class="card-video-title">${escapeHtml(v.video_name)}</h3>
                            <div class="card-footer">
                                <span class="srt-name">📄 ${escapeHtml(v.srt_filename || '')}</span>
                                <span class="btn-launch-player">Watch & Chat →</span>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        // Render Admin Panel Managed Table
        const adminListContainer = document.getElementById('admin-managed-list');
        if (adminListContainer) {
            if (videos.length === 0) {
                adminListContainer.innerHTML = `<div class="empty-video-state">No videos in registry. Use the form above to add a video.</div>`;
            } else {
                adminListContainer.innerHTML = `
                    <table class="admin-table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Video Title</th>
                                <th>Type</th>
                                <th>SRT Subtitle</th>
                                <th>Vector Chunks</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${videos.map(v => `
                                <tr>
                                    <td>#${v.id}</td>
                                    <td><strong>${escapeHtml(v.video_name)}</strong></td>
                                    <td><span class="badge-source ${v.source_type === 'local' ? 'local' : 'yt'}">${v.source_type}</span></td>
                                    <td>${escapeHtml(v.srt_filename || '')}</td>
                                    <td>${v.total_chunks || 0} chunks</td>
                                    <td>
                                        <div class="action-buttons-cell">
                                            <button type="button" class="btn-edit" onclick="editVideo(${v.id})">✏️ Edit</button>
                                            <button type="button" class="btn-delete" onclick="deleteVideo(${v.id})">🗑️ Delete</button>
                                        </div>
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                `;
            }
        }

    } catch (err) {
        console.error("Error loading video list:", err);
        const listContainer = document.getElementById('video-list-container');
        if (listContainer) {
            listContainer.innerHTML = `<div class="empty-video-state"><p>⚠️ Unable to load videos: ${escapeHtml(err.message)}</p></div>`;
        }
    }
}

// Clear chat messages window
function clearChat() {
    const chatMessages = document.getElementById('chat-messages');
    if (chatMessages) chatMessages.innerHTML = '';
}

// Select video card -> Open Video Player Screen & set RAG context
window.selectVideo = async function (videoId) {
    try {
        const res = await fetch(`/api/select-video/${videoId}`, { method: 'POST' });
        const data = await res.json();

        if (res.ok && data.success) {
            const v = data.video;
            currentActiveVideoId = videoId;
            lastUploadedSrtFilename = v.srt_filename || "sample_malayalam.srt";

            // Switch from Gallery View to Video Player View
            const galleryView = document.getElementById('home-gallery-view');
            const playerView = document.getElementById('home-player-view');

            if (galleryView) galleryView.style.display = 'none';
            if (playerView) playerView.style.display = 'flex';
            if (btnToggleChat) btnToggleChat.style.display = 'inline-flex';
            closeChatDrawer();

            // Load Video into Player
            if (v.source_type === "local" || v.video_url.startsWith("/uploads/")) {
                loadLocalVideo(v.video_url);
            } else {
                loadYouTubeVideo(v.video_url);
            }

            // Update Header & Active Badges
            const activeBadge = document.getElementById('active-video-name-display');
            if (activeBadge) activeBadge.innerText = `Active: ${v.video_name}`;

            document.getElementById('indexed-count-badge').innerText = `${data.total_chunks} Vector Chunks`;

            // Clear old chat history and notify in Chat Drawer
            clearChat();
            appendSystemMessage(`🎬 Opened <strong>${escapeHtml(v.video_name)}</strong> on player screen! (${data.total_chunks} vector chunks active). Ask your questions below!`);
        } else {
            alert('Failed to load video: ' + (data.detail || 'Unknown error'));
        }
    } catch (err) {
        alert('Error opening video: ' + err.message);
    }
};

// Centralized handler to pause/stop all video players (local video and YouTube iframe)
window.stopOrPauseVideoPlayer = function () {
    // 1. Pause HTML5 local video player
    const localPlayer = document.getElementById('local-player');
    if (localPlayer) {
        try {
            localPlayer.pause();
        } catch (e) { }
    }

    // 2. Pause YouTube JS API player
    try {
        if (player && typeof player.pauseVideo === 'function') {
            player.pauseVideo();
        }
    } catch (e) { }

    // 3. Send postMessage pause to YouTube iframe embed
    try {
        const iframe = document.getElementById('yt-embed-iframe') || document.querySelector('#player iframe');
        if (iframe && iframe.contentWindow) {
            iframe.contentWindow.postMessage(JSON.stringify({
                'event': 'command',
                'func': 'pauseVideo',
                'args': []
            }), '*');
        }
    } catch (e) { }
};

// Return from Video Player Screen back to Video Gallery
window.backToGallery = function () {
    const galleryView = document.getElementById('home-gallery-view');
    const playerView = document.getElementById('home-player-view');
    const btnToggleChat = document.getElementById('btn-toggle-chat');

    // Pause player immediately
    window.stopOrPauseVideoPlayer();

    if (playerView) playerView.style.display = 'none';
    if (galleryView) galleryView.style.display = 'flex';
    if (btnToggleChat) btnToggleChat.style.display = 'none';
    closeChatDrawer();

    // Clear previous chat history when returning to gallery
    clearChat();
    loadVideoList();
};

// Edit Video Modal Handler
window.editVideo = async function (videoId) {
    try {
        const res = await fetch(`/api/videos/${videoId}`);
        const data = await res.json();
        if (res.ok && data.video) {
            document.getElementById('edit-video-id').value = data.video.id;
            document.getElementById('edit-video-name').value = data.video.video_name;

            // Reset file input & label
            const fileInput = document.getElementById('edit-video-file');
            if (fileInput) fileInput.value = '';
            const fileLabel = document.getElementById('edit-video-file-label');
            if (fileLabel) fileLabel.innerText = 'Click or drop new video file to replace';

            // Privacy protection: DO NOT display/share local server file paths in the form input
            const urlInput = document.getElementById('edit-video-url');
            const isYt = data.video.video_url && (data.video.video_url.includes('youtube.com') || data.video.video_url.includes('youtu.be'));

            if (urlInput) {
                if (isYt) {
                    urlInput.value = data.video.video_url;
                } else {
                    // Local video file - keep input clean so server/local path is never exposed
                    urlInput.value = '';
                }
            }

            // Switch to appropriate source mode tab
            if (window.switchEditSourceMode) {
                window.switchEditSourceMode(isYt ? 'yt' : 'local');
            }

            const modal = document.getElementById('edit-video-modal');
            if (modal) modal.style.display = 'flex';
        } else {
            alert('Failed to load video details.');
        }
    } catch (err) {
        alert('Error fetching video details: ' + err.message);
    }
};

// Delete video from PostgreSQL registry
window.deleteVideo = async function (videoId) {
    if (!confirm(`Are you sure you want to delete this video from PostgreSQL database?`)) return;
    try {
        const res = await fetch(`/api/videos/${videoId}`, { method: 'DELETE' });
        const data = await res.json();
        if (res.ok && data.success) {
            if (currentActiveVideoId == videoId) {
                window.stopOrPauseVideoPlayer();
            }
            loadVideoList();
        } else {
            alert('Failed to delete video: ' + (data.detail || 'Error'));
        }
    } catch (err) {
        alert('Error deleting video: ' + err.message);
    }
};

// Navigation View Switcher (Home vs Admin)
window.switchNavView = function (targetView) {
    const viewHome = document.getElementById('view-home');
    const viewAdmin = document.getElementById('view-admin');
    const tabHome = document.getElementById('tab-nav-home');
    const tabAdmin = document.getElementById('tab-nav-admin');
    const chatDrawer = document.getElementById('chat-drawer');
    const btnToggleChat = document.getElementById('btn-toggle-chat');

    // Pause all playing audio/video when switching views
    window.stopOrPauseVideoPlayer();

    if (targetView === 'admin') {
        viewHome.style.display = 'none';
        viewAdmin.style.display = 'flex';
        tabAdmin.classList.add('active');
        tabHome.classList.remove('active');

        if (chatDrawer) chatDrawer.style.display = 'none';
        if (btnToggleChat) btnToggleChat.style.display = 'none';
    } else {
        viewAdmin.style.display = 'none';
        viewHome.style.display = 'flex';
        tabHome.classList.add('active');
        tabAdmin.classList.remove('active');

        // Always show Gallery View first on Home tab
        window.backToGallery();
    }
    loadVideoList();
};

// Status Check for Backend, PostgreSQL, and Ollama
async function checkStatus() {
    const statusPill = document.getElementById('ollama-status');
    const statusText = document.getElementById('status-text');
    const dbPill = document.getElementById('db-status-pill');
    const dbText = document.getElementById('db-status-text');

    try {
        const res = await fetch('/api/status');
        const data = await res.json();

        // PostgreSQL Status
        if (dbPill && dbText) {
            if (data.postgres_connected) {
                dbPill.className = 'status-pill online';
                dbText.innerText = 'PostgreSQL Vector DB Online';
            } else {
                dbPill.className = 'status-pill fallback';
                dbText.innerText = 'PostgreSQL Offline (In-Memory Fallback)';
            }
        }

        // Ollama Status
        if (data.ollama && data.ollama.available) {
            const models = data.ollama.models.join(', ') || 'Connected';
            statusPill.className = 'status-pill online';
            statusText.innerText = `Ollama Online (${models})`;
        } else {
            statusPill.className = 'status-pill fallback';
            statusText.innerText = 'Ollama Offline (Using Fallback RAG)';
        }

        if (data.indexed_chunks > 0) {
            document.getElementById('indexed-count-badge').innerText = `${data.indexed_chunks} Vector Chunks`;
        }
    } catch (err) {
        statusPill.className = 'status-pill offline';
        statusText.innerText = 'Backend Offline';
    }
}

// Chat Drawer Logic
const chatDrawer = document.getElementById('chat-drawer');
const btnToggleChat = document.getElementById('btn-toggle-chat');
const btnCloseChat = document.getElementById('btn-close-chat');

function openChatDrawer() {
    if (chatDrawer) {
        chatDrawer.style.display = 'flex';
        chatDrawer.classList.remove('collapsed');
    }
    if (btnToggleChat) {
        btnToggleChat.style.display = 'inline-flex';
        btnToggleChat.innerHTML = '<span>→ Chat open</span>';
    }
}

function closeChatDrawer() {
    if (chatDrawer) {
        chatDrawer.style.display = 'none';
        chatDrawer.classList.add('collapsed');
    }
    if (btnToggleChat) {
        btnToggleChat.innerHTML = '<span>→ Ask AI</span>';
    }
}

function toggleChatDrawer() {
    if (!chatDrawer) return;
    const isHidden = chatDrawer.style.display === 'none' || chatDrawer.classList.contains('collapsed');
    if (isHidden) {
        openChatDrawer();
    } else {
        closeChatDrawer();
    }
}

// App Initialization
document.addEventListener('DOMContentLoaded', () => {
    checkStatus();
    setInterval(checkStatus, 10000);
    loadVideoList();

    // View Switching Listeners
    const tabHome = document.getElementById('tab-nav-home');
    const tabAdmin = document.getElementById('tab-nav-admin');
    const btnBackGallery = document.getElementById('btn-back-to-gallery');

    if (tabHome) tabHome.addEventListener('click', () => switchNavView('home'));
    if (tabAdmin) tabAdmin.addEventListener('click', () => switchNavView('admin'));
    if (btnBackGallery) btnBackGallery.addEventListener('click', window.backToGallery);

    if (btnToggleChat) btnToggleChat.addEventListener('click', toggleChatDrawer);
    if (btnCloseChat) btnCloseChat.addEventListener('click', closeChatDrawer);

    // Admin Source Mode Toggles
    const adminTabLocal = document.getElementById('admin-tab-local');
    const adminTabYt = document.getElementById('admin-tab-yt');
    const adminGroupLocal = document.getElementById('admin-group-local');
    const adminGroupYt = document.getElementById('admin-group-yt');
    const adminVideoFileInput = document.getElementById('admin-video-file');
    const adminVideoFileLabel = document.getElementById('admin-video-file-label');
    const adminSrtFileInput = document.getElementById('admin-srt-file');
    const adminSrtFileLabel = document.getElementById('admin-srt-file-label');

    if (adminTabLocal && adminTabYt) {
        adminTabLocal.addEventListener('click', () => {
            adminTabLocal.classList.add('active');
            adminTabYt.classList.remove('active');
            adminGroupLocal.style.display = 'flex';
            adminGroupYt.style.display = 'none';
            adminSourceMode = "local";
        });

        adminTabYt.addEventListener('click', () => {
            adminTabYt.classList.add('active');
            adminTabLocal.classList.remove('active');
            adminGroupYt.style.display = 'flex';
            adminGroupLocal.style.display = 'none';
            adminSourceMode = "youtube";
        });
    }

    if (adminVideoFileInput) {
        adminVideoFileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                adminVideoFileLabel.innerText = `🎬 ${e.target.files[0].name}`;
            }
        });
    }

    if (adminSrtFileInput) {
        adminSrtFileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                adminSrtFileLabel.innerText = `📄 ${e.target.files[0].name}`;
            }
        });
    }

    // Admin Form Process & Store Vectors in PostgreSQL
    const adminForm = document.getElementById('admin-upload-form');
    if (adminForm) {
        adminForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const videoName = document.getElementById('admin-video-name').value.trim();
            const videoUrl = document.getElementById('admin-video-url').value.trim();
            const srtFile = adminSrtFileInput.files[0];
            const videoFile = adminVideoFileInput.files[0];

            if (!videoName) {
                alert('Please enter a Video Title/Name.');
                return;
            }
            if (!srtFile) {
                alert('Please select an SRT subtitle file to index.');
                return;
            }

            const btnProcess = document.getElementById('btn-admin-process');
            btnProcess.innerHTML = '<span>⚡ Chunking & Generating Vectors into Postgres...</span>';
            btnProcess.disabled = true;

            try {
                const formData = new FormData();
                formData.append('video_name', videoName);
                formData.append('source_type', adminSourceMode);
                formData.append('video_url', videoUrl);
                formData.append('srt_file', srtFile);
                if (videoFile && adminSourceMode === 'local') {
                    formData.append('video_file', videoFile);
                }

                const res = await fetch('/api/admin/upload', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();

                if (res.ok && data.success) {
                    alert(`✅ Video "${videoName}" successfully vectorized into PostgreSQL! (${data.total_chunks} chunks stored).`);
                    adminForm.reset();
                    adminVideoFileLabel.innerText = "Drop video file";
                    adminSrtFileLabel.innerText = "Drop subtitle file";

                    // Stay on Admin Panel and refresh managed video registry
                    loadVideoList();
                } else {
                    alert('Admin Upload Error: ' + (data.detail || 'Failed to vectorize video.'));
                }
            } catch (err) {
                alert('Connection error: ' + err.message);
            } finally {
                btnProcess.innerHTML = '<span>⚡ Store Vector & Save to Database</span>';
                btnProcess.disabled = false;
            }
        });
    }

    // Edit Video Source Mode Toggle
    let editSourceMode = 'local';
    const editTabLocal = document.getElementById('edit-tab-local');
    const editTabYt = document.getElementById('edit-tab-yt');
    const editGroupLocal = document.getElementById('edit-group-local');
    const editGroupYt = document.getElementById('edit-group-yt');
    const editVideoFileInput = document.getElementById('edit-video-file');
    const editVideoFileLabel = document.getElementById('edit-video-file-label');

    window.switchEditSourceMode = function (mode) {
        editSourceMode = mode;
        if (mode === 'local') {
            if (editTabLocal) editTabLocal.classList.add('active');
            if (editTabYt) editTabYt.classList.remove('active');
            if (editGroupLocal) editGroupLocal.style.display = 'block';
            if (editGroupYt) editGroupYt.style.display = 'none';
        } else {
            if (editTabYt) editTabYt.classList.add('active');
            if (editTabLocal) editTabLocal.classList.remove('active');
            if (editGroupYt) editGroupYt.style.display = 'block';
            if (editGroupLocal) editGroupLocal.style.display = 'none';
        }
    };

    if (editTabLocal) editTabLocal.addEventListener('click', () => window.switchEditSourceMode('local'));
    if (editTabYt) editTabYt.addEventListener('click', () => window.switchEditSourceMode('yt'));

    if (editVideoFileInput) {
        editVideoFileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                if (editVideoFileLabel) {
                    editVideoFileLabel.innerHTML = `🎥 Selected: <strong>${escapeHtml(e.target.files[0].name)}</strong>`;
                }
            } else {
                if (editVideoFileLabel) editVideoFileLabel.innerText = 'Click or drop new video file to replace';
            }
        });
    }

    // Edit Video Form Submit Handler
    const editForm = document.getElementById('edit-video-form');
    const editModal = document.getElementById('edit-video-modal');
    const btnCloseEditModal = document.getElementById('btn-close-edit-modal');
    const btnCancelEdit = document.getElementById('btn-cancel-edit');

    function closeEditModal() {
        if (editModal) editModal.style.display = 'none';
    }

    if (btnCloseEditModal) {
        btnCloseEditModal.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault();
            closeEditModal();
        });
    }
    if (btnCancelEdit) {
        btnCancelEdit.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault();
            closeEditModal();
        });
    }

    if (editForm) {
        editForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const videoId = document.getElementById('edit-video-id').value;
            const videoName = document.getElementById('edit-video-name').value.trim();
            const videoUrlInput = document.getElementById('edit-video-url');
            const fileInput = document.getElementById('edit-video-file');
            const btnSaveEdit = document.getElementById('btn-save-edit');

            if (!videoName) {
                alert('Please enter a video name.');
                return;
            }

            let finalVideoUrl = "";

            try {
                if (btnSaveEdit) {
                    btnSaveEdit.disabled = true;
                    btnSaveEdit.innerText = 'Saving...';
                }

                // Check if user selected a new video file to re-upload
                if (editSourceMode === 'local' && fileInput && fileInput.files.length > 0) {
                    btnSaveEdit.innerText = 'Uploading new video...';
                    const formData = new FormData();
                    formData.append('video_file', fileInput.files[0]);

                    const uploadRes = await fetch('/api/upload-video', {
                        method: 'POST',
                        body: formData
                    });

                    const uploadData = await uploadRes.json();
                    if (!uploadRes.ok || !uploadData.url) {
                        throw new Error(uploadData.detail || 'Failed to upload new video file');
                    }
                    finalVideoUrl = uploadData.url;
                } else if (editSourceMode === 'yt' && videoUrlInput && videoUrlInput.value.trim()) {
                    finalVideoUrl = videoUrlInput.value.trim();
                }

                btnSaveEdit.innerText = 'Updating record...';

                const res = await fetch(`/api/videos/${videoId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ video_name: videoName, video_url: finalVideoUrl })
                });

                const data = await res.json();
                if (res.ok && data.success) {
                    closeEditModal();
                    loadVideoList();
                } else {
                    alert('Error updating video: ' + (data.detail || 'Failed to update'));
                }
            } catch (err) {
                alert('Error updating video: ' + err.message);
            } finally {
                if (btnSaveEdit) {
                    btnSaveEdit.disabled = false;
                    btnSaveEdit.innerText = 'Save Changes';
                }
            }
        });
    }

    // Open SRT in TextEdit
    window.openSrtInTextEdit = async function () {
        try {
            const res = await fetch('/api/open-srt-textedit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename: lastUploadedSrtFilename })
            });
            const data = await res.json();
            if (res.ok && data.success) {
                openChatDrawer();
                appendSystemMessage(`📝 Opened <strong>${data.filename}</strong> in macOS TextEdit.`);
            } else {
                alert('Error opening TextEdit: ' + (data.detail || 'SRT file not found.'));
            }
        } catch (err) {
            alert('Failed to connect to backend: ' + err.message);
        }
    };

    const btnOpenTextEdit = document.getElementById('btn-open-textedit');
    if (btnOpenTextEdit) {
        btnOpenTextEdit.addEventListener('click', window.openSrtInTextEdit);
    }

    // Provider select change & API Key handling
    const llmSelect = document.getElementById('llm-provider-select');
    const apiKeyInput = document.getElementById('api-key-input');
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const chatMessages = document.getElementById('chat-messages');

    const savedApiKey = localStorage.getItem('ai_api_key') || '';
    if (savedApiKey && apiKeyInput) {
        apiKeyInput.value = savedApiKey;
        apiKeyInput.style.display = 'inline-block';
    }

    if (llmSelect && apiKeyInput) {
        llmSelect.addEventListener('change', (e) => {
            if (['openrouter', 'gemini', 'auto'].includes(e.target.value)) {
                apiKeyInput.style.display = 'inline-block';
            } else {
                apiKeyInput.style.display = 'none';
            }
        });

        apiKeyInput.addEventListener('input', (e) => {
            localStorage.setItem('ai_api_key', e.target.value.trim());
        });
    }

    // Submit Chat Question
    if (chatForm) {
        chatForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const query = chatInput.value.trim();
            if (!query) return;

            const btnSend = document.getElementById('btn-send');

            openChatDrawer();
            appendUserMessage(query);
            chatInput.value = '';

            const provider = llmSelect ? llmSelect.value : 'auto';
            const apiKey = apiKeyInput ? apiKeyInput.value.trim() : '';

            // Disable send button while response is loading
            if (btnSend) btnSend.disabled = true;

            const botMsgDiv = appendBotLoadingMessage();

            try {
                const res = await fetch('/api/query', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query, provider, api_key: apiKey })
                });

                const data = await res.json();

                if (res.ok) {
                    const formattedAnswer = renderTimestampPills(data.answer);
                    botMsgDiv.querySelector('.msg-body').innerHTML = `
                        <div class="msg-text">${formattedAnswer}</div>
                    `;
                } else {
                    botMsgDiv.querySelector('.msg-body').innerHTML = `⚠️ Error: ${data.detail || 'Failed to generate response'}`;
                }
            } catch (err) {
                botMsgDiv.querySelector('.msg-body').innerHTML = `⚠️ Network error connecting to backend: ${err.message}`;
            } finally {
                // Re-enable send button once output or error is displayed
                if (btnSend) btnSend.disabled = false;
            }

            scrollToBottom(chatMessages);
        });
    }
});

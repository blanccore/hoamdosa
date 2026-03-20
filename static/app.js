/* ── 호암도사 대시보드 JS ── */

// ── 네비게이션 ──
document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
        document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        item.classList.add('active');
        document.getElementById(`page-${item.dataset.page}`).classList.add('active');

        // 히스토리/설정 페이지 진입 시 데이터 로드
        if (item.dataset.page === 'history') loadHistory();
        if (item.dataset.page === 'settings') loadStatus();
    });
});

// ── 상태 확인 ──
async function checkStatus() {
    try {
        const res = await fetch('/api/status');
        if (res.ok) {
            document.getElementById('status-indicator').classList.add('online');
            document.getElementById('status-indicator').classList.remove('offline');
            document.getElementById('status-text').textContent = '서버 연결됨';
        }
    } catch {
        document.getElementById('status-indicator').classList.add('offline');
        document.getElementById('status-indicator').classList.remove('online');
        document.getElementById('status-text').textContent = '서버 오프라인';
    }
}
checkStatus();
setInterval(checkStatus, 30000);

// ── 음성 업로드 ──
const uploadZone = document.getElementById('upload-zone');
const fileInput = document.getElementById('audio-file');
const processBtn = document.getElementById('process-btn');
let selectedFile = null;

uploadZone.addEventListener('click', () => fileInput.click());

uploadZone.addEventListener('dragover', e => {
    e.preventDefault();
    uploadZone.classList.add('dragover');
});

uploadZone.addEventListener('dragleave', () => {
    uploadZone.classList.remove('dragover');
});

uploadZone.addEventListener('drop', e => {
    e.preventDefault();
    uploadZone.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
        selectFile(e.dataTransfer.files[0]);
    }
});

fileInput.addEventListener('change', () => {
    if (fileInput.files.length) selectFile(fileInput.files[0]);
});

function selectFile(file) {
    selectedFile = file;
    uploadZone.classList.add('has-file');
    uploadZone.innerHTML = `
        <div class="upload-icon">🎵</div>
        <p><strong>${file.name}</strong></p>
        <p class="upload-hint">${(file.size / 1024 / 1024).toFixed(1)}MB</p>
    `;
    processBtn.disabled = false;
}

// ── 음성 처리 ──
processBtn.addEventListener('click', async () => {
    if (!selectedFile) return;

    const btnText = processBtn.querySelector('.btn-text');
    const btnLoading = processBtn.querySelector('.btn-loading');
    btnText.hidden = true;
    btnLoading.hidden = false;
    processBtn.disabled = true;

    const speed = document.getElementById('speed-input').value;
    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('speed', speed);

    try {
        const res = await fetch('/api/process-audio', { method: 'POST', body: formData });
        const data = await res.json();

        if (!res.ok) throw new Error(data.detail || '처리 실패');

        const resultCard = document.getElementById('audio-result');
        const resultInfo = document.getElementById('result-info');
        resultInfo.innerHTML = `
            ⏱ 길이: ${data.duration}초<br>
            ⚡ 배속: ${data.speed}x<br>
            ✂️ 무음 ${data.silences_count}구간 처리됨
        `;

        document.getElementById('download-audio').href = data.audio;
        if (data.srt) {
            document.getElementById('download-srt').href = data.srt;
            document.getElementById('download-srt').hidden = false;
        } else {
            document.getElementById('download-srt').hidden = true;
        }

        resultCard.hidden = false;
    } catch (err) {
        alert(`❌ 에러: ${err.message}`);
    } finally {
        btnText.hidden = false;
        btnLoading.hidden = true;
        processBtn.disabled = false;
    }
});

// ── 유튜브 분석 ──
document.getElementById('youtube-btn').addEventListener('click', async () => {
    const url = document.getElementById('youtube-url').value.trim();
    if (!url) return;

    const btn = document.getElementById('youtube-btn');
    btn.disabled = true;
    btn.textContent = '⏳ 분석 중...';

    const formData = new FormData();
    formData.append('url', url);

    try {
        const res = await fetch('/api/youtube-script', { method: 'POST', body: formData });
        const data = await res.json();

        if (!res.ok) throw new Error(data.detail || '분석 실패');

        document.getElementById('yt-title').textContent = `📹 ${data.title}`;
        document.getElementById('yt-script').textContent = data.script;

        const kwDiv = document.getElementById('yt-keywords');
        kwDiv.innerHTML = data.keywords.map((kw, i) => `
            <div class="keyword-item">
                <span class="keyword-num">${i + 1}</span>
                <div>
                    <div>${kw.sentence.substring(0, 60)}${kw.sentence.length > 60 ? '...' : ''}</div>
                    <div class="keyword-tags">
                        ${kw.keywords.map(k => `<span class="keyword-tag">${k}</span>`).join('')}
                    </div>
                </div>
            </div>
        `).join('');

        document.getElementById('youtube-result').hidden = false;
    } catch (err) {
        alert(`❌ 에러: ${err.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = '분석 시작';
    }
});

// ── 검색어 생성 ──
document.getElementById('keyword-btn').addEventListener('click', async () => {
    const text = document.getElementById('script-text').value.trim();
    if (!text) return;

    const btn = document.getElementById('keyword-btn');
    btn.disabled = true;
    btn.textContent = '⏳ 생성 중...';

    const formData = new FormData();
    formData.append('text', text);

    try {
        const res = await fetch('/api/generate-keywords', { method: 'POST', body: formData });
        const data = await res.json();

        if (!res.ok) throw new Error(data.detail || '생성 실패');

        const listDiv = document.getElementById('keyword-list');
        listDiv.innerHTML = data.keywords.map((kw, i) => `
            <div class="keyword-item">
                <span class="keyword-num">${i + 1}</span>
                <div>
                    <div>${kw.sentence.substring(0, 60)}${kw.sentence.length > 60 ? '...' : ''}</div>
                    <div class="keyword-tags">
                        ${kw.keywords.map(k => `<span class="keyword-tag">${k}</span>`).join('')}
                    </div>
                </div>
            </div>
        `).join('');

        document.getElementById('keyword-result').hidden = false;
    } catch (err) {
        alert(`❌ 에러: ${err.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = '검색어 생성';
    }
});

// ── 히스토리 ──
async function loadHistory() {
    const listDiv = document.getElementById('history-list');
    listDiv.innerHTML = '<div class="loading"><div class="spinner"></div> 로딩 중...</div>';

    try {
        const res = await fetch('/api/history');
        const data = await res.json();

        if (!data.length) {
            listDiv.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:24px">파일이 없습니다</p>';
            return;
        }

        listDiv.innerHTML = data.map(f => {
            const icon = f.type === 'mp3' ? '🎵' : '📝';
            const iconClass = f.type;
            const date = new Date(f.created);
            const dateStr = `${date.getMonth() + 1}/${date.getDate()} ${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`;
            return `
                <div class="history-item">
                    <div class="history-info">
                        <div class="history-icon ${iconClass}">${icon}</div>
                        <div>
                            <div class="history-name">${f.name}</div>
                            <div class="history-meta">${f.size_kb}KB · ${dateStr}</div>
                        </div>
                    </div>
                    <a href="/api/download/${f.name}" class="history-download" download>다운로드</a>
                </div>
            `;
        }).join('');
    } catch {
        listDiv.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:24px">로드 실패</p>';
    }
}

// ── 설정/상태 ──
async function loadStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        document.getElementById('stat-files').textContent = `${data.files_count}개`;
        document.getElementById('stat-size').textContent = `${data.total_size_mb}MB`;
        document.getElementById('stat-disk').textContent = `${data.disk_free_gb}GB`;
    } catch {}
}

// ── PWA 등록 ──
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/sw.js').catch(() => {});
}

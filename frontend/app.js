const API = '';
let uploadedImages = [];
let currentBatchId = null;
let ws = null;

// ─── Upload ───

const uploadZone = document.getElementById('uploadZone');
const fileInput = document.getElementById('fileInput');
const uploadProgress = document.getElementById('uploadProgress');
const uploadProgressFill = document.getElementById('uploadProgressFill');
const uploadProgressText = document.getElementById('uploadProgressText');

uploadZone.addEventListener('click', () => fileInput.click());
uploadZone.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('dragover'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
uploadZone.addEventListener('drop', e => {
    e.preventDefault();
    uploadZone.classList.remove('dragover');
    handleFiles(e.dataTransfer.files);
});
fileInput.addEventListener('change', e => handleFiles(e.target.files));

function handleFiles(files) {
    if (!files.length) return;
    const formData = new FormData();
    for (const f of files) formData.append('files', f);

    uploadProgress.style.display = 'block';
    uploadProgressFill.style.width = '0%';
    uploadProgressText.textContent = '上传中...';

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API}/api/upload`);

    xhr.upload.onprogress = e => {
        if (e.lengthComputable) {
            const pct = Math.round((e.loaded / e.total) * 100);
            uploadProgressFill.style.width = pct + '%';
            uploadProgressText.textContent = `上传中 ${pct}%`;
        }
    };

    xhr.onload = () => {
        if (xhr.status === 200) {
            const data = JSON.parse(xhr.responseText);
            uploadedImages.push(...data.images);
            renderImages();
            uploadProgressText.textContent = `上传完成，${data.total} 张图片`;
        } else {
            uploadProgressText.textContent = '上传失败';
        }
    };

    xhr.onerror = () => { uploadProgressText.textContent = '网络错误'; };
    xhr.send(formData);
}

function renderImages() {
    const grid = document.getElementById('imageGrid');
    grid.innerHTML = '';
    uploadedImages.forEach(img => {
        const card = document.createElement('div');
        card.className = 'image-card';
        card.innerHTML = `
            <img src="${API}${img.thumbnail_url}" onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><rect fill=%22%23eee%22 width=%22100%22 height=%22100%22/></svg>'">
            <button class="delete-btn" onclick="deleteImage('${img.id}')">&times;</button>
            <div class="info">${img.filename} <span class="dims">${img.width}x${img.height}</span></div>
        `;
        grid.appendChild(card);
    });
    document.getElementById('imageCount').textContent = `${uploadedImages.length} 张图片`;
    document.getElementById('processBtn').disabled = uploadedImages.length === 0;
}

async function deleteImage(id) {
    await fetch(`${API}/api/images/${id}`, { method: 'DELETE' });
    uploadedImages = uploadedImages.filter(i => i.id !== id);
    renderImages();
}

// ─── Settings toggle ───

document.getElementById('enableBgRemoval').addEventListener('change', e => {
    document.getElementById('bgSection').classList.toggle('hidden', !e.target.checked);
    document.getElementById('featureBgRemoval').classList.toggle('feature-item--active', e.target.checked);
});
document.getElementById('bgMethod').addEventListener('change', e => {
    const isApi = e.target.value === 'api';
    document.getElementById('apiKeyRow').classList.toggle('hidden', !isApi);
    document.getElementById('localModelRow').classList.toggle('hidden', isApi);
});
document.getElementById('enableLogo').addEventListener('change', e => {
    document.getElementById('logoSection').classList.toggle('hidden', !e.target.checked);
    document.getElementById('featureLogo').classList.toggle('feature-item--active', e.target.checked);
});
document.getElementById('enableCompress').addEventListener('change', e => {
    document.getElementById('compressSection').classList.toggle('hidden', !e.target.checked);
    document.getElementById('featureCompress').classList.toggle('feature-item--active', e.target.checked);
});
document.getElementById('enableWatermark').addEventListener('change', e => {
    document.getElementById('watermarkSection').classList.toggle('hidden', !e.target.checked);
    document.getElementById('featureWatermark').classList.toggle('feature-item--active', e.target.checked);
});
document.getElementById('enableBlindWatermark').addEventListener('change', e => {
    document.getElementById('blindSection').classList.toggle('hidden', !e.target.checked);
    document.getElementById('featureBlindWatermark').classList.toggle('feature-item--active', e.target.checked);
});

function toggleFeature(name) {
    const sectionMap = { bg: 'bgSection', logo: 'logoSection', compress: 'compressSection', watermark: 'watermarkSection', blind: 'blindSection' };
    const featureMap = { bg: 'featureBgRemoval', logo: 'featureLogo', compress: 'featureCompress', watermark: 'featureWatermark', blind: 'featureBlindWatermark' };
    const section = document.getElementById(sectionMap[name]);
    const feature = document.getElementById(featureMap[name]);
    const expandBtn = feature.querySelector('.feature-expand');
    section.classList.toggle('hidden');
    expandBtn.classList.toggle('expanded');
}

// ─── API Key 管理 ───
let savedApiKey = '';

async function loadApiKey() {
    try {
        const res = await fetch(`${API}/api/config/apikey`);
        const data = await res.json();
        savedApiKey = data.api_key || '';
        document.getElementById('apiKey').value = savedApiKey;
    } catch (e) {}
}

document.getElementById('apiKey').addEventListener('blur', async e => {
    const newKey = e.target.value.trim();
    if (newKey === savedApiKey) return;
    try {
        await fetch(`${API}/api/config/apikey`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: `api_key=${encodeURIComponent(newKey)}`,
        });
        savedApiKey = newKey;
    } catch (e) {}
});

// 页面加载时读取 API Key
loadApiKey();

// ─── Logo position grid ───

const positionLabels = {
    'left-top': '左上', 'center-top': '上中', 'right-top': '右上',
    'left-center': '左中', 'center': '居中', 'right-center': '右中',
    'left-bottom': '左下', 'center-bottom': '下中', 'right-bottom': '右下',
};
const positionOrder = ['left-top','center-top','right-top','left-center','center','right-center','left-bottom','center-bottom','right-bottom'];
let selectedPosition = 'right-bottom';

function initPositionGrid() {
    const grid = document.getElementById('positionGrid');
    grid.innerHTML = '';
    positionOrder.forEach(pos => {
        const btn = document.createElement('button');
        btn.textContent = positionLabels[pos];
        btn.dataset.pos = pos;
        if (pos === selectedPosition) btn.classList.add('active');
        btn.addEventListener('click', () => {
            grid.querySelectorAll('button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            selectedPosition = pos;
        });
        grid.appendChild(btn);
    });
}
initPositionGrid();

// ─── Watermark position grid ───

let selectedWmPosition = 'right-bottom';

function initWmPositionGrid() {
    const grid = document.getElementById('wmPositionGrid');
    if (!grid) return;
    grid.innerHTML = '';
    positionOrder.forEach(pos => {
        const btn = document.createElement('button');
        btn.textContent = positionLabels[pos];
        btn.dataset.pos = pos;
        if (pos === selectedWmPosition) btn.classList.add('active');
        btn.addEventListener('click', () => {
            grid.querySelectorAll('button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            selectedWmPosition = pos;
        });
        grid.appendChild(btn);
    });
}
initWmPositionGrid();

// ─── Logo file upload ───

let logoFileId = null;

function handleLogoUpload(files) {
    if (!files.length) return;
    const formData = new FormData();
    formData.append('file', files[0]);

    fetch(`${API}/api/upload-logo`, { method: 'POST', body: formData })
        .then(r => r.json())
        .then(data => {
            logoFileId = data.logo_id;
            document.getElementById('logoPreview').innerHTML = `<img src="${API}${data.thumbnail_url}">`;
        })
        .catch(() => {});
}

document.getElementById('logoMode').addEventListener('change', e => {
    const mode = e.target.value;
    document.getElementById('logoUploadGroup').classList.toggle('hidden', mode !== 'image');
});

// ─── Range slider ───

document.querySelectorAll('input[type="range"]').forEach(input => {
    const display = input.parentElement.querySelector('.value');
    if (display) {
        input.addEventListener('input', () => {
            const suffix = display.id.includes('Ratio') || display.id.includes('Opacity') || display.id.includes('quality') ? '%' : '';
            display.textContent = input.value + suffix;
        });
    }
});

// ─── Collect current config ───

function collectConfig() {
    const logoMode = document.getElementById('logoMode').value;
    const form = new FormData();
    form.append('bg_method', document.getElementById('enableBgRemoval').checked ? document.getElementById('bgMethod').value : 'none');
    form.append('bg_model', document.getElementById('bgModel').value);
    form.append('api_key', document.getElementById('apiKey').value);
    form.append('bg_threads', localStorage.getItem('settingThreads') || 0);
    form.append('bg_disable_arena', localStorage.getItem('settingDisableArena') !== 'false');
    form.append('logo_enabled', document.getElementById('enableLogo').checked);
    form.append('logo_position', selectedPosition);
    form.append('logo_ratio', document.getElementById('logoRatio').value / 100);
    form.append('logo_opacity', document.getElementById('logoOpacity').value / 100);
    form.append('logo_tile', document.getElementById('logoTile').checked);
    if (logoMode === 'image' && logoFileId) {
        form.append('logo_file_id', logoFileId);
    }
    form.append('wm_mode', document.getElementById('enableWatermark').checked ? document.getElementById('wmMode').value : 'off');
    form.append('wm_text', document.getElementById('wmText').value);
    form.append('wm_text_color', document.getElementById('wmTextColor').value);
    form.append('wm_position', selectedWmPosition);
    form.append('wm_blind_enabled', document.getElementById('enableBlindWatermark').checked);
    form.append('wm_blind_text', document.getElementById('wmBlindText').value);
    form.append('compress_enabled', document.getElementById('enableCompress').checked);
    if (document.getElementById('enableCompress').checked) {
        form.append('output_format', document.getElementById('outputFormat').value);
        form.append('quality', document.getElementById('quality').value);
        form.append('max_file_size_kb', document.getElementById('maxFileSize').value);
        form.append('max_width', document.getElementById('maxWidth').value);
    } else {
        form.append('output_format', 'PNG');
        form.append('quality', '95');
    }
    return form;
}

// ─── Process ───

async function startProcess() {
    const btn = document.getElementById('processBtn');
    btn.disabled = true;
    btn.textContent = '处理中...';

    try {
        const res = await fetch(`${API}/api/process`, { method: 'POST', body: collectConfig() });
        const data = await res.json();
        currentBatchId = data.batch_id;
        document.getElementById('progressPanel').classList.remove('hidden');
        initResultCards();
        connectWebSocket(data.batch_id);
    } catch (err) {
        alert('启动处理失败: ' + err.message);
        btn.disabled = false;
        btn.textContent = '开始处理';
    }
}

function initResultCards() {
    const grid = document.getElementById('resultGrid');
    uploadedImages.forEach(img => {
        if (document.getElementById(`result-${img.id}`)) return;
        const card = document.createElement('div');
        card.className = 'result-card';
        card.id = `result-${img.id}`;
        card.innerHTML = `
            <div class="status-processing"><div class="spinner"></div><div class="text">处理中...</div></div>
            <div class="meta"><span class="filename">${img.filename}</span></div>
        `;
        grid.appendChild(card);
    });
}

// ─── WebSocket ───

function connectWebSocket(batchId) {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/api/ws/progress/${batchId}`);

    ws.onmessage = event => {
        const data = JSON.parse(event.data);
        if (data.error) return;
        updateProgress(data);
    };
    ws.onclose = () => { if (currentBatchId) pollProgress(currentBatchId); };
    ws.onerror = () => {};
}

async function pollProgress(batchId) {
    try {
        const res = await fetch(`${API}/api/progress/${batchId}`);
        const data = await res.json();
        updateProgress(data);
        if (data.status !== 'done' && data.status !== 'error') {
            setTimeout(() => pollProgress(batchId), 1000);
        }
    } catch (e) {}
}

function updateProgress(data) {
    const pct = data.total > 0 ? Math.round((data.done / data.total) * 100) : 0;
    const fill = document.getElementById('progressFill');
    fill.style.width = pct + '%';
    document.getElementById('progressPercent').textContent = pct + '%';
    if (pct >= 100) fill.classList.add('done');

    document.getElementById('progressText').textContent =
        `已完成 ${data.done}/${data.total}` + (data.failed > 0 ? `，失败 ${data.failed}` : '');

    if (data.result) updateResultCard(data.result, pct);

    if (data.status === 'done') {
        document.getElementById('processBtn').disabled = false;
        document.getElementById('processBtn').textContent = '开始处理';
        document.getElementById('downloadAllBtn').classList.remove('hidden');
    } else if (data.status === 'processing' || data.status === 'pending') {
        document.getElementById('progressSection').classList.remove('hidden');
    }
}

function updateResultCard(result, itemPct) {
    const card = document.getElementById(`result-${result.id}`);
    if (!card) return;

    if (result.status === 'processing') {
        card.innerHTML = `
            <div class="status-processing"><div class="spinner"></div><div class="text">处理中... ${itemPct > 0 ? itemPct + '%' : ''}</div></div>
            <div class="meta"><span class="filename">${result.filename}</span></div>
        `;
    } else if (result.status === 'done') {
        const meta = uploadedImages.find(i => i.id === result.id);
        card.innerHTML = `
            <div class="preview-row">
                <div class="before">
                    <img src="${API}${meta ? meta.thumbnail_url : ''}" onerror="this.style.display='none'">
                    <span class="label">原图</span>
                </div>
                <div class="after">
                    <img src="${API}${result.thumbnail_url}" onerror="this.style.display='none'">
                    <span class="label">处理后</span>
                </div>
            </div>
            <div class="meta">
                <span class="filename" title="${result.filename}">${result.filename.length > 10 ? result.filename.slice(0, 10) + '...' : result.filename}</span>
                ${result.finished_at ? `<span class="time">${result.finished_at}</span>` : ''}
                <span class="size">${(result.output_size / 1024 / 1024).toFixed(2)} MB</span>
            </div>
            <div class="actions">
                <a class="btn btn-primary btn-sm" href="${API}${result.output_url}" download>下载</a>
                <button class="btn btn-outline btn-sm" onclick="showPreview('${result.id}', '${API}${result.output_url}', '${result.filename}')">预览</button>
                <button class="btn btn-outline btn-sm" onclick="openEditor('${result.id}')">手动抠图</button>
                <button class="btn btn-danger btn-sm" onclick="deleteResult('result-${result.id}')">删除</button>
            </div>
        `;
    } else if (result.status === 'error') {
        card.classList.add('error');
        card.innerHTML = `
            <div class="status-pending" style="color:var(--danger)">处理失败</div>
            <div class="error-msg">${result.error_msg}</div>
            <div class="meta">
                <span class="filename">${result.filename.length > 10 ? result.filename.slice(0, 10) + '...' : result.filename}</span>
                ${result.finished_at ? `<span class="time">${result.finished_at}</span>` : ''}
                <span class="size">${(result.output_size / 1024 / 1024).toFixed(2)} MB</span>
            </div>
            <div class="actions">
                <button class="btn btn-outline btn-sm" onclick="openEditor('${result.id}')">手动抠图</button>
                <button class="btn btn-danger btn-sm" onclick="deleteResult('result-${result.id}')">删除</button>
            </div>
        `;
    }
}

function cancelProcess() {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send('cancel');
}

function downloadAll() {
    window.location.href = `${API}/api/download-all?batch_id=${currentBatchId || ''}`;
}

function clearAll() {
    uploadedImages = [];
    renderImages();
    document.getElementById('progressSection').classList.add('hidden');
    document.getElementById('downloadAllBtn').classList.add('hidden');
    document.getElementById('progressFill').style.width = '0%';
    document.getElementById('progressFill').classList.remove('done');
    document.getElementById('resultGrid').innerHTML = '';
    if (ws) ws.close();
    currentBatchId = null;
}

async function deleteResult(cardId) {
    if (!confirm('确定要删除这张处理结果吗？')) return;
    const card = document.getElementById(cardId);
    if (!card) {
        const all = document.querySelectorAll('.result-card');
        return;
    }
    card.remove();
    const imageId = cardId.replace('result-', '').split('-edit-')[0];
    if (imageId) {
        try {
            await fetch(`${API}/api/results/${imageId}`, { method: 'DELETE' });
        } catch (e) {}
    }
}

// ═══════════════════════════════════════
// ─── Mask Editor ───
// ═══════════════════════════════════════

let editorImageId = null;
let editorCanvas = null;
let editorCtx = null;
let editorTool = 'erase';
let editorBrushSize = 20;
let isDrawing = false;
let editorHistory = [];
let editorCutoutImg = null;   // 已抠图的底图（含透明通道）
let editorMaskData = null;    // 全尺寸蒙版 (白=保留, 黑=擦除)
let editorScale = 1;
let editorZoom = 1;           // 缩放倍数
let editorReady = false;      // 编辑器是否就绪

function openEditor(imageId) {
    editorImageId = imageId;
    editorReady = false;
    editorHistory = [];
    editorTool = 'erase';
    editorBrushSize = 20;
    editorZoom = 1;

    // 重置工具栏 UI
    document.getElementById('brushSize').value = 20;
    document.getElementById('brushSizeVal').textContent = '20';
    document.getElementById('editorZoomVal').textContent = '100%';
    document.getElementById('toolErase').classList.add('active');
    document.getElementById('toolKeep').classList.remove('active');

    // 显示弹窗
    document.getElementById('editorOverlay').classList.remove('hidden');

    // 加载抠图结果 PNG（含透明通道）
    const img = new Image();
    img.onload = () => {
        editorCutoutImg = img;
        initEditorCanvas();
    };
    img.onerror = () => {
        // 抠图结果不存在，回退到加载原图
        const fallback = new Image();
        fallback.onload = () => {
            editorCutoutImg = fallback;
            initEditorCanvas();
        };
        fallback.onerror = () => { alert('图片加载失败'); closeEditor(); };
        fallback.src = `${API}/api/original/${imageId}`;
    };
    img.src = `${API}/api/cutout/${imageId}`;
}

function initEditorCanvas() {
    const canvas = document.getElementById('editorCanvas');
    editorCanvas = canvas;
    editorCtx = canvas.getContext('2d');

    const img = editorCutoutImg;
    canvas.width = img.width;
    canvas.height = img.height;

    // CSS 缩放到可视区域
    const wrap = document.querySelector('.editor-canvas-wrap');
    const maxW = wrap.clientWidth - 32;
    const maxH = window.innerHeight - 220;
    const baseScale = Math.min(1, maxW / img.width, maxH / img.height);
    editorScale = baseScale * editorZoom;
    canvas.style.width = Math.round(img.width * editorScale) + 'px';
    canvas.style.height = Math.round(img.height * editorScale) + 'px';

    // 先把抠图画到临时 canvas 上，取 alpha 通道生成初始蒙版
    const tmpC = document.createElement('canvas');
    tmpC.width = img.width; tmpC.height = img.height;
    const tmpCtx = tmpC.getContext('2d');
    tmpCtx.drawImage(img, 0, 0);
    const cutoutPixels = tmpCtx.getImageData(0, 0, img.width, img.height);

    // 蒙版：alpha > 128 → 白(保留)，否则 → 黑(擦除)
    const mask = new ImageData(img.width, img.height);
    const cd = cutoutPixels.data, md = mask.data;
    for (let i = 0; i < cd.length; i += 4) {
        const val = cd[i + 3] > 128 ? 255 : 0;
        md[i] = val; md[i + 1] = val; md[i + 2] = val; md[i + 3] = 255;
    }
    editorMaskData = mask;

    showMaskView();
    saveEditorState();
    editorReady = true;
}

function showMaskView() {
    if (!editorCutoutImg || !editorMaskData || !editorCtx) return;
    const w = editorCanvas.width, h = editorCanvas.height;
    const cs = 12;

    // 棋盘格背景
    editorCtx.fillStyle = '#fff';
    editorCtx.fillRect(0, 0, w, h);
    editorCtx.fillStyle = '#ddd';
    for (let y = 0; y < h; y += cs) {
        for (let x = 0; x < w; x += cs) {
            if (((x / cs | 0) + (y / cs | 0)) % 2 === 0) editorCtx.fillRect(x, y, cs, cs);
        }
    }

    // 抠图底图
    editorCtx.drawImage(editorCutoutImg, 0, 0);

    // 擦除区域叠加红色
    const imgData = editorCtx.getImageData(0, 0, w, h);
    const m = editorMaskData.data;
    const p = imgData.data;
    for (let i = 0; i < m.length; i += 4) {
        if (m[i] < 128) {
            p[i]     = (p[i] * 3 + 220) >> 2;
            p[i + 1] = (p[i + 1] * 3 + 40) >> 2;
            p[i + 2] = (p[i + 2] * 3 + 40) >> 2;
        }
    }
    editorCtx.putImageData(imgData, 0, 0);
}

// ─── 工具栏 ───

function setTool(tool) {
    editorTool = tool;
    document.getElementById('toolErase').classList.toggle('active', tool === 'erase');
    document.getElementById('toolKeep').classList.toggle('active', tool === 'keep');
}

function updateBrushSize(val) {
    editorBrushSize = parseInt(val);
    document.getElementById('brushSizeVal').textContent = val;
}

function applyEditorZoom() {
    if (!editorCanvas || !editorCutoutImg) return;
    const wrap = document.querySelector('.editor-canvas-wrap');
    const maxW = wrap.clientWidth - 32;
    const maxH = window.innerHeight - 220;
    const baseScale = Math.min(1, maxW / editorCutoutImg.width, maxH / editorCutoutImg.height);
    editorScale = baseScale * editorZoom;
    editorCanvas.style.width = Math.round(editorCutoutImg.width * editorScale) + 'px';
    editorCanvas.style.height = Math.round(editorCutoutImg.height * editorScale) + 'px';
    document.getElementById('editorZoomVal').textContent = Math.round(editorZoom * 100) + '%';
}

function zoomInEditor() {
    editorZoom = Math.min(5, editorZoom * 1.25);
    applyEditorZoom();
}

function zoomOutEditor() {
    editorZoom = Math.max(0.2, editorZoom / 1.25);
    applyEditorZoom();
}

function saveEditorState() {
    if (!editorMaskData) return;
    editorHistory.push(new ImageData(
        new Uint8ClampedArray(editorMaskData.data),
        editorMaskData.width,
        editorMaskData.height
    ));
    if (editorHistory.length > 30) editorHistory.shift();
}

function undoEditor() {
    if (editorHistory.length <= 1) return;
    editorHistory.pop();
    const prev = editorHistory[editorHistory.length - 1];
    editorMaskData = new ImageData(new Uint8ClampedArray(prev.data), prev.width, prev.height);
    showMaskView();
}

function resetEditor() {
    if (!editorCutoutImg) return;
    const w = editorCanvas.width, h = editorCanvas.height;
    const mask = new ImageData(w, h);
    const d = mask.data;
    for (let i = 0; i < d.length; i += 4) { d[i] = 255; d[i + 1] = 255; d[i + 2] = 255; d[i + 3] = 255; }
    editorMaskData = mask;
    showMaskView();
    saveEditorState();
}

// ─── 画笔绘制（事件委托 + 线段插值平滑笔触）───

(function initEditorEvents() {
    const wrap = document.querySelector('.editor-canvas-wrap');
    if (!wrap) return;

    let lastX = -1, lastY = -1; // 上次绘制的画布坐标

    function getPos(e) {
        const canvas = document.getElementById('editorCanvas');
        if (!canvas || !editorReady) return null;
        const rect = canvas.getBoundingClientRect();
        const src = e.touches ? e.touches[0] : e;
        return {
            x: (src.clientX - rect.left) / editorScale,
            y: (src.clientY - rect.top) / editorScale,
        };
    }

    // 在蒙版 (ox,oy) 处画一个圆
    function stamp(ox, oy) {
        const val = editorTool === 'erase' ? 0 : 255;
        const r = editorBrushSize;
        const w = editorMaskData.width, h = editorMaskData.height;
        const m = editorMaskData.data;
        const r2 = r * r;
        for (let dy = -r; dy <= r; dy++) {
            const py = oy + dy;
            if (py < 0 || py >= h) continue;
            const dy2 = dy * dy;
            const row = py * w * 4;
            for (let dx = -r; dx <= r; dx++) {
                if (dx * dx + dy2 > r2) continue;
                const px = ox + dx;
                if (px < 0 || px >= w) continue;
                m[row + px * 4] = val;
                m[row + px * 4 + 1] = val;
                m[row + px * 4 + 2] = val;
            }
        }
    }

    // 从 (x0,y0) 到 (x1,y1) 沿线段每隔 r/2 画一个 stamp，形成连续笔触
    function stroke(x0, y0, x1, y1) {
        const dx = x1 - x0, dy = y1 - y0;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const step = Math.max(1, editorBrushSize * 0.4);
        const steps = Math.max(1, Math.ceil(dist / step));
        for (let i = 0; i <= steps; i++) {
            const t = i / steps;
            stamp(Math.round(x0 + dx * t), Math.round(y0 + dy * t));
        }
    }

    function onDown(e) {
        if (!editorReady || !editorMaskData) return;
        e.preventDefault();
        isDrawing = true;
        const p = getPos(e);
        if (!p) return;
        lastX = Math.round(p.x);
        lastY = Math.round(p.y);
        stamp(lastX, lastY);
        showMaskView();
    }

    function onMove(e) {
        if (!isDrawing || !editorReady || !editorMaskData) return;
        e.preventDefault();
        const p = getPos(e);
        if (!p) return;
        const cx = Math.round(p.x), cy = Math.round(p.y);
        if (lastX >= 0) {
            stroke(lastX, lastY, cx, cy);
        } else {
            stamp(cx, cy);
        }
        lastX = cx;
        lastY = cy;
        showMaskView();
    }

    function onUp() {
        if (isDrawing) {
            isDrawing = false;
            lastX = lastY = -1;
            saveEditorState();
        }
    }

    wrap.addEventListener('mousedown', onDown);
    wrap.addEventListener('mousemove', onMove);
    wrap.addEventListener('mouseup', onUp);
    wrap.addEventListener('mouseleave', onUp);
    wrap.addEventListener('touchstart', onDown, { passive: false });
    wrap.addEventListener('touchmove', onMove, { passive: false });
    wrap.addEventListener('touchend', onUp);

    // 鼠标滚轮缩放
    wrap.addEventListener('wheel', function(e) {
        if (!editorReady) return;
        e.preventDefault();
        if (e.deltaY < 0) {
            editorZoom = Math.min(5, editorZoom * 1.1);
        } else {
            editorZoom = Math.max(0.2, editorZoom / 1.1);
        }
        applyEditorZoom();
    }, { passive: false });
})();

function closeEditor() {
    document.getElementById('editorOverlay').classList.add('hidden');
    editorReady = false;
    editorImageId = null;
    editorCutoutImg = null;
    editorMaskData = null;
    editorHistory = [];
    editorZoom = 1;
    if (editorCanvas) {
        editorCanvas.style.width = '';
        editorCanvas.style.height = '';
    }
}

async function saveMask() {
    if (!editorImageId || !editorMaskData) return;

    const tmpC = document.createElement('canvas');
    tmpC.width = editorMaskData.width;
    tmpC.height = editorMaskData.height;
    tmpC.getContext('2d').putImageData(editorMaskData, 0, 0);
    const blob = await new Promise(resolve => tmpC.toBlob(resolve, 'image/png'));

    const form = collectConfig();
    form.append('mask', blob, 'mask.png');

    try {
        const res = await fetch(`${API}/api/edit-mask/${editorImageId}`, { method: 'POST', body: form });
        const data = await res.json();
        if (data.ok) {
            // 创建新的结果卡片，而不是覆盖原有卡片
            const meta = uploadedImages.find(i => i.id === editorImageId);
            const grid = document.getElementById('resultGrid');
            const newCard = document.createElement('div');
            newCard.className = 'result-card';
            newCard.id = `result-${editorImageId}-edit-${Date.now()}`;
            newCard.innerHTML = `
                <div class="preview-row">
                    <div class="before">
                        <img src="${API}${meta ? meta.thumbnail_url : ''}" onerror="this.style.display='none'">
                        <span class="label">原图</span>
                    </div>
                    <div class="after">
                        <img src="${API}${data.thumbnail_url}?t=${Date.now()}" onerror="this.style.display='none'">
                        <span class="label">已编辑</span>
                    </div>
                </div>
                <div class="meta">
                    <span class="filename">${meta ? meta.filename : ''}</span>
                    <span class="size">${(data.output_size / 1024).toFixed(1)} KB</span>
                </div>
                <div class="actions">
                    <a class="btn btn-primary btn-sm" href="${API}${data.output_url}" download>下载</a>
                    <button class="btn btn-outline btn-sm" onclick="showPreview('${editorImageId}', '${API}${data.output_url}', '${meta ? meta.filename : ''}')">预览</button>
                    <button class="btn btn-outline btn-sm" onclick="openEditor('${editorImageId}')">再次编辑</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteResult('${newCard.id}')">删除</button>
                </div>
            `;
            grid.appendChild(newCard);
            closeEditor();
        } else {
            alert('保存失败');
        }
    } catch (err) {
        alert('保存出错: ' + err.message);
    }
}

// ─── 预览弹窗 ───

function showPreview(imageId, processedSrc, filename) {
    document.getElementById('previewOriginal').src = `${API}/api/original/${imageId}`;
    document.getElementById('previewProcessed').src = processedSrc;
    const dlBtn = document.getElementById('previewDownloadBtn');
    dlBtn.href = processedSrc;
    dlBtn.download = filename || 'image';
    document.getElementById('previewOverlay').classList.remove('hidden');
}

function closePreview() {
    document.getElementById('previewOverlay').classList.add('hidden');
    document.getElementById('previewOriginal').src = '';
    document.getElementById('previewProcessed').src = '';
}

// ─── Settings Modal ───

function openSettings() {
    document.getElementById('settingThreads').value = localStorage.getItem('settingThreads') || 0;
    document.getElementById('settingDisableArena').checked = localStorage.getItem('settingDisableArena') !== 'false';
    document.getElementById('settingsOverlay').classList.remove('hidden');
}

function closeSettings() {
    document.getElementById('settingsOverlay').classList.add('hidden');
}

function saveSettings() {
    const threads = document.getElementById('settingThreads').value;
    const disableArena = document.getElementById('settingDisableArena').checked;
    localStorage.setItem('settingThreads', threads);
    localStorage.setItem('settingDisableArena', disableArena);
    fetch(`${API}/api/config/settings`, {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: new URLSearchParams({threads, disable_arena: disableArena}),
    });
    closeSettings();
}

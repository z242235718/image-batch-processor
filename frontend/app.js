const API = '';
let uploadedImages = [];
let currentBatchId = null;
let ws = null;
let currentFeatures = [];

// ─── Cutout Editor State ───
let cutoutEditor = {
    imageId: null,
    canvas: null,
    ctx: null,
    maskCanvas: null,    // offscreen mask canvas (same size as image)
    maskCtx: null,
    cutoutImg: null,     // loaded cutout PNG Image object
    zoom: 1,
    brushSize: 30,
    brushMode: 'restore', // 'restore' or 'erase'
    isDrawing: false,
    ready: false,
    lastX: -1,
    lastY: -1,
};

// ─── Cutout Editor Functions ───

function openCutoutEditor(imageId) {
    cutoutEditor.imageId = imageId;
    cutoutEditor.zoom = 1;
    cutoutEditor.isDrawing = false;
    cutoutEditor.ready = false;
    cutoutEditor.lastX = -1;
    cutoutEditor.lastY = -1;
    cutoutEditor.brushSize = parseInt(document.getElementById('cutoutBrushSize').value) || 40;

    // Reset toolbar UI
    document.querySelectorAll('.brush-mode-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('.brush-mode-btn[data-mode="restore"]')?.classList.add('active');
    document.getElementById('cutoutEditorZoomVal').textContent = '100%';

    // Show modal with loading spinner
    document.getElementById('cutoutLoading').classList.remove('hidden');
    document.getElementById('cutoutEditorOverlay').classList.remove('hidden');

    const img = new Image();
    img.onload = () => {
        cutoutEditor.cutoutImg = img;
        initCutoutEditorCanvas();
        document.getElementById('cutoutLoading').classList.add('hidden');
    };
    img.onerror = () => {
        document.getElementById('cutoutLoading').classList.add('hidden');
        alert('加载抠图结果失败，请先进行抠图处理');
        closeCutoutEditor();
    };
    img.src = `${API}/api/cutout/${imageId}?t=${Date.now()}`;
}

function closeCutoutEditor() {
    document.getElementById('cutoutEditorOverlay').classList.add('hidden');
    cutoutEditor.ready = false;
    cutoutEditor.imageId = null;
    cutoutEditor.cutoutImg = null;
    cutoutEditor.canvas = null;
    cutoutEditor.ctx = null;
    cutoutEditor.maskCanvas = null;
    cutoutEditor.maskCtx = null;
    // Hide custom brush cursor (appended to document.body)
    if (cutoutEditor._cursor) {
        cutoutEditor._cursor.style.display = 'none';
    }
}

function setCutoutBrushMode(mode) {
    cutoutEditor.brushMode = mode;
    document.querySelectorAll('.brush-mode-btn').forEach(b => b.classList.remove('active'));
    document.querySelector(`.brush-mode-btn[data-mode="${mode}"]`)?.classList.add('active');
    // Update cursor style if it exists (cursor is appended to document.body)
    const fillEl = document.querySelector('[data-brush-fill]');
    const ringEl = document.querySelector('[data-brush-ring]');
    if (fillEl && ringEl) {
        const isErase = mode === 'erase';
        ringEl.style.border = isErase ? '2px solid rgba(220,50,50,0.9)' : '2px solid rgba(50,180,50,0.9)';
        fillEl.style.background = isErase ? 'rgba(220,50,50,0.12)' : 'rgba(50,180,50,0.12)';
        fillEl.style.border = isErase ? '1px solid rgba(220,50,50,0.25)' : '1px solid rgba(50,180,50,0.25)';
    }
}

function zoomInCutoutEditor() {
    if (!cutoutEditor.ready) return;
    cutoutEditor.zoom = Math.min(5, cutoutEditor.zoom * 1.2);
    applyCutoutEditorZoom();
}

function zoomOutCutoutEditor() {
    if (!cutoutEditor.ready) return;
    cutoutEditor.zoom = Math.max(0.2, cutoutEditor.zoom / 1.2);
    applyCutoutEditorZoom();
}

function applyCutoutEditorZoom() {
    const canvas = cutoutEditor.canvas;
    const img = cutoutEditor.cutoutImg;
    if (!canvas || !img) return;
    const z = cutoutEditor.zoom;
    canvas.style.width = Math.round(img.width * z) + 'px';
    canvas.style.height = Math.round(img.height * z) + 'px';
    document.getElementById('cutoutEditorZoomVal').textContent = Math.round(z * 100) + '%';
    // Keep the image centered after zoom
    requestAnimationFrame(() => adjustCutoutEditorScroll());
}

function adjustCutoutEditorScroll() {
    const wrap = document.querySelector('#cutoutEditorOverlay .editor-canvas-wrap');
    const canvas = cutoutEditor.canvas;
    if (!wrap || !canvas) return;
    // Canvas fits → center it; overflow → top-left for full scroll range
    const fits = canvas.offsetWidth <= wrap.clientWidth && canvas.offsetHeight <= wrap.clientHeight;
    wrap.style.justifyContent = '';  // reset
    wrap.style.alignItems = '';
    if (fits) {
        wrap.style.justifyContent = 'center';
        wrap.style.alignItems = 'center';
    } else {
        wrap.style.justifyContent = 'flex-start';
        wrap.style.alignItems = 'flex-start';
        wrap.scrollLeft = 0;
        wrap.scrollTop = 0;
    }
}

function initCutoutEditorCanvas() {
    const canvas = document.getElementById('cutoutEditorCanvas');
    const ctx = canvas.getContext('2d');
    cutoutEditor.canvas = canvas;
    cutoutEditor.ctx = ctx;

    const img = cutoutEditor.cutoutImg;
    canvas.width = img.width;
    canvas.height = img.height;

    // Offscreen mask canvas — filled with 127 (neutral: no change)
    const maskCanvas = document.createElement('canvas');
    maskCanvas.width = img.width;
    maskCanvas.height = img.height;
    const maskCtx = maskCanvas.getContext('2d');
    maskCtx.fillStyle = 'rgb(127, 127, 127)';
    maskCtx.fillRect(0, 0, img.width, img.height);
    cutoutEditor.maskCanvas = maskCanvas;
    cutoutEditor.maskCtx = maskCtx;

    applyCutoutEditorZoom();
    renderCutoutEditor();
    requestAnimationFrame(() => adjustCutoutEditorScroll());
    cutoutEditor.ready = true;

    // Setup events once
    if (!canvas._cutoutEvents) {
        canvas._cutoutEvents = true;
        setupCutoutEditorEvents();
    }
}

function renderCutoutEditor() {
    const ctx = cutoutEditor.ctx;
    const img = cutoutEditor.cutoutImg;
    const canvas = cutoutEditor.canvas;
    if (!ctx || !img) return;

    // 1. Checkerboard background (shows through transparent areas)
    drawCheckerboard(ctx, 0, 0, canvas.width, canvas.height);

    // 2. Cutout image with mask composited into alpha channel
    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = canvas.width;
    tempCanvas.height = canvas.height;
    const tempCtx = tempCanvas.getContext('2d');
    tempCtx.drawImage(img, 0, 0);

    const imgData = tempCtx.getImageData(0, 0, canvas.width, canvas.height);
    const maskData = cutoutEditor.maskCtx.getImageData(0, 0, canvas.width, canvas.height);

    for (let i = 3; i < imgData.data.length; i += 4) {
        const m = maskData.data[i - 3]; // R channel of grayscale mask
        if (m === 0) {
            imgData.data[i] = 0;         // erase → transparent
        } else if (m === 255) {
            imgData.data[i] = 255;       // restore → opaque
        }
        // 127 → keep original alpha
    }
    tempCtx.putImageData(imgData, 0, 0);
    ctx.drawImage(tempCanvas, 0, 0);
}

function setupCutoutEditorEvents() {
    const canvas = cutoutEditor.canvas;
    const wrap = canvas.parentElement;

    // Floating brush cursor — visible ring + semi-transparent fill + crosshair
    const cursor = document.createElement('div');
    cursor.style.cssText = 'position:fixed;pointer-events:none;border-radius:50%;display:none;z-index:1000;transform:translate(-50%,-50%)';
    // Outer ring element
    const ring = document.createElement('div');
    ring.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;border-radius:50%;box-sizing:border-box;pointer-events:none';
    ring.setAttribute('data-brush-ring', '');
    cursor.appendChild(ring);
    // Fill element (inner semi-transparent overlay)
    const fill = document.createElement('div');
    fill.style.cssText = 'position:absolute;top:2px;left:2px;width:calc(100% - 4px);height:calc(100% - 4px);border-radius:50%;box-sizing:border-box;pointer-events:none;transition:opacity 0.05s';
    fill.setAttribute('data-brush-fill', '');
    cursor.appendChild(fill);
    // Crosshair center
    const crosshair = document.createElement('div');
    crosshair.style.cssText = 'position:absolute;top:50%;left:50%;width:9px;height:9px;transform:translate(-50%,-50%);pointer-events:none';
    crosshair.innerHTML = '<svg viewBox="0 0 9 9" width="9" height="9"><circle cx="4.5" cy="4.5" r="1.5" fill="#fff" stroke="#333" stroke-width="0.8"/><line x1="4.5" y1="0" x2="4.5" y2="9" stroke="#fff" stroke-width="1" opacity="0.7"/><line x1="0" y1="4.5" x2="9" y2="4.5" stroke="#fff" stroke-width="1" opacity="0.7"/></svg>';
    cursor.appendChild(crosshair);
    document.body.appendChild(cursor);
    cutoutEditor._cursor = cursor;

    function updateCursorStyle() {
        const isErase = cutoutEditor.brushMode === 'erase';
        if (isErase) {
            ring.style.border = '2px solid rgba(220,50,50,0.9)';
            fill.style.background = 'rgba(220,50,50,0.12)';
            fill.style.border = '1px solid rgba(220,50,50,0.25)';
        } else {
            ring.style.border = '2px solid rgba(50,180,50,0.9)';
            fill.style.background = 'rgba(50,180,50,0.12)';
            fill.style.border = '1px solid rgba(50,180,50,0.25)';
        }
    }
    updateCursorStyle();

    function getPos(e) {
        const rect = canvas.getBoundingClientRect();
        const cx = e.touches ? e.touches[0].clientX : e.clientX;
        const cy = e.touches ? e.touches[0].clientY : e.clientY;
        return {
            x: Math.round((cx - rect.left) * (canvas.width / rect.width)),
            y: Math.round((cy - rect.top) * (canvas.height / rect.height)),
        };
    }

    function startDraw(e) {
        e.preventDefault();
        if (!cutoutEditor.ready) return;
        cutoutEditor.isDrawing = true;
        const pos = getPos(e);
        cutoutEditor.lastX = pos.x;
        cutoutEditor.lastY = pos.y;
        // Make fill more visible while drawing
        fill.style.opacity = '0.5';
        paintAt(pos.x, pos.y);
    }

    function moveDraw(e) {
        e.preventDefault();
        if (!cutoutEditor.ready) return;
        const pos = getPos(e);
        // Update cursor ring size to account for zoom
        const scale = canvas.getBoundingClientRect().width / canvas.width;
        const bs = Math.round(cutoutEditor.brushSize * scale);
        const outerSize = bs + 8;
        cursor.style.width = outerSize + 'px';
        cursor.style.height = outerSize + 'px';
        cursor.style.left = (e.touches ? e.touches[0].clientX : e.clientX) + 'px';
        cursor.style.top = (e.touches ? e.touches[0].clientY : e.clientY) + 'px';
        cursor.style.display = 'block';

        if (cutoutEditor.isDrawing) {
            paintLine(cutoutEditor.lastX, cutoutEditor.lastY, pos.x, pos.y);
            cutoutEditor.lastX = pos.x;
            cutoutEditor.lastY = pos.y;
        }
    }

    function endDraw(e) {
        if (!cutoutEditor.isDrawing) return;
        cutoutEditor.isDrawing = false;
        cutoutEditor.lastX = -1;
        cutoutEditor.lastY = -1;
        fill.style.opacity = '';
        cursor.style.display = 'none';
        // Full re-render to ensure perfect accumulation
        renderCutoutEditor();
    }

    wrap.addEventListener('mousedown', startDraw);
    window.addEventListener('mousemove', moveDraw);
    window.addEventListener('mouseup', endDraw);
    wrap.addEventListener('touchstart', startDraw, { passive: false });
    window.addEventListener('touchmove', moveDraw, { passive: false });
    window.addEventListener('touchend', endDraw);

    // Wheel zoom
    wrap.addEventListener('wheel', (e) => {
        e.preventDefault();
        if (!cutoutEditor.ready) return;
        cutoutEditor.zoom = e.deltaY < 0
            ? Math.min(5, cutoutEditor.zoom * 1.1)
            : Math.max(0.2, cutoutEditor.zoom / 1.1);
        applyCutoutEditorZoom();
        renderCutoutEditor();
    }, { passive: false });

    // Hide cursor when leaving canvas
    wrap.addEventListener('mouseleave', () => {
        cursor.style.display = 'none';
        if (cutoutEditor.isDrawing) {
            cutoutEditor.isDrawing = false;
            renderCutoutEditor();
        }
    });
}

function paintAt(x, y) {
    const maskCtx = cutoutEditor.maskCtx;
    const bs = cutoutEditor.brushSize;
    const isRestore = cutoutEditor.brushMode === 'restore';
    const c = isRestore ? 255 : 0;
    maskCtx.fillStyle = `rgb(${c},${c},${c})`;
    maskCtx.beginPath();
    maskCtx.arc(x, y, bs / 2, 0, Math.PI * 2);
    maskCtx.fill();

    // Real-time effect: composite the brush bounding box
    const r = bs / 2;
    const img = cutoutEditor.cutoutImg;
    const sx = Math.max(0, x - r);
    const sy = Math.max(0, y - r);
    const sw = Math.min(img.width - sx, r * 2);
    const sh = Math.min(img.height - sy, r * 2);
    if (sw > 0 && sh > 0) applyCutoutBrushRegion(sx, sy, sw, sh);
}

function paintLine(x1, y1, x2, y2) {
    const maskCtx = cutoutEditor.maskCtx;
    const bs = cutoutEditor.brushSize;
    const isRestore = cutoutEditor.brushMode === 'restore';
    const c = isRestore ? 255 : 0;
    maskCtx.strokeStyle = `rgb(${c},${c},${c})`;
    maskCtx.lineWidth = bs;
    maskCtx.lineCap = 'round';
    maskCtx.lineJoin = 'round';
    maskCtx.beginPath();
    maskCtx.moveTo(x1, y1);
    maskCtx.lineTo(x2, y2);
    maskCtx.stroke();

    // Real-time effect: composite the bounding box of the entire line segment ONCE
    // (the full stroke is already on the mask canvas above)
    const r = bs / 2;
    const img = cutoutEditor.cutoutImg;
    const sx = Math.max(0, Math.min(x1, x2) - r);
    const sy = Math.max(0, Math.min(y1, y2) - r);
    const ex = Math.min(img.width, Math.max(x1, x2) + r);
    const ey = Math.min(img.height, Math.max(y1, y2) + r);
    const sw = ex - sx;
    const sh = ey - sy;
    if (sw > 0 && sh > 0) applyCutoutBrushRegion(sx, sy, sw, sh);
}

/**
 * Real-time brush region composite: renders checkerboard + cutout-with-mask
 * for the given bounding box (sx, sy, sw, sh) on the display canvas.
 * Uses direct pixel blending to avoid any GPU/drawImage alpha premultiplication issues.
 */
function applyCutoutBrushRegion(sx, sy, sw, sh) {
    const ctx = cutoutEditor.ctx;
    const img = cutoutEditor.cutoutImg;
    const maskCtx = cutoutEditor.maskCtx;

    // 1. Read cutout image pixels for this region via a temp canvas
    const tc = document.createElement('canvas');
    tc.width = sw;
    tc.height = sh;
    const tctx = tc.getContext('2d');
    tctx.drawImage(img, sx, sy, sw, sh, 0, 0, sw, sh);
    const imgData = tctx.getImageData(0, 0, sw, sh);

    // 2. Read mask data for this region
    const maskData = maskCtx.getImageData(sx, sy, sw, sh);

    // 3. Draw fresh checkerboard directly on the display canvas at this region
    drawCheckerboard(ctx, sx, sy, sw, sh);

    // 4. Read back the checkerboard pixels (now in the display canvas)
    const cbData = ctx.getImageData(sx, sy, sw, sh);

    // 5. Manually blend cutout pixels onto checkerboard based on mask-modified alpha
    const d = imgData.data;
    const cb = cbData.data;
    const mk = maskData.data;
    for (let i = 0; i < d.length; i += 4) {
        const m = mk[i]; // R channel of grayscale mask
        let srcAlpha;
        if (m === 0) {
            srcAlpha = 0;        // erase → fully transparent
        } else if (m === 255) {
            srcAlpha = 255;      // restore → fully opaque
        } else {
            srcAlpha = d[i + 3]; // keep original cutout alpha
        }
        // Blend: result = src * a + dst * (1 - a)
        const a = srcAlpha / 255;
        const ia = 1 - a;
        cb[i]     = Math.round(d[i]     * a + cb[i]     * ia);
        cb[i + 1] = Math.round(d[i + 1] * a + cb[i + 1] * ia);
        cb[i + 2] = Math.round(d[i + 2] * a + cb[i + 2] * ia);
        cb[i + 3] = 255; // always opaque for display
    }

    // 6. Write blended result directly to the display canvas
    ctx.putImageData(cbData, sx, sy);
}

async function saveCutoutEdit() {
    if (!cutoutEditor.imageId || !cutoutEditor.maskCanvas) return;

    const btn = document.querySelector('#cutoutEditorOverlay .btn-primary');
    if (btn) btn.disabled = true;

    try {
        const maskBlob = await new Promise(resolve => cutoutEditor.maskCanvas.toBlob(resolve, 'image/png'));
        if (!maskBlob) { alert('生成蒙版失败'); return; }

        const form = collectConfig();
        form.append('mask', maskBlob, 'mask.png');

        const res = await fetch(`${API}/api/edit-cutout/${cutoutEditor.imageId}`, { method: 'POST', body: form });
        const data = await res.json();

        if (data.ok) {
            // Append result card
            const grid = document.getElementById('resultGrid');
            const cardId = `result-${cutoutEditor.imageId}-cutout-${Date.now()}`;
            const features = collectFeatures();
            const hasBg = features.includes('bg');
            const card = document.createElement('div');
            card.className = 'result-card';
            card.id = cardId;
            card.dataset.imageId = cutoutEditor.imageId;
            card.dataset.features = features.join(',');
            card.innerHTML = `
                <div class="preview-row">
                    <div class="before">
                        <img src="${API}/api/cutout/${cutoutEditor.imageId}?t=${Date.now()}" onerror="this.style.display='none'">
                        <span class="label">编辑前</span>
                    </div>
                    <div class="after">
                        <img src="${API}${data.thumbnail_url}?t=${Date.now()}" onerror="this.style.display='none'">
                        <span class="label">已编辑</span>
                    </div>
                </div>
                <div class="meta">
                    <span class="filename">${cutoutEditor.imageId}_cutout.png</span>
                    <span class="size">${(data.output_size / 1024 / 1024).toFixed(2)} MB</span>
                </div>
                <div class="actions">
                    <a class="btn btn-primary btn-sm" href="${API}${data.output_url}" download>下载</a>
                    <button class="btn btn-outline btn-sm" onclick="showPreview('${cutoutEditor.imageId}', '${API}${data.output_url}', '${cutoutEditor.imageId}_cutout.png')">预览</button>
                    ${hasBg ? `<button class="btn btn-outline btn-sm" onclick="openCutoutEditor('${cutoutEditor.imageId}')">修改抠图</button>` : ''}
                    <button class="btn btn-outline btn-sm" onclick="openEditor('${cutoutEditor.imageId}')">裁切</button>
                    <button class="btn btn-outline btn-sm" onclick="openReprocess('${data.run_id}', '${cutoutEditor.imageId}', '${features.join(',')}')">继续处理</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteResult('${cardId}')">删除</button>
                </div>
            `;
            grid.appendChild(card);
            resultPage = Math.ceil((grid.querySelectorAll('.result-card').length) / resultPerPage);
            applyPagination();
            closeCutoutEditor();
        } else {
            alert('保存失败: ' + (data.detail || '未知错误'));
        }
    } catch (err) {
        alert('保存出错: ' + err.message);
    } finally {
        if (btn) btn.disabled = false;
    }
}

// ─── Pagination ───
let resultPage = 1;
let resultPerPage = 20;
let resultTotalPages = 0;

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
    const maskBtn = document.getElementById('openMaskCropBtn');
    if (maskBtn) maskBtn.disabled = uploadedImages.length === 0;
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

// ─── 水印模式联动 ───

document.getElementById('wmMode').addEventListener('change', updateWmModeUI);
updateWmModeUI();

function updateWmModeUI() {
    const mode = document.getElementById('wmMode').value;
    document.getElementById('wmPositionRow').classList.toggle('hidden', mode !== 'position');
    document.getElementById('wmDirectionRow').classList.toggle('hidden', mode === 'position');
    document.getElementById('wmDenseRow').classList.toggle('hidden', mode !== 'dense');
    document.getElementById('wmFontRow').classList.toggle('hidden', mode === 'dense');
}

document.getElementById('reprocessWmMode').addEventListener('change', updateReprocessWmModeUI);

function updateReprocessWmModeUI() {
    const mode = document.getElementById('reprocessWmMode').value;
    const dirRow = document.getElementById('reprocessWmDirectionRow');
    const denseRow = document.getElementById('reprocessWmDenseRow');
    if (dirRow) dirRow.classList.toggle('hidden', mode === 'position');
    if (denseRow) denseRow.classList.toggle('hidden', mode !== 'dense');
}

// ─── 调色板 ───

function _updatePickerBtn(selectId, color) {
    const upper = color.toUpperCase();
    const isPreset = upper === '#CCCCCC' || upper === '#666666' || upper === '#FFFFFF' || upper === '#000000';
    const pickerBtn = document.getElementById(selectId + 'PickerBtn');
    if (!pickerBtn) return;
    if (isPreset) {
        // 选中的是预设色块 → 恢复彩虹渐变
        pickerBtn.classList.remove('active');
        pickerBtn.style.background = '';
    } else {
        // 自定义颜色 → 显示该颜色
        pickerBtn.classList.add('active');
        pickerBtn.style.background = color;
    }
    // 同步原生取色器 value（用于下次打开时定位到该颜色）
    const picker = document.getElementById(selectId + 'Picker');
    if (picker) picker.value = color;
}

function selectPaletteColor(el, selectId) {
    const color = el.dataset.color || el.value;
    document.getElementById(selectId).value = color;
    // 更新色块选中态
    const paletteWrap = document.getElementById(selectId).closest('.color-palette-wrap');
    if (paletteWrap) {
        paletteWrap.querySelectorAll('.color-swatch').forEach(s => s.classList.toggle('active', s.dataset.color === color));
    }
    // 更新取色器按钮
    _updatePickerBtn(selectId, color);
}

function syncPaletteFromSelect(selectId) {
    const val = document.getElementById(selectId).value;
    // 更新色块选中态
    const paletteWrap = document.getElementById(selectId).closest('.color-palette-wrap');
    if (paletteWrap) {
        paletteWrap.querySelectorAll('.color-swatch').forEach(s => s.classList.toggle('active', s.dataset.color === val));
    }
    // 更新取色器按钮
    _updatePickerBtn(selectId, val);
}

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

function updatePositionUI() {
    const grid = document.getElementById('positionGrid');
    grid.querySelectorAll('button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.pos === selectedPosition);
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

// Reprocess 抠图方式切换
document.getElementById('reprocessBgMethod')?.addEventListener('change', e => {
    const isApi = e.target.value === 'api';
    document.getElementById('reprocessApiKeyRow').classList.toggle('hidden', !isApi);
});

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

// Logo 上传拖拽
const logoDropZone = document.getElementById('logoDropZone');
const logoFileInput = document.getElementById('logoFileInput');
if (logoDropZone) {
    logoDropZone.addEventListener('click', () => logoFileInput.click());
    logoDropZone.addEventListener('dragover', e => { e.preventDefault(); logoDropZone.classList.add('dragover'); });
    logoDropZone.addEventListener('dragleave', () => logoDropZone.classList.remove('dragover'));
    logoDropZone.addEventListener('drop', e => {
        e.preventDefault();
        logoDropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) handleLogoUpload(e.dataTransfer.files);
    });
}

// 设置面板 Logo 上传拖拽
const settingLogoDropZone = document.getElementById('settingLogoDropZone');
const settingLogoFileInput = document.getElementById('settingLogoFile');
if (settingLogoDropZone) {
    settingLogoDropZone.addEventListener('click', () => settingLogoFileInput.click());
    settingLogoDropZone.addEventListener('dragover', e => { e.preventDefault(); settingLogoDropZone.classList.add('dragover'); });
    settingLogoDropZone.addEventListener('dragleave', () => settingLogoDropZone.classList.remove('dragover'));
    settingLogoDropZone.addEventListener('drop', e => {
        e.preventDefault();
        settingLogoDropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) handleSettingLogoUpload(e.dataTransfer.files);
    });
}

document.getElementById('logoMode').addEventListener('change', e => {
    updateLogoPreview();
});

let defaultLogoConfig = { position: 'right-bottom', ratio: 0.15, opacity: 0.8 };

// 初始化默认 Logo 预览
async function initLogoPreview() {
    // 加载默认 Logo 配置
    try {
        const res = await fetch(`${API}/api/config/default-logo`);
        if (res.ok) {
            defaultLogoConfig = await res.json();
        }
    } catch (e) {}

    updateLogoPreview();
}

function updateLogoPreview() {
    const mode = document.getElementById('logoMode').value;
    const preview = document.getElementById('logoPreview');
    const hint = document.getElementById('defaultLogoHint');
    if (mode === 'default') {
        document.getElementById('logoUploadGroup').classList.add('hidden');
        preview.innerHTML = `<img src="${API}/api/logo-default?v=${Date.now()}">`;
        selectedPosition = defaultLogoConfig.position;
        document.getElementById('logoRatio').value = Math.round(defaultLogoConfig.ratio * 100);
        document.getElementById('logoRatioVal').textContent = Math.round(defaultLogoConfig.ratio * 100) + '%';
        document.getElementById('logoOpacity').value = Math.round(defaultLogoConfig.opacity * 100);
        document.getElementById('logoOpacityVal').textContent = Math.round(defaultLogoConfig.opacity * 100) + '%';
        document.getElementById('logoMargin').value = defaultLogoConfig.margin || 20;
        document.getElementById('logoMarginVal').textContent = (defaultLogoConfig.margin || 20) + 'px';
        if (hint) hint.classList.remove('hidden');
        updatePositionUI();
    } else {
        document.getElementById('logoUploadGroup').classList.remove('hidden');
        if (hint) hint.classList.add('hidden');
        if (logoFileId) {
            preview.innerHTML = `<img src="${API}/api/thumbnail/${logoFileId}">`;
        } else {
            preview.innerHTML = `<span class="placeholder">+</span>`;
        }
    }
}

// 页面加载时初始化
window.addEventListener('load', initLogoPreview);

// ─── Range slider ───

document.querySelectorAll('input[type="range"]').forEach(input => {
    const display = input.parentElement.querySelector('.value, .value-input');
    if (display) {
        input.addEventListener('input', () => {
            const suffix = display.id.includes('Margin') ? 'px' : (display.id.includes('Ratio') || display.id.includes('Opacity') || display.id.includes('quality') || display.id.includes('settingLogo') ? '%' : '');
            if (display.tagName === 'INPUT') {
                display.value = input.value + suffix;
            } else {
                display.textContent = input.value + suffix;
            }
        });
    }
});

// 可编辑数值输入 → 滑块同步
document.querySelectorAll('.value-input').forEach(input => {
    input.addEventListener('input', () => {
        const raw = input.value.replace(/[^\d.]/g, '');
        const num = parseFloat(raw);
        if (isNaN(num)) return;
        const sliderId = input.id.replace('Val', '');
        const slider = document.getElementById(sliderId);
        if (!slider) return;
        const clamped = Math.min(Math.max(num, parseInt(slider.min)), parseInt(slider.max));
        slider.value = clamped;
        input.value = clamped;
    });
    input.addEventListener('blur', () => {
        const sliderId = input.id.replace('Val', '');
        const slider = document.getElementById(sliderId);
        if (!slider) return;
        input.value = slider.value;
    });
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
    form.append('logo_margin', parseInt(document.getElementById('logoMargin').value) || 20);
    form.append('logo_tile', document.getElementById('logoTile').checked);
    if (logoMode === 'image' && logoFileId) {
        form.append('logo_file_id', logoFileId);
    }
    form.append('wm_mode', document.getElementById('enableWatermark').checked ? document.getElementById('wmMode').value : 'off');
    form.append('wm_text', document.getElementById('wmText').value);
    form.append('wm_text_color', document.getElementById('wmTextColor').value);
    form.append('wm_text_ratio', parseInt(document.getElementById('wmTextRatio').value) / 100);
    form.append('wm_opacity', parseInt(document.getElementById('wmOpacity').value) / 100);
    form.append('wm_position', selectedWmPosition);
    form.append('wm_tile_direction', document.getElementById('wmTileDirection').value);
    form.append('wm_dense_density', parseInt(document.getElementById('wmDenseDensity').value));
    // [DISABLED: 盲水印暂屏蔽] 强制不上传盲水印相关参数
    form.append('wm_blind_enabled', false);
    form.append('wm_blind_text', '');
    form.append('wm_blind_strength', 16);
    form.append('wm_blind_use_mask', false);
    /* 原代码（已禁用）
    form.append('wm_blind_enabled', document.getElementById('enableBlindWatermark').checked);
    form.append('wm_blind_text', document.getElementById('wmBlindText').value);
    form.append('wm_blind_strength', parseInt(document.getElementById('wmBlindStrength').value) || 16);
    form.append('wm_blind_use_mask', document.getElementById('wmBlindUseMask').checked);
    */
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
    // 蒙版由 openMaskCropFrom* 入口直接附加 mask 文件，无需在 collectConfig 中处理
    return form;
}

function collectFeatures() {
    const features = [];
    if (document.getElementById('enableBgRemoval').checked) features.push('bg');
    if (document.getElementById('enableLogo').checked) features.push('logo');
    if (document.getElementById('enableWatermark').checked) features.push('watermark');
    // if (document.getElementById('enableBlindWatermark').checked) features.push('blind');  // [DISABLED: 盲水印暂屏蔽]
    if (document.getElementById('enableCompress').checked) features.push('compress');
    return features;
}

// ─── Process ───

async function startProcess() {
    const btn = document.getElementById('processBtn');
    if (uploadedImages.length === 0) {
        alert('请先上传图片');
        return;
    }
    btn.disabled = true;
    btn.textContent = '处理中...';
    currentFeatures = collectFeatures();

    try {
        const form = collectConfig();
        // 告诉后端只处理当前上传的图片，避免处理已删除的旧图片
        form.append('image_ids', uploadedImages.map(i => i.id).join(','));
        const res = await fetch(`${API}/api/process`, { method: 'POST', body: form });
        const data = await res.json();

        if (!res.ok) {
            // 后端拒绝（如重启后旧图片 ID 失效），清除本地状态让用户重新上传
            uploadedImages = [];
            document.getElementById('fileList').innerHTML = '';
            document.getElementById('imageCount').textContent = '0 张图片';
            document.getElementById('processBtn').disabled = true;
            const maskBtn = document.getElementById('openMaskCropBtn');
            if (maskBtn) maskBtn.disabled = true;
            alert(data.detail || '图片已失效，请重新上传');
            btn.disabled = false;
            btn.textContent = '开始处理';
            return;
        }

        // 只保留后端确认有效的图片 ID（重启后部分 ID 可能已失效）
        if (data.image_ids) {
            uploadedImages = uploadedImages.filter(i => data.image_ids.includes(i.id));
            renderImages();
        }

        currentBatchId = data.batch_id;
        document.getElementById('progressPanel').classList.remove('hidden');
        // 重置进度显示，避免旧批次数据残留
        document.getElementById('progressText').textContent = '准备中...';
        document.getElementById('progressPercent').textContent = '0%';
        document.getElementById('progressFill').style.width = '0%';
        document.getElementById('progressFill').classList.remove('done');
        // 清除前一批次中残留的处理中卡片（保留已完成的结果）
        document.querySelectorAll('#resultGrid .result-card .status-processing').forEach(el => {
            const card = el.closest('.result-card');
            if (card) card.remove();
        });
        document.getElementById('resultPagination').innerHTML = '';
        document.getElementById('resultPagination').classList.add('hidden');
        initResultCards(data.batch_id);
        connectWebSocket(data.batch_id);
    } catch (err) {
        alert('启动处理失败: ' + err.message);
        btn.disabled = false;
        btn.textContent = '开始处理';
    }
}

function initResultCards(batchId) {
    const grid = document.getElementById('resultGrid');
    uploadedImages.forEach(img => {
        const cardId = `result-${batchId}-${img.id}`;
        if (document.getElementById(cardId)) return;
        const card = document.createElement('div');
        card.className = 'result-card';
        card.id = cardId;
        card.dataset.runId = batchId;
        card.dataset.imageId = img.id;
        card.dataset.features = currentFeatures.join(',');
        card.innerHTML = `
            <div class="status-processing"><div class="spinner"></div><div class="text">处理中...</div></div>
            <div class="meta"><span class="filename">${img.filename}</span></div>
        `;
        grid.appendChild(card);
    });
    resultPage = 1;
    applyPagination();
}

// ─── WebSocket ───

function connectWebSocket(batchId) {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    // 关闭旧 WebSocket，避免旧批次消息干扰新批次
    if (ws && ws.readyState === WebSocket.OPEN || ws && ws.readyState === WebSocket.CONNECTING) {
        ws.onclose = null; // 去掉 onclose 回调，避免触发旧批次的 pollProgress
        ws.close();
    }
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
    // 已完成数 = 总完成数 - 失败数（后端 done 包含 error 状态）
    const successCount = Math.max(0, data.done - data.failed);
    const pct = data.total > 0 ? Math.round((data.done / data.total) * 100) : 0;
    const fill = document.getElementById('progressFill');
    fill.style.width = pct + '%';
    document.getElementById('progressPercent').textContent = pct + '%';
    if (pct >= 100) fill.classList.add('done');

    document.getElementById('progressText').textContent =
        `已完成 ${successCount}/${data.total}` + (data.failed > 0 ? `，失败 ${data.failed}` : '');

    // 处理单条结果更新（WebSocket 广播）
    if (data.result) updateResultCard(data.result, pct);
    // 处理批量结果更新（初始 WS 消息或轮询降级）
    if (data.results) data.results.forEach(r => updateResultCard(r, pct));

    // 显示进度条区域（只要还没完成就显示）
    if (data.status === 'done') {
        document.getElementById('processBtn').disabled = false;
        document.getElementById('processBtn').textContent = '开始处理';
        document.getElementById('progressSection').classList.remove('hidden');
        // 完成后自动清空已上传图片，下一批从头开始（不累加）
        const _doneBatchId = data.batch_id;
        setTimeout(() => {
            if (currentBatchId !== _doneBatchId) return; // 用户已开始新一批，跳过
            uploadedImages = [];
            renderImages();
        }, 500);
    } else {
        document.getElementById('progressSection').classList.remove('hidden');
    }
}

function updateResultCard(result, itemPct) {
    // 优先用 run_id + id 查找（每批处理独立卡片），否则回退到旧格式
    const cardId = result.run_id ? `result-${result.run_id}-${result.id}` : `result-${result.id}`;
    const card = document.getElementById(cardId) || document.getElementById(`result-${result.id}`);
    if (!card) return;

    if (result.status === 'processing') {
        card.innerHTML = `
            <div class="status-processing"><div class="spinner"></div><div class="text">处理中... ${itemPct > 0 ? itemPct + '%' : ''}</div></div>
            <div class="meta"><span class="filename">${result.filename}</span></div>
        `;
    } else if (result.status === 'done') {
        const meta = uploadedImages.find(i => i.id === result.id);
        card.dataset.features = currentFeatures.join(',');
        const featuresStr = card.dataset.features;
        const features = card.dataset.features ? card.dataset.features.split(',') : [];
        const hasBg = features.includes('bg');
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
                ${hasBg ? `<button class="btn btn-outline btn-sm" onclick="openCutoutEditor('${result.id}')">修改抠图</button>` : ''}
                <button class="btn btn-outline btn-sm" onclick="openEditor('${result.id}')">裁切</button>
                <button class="btn btn-outline btn-sm" onclick="openReprocess('${result.run_id}', '${result.id}', '${featuresStr}')">继续处理</button>
                <!-- [HIDDEN: 盲水印提取功能暂屏蔽] <button class="btn btn-outline btn-sm" onclick="extractWatermarkFromResult('${result.run_id}', '${result.id}')">提取水印</button> -->
                <button class="btn btn-danger btn-sm" onclick="deleteResult('result-${result.id}')">删除</button>
            </div>
        `;
        applyPagination();
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
                <button class="btn btn-outline btn-sm" onclick="openEditor('${result.id}')">裁切</button>
                <button class="btn btn-danger btn-sm" onclick="deleteResult('result-${result.id}')">删除</button>
            </div>
        `;
    }
}

function cancelProcess() {
    const btn = document.querySelector('#progressSection .btn-danger');
    if (btn) { btn.disabled = true; btn.textContent = '取消中...'; }
    document.getElementById('progressText').textContent = '正在取消...';
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send('cancel');
    } else {
        // WebSocket 未连接时直接重置
        document.getElementById('processBtn').disabled = false;
        document.getElementById('processBtn').textContent = '开始处理';
        document.getElementById('progressSection').classList.add('hidden');
    }
}

function downloadAll() {
    const items = [];
    document.querySelectorAll('#resultGrid .result-card').forEach(card => {
        const link = card.querySelector('.actions a[download]');
        if (!link) return;
        const href = link.getAttribute('href');
        const path = href.replace(API, '');
        const match = path.match(/\/api\/download\/([^/]+)\/([^/]+)/);
        if (match) {
            items.push({ run_id: match[1], image_id: match[2] });
        }
    });
    if (!items.length) {
        alert('没有可下载的处理结果');
        return;
    }

    // Show progress modal
    const overlay = document.getElementById('downloadProgressOverlay');
    const fill = document.getElementById('downloadProgressFill');
    const text = document.getElementById('downloadProgressText');
    const detail = document.getElementById('downloadProgressDetail');
    overlay.classList.remove('hidden');
    fill.style.width = '0%';
    text.textContent = '正在打包下载...';
    detail.textContent = `共 ${items.length} 个文件，准备中...`;

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API}/api/download-all`);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.responseType = 'blob';

    xhr.onprogress = e => {
        if (e.lengthComputable) {
            const pct = Math.min(100, Math.round((e.loaded / e.total) * 100));
            fill.style.width = pct + '%';
            detail.textContent = `下载中 ${(e.loaded / 1024 / 1024).toFixed(1)} MB / ${(e.total / 1024 / 1024).toFixed(1)} MB`;
        } else {
            detail.textContent = `正在下载... ${items.length} 个文件打包中`;
        }
    };

    xhr.onload = () => {
        overlay.classList.add('hidden');
        if (xhr.status !== 200) {
            alert('下载失败: ' + (xhr.statusText || '未知错误'));
            return;
        }
        const blob = xhr.response;
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'processed_images.zip';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    };

    xhr.onerror = () => {
        overlay.classList.add('hidden');
        alert('下载失败: 网络错误');
    };

    xhr.send(JSON.stringify({ items }));
}

// ─── 继续处理 ───

let reprocessSourceId = null;
let reprocessRunId = null;

function openReprocess(runId, imageId, excludeFeatures) {
    reprocessSourceId = imageId;
    reprocessRunId = runId;

    const exclude = excludeFeatures ? excludeFeatures.split(',').filter(Boolean) : [];

    document.getElementById('reprocessPreview').innerHTML =
        `<img src="${API}/api/result-thumbnail/${runId}/${imageId}?t=${Date.now()}">`;

    // 显示所有分区，排除已处理的功能（盲水印 [DISABLED] 已从列表中移除）
    const sections = ['reprocessBg', 'reprocessLogo', 'reprocessWm', 'reprocessCompress'];
    const featureKeys = ['bg', 'logo', 'watermark', 'compress'];
    sections.forEach((id, i) => {
        const el = document.getElementById(id);
        if (el) {
            el.classList.toggle('hidden', exclude.includes(featureKeys[i]));
        }
    });

    // 抠图：初始化为未启用，从主面板复制方法/模型，API Key
    document.getElementById('reprocessBgEnabled').checked = false;
    document.getElementById('reprocessBg').classList.remove('open');
    document.getElementById('reprocessBgMethod').value = document.getElementById('bgMethod').value;
    document.getElementById('reprocessBgModel').value = document.getElementById('bgModel').value;
    document.getElementById('reprocessApiKey').value = savedApiKey || '';
    const isBgApi = document.getElementById('reprocessBgMethod').value === 'api';
    document.getElementById('reprocessApiKeyRow').classList.toggle('hidden', !isBgApi);

    // Logo：从默认配置初始化
    document.getElementById('reprocessLogoEnabled').checked = false;
    document.getElementById('reprocessLogo').classList.remove('open');
    document.getElementById('reprocessLogoPosition').value = defaultLogoConfig.position || 'right-bottom';
    document.getElementById('reprocessLogoRatio').value = Math.round((defaultLogoConfig.ratio || 0.15) * 100);
    document.getElementById('reprocessLogoRatioVal').textContent = Math.round((defaultLogoConfig.ratio || 0.15) * 100) + '%';
    document.getElementById('reprocessLogoOpacity').value = Math.round((defaultLogoConfig.opacity || 0.8) * 100);
    document.getElementById('reprocessLogoOpacityVal').textContent = Math.round((defaultLogoConfig.opacity || 0.8) * 100) + '%';
    document.getElementById('reprocessLogoMargin').value = defaultLogoConfig.margin || 20;
    document.getElementById('reprocessLogoMarginVal').textContent = (defaultLogoConfig.margin || 20) + 'px';
    document.getElementById('reprocessLogoTile').checked = false;

    // 显式水印
    document.getElementById('reprocessWmEnabled').checked = false;
    document.getElementById('reprocessWm').classList.remove('open');
    document.getElementById('reprocessWmMode').value = document.getElementById('wmMode').value;
    document.getElementById('reprocessWmText').value = document.getElementById('wmText').value || '';
    document.getElementById('reprocessWmTextColor').value = document.getElementById('wmTextColor').value;
    syncPaletteFromSelect('reprocessWmTextColor');
    document.getElementById('reprocessWmTextRatio').value = document.getElementById('wmTextRatio').value;
    document.getElementById('reprocessWmTextRatioVal').textContent = document.getElementById('wmTextRatio').value + '%';
    document.getElementById('reprocessWmOpacity').value = document.getElementById('wmOpacity').value;
    document.getElementById('reprocessWmOpacityVal').textContent = document.getElementById('wmOpacity').value + '%';
    document.getElementById('reprocessWmPosition').value = selectedWmPosition;
    document.getElementById('reprocessWmTileDirection').value = document.getElementById('wmTileDirection').value;
    document.getElementById('reprocessWmDenseDensity').value = document.getElementById('wmDenseDensity').value;
    document.getElementById('reprocessWmDenseDensityVal').textContent = document.getElementById('wmDenseDensity').value;
    updateReprocessWmModeUI();

    // 盲水印
    document.getElementById('reprocessBlindEnabled').checked = false;
    document.getElementById('reprocessBlind').classList.remove('open');
    document.getElementById('reprocessBlindText').value = document.getElementById('wmBlindText').value || '';

    // 压缩：从主面板复制设置
    document.getElementById('reprocessCompressEnabled').checked = true;
    document.getElementById('reprocessCompress').classList.add('open');
    document.getElementById('reprocessOutputFormat').value = document.getElementById('outputFormat').value;
    document.getElementById('reprocessQuality').value = document.getElementById('quality').value;
    document.getElementById('reprocessQualityVal').textContent = document.getElementById('quality').value + '%';
    document.getElementById('reprocessMaxFileSize').value = document.getElementById('maxFileSize').value;
    document.getElementById('reprocessMaxWidth').value = document.getElementById('maxWidth').value;

    document.getElementById('reprocessOverlay').classList.remove('hidden');
}

function closeReprocess() {
    document.getElementById('reprocessOverlay').classList.add('hidden');
    reprocessSourceId = null;
    reprocessRunId = null;
}

function toggleReprocessSection(id) {
    const section = document.getElementById(id);
    if (section) section.classList.toggle('open');
}

function collectReprocessFeatures() {
    const features = [];
    if (document.getElementById('reprocessBgEnabled').checked) features.push('bg');
    if (document.getElementById('reprocessLogoEnabled').checked) features.push('logo');
    if (document.getElementById('reprocessWmEnabled').checked) features.push('watermark');
    // if (document.getElementById('reprocessBlindEnabled').checked) features.push('blind');  // [DISABLED: 盲水印暂屏蔽]
    if (document.getElementById('reprocessCompressEnabled').checked) features.push('compress');
    return features;
}

async function startReprocess() {
    const form = buildReprocessForm();
    if (!form) return;  // 已 alert 过

    const btn = document.querySelector('#reprocessOverlay .modal-footer .btn-primary');
    const origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '处理中...';

    try {
        const res = await fetch(`${API}/api/reprocess`, { method: 'POST', body: form });
        const data = await res.json();
        if (data.ok) {
            appendReprocessCard(data);
            closeReprocess();
        } else {
            alert('处理失败: ' + (data.detail || '未知错误'));
        }
    } catch (e) {
        alert('网络错误: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = origText;
    }
}

/**
 * 构造「继续处理」表单（startReprocess 与 mask-crop-reprocess 入口复用）
 * @param {Blob|null} maskBlob - 用户在编辑器中手绘的蒙版 PNG；为 null 则不带 mask 字段
 * @returns {FormData|null} 当未选任何操作时 alert 并返回 null
 */
function buildReprocessForm(maskBlob) {
    const bgEnabled = document.getElementById('reprocessBgEnabled').checked;
    const logoEnabled = document.getElementById('reprocessLogoEnabled').checked;
    const wmEnabled = document.getElementById('reprocessWmEnabled').checked;
    const blindEnabled = document.getElementById('reprocessBlindEnabled').checked;
    const compressEnabled = document.getElementById('reprocessCompressEnabled').checked;

    if (!bgEnabled && !logoEnabled && !wmEnabled && !blindEnabled && !compressEnabled && !maskBlob) {
        alert('请至少选择一个处理操作');
        return null;
    }

    const form = new FormData();
    form.append('source_run_id', reprocessRunId);
    form.append('source_image_id', reprocessSourceId);

    form.append('bg_enabled', bgEnabled);
    form.append('bg_method', bgEnabled ? document.getElementById('reprocessBgMethod').value : 'none');
    form.append('bg_model', document.getElementById('reprocessBgModel').value);
    form.append('api_key', document.getElementById('reprocessApiKey').value);
    form.append('bg_threads', localStorage.getItem('settingThreads') || 0);
    form.append('bg_disable_arena', localStorage.getItem('settingDisableArena') !== 'false');

    form.append('logo_enabled', logoEnabled);
    if (logoEnabled) {
        form.append('logo_position', document.getElementById('reprocessLogoPosition').value);
        form.append('logo_ratio', document.getElementById('reprocessLogoRatio').value / 100);
        form.append('logo_opacity', document.getElementById('reprocessLogoOpacity').value / 100);
        form.append('logo_margin', parseInt(document.getElementById('reprocessLogoMargin').value) || 20);
        form.append('logo_tile', document.getElementById('reprocessLogoTile').checked);
    }

    form.append('wm_mode', wmEnabled ? document.getElementById('reprocessWmMode').value : 'off');
    form.append('wm_text', document.getElementById('reprocessWmText').value || '');
    form.append('wm_text_color', document.getElementById('reprocessWmTextColor').value);
    form.append('wm_text_ratio', parseInt(document.getElementById('reprocessWmTextRatio').value) / 100);
    form.append('wm_opacity', parseInt(document.getElementById('reprocessWmOpacity').value) / 100);
    form.append('wm_position', document.getElementById('reprocessWmPosition').value);
    form.append('wm_tile_direction', document.getElementById('reprocessWmTileDirection').value);
    form.append('wm_dense_density', parseInt(document.getElementById('reprocessWmDenseDensity').value));

    // [DISABLED: 盲水印暂屏蔽] 强制不上传盲水印相关参数
    form.append('wm_blind_enabled', false);
    form.append('wm_blind_text', '');
    form.append('wm_blind_strength', 16);
    form.append('wm_blind_use_mask', false);
    /* 原代码（已禁用）
    form.append('wm_blind_enabled', blindEnabled);
    form.append('wm_blind_text', document.getElementById('reprocessBlindText').value || '');
    form.append('wm_blind_strength', parseInt(document.getElementById('wmBlindStrength').value) || 16);
    form.append('wm_blind_use_mask', document.getElementById('wmBlindUseMask').checked);
    */

    form.append('compress_enabled', compressEnabled);
    if (compressEnabled) {
        form.append('output_format', document.getElementById('reprocessOutputFormat').value);
        form.append('quality', parseInt(document.getElementById('reprocessQuality').value) || 85);
        form.append('max_file_size_kb', parseInt(document.getElementById('reprocessMaxFileSize').value) || 0);
        form.append('max_width', parseInt(document.getElementById('reprocessMaxWidth').value) || 0);
    } else {
        form.append('output_format', 'PNG');
        form.append('quality', '95');
    }

    if (maskBlob) {
        form.append('mask', maskBlob, 'mask.png');
    }

    return form;
}

function appendReprocessCard(data) {
    const meta = uploadedImages.find(i => i.id === data.image_id);
    const reprocessFeatures = collectReprocessFeatures();
    const hasBg = reprocessFeatures.includes('bg');
    const grid = document.getElementById('resultGrid');
    const card = document.createElement('div');
    card.className = 'result-card';
    card.id = `result-reprocess-${Date.now()}`;
    card.dataset.runId = data.run_id;
    card.dataset.imageId = data.image_id;
    card.dataset.features = reprocessFeatures.join(',');
    card.innerHTML = `
        <div class="preview-row">
            <div class="before">
                <img src="${API}/api/result-thumbnail/${data.run_id}/${data.image_id}" onerror="this.style.display='none'">
                <span class="label">继续处理</span>
            </div>
            <div class="after">
                <img src="${API}${data.thumbnail_url}?t=${Date.now()}" onerror="this.style.display='none'">
                <span class="label">处理后</span>
            </div>
        </div>
        <div class="meta">
            <span class="filename" title="${data.filename}">${data.filename.length > 10 ? data.filename.slice(0,10)+'...' : data.filename}</span>
            ${data.finished_at ? `<span class="time">${data.finished_at}</span>` : ''}
            <span class="size">${(data.output_size / 1024 / 1024).toFixed(2)} MB</span>
        </div>
        <div class="actions">
            <a class="btn btn-primary btn-sm" href="${API}${data.output_url}" download>下载</a>
            <button class="btn btn-outline btn-sm" onclick="showPreview('${data.image_id}', '${API}${data.output_url}', '${data.filename}')">预览</button>
            ${hasBg ? `<button class="btn btn-outline btn-sm" onclick="openCutoutEditor('${data.image_id}')">修改抠图</button>` : ''}
            <button class="btn btn-outline btn-sm" onclick="openEditor('${data.image_id}')">裁切</button>
            <button class="btn btn-outline btn-sm" onclick="openReprocess('${data.run_id}', '${data.image_id}', '${card.dataset.features}')">继续处理</button>
            <button class="btn btn-danger btn-sm" onclick="deleteResult('${card.id}')">删除</button>
        </div>
    `;
    grid.appendChild(card);
    resultPage = Math.ceil((grid.querySelectorAll('.result-card').length) / resultPerPage);
    applyPagination();
}

async function clearAll() {
    try {
        await fetch(`${API}/api/results`, { method: 'DELETE' });
    } catch (e) {}
    uploadedImages = [];
    renderImages();
    document.getElementById('progressSection').classList.add('hidden');
    document.getElementById('downloadAllBtn').classList.add('hidden');
    document.getElementById('progressFill').style.width = '0%';
    document.getElementById('progressFill').classList.remove('done');
    document.getElementById('progressPercent').textContent = '0%';
    document.getElementById('progressText').textContent = '准备中...';
    document.getElementById('resultGrid').innerHTML = '';
    document.getElementById('resultPagination').innerHTML = '';
    document.getElementById('resultPagination').classList.add('hidden');
    resultPage = 1;
    resultTotalPages = 0;
    if (ws) ws.close();
    currentBatchId = null;
}

async function deleteResult(cardId) {
    if (!confirm('确定要删除这张处理结果吗？')) return;
    const card = document.getElementById(cardId);
    if (!card) return;
    card.remove();
    applyPagination();
    // 优先使用 data 属性（reprocess/编辑卡片），否则解析卡片 ID
    let imageId = card.dataset.imageId || '';
    let runId = card.dataset.runId || '';
    if (!imageId) {
        // 解析卡片 ID: result-{run_id}-{image_id} 或 result-{image_id}-edit-{ts} 或 result-{image_id}
        if (cardId.includes('-edit-')) {
            // 编辑结果: result-{image_id}-edit-{ts}
            imageId = cardId.replace('result-', '').split('-edit-')[0];
        } else {
            // 新格式: result-{run_id}-{image_id}
            const parts = cardId.replace('result-', '').split('-');
            if (parts.length >= 2) {
                runId = parts[0];
                imageId = parts.slice(1).join('-');
            } else {
                imageId = parts[0];
            }
        }
    }
    if (imageId) {
        try {
            const url = runId ? `${API}/api/results/${imageId}?run_id=${runId}` : `${API}/api/results/${imageId}`;
            await fetch(url, { method: 'DELETE' });
        } catch (e) {}
    }
}

// ═══════════════════════════════════════
// ─── Pagination ───
// ═══════════════════════════════════════

function applyPagination() {
    const grid = document.getElementById('resultGrid');
    const cards = grid.querySelectorAll('.result-card');
    const total = cards.length;
    resultTotalPages = Math.max(1, Math.ceil(total / resultPerPage));
    if (resultPage > resultTotalPages) resultPage = resultTotalPages;
    if (resultPage < 1) resultPage = 1;

    const start = (resultPage - 1) * resultPerPage;
    const end = Math.min(start + resultPerPage, total);

    cards.forEach((card, i) => {
        card.style.display = (i >= start && i < end) ? '' : 'none';
    });

    renderPaginationControls();

    // Show download button if there are any completed result cards
    const hasResults = Array.from(cards).some(c =>
        c.querySelector('.actions a[download]')
    );
    const btn = document.getElementById('downloadAllBtn');
    if (btn) btn.classList.toggle('hidden', !hasResults);
}

function renderPaginationControls() {
    const container = document.getElementById('resultPagination');
    if (!container) return;

    if (resultTotalPages <= 1) {
        container.innerHTML = '';
        container.classList.add('hidden');
        return;
    }
    container.classList.remove('hidden');

    let html = '';
    // Prev button
    const prevDisabled = resultPage <= 1;
    html += `<button class="page-btn" onclick="goResultPage(${resultPage - 1})"${prevDisabled ? ' disabled' : ''}>‹ 上一页</button>`;

    // Page numbers - show window of pages around current
    const maxVisible = 7;
    let pageStart = Math.max(1, resultPage - Math.floor(maxVisible / 2));
    let pageEnd = Math.min(resultTotalPages, pageStart + maxVisible - 1);
    if (pageEnd - pageStart < maxVisible - 1) {
        pageStart = Math.max(1, pageEnd - maxVisible + 1);
    }

    if (pageStart > 1) {
        html += `<button class="page-btn" onclick="goResultPage(1)">1</button>`;
        if (pageStart > 2) html += `<span class="page-ellipsis">…</span>`;
    }
    for (let i = pageStart; i <= pageEnd; i++) {
        html += `<button class="page-btn${i === resultPage ? ' active' : ''}" onclick="goResultPage(${i})">${i}</button>`;
    }
    if (pageEnd < resultTotalPages) {
        if (pageEnd < resultTotalPages - 1) html += `<span class="page-ellipsis">…</span>`;
        html += `<button class="page-btn" onclick="goResultPage(${resultTotalPages})">${resultTotalPages}</button>`;
    }

    // Next button
    const nextDisabled = resultPage >= resultTotalPages;
    html += `<button class="page-btn" onclick="goResultPage(${resultPage + 1})"${nextDisabled ? ' disabled' : ''}>下一页 ›</button>`;

    // Page info
    html += `<span class="page-info">第 ${resultPage}/${resultTotalPages} 页，共 ${document.querySelectorAll('#resultGrid .result-card').length} 项</span>`;

    container.innerHTML = html;
}

function goResultPage(page) {
    if (page < 1 || page > resultTotalPages) return;
    resultPage = page;
    applyPagination();
    // Scroll result panel into view
    document.getElementById('progressPanel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ═══════════════════════════════════════
// ─── Crop Box Editor ───
// ═══════════════════════════════════════

let editorImageId = null;
let editorCanvas = null;
let editorCtx = null;
let editorCutoutImg = null;
let editorScale = 1;
let editorZoom = 1;
let editorReady = false;
let editorMode = 'modify';    // 'modify' | 'mask-crop-main' | 'mask-crop-reprocess'
let editorSourceRunId = null;

// Crop box state
let editorCropBox = null;        // { x, y, w, h } in image pixel coords
let editorAspectRatio = null;    // null = free, number = locked W/H ratio
let editorDragType = null;       // null | 'move' | handle key ('nw','ne','sw','se','n','s','w','e')
let editorDragStart = null;      // { mx, my, origBox } at drag begin
let editorCanvasOffset = { ox: 0, oy: 0 };  // image → canvas offset for crop-box-beyond-image

// ─── Open / Init ───

function openEditor(imageId) {
    editorImageId = imageId;
    editorReady = false;
    editorZoom = 1;
    editorMode = 'modify';
    editorSourceRunId = null;
    editorCropBox = null;
    editorAspectRatio = null;
    editorDragType = null;
    editorDragStart = null;

    // Reset ratio UI
    document.querySelectorAll('.ratio-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('.ratio-btn[data-ratio="free"]')?.classList.add('active');
    document.getElementById('editorZoomVal').textContent = '100%';

    // Show modal
    document.getElementById('editorOverlay').classList.remove('hidden');

    // Load cutout PNG first (has alpha), fallback to original
    const img = new Image();
    img.onload = () => {
        editorCutoutImg = img;
        initEditorCanvas();
    };
    img.onerror = () => {
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

    // CSS scale to fit viewport
    const wrap = document.querySelector('.editor-canvas-wrap');
    const maxW = wrap.clientWidth - 32;
    const maxH = window.innerHeight - 220;
    const baseScale = Math.min(1, maxW / img.width, maxH / img.height);
    editorScale = baseScale * editorZoom;
    canvas.style.width = Math.round(img.width * editorScale) + 'px';
    canvas.style.height = Math.round(img.height * editorScale) + 'px';

    // Default crop box: centered, ~80 % of image, free ratio
    const margin = 0.1;
    editorCropBox = {
        x: Math.round(img.width * margin),
        y: Math.round(img.height * margin),
        w: Math.round(img.width * (1 - 2 * margin)),
        h: Math.round(img.height * (1 - 2 * margin)),
    };

    showCropView();
    editorReady = true;
}

// ─── Crop View Rendering ───

/** Draw a checkerboard pattern over the given rect (cell size = cs).
 *  Uses world-coordinate-based cell calculation so patterns align
 *  when drawing sub-regions at different (x, y) offsets on the same grid. */
function drawCheckerboard(ctx, x, y, w, h, cs) {
    cs = cs || 10;
    for (let iy = 0; iy < h; iy += cs) {
        for (let ix = 0; ix < w; ix += cs) {
            const cellX = Math.floor((x + ix) / cs);
            const cellY = Math.floor((y + iy) / cs);
            const light = ((cellX + cellY) % 2 === 0);
            ctx.fillStyle = light ? '#d0d0d0' : '#ffffff';
            ctx.fillRect(x + ix, y + iy, Math.min(cs, w - ix), Math.min(cs, h - iy));
        }
    }
}

function showCropView() {
    if (!editorCutoutImg || !editorCropBox || !editorCtx) return;

    const IW = editorCutoutImg.width;
    const IH = editorCutoutImg.height;
    const cb = editorCropBox;

    // Calculate viewport bounds: union of image and crop box
    const viewX = Math.min(0, cb.x);
    const viewY = Math.min(0, cb.y);
    const viewW = Math.max(IW, cb.x + cb.w) - viewX;
    const viewH = Math.max(IH, cb.y + cb.h) - viewY;
    const ox = -viewX;  // image top-left in expanded canvas coords
    const oy = -viewY;

    // Store offset for hit testing
    editorCanvasOffset.ox = ox;
    editorCanvasOffset.oy = oy;

    // Resize canvas only when dimensions change
    if (editorCanvas.width !== viewW || editorCanvas.height !== viewH) {
        editorCanvas.width = viewW;
        editorCanvas.height = viewH;
        editorCanvas.style.width = Math.round(viewW * editorScale) + 'px';
        editorCanvas.style.height = Math.round(viewH * editorScale) + 'px';
    }

    // 1. Background: checkerboard for padding area, then draw image
    const needsExpansion = viewX < 0 || viewY < 0 || viewX + viewW > IW || viewY + viewH > IH;
    if (needsExpansion) {
        drawCheckerboard(editorCtx, 0, 0, viewW, viewH, 12);
    } else {
        editorCtx.fillStyle = '#e2e8f0';
        editorCtx.fillRect(0, 0, viewW, viewH);
    }
    editorCtx.drawImage(editorCutoutImg, ox, oy);

    // 2. Semi-transparent dark overlay around the crop box (4 rects, in canvas coords)
    const cx = cb.x + ox;  // crop box top-left in canvas coords
    const cy = cb.y + oy;
    editorCtx.fillStyle = 'rgba(0, 0, 0, 0.55)';
    // top strip
    if (cy > 0) editorCtx.fillRect(0, 0, viewW, cy);
    // bottom strip
    if (cy + cb.h < viewH) editorCtx.fillRect(0, cy + cb.h, viewW, viewH - cy - cb.h);
    // left strip
    if (cx > 0) editorCtx.fillRect(0, cy, cx, cb.h);
    // right strip
    if (cx + cb.w < viewW) editorCtx.fillRect(cx + cb.w, cy, viewW - cx - cb.w, cb.h);

    // 3. Crop box border
    editorCtx.strokeStyle = '#fff';
    editorCtx.lineWidth = 2;
    editorCtx.setLineDash([]);
    editorCtx.strokeRect(cx, cy, cb.w, cb.h);

    // 4. Corner handles (≈10 screen px)
    const s = editorScale || 1;
    const hs = Math.max(8, 10 / s);
    const corners = [
        { x: cx, y: cy },                         // nw
        { x: cx + cb.w, y: cy },                  // ne
        { x: cx, y: cy + cb.h },                  // sw
        { x: cx + cb.w, y: cy + cb.h },           // se
    ];
    editorCtx.fillStyle = '#fff';
    editorCtx.strokeStyle = '#444';
    editorCtx.lineWidth = 1.5;
    for (const c of corners) {
        editorCtx.fillRect(c.x - hs / 2, c.y - hs / 2, hs, hs);
        editorCtx.strokeRect(c.x - hs / 2, c.y - hs / 2, hs, hs);
    }

    // 5. Edge midpoint handles (≈6 screen px)
    const ehs = Math.max(5, 6 / (editorScale || 1));
    const edges = [
        { x: cx + cb.w / 2, y: cy },              // n
        { x: cx + cb.w / 2, y: cy + cb.h },       // s
        { x: cx, y: cy + cb.h / 2 },              // w
        { x: cx + cb.w, y: cy + cb.h / 2 },       // e
    ];
    for (const e of edges) {
        editorCtx.fillRect(e.x - ehs / 2, e.y - ehs / 2, ehs, ehs);
        editorCtx.strokeRect(e.x - ehs / 2, e.y - ehs / 2, ehs, ehs);
    }

    // 6. Rule‑of‑thirds grid (subtle)
    editorCtx.strokeStyle = 'rgba(255, 255, 255, 0.25)';
    editorCtx.lineWidth = 1;
    editorCtx.setLineDash([4, 4]);
    const x1 = cx + cb.w / 3, x2 = cx + cb.w * 2 / 3;
    const y1 = cy + cb.h / 3, y2 = cy + cb.h * 2 / 3;
    editorCtx.beginPath();
    editorCtx.moveTo(x1, cy); editorCtx.lineTo(x1, cy + cb.h);
    editorCtx.moveTo(x2, cy); editorCtx.lineTo(x2, cy + cb.h);
    editorCtx.moveTo(cx, y1); editorCtx.lineTo(cx + cb.w, y1);
    editorCtx.moveTo(cx, y2); editorCtx.lineTo(cx + cb.w, y2);
    editorCtx.stroke();
    editorCtx.setLineDash([]);
}

// ─── Zoom ───

function applyEditorZoom() {
    if (!editorCanvas || !editorCutoutImg) return;
    const wrap = document.querySelector('.editor-canvas-wrap');
    const maxW = wrap.clientWidth - 32;
    const maxH = window.innerHeight - 220;
    const baseScale = Math.min(1, maxW / editorCutoutImg.width, maxH / editorCutoutImg.height);
    editorScale = baseScale * editorZoom;
    editorCanvas.style.width = Math.round(editorCanvas.width * editorScale) + 'px';
    editorCanvas.style.height = Math.round(editorCanvas.height * editorScale) + 'px';
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

// ─── Aspect Ratio ───

function setAspectRatio(ratio) {
    editorAspectRatio = ratio;

    // Update active button in ratio group
    document.querySelectorAll('.ratio-btn').forEach(b => b.classList.remove('active'));
    let matched = false;
    document.querySelectorAll('.ratio-btn').forEach(b => {
        const v = b.dataset.ratio;
        const match =
            (ratio === null && v === 'free') ||
            (v === '1x1' && ratio !== null && Math.abs(ratio - 1) < 0.001) ||
            (v === '4x3' && ratio !== null && Math.abs(ratio - 4 / 3) < 0.001) ||
            (v === '3x4' && ratio !== null && Math.abs(ratio - 3 / 4) < 0.001) ||
            (v === '16x9' && ratio !== null && Math.abs(ratio - 16 / 9) < 0.001) ||
            (v === '9x16' && ratio !== null && Math.abs(ratio - 9 / 16) < 0.001) ||
            (v === '3x2' && ratio !== null && Math.abs(ratio - 3 / 2) < 0.001) ||
            (v === '2x3' && ratio !== null && Math.abs(ratio - 2 / 3) < 0.001);
        if (match) { b.classList.add('active'); matched = true; }
    });
    if (!matched) {
        document.querySelector('.ratio-btn[data-ratio="free"]')?.classList.add('active');
        editorAspectRatio = null;
        return;
    }

    if (!editorCropBox || ratio === null) return;

    // Adjust the current crop box to match the new ratio keeping area ≈ same
    const cb = editorCropBox;
    const curRatio = cb.w / cb.h;
    if (Math.abs(curRatio - ratio) < 0.01) return;

    const maxW = editorCutoutImg.width;
    const maxH = editorCutoutImg.height;
    let newW, newH;

    if (ratio > curRatio) {
        // Need wider → keep height, derive width
        newH = cb.h;
        newW = Math.min(cb.h * ratio, maxW);
        // If limited by image width, recalc height
        if (newW >= maxW) { newW = maxW; newH = newW / ratio; }
    } else {
        // Need taller → keep width, derive height
        newW = cb.w;
        newH = Math.min(cb.w / ratio, maxH);
        if (newH >= maxH) { newH = maxH; newW = newH * ratio; }
    }

    // Shrink/expand evenly from center, clamped to image bounds
    const dx = Math.round((cb.w - newW) / 2);
    const dy = Math.round((cb.h - newH) / 2);

    let nx = cb.x + dx;
    let ny = cb.y + dy;
    // Clamp position so box stays inside image
    if (nx < 0) nx = 0;
    if (ny < 0) ny = 0;
    if (nx + newW > maxW) nx = maxW - newW;
    if (ny + newH > maxH) ny = maxH - newH;

    editorCropBox = {
        x: Math.round(nx),
        y: Math.round(ny),
        w: Math.round(Math.min(newW, maxW)),
        h: Math.round(Math.min(newH, maxH)),
    };
    showCropView();
}

// ─── Interaction helpers ───

function getCanvasPos(e) {
    const canvas = document.getElementById('editorCanvas');
    if (!canvas || !editorReady) return null;
    const rect = canvas.getBoundingClientRect();
    const src = e.touches ? e.touches[0] : e;
    return {
        x: (src.clientX - rect.left) / editorScale - editorCanvasOffset.ox,
        y: (src.clientY - rect.top) / editorScale - editorCanvasOffset.oy,
    };
}

/** Returns the handle key if (mx,my) is near a handle, or 'move' if inside box, or null. */
function hitTest(mx, my) {
    if (!editorCropBox) return null;
    const cb = editorCropBox;
    // Adaptive radius ≈12 screen px so handles are clickable even when zoomed out
    const r = Math.max(8, 12 / (editorScale || 1));

    // Corners first (higher priority)
    const corners = [
        { k: 'nw', x: cb.x, y: cb.y },
        { k: 'ne', x: cb.x + cb.w, y: cb.y },
        { k: 'sw', x: cb.x, y: cb.y + cb.h },
        { k: 'se', x: cb.x + cb.w, y: cb.y + cb.h },
    ];
    for (const c of corners) {
        if (Math.abs(mx - c.x) < r && Math.abs(my - c.y) < r) return c.k;
    }
    // Edges
    const edges = [
        { k: 'n',  x: cb.x + cb.w / 2, y: cb.y },
        { k: 's',  x: cb.x + cb.w / 2, y: cb.y + cb.h },
        { k: 'w',  x: cb.x, y: cb.y + cb.h / 2 },
        { k: 'e',  x: cb.x + cb.w, y: cb.y + cb.h / 2 },
    ];
    for (const e of edges) {
        if (Math.abs(mx - e.x) < r && Math.abs(my - e.y) < r) return e.k;
    }
    // Inside box?
    if (mx >= cb.x && mx <= cb.x + cb.w && my >= cb.y && my <= cb.y + cb.h) return 'move';
    return null;
}

/** Constrain (w, h) to match target aspect ratio, keeping area ≈ same. */
function constrainRatio(w, h, ratio) {
    const wFromH = h * ratio;
    const hFromW = w / ratio;
    if (wFromH <= w) return { w: Math.round(wFromH), h: Math.round(h) };
    return { w: Math.round(w), h: Math.round(hFromW) };
}

// ─── Mouse / Touch Interaction ───

(function initCropEditorEvents() {
    const wrap = document.querySelector('.editor-canvas-wrap');
    if (!wrap) return;

    function onPointerDown(e) {
        if (!editorReady || !editorCropBox) return;
        e.preventDefault();
        const p = getCanvasPos(e);
        if (!p) return;
        const mx = Math.round(p.x), my = Math.round(p.y);

        let hit = hitTest(mx, my);
        if (!hit) hit = 'create';

        editorDragType = hit;
        editorDragStart = {
            mx,
            my,
            origBox: { ...editorCropBox },
        };

        // Update cursor
        if (hit === 'move') {
            wrap.classList.add('canvas-crop-move');
        } else if (hit !== 'create') {
            wrap.classList.add('canvas-crop-resize');
        }
    }

    function onPointerMove(e) {
        if (!editorReady || !editorCropBox) return;

        // Update cursor even when not dragging
        if (!editorDragType) {
            const p = getCanvasPos(e);
            if (p) {
                const hit = hitTest(Math.round(p.x), Math.round(p.y));
                wrap.classList.toggle('canvas-crop-move', hit === 'move');
                wrap.classList.toggle('canvas-crop-resize', hit && hit !== 'move');
            }
            return;
        }

        e.preventDefault();
        const p = getCanvasPos(e);
        if (!p) return;
        const mx = Math.round(p.x), my = Math.round(p.y);
        const start = editorDragStart;
        const ob = start.origBox;
        const ratio = editorAspectRatio;
        const MIN = 20;
        const IW = editorCutoutImg.width;
        const IH = editorCutoutImg.height;
        let newBox;

        // Create a new crop box by dragging on empty area
        if (editorDragType === 'create') {
            let nx = Math.min(mx, start.mx);
            let ny = Math.min(my, start.my);
            let nw = Math.max(MIN, Math.abs(mx - start.mx));
            let nh = Math.max(MIN, Math.abs(my - start.my));
            if (ratio) {
                if (nw / nh > ratio) {
                    nw = Math.round(nh * ratio);
                } else {
                    nh = Math.round(nw / ratio);
                }
            }
            // Clamp to image bounds
            if (nx < 0) nx = 0;
            if (ny < 0) ny = 0;
            if (nx + nw > IW) nw = IW - nx;
            if (ny + nh > IH) nh = IH - ny;
            newBox = { x: Math.round(nx), y: Math.round(ny), w: Math.round(Math.max(MIN, nw)), h: Math.round(Math.max(MIN, nh)) };

        } else if (editorDragType === 'move') {
            const dx = mx - start.mx;
            const dy = my - start.my;
            let nx = ob.x + dx;
            let ny = ob.y + dy;
            // Clamp to image bounds
            nx = Math.max(0, Math.min(nx, IW - ob.w));
            ny = Math.max(0, Math.min(ny, IH - ob.h));
            newBox = { x: Math.round(nx), y: Math.round(ny), w: ob.w, h: ob.h };
        } else if (editorDragType === 'se') {
            let nw = Math.max(MIN, ob.w + (mx - start.mx));
            let nh = Math.max(MIN, ob.h + (my - start.my));
            if (ratio) { const c = constrainRatio(nw, nh, ratio); nw = Math.max(MIN, c.w); nh = Math.max(MIN, c.h); }
            newBox = { x: ob.x, y: ob.y, w: Math.round(nw), h: Math.round(nh) };
        } else if (editorDragType === 'ne') {
            let nw = Math.max(MIN, ob.w + (mx - start.mx));
            let nh = Math.max(MIN, ob.h - (my - start.my));
            if (ratio) { const c = constrainRatio(nw, nh, ratio); nw = Math.max(MIN, c.w); nh = Math.max(MIN, c.h); }
            newBox = { x: ob.x, y: Math.round((ob.y + ob.h) - nh), w: Math.round(nw), h: Math.round(nh) };
        } else if (editorDragType === 'sw') {
            let nw = Math.max(MIN, ob.w - (mx - start.mx));
            let nh = Math.max(MIN, ob.h + (my - start.my));
            if (ratio) { const c = constrainRatio(nw, nh, ratio); nw = Math.max(MIN, c.w); nh = Math.max(MIN, c.h); }
            newBox = { x: Math.round((ob.x + ob.w) - nw), y: ob.y, w: Math.round(nw), h: Math.round(nh) };
        } else if (editorDragType === 'nw') {
            let nw = Math.max(MIN, ob.w - (mx - start.mx));
            let nh = Math.max(MIN, ob.h - (my - start.my));
            if (ratio) { const c = constrainRatio(nw, nh, ratio); nw = Math.max(MIN, c.w); nh = Math.max(MIN, c.h); }
            newBox = { x: Math.round((ob.x + ob.w) - nw), y: Math.round((ob.y + ob.h) - nh), w: Math.round(nw), h: Math.round(nh) };
        } else if (editorDragType === 'e') {
            let nw = Math.max(MIN, ob.w + (mx - start.mx));
            if (ratio) { const nh = Math.round(nw / ratio); nw = Math.round(nh * ratio); }
            newBox = { x: ob.x, y: ob.y, w: Math.round(nw), h: ob.h };
        } else if (editorDragType === 'w') {
            let nw = Math.max(MIN, ob.w - (mx - start.mx));
            if (ratio) { const nh = Math.round(nw / ratio); nw = Math.round(nh * ratio); }
            newBox = { x: Math.round((ob.x + ob.w) - nw), y: ob.y, w: Math.round(nw), h: ob.h };
        } else if (editorDragType === 's') {
            let nh = Math.max(MIN, ob.h + (my - start.my));
            if (ratio) { const nw = Math.round(nh * ratio); nh = Math.round(nw / ratio); }
            newBox = { x: ob.x, y: ob.y, w: ob.w, h: Math.round(nh) };
        } else if (editorDragType === 'n') {
            let nh = Math.max(MIN, ob.h - (my - start.my));
            if (ratio) { const nw = Math.round(nh * ratio); nh = Math.round(nw / ratio); }
            newBox = { x: ob.x, y: Math.round((ob.y + ob.h) - nh), w: ob.w, h: Math.round(nh) };
        } else {
            return;
        }

        // For resize: allow box to extend beyond image bounds → canvas expands with padding.
        // Move & create clamp within their branches above.

        editorCropBox = newBox;
        showCropView();
    }

    function onPointerUp() {
        if (!editorDragType) return;
        editorDragType = null;
        editorDragStart = null;
        wrap.classList.remove('canvas-crop-move', 'canvas-crop-resize');
    }

    wrap.addEventListener('mousedown', onPointerDown);
    wrap.addEventListener('mousemove', onPointerMove);
    wrap.addEventListener('mouseup', onPointerUp);
    wrap.addEventListener('mouseleave', onPointerUp);
    wrap.addEventListener('touchstart', onPointerDown, { passive: false });
    wrap.addEventListener('touchmove', onPointerMove, { passive: false });
    wrap.addEventListener('touchend', onPointerUp);

    // Mouse wheel zoom
    wrap.addEventListener('wheel', function (e) {
        if (!editorReady) return;
        e.preventDefault();
        editorZoom = e.deltaY < 0
            ? Math.min(5, editorZoom * 1.1)
            : Math.max(0.2, editorZoom / 1.1);
        applyEditorZoom();
    }, { passive: false });
})();

function closeEditor() {
    document.getElementById('editorOverlay').classList.add('hidden');
    editorReady = false;
    editorImageId = null;
    editorCutoutImg = null;
    editorCropBox = null;
    editorDragType = null;
    editorDragStart = null;
    editorCanvasOffset = { ox: 0, oy: 0 };
    editorZoom = 1;
    if (editorCanvas) {
        editorCanvas.style.width = '';
        editorCanvas.style.height = '';
    }
    document.querySelector('.editor-canvas-wrap')?.classList.remove('canvas-crop-move', 'canvas-crop-resize');
}

// ─── Save: produce mask from crop box & submit ───

async function saveMask() {
    if (!editorImageId || !editorCropBox) return;

    const cb = editorCropBox;
    const IW = editorCutoutImg.width;
    const IH = editorCutoutImg.height;

    // Check if crop box extends beyond image → needs canvas padding
    const needsExpand = cb.x < 0 || cb.y < 0 || cb.x + cb.w > IW || cb.y + cb.h > IH;

    let targetId = editorImageId;
    let maskBlob;

    if (needsExpand) {
        // Expanded canvas bounds: union of image and crop box
        const ex = Math.min(0, cb.x);
        const ey = Math.min(0, cb.y);
        const ew = Math.max(IW, cb.x + cb.w) - ex;
        const eh = Math.max(IH, cb.y + cb.h) - ey;
        const ox = -ex;  // image top-left in expanded canvas
        const oy = -ey;

        // 1. Create padded image (white fill for regular, transparent for cutout)
        const expCanvas = document.createElement('canvas');
        expCanvas.width = ew;
        expCanvas.height = eh;
        const expCtx = expCanvas.getContext('2d');
        const hasAlpha = editorCutoutImg.src.includes('cutout');
        if (hasAlpha) {
            expCtx.clearRect(0, 0, ew, eh);
        } else {
            expCtx.fillStyle = '#fff';
            expCtx.fillRect(0, 0, ew, eh);
        }
        expCtx.drawImage(editorCutoutImg, ox, oy);

        // 2. Upload padded image
        const expBlob = await new Promise(resolve => expCanvas.toBlob(resolve, 'image/png'));
        const uploadForm = new FormData();
        uploadForm.append('files', expBlob, 'padded-' + editorImageId + '.png');
        const uploadRes = await fetch(`${API}/api/upload`, { method: 'POST', body: uploadForm });
        if (!uploadRes.ok) { alert('上传填充图片失败'); return; }
        const uploadData = await uploadRes.json();
        targetId = uploadData.images?.[0]?.id;
        if (!targetId) { alert('上传填充图片失败'); return; }

        // 3. All-white mask at expanded size → mask crop is a no-op (keep everything)
        const mc = document.createElement('canvas');
        mc.width = ew;
        mc.height = eh;
        const mctx = mc.getContext('2d');
        mctx.fillStyle = '#fff';
        mctx.fillRect(0, 0, ew, eh);
        maskBlob = await new Promise(resolve => mc.toBlob(resolve, 'image/png'));
    } else {
        // Normal: mask at image size, white = crop box area
        const mc = document.createElement('canvas');
        mc.width = IW;
        mc.height = IH;
        const mctx = mc.getContext('2d');
        mctx.fillStyle = '#000';
        mctx.fillRect(0, 0, IW, IH);
        mctx.fillStyle = '#fff';
        mctx.fillRect(cb.x, cb.y, cb.w, cb.h);
        maskBlob = await new Promise(resolve => mc.toBlob(resolve, 'image/png'));
    }

    try {
        if (editorMode === 'mask-crop-main') {
            const form = collectConfig();
            form.append('mask', maskBlob, 'mask.png');
            form.append('target_image_id', targetId);
            const res = await fetch(`${API}/api/process`, { method: 'POST', body: form });
            const data = await res.json();
            if (data.batch_id) {
                currentBatchId = data.batch_id;
                document.getElementById('progressPanel').classList.remove('hidden');
                initResultCards(data.batch_id);
                connectWebSocket(data.batch_id);
                closeEditor();
            } else {
                alert('提交失败: ' + (data.detail || '未知错误'));
            }
            return;
        }

        if (editorMode === 'mask-crop-reprocess') {
            const form = buildReprocessForm(maskBlob);
            if (!form) return;
            if (needsExpand) {
                form.set('source_image_id', targetId);
            }
            const res = await fetch(`${API}/api/reprocess`, { method: 'POST', body: form });
            const data = await res.json();
            if (data.ok) {
                appendReprocessCard(data);
                closeReprocess();
                closeEditor();
            } else {
                alert('处理失败: ' + (data.detail || '未知错误'));
            }
            return;
        }

        // Default: edit existing result
        const form = collectConfig();
        form.append('mask', maskBlob, 'mask.png');
        const editUrl = needsExpand ? `${API}/api/edit-mask/${targetId}` : `${API}/api/edit-mask/${editorImageId}`;
        const res = await fetch(editUrl, { method: 'POST', body: form });
        const data = await res.json();
        if (data.ok) {
            const meta = uploadedImages.find(i => i.id === editorImageId);
            const editFeatures = collectFeatures();
            const editHasBg = editFeatures.includes('bg');
            const grid = document.getElementById('resultGrid');
            const newCard = document.createElement('div');
            newCard.className = 'result-card';
            newCard.id = `result-${editorImageId}-edit-${Date.now()}`;
            newCard.dataset.imageId = editorImageId;
            newCard.dataset.features = editFeatures.join(',');
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
                    <span class="size">${(data.output_size / 1024 / 1024).toFixed(2)} MB</span>
                </div>
                <div class="actions">
                    <a class="btn btn-primary btn-sm" href="${API}${data.output_url}" download>下载</a>
                    <button class="btn btn-outline btn-sm" onclick="showPreview('${editorImageId}', '${API}${data.output_url}', '${meta ? meta.filename : ''}')">预览</button>
                    ${editHasBg ? `<button class="btn btn-outline btn-sm" onclick="openCutoutEditor('${editorImageId}')">修改抠图</button>` : ''}
                    <button class="btn btn-outline btn-sm" onclick="openEditor('${editorImageId}')">再次编辑</button>
                    <button class="btn btn-outline btn-sm" onclick="openReprocess('${data.run_id}', '${editorImageId}', '${editFeatures.join(',')}')">继续处理</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteResult('${newCard.id}')">删除</button>
                </div>
            `;
            grid.appendChild(newCard);
            resultPage = Math.ceil((grid.querySelectorAll('.result-card').length) / resultPerPage);
            applyPagination();
            closeEditor();
        } else {
            alert('保存失败: ' + (data.detail || '未知错误'));
        }
    } catch (err) {
        alert('保存出错: ' + err.message);
    }
}

// ─── Entry points: mask-crop from main panel / reprocess ───

function openMaskCropFromMain() {
    if (!uploadedImages.length) {
        alert('请先上传图片');
        return;
    }
    const id = uploadedImages[0].id;
    editorMode = 'mask-crop-main';
    openEditor(id);
}

function openMaskCropFromReprocess() {
    if (!reprocessSourceId) {
        alert('请先打开「继续处理」窗口');
        return;
    }
    editorMode = 'mask-crop-reprocess';
    editorSourceRunId = reprocessRunId;
    openEditor(reprocessSourceId);
}

// ─── 预览弹窗 ───

function showPreview(imageId, processedSrc, filename) {
    const origImg = document.getElementById('previewOriginal');
    origImg.src = `${API}/api/original/${imageId}`;
    origImg.onerror = function() {
        this.src = ''; // 清除无效地址，避免显示 broken icon
        this.style.display = 'none';
        const label = this.nextElementSibling;
        if (label) label.style.display = 'none';
    };
    origImg.onload = function() {
        this.style.display = '';
        const label = this.nextElementSibling;
        if (label) label.style.display = '';
    };
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

function handleSettingLogoUpload(files) {
    if (!files.length) return;
    const formData = new FormData();
    formData.append('file', files[0]);

    fetch(`${API}/api/config/default-logo-image`, { method: 'POST', body: formData })
        .then(r => r.json())
        .then(data => {
            if (data.ok) {
                document.getElementById('settingLogoPreview').innerHTML = `<img src="${API}/api/logo-default?v=${Date.now()}">`;
                updateLogoPreview();
            }
        })
        .catch(() => {});
}

function openSettings() {
    document.getElementById('settingThreads').value = localStorage.getItem('settingThreads') || 0;
    document.getElementById('settingDisableArena').checked = localStorage.getItem('settingDisableArena') !== 'false';
    // 当前CPU线程数
    const cores = navigator.hardwareConcurrency || '未知';
    document.getElementById('currentCpuCores').textContent = `当前CPU线程数: ${cores}`;
    const recommended = Math.max(1, (navigator.hardwareConcurrency || 4) - 1);
    document.getElementById('recommendedThreads').textContent = `推荐数量：${recommended}（核心数 - 1）`;
    // 加载默认 Logo 配置
    document.getElementById('settingLogoPosition').value = defaultLogoConfig.position;
    document.getElementById('settingLogoRatio').value = Math.round(defaultLogoConfig.ratio * 100);
    document.getElementById('settingLogoRatioVal').textContent = Math.round(defaultLogoConfig.ratio * 100) + '%';
    document.getElementById('settingLogoOpacity').value = Math.round(defaultLogoConfig.opacity * 100);
    document.getElementById('settingLogoOpacityVal').textContent = Math.round(defaultLogoConfig.opacity * 100) + '%';
    document.getElementById('settingLogoMargin').value = defaultLogoConfig.margin || 20;
    document.getElementById('settingLogoMarginVal').textContent = (defaultLogoConfig.margin || 20) + 'px';
    document.getElementById('settingLogoPreview').innerHTML = `<img src="${API}/api/logo-default?v=${Date.now()}">`;
    document.getElementById('bgSettingsContent').parentElement.classList.add('open');
    document.getElementById('logoSettingsContent').parentElement.classList.add('open');
    document.getElementById('settingsOverlay').classList.remove('hidden');
}

function closeSettings() {
    document.getElementById('settingsOverlay').classList.add('hidden');
}

function toggleSettingsSection(id) {
    const content = document.getElementById(id + 'Content');
    if (content) {
        content.parentElement.classList.toggle('open');
    }
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

    // 保存默认 Logo 配置
    const logoPosition = document.getElementById('settingLogoPosition').value;
    const logoRatio = document.getElementById('settingLogoRatio').value / 100;
    const logoOpacity = document.getElementById('settingLogoOpacity').value / 100;
    const logoMargin = parseInt(document.getElementById('settingLogoMargin').value) || 20;
    localStorage.setItem('settingLogoMargin', logoMargin);
    fetch(`${API}/api/config/default-logo`, {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: new URLSearchParams({
            position: logoPosition,
            ratio: logoRatio,
            opacity: logoOpacity,
            margin: logoMargin,
        }),
    }).then(res => res.json()).then(data => {
        defaultLogoConfig = data;
        updateLogoPreview();
    });

    closeSettings();
}

// ─── 盲水印提取 [DISABLED: 功能暂屏蔽] ───

async function extractWatermarkFromResult(runId, imageId) {
    console.warn('[disabled] extractWatermarkFromResult 已禁用');
    showWatermarkPopup({ ok: false, detail: '水印提取功能已临时关闭' });
    return;
    try {
        const res = await fetch(`${API}/api/extract-watermark/${runId}/${imageId}`);
        const data = await res.json();
        if (!data.ok) {
            showWatermarkPopup({ ok: false, detail: data.detail || '未知错误' });
            return;
        }
        showWatermarkPopup(data);
    } catch (e) {
        showWatermarkPopup({ ok: false, detail: e.message });
    }
}

async function extractWatermarkFromUrl(url) {
    console.warn('[disabled] extractWatermarkFromUrl 已禁用');
    showWatermarkPopup({ ok: false, detail: '水印提取功能已临时关闭' });
    return;
    try {
        const res = await fetch(url);
        const blob = await res.blob();
        await extractWatermarkFromBlob(blob);
    } catch (e) {
        showWatermarkPopup({ ok: false, detail: e.message });
    }
}

async function extractWatermarkFromBlob(blob) {
    console.warn('[disabled] extractWatermarkFromBlob 已禁用');
    showWatermarkPopup({ ok: false, detail: '水印提取功能已临时关闭' });
    return;
    const formData = new FormData();
    formData.append('file', blob, 'watermarked.png');

    try {
        const res = await fetch(`${API}/api/extract-watermark`, {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();
        if (!data.ok) {
            showWatermarkPopup({ ok: false, detail: data.detail || '未知错误' });
            return;
        }
        showWatermarkPopup(data);
    } catch (e) {
        showWatermarkPopup({ ok: false, detail: e.message });
    }
}

function showWatermarkPopup(data) {
    // [DISABLED: 水印提取功能暂屏蔽] 不再弹出结果弹窗
    if (data && data.detail) console.info('[watermark disabled]', data.detail);
    return;
    const body = document.getElementById('watermarkBody');
    if (!body) return;

    if (!data.ok) {
        body.innerHTML = `
            <div class="wm-result-fail">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:40px;height:40px;color:var(--danger);margin-bottom:12px"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
                <div class="wm-fail-text">提取失败</div>
                <div class="wm-fail-detail">${escapeHtml(data.detail || '未知错误')}</div>
            </div>`;
    } else {
        const methodLabel = data.method === 'dct' ? 'DCT 鲁棒水印' : '感知哈希兜底';
        const methodIcon = data.method === 'dct' ? '🔐' : '🔑';
        const methodDesc = data.method === 'dct'
            ? '从 DCT 中频系数中成功解码水印文字'
            : 'DCT 水印未检测到，通过感知哈希标识图片';
        body.innerHTML = `
            <div class="wm-result-item">
                <span class="wm-result-label">提取文字</span>
                <span class="wm-result-value wm-text">${escapeHtml(data.extracted_text || '(空)')}</span>
            </div>
            <div class="wm-result-item">
                <span class="wm-result-label">提取方案</span>
                <span class="wm-result-value">${methodIcon} ${methodLabel}</span>
                <span class="wm-result-hint">${methodDesc}</span>
            </div>
            <div class="wm-result-item">
                <span class="wm-result-label">感知哈希</span>
                <span class="wm-result-value wm-phash">${data.phash || '-'}</span>
                <span class="wm-result-hint">64-bit DCT 感知哈希，可用于图片相似度比对</span>
            </div>
            ${data.filename ? `
            <div class="wm-result-item">
                <span class="wm-result-label">源文件</span>
                <span class="wm-result-value">${escapeHtml(data.filename)}</span>
            </div>` : ''}
        `;
    }

    document.getElementById('watermarkOverlay').classList.remove('hidden');
}

function closeWatermarkPopup() {
    document.getElementById('watermarkOverlay').classList.add('hidden');
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

async function loadPersistedResults() {
    try {
        const res = await fetch(`${API}/api/results`);
        const data = await res.json();
        if (!data.results || !data.results.length) return;
        const grid = document.getElementById('resultGrid');
        // 如果有 WebSocket 批次卡片（处理中），不覆盖
        if (grid.querySelector('.status-processing')) return;
        grid.innerHTML = '';
        data.results.forEach(r => {
            const cardId = r.run_id ? `result-${r.run_id}-${r.id}` : `result-${r.id}`;
            if (document.getElementById(cardId)) return;
            const features = r.features ? r.features.split(',').filter(Boolean) : [];
            const hasBg = features.includes('bg');
            const card = document.createElement('div');
            card.className = 'result-card';
            card.id = cardId;
            card.dataset.runId = r.run_id || '';
            card.dataset.imageId = r.id;
            card.dataset.features = r.features || '';
            const beforeThumbUrl = `${API}/api/thumbnail/${r.id}`;
            card.innerHTML = `
                <div class="preview-row">
                    <div class="before">
                        <img src="${beforeThumbUrl}" onerror="this.style.display='none'">
                        <span class="label">原图</span>
                    </div>
                    <div class="after">
                        <img src="${API}${r.thumbnail_url}" onerror="this.style.display='none'">
                        <span class="label">处理后</span>
                    </div>
                </div>
                <div class="meta">
                    <span class="filename" title="${escapeHtml(r.filename)}">${r.filename && r.filename.length > 10 ? escapeHtml(r.filename.slice(0, 10)) + '...' : escapeHtml(r.filename || '')}</span>
                    ${r.finished_at ? `<span class="time">${escapeHtml(r.finished_at)}</span>` : ''}
                    <span class="size">${(r.output_size / 1024 / 1024).toFixed(2)} MB</span>
                </div>
                <div class="actions">
                    <a class="btn btn-primary btn-sm" href="${API}${r.output_url}" download>下载</a>
                    <button class="btn btn-outline btn-sm" onclick="showPreview('${r.id}', '${API}${r.output_url}', '${escapeHtml(r.filename || '')}')">预览</button>
                    ${hasBg ? `<button class="btn btn-outline btn-sm" onclick="openCutoutEditor('${r.id}')">修改抠图</button>` : ''}
                    <button class="btn btn-outline btn-sm" onclick="openEditor('${r.id}')">裁切</button>
                    <button class="btn btn-outline btn-sm" onclick="openReprocess('${r.run_id}', '${r.id}', '${r.features || ''}')">继续处理</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteResult('${cardId}')">删除</button>
                </div>
            `;
            grid.appendChild(card);
        });
        document.getElementById('progressSection').classList.remove('hidden');
        // 显示下载全部按钮（如果有可下载的结果）
        const hasDownloadable = Array.from(grid.querySelectorAll('.result-card')).some(c =>
            c.querySelector('.actions a[download]')
        );
        const dlBtn = document.getElementById('downloadAllBtn');
        if (dlBtn) dlBtn.classList.toggle('hidden', !hasDownloadable);
        resultPage = 1;
        applyPagination();
    } catch (e) {
        // 无持久化结果，静默忽略
    }
}

// 从上传文件提取水印（拖放或文件选择）[DISABLED: 功能暂屏蔽]
function setupExtractWatermarkUI() {
    return;  // [DISABLED] 不再绑定拖放/选择事件
    const zone = document.getElementById('extractWatermarkZone');
    const input = document.getElementById('extractWatermarkInput');
    if (!zone || !input) return;

    zone.addEventListener('click', () => input.click());
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', e => {
        e.preventDefault();
        zone.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            extractWatermarkFromBlob(e.dataTransfer.files[0]);
        }
    });
    input.addEventListener('change', e => {
        if (e.target.files.length) {
            extractWatermarkFromBlob(e.target.files[0]);
        }
    });
}

// 延迟初始化提取UI
document.addEventListener('DOMContentLoaded', () => {
    setupExtractWatermarkUI();
    loadPersistedResults();
});

// 点击水印弹窗遮罩关闭 [DISABLED: 功能暂屏蔽]
(function(){
    const ov = document.getElementById('watermarkOverlay');
    if (ov) { ov.classList.add('hidden'); ov.style.display = 'none'; }
})();

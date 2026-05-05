/* ── Utilities ──────────────────────────────────────────
 * rafThrottle(fn) — wraps fn so it runs at most once per animation frame.
 * Prevents forced reflow when fn reads layout after a style write.
 */
function rafThrottle(fn) {
  let raf = null;
  return function(...args) {
    if (raf) return;
    raf = requestAnimationFrame(() => { raf = null; fn.apply(this, args); });
  };
}

function fmt(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

function showStatus(el, type, msg) {
  el.className = 'status-msg ' + type;
  el.textContent = msg;
  el.classList.remove('hidden');
}

function setupDrop(zone, input, onFiles) {
  if (!zone || !input) return;
  zone.addEventListener('click', e => {
    // Label click already opens the dialog natively — don't double-trigger
    if (e.target.tagName === 'LABEL' || e.target === input) return;
    input.click();
  });
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault(); zone.classList.remove('dragover');
    if (e.dataTransfer.files.length) onFiles(e.dataTransfer.files);
  });
  input.addEventListener('change', () => { if (input.files.length) onFiles(input.files); });
}

function showPreview(box, file) {
  const reader = new FileReader();
  reader.onload = e => {
    box.innerHTML = `
      <img src="${e.target.result}" alt="preview" />
      <div class="preview-info">
        <div class="p-name">${file.name}</div>
        <div class="p-meta">${fmt(file.size)} &nbsp;•&nbsp; ${file.type || 'unknown'}</div>
      </div>`;
    box.classList.remove('hidden');
  };
  reader.readAsDataURL(file);
}

async function submitForm(url, formData, statusEl, btnEl, btnText) {
  btnEl.disabled = true;
  btnEl.querySelector('.btn-icon').textContent = '⏳';
  showStatus(statusEl, 'loading', 'Processing… please wait');

  try {
    const res = await fetch(url, { method: 'POST', body: formData });
    if (!res.ok) {
      const data = await res.json().catch(() => ({ error: 'Unknown error' }));
      throw new Error(data.error || res.statusText);
    }
    // Trigger download
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    const match = cd.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : 'download';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    showStatus(statusEl, 'success', `✅ Done! Downloading "${filename}"`);
  } catch (err) {
    showStatus(statusEl, 'error', '❌ ' + err.message);
  } finally {
    btnEl.disabled = false;
    btnEl.querySelector('.btn-icon').textContent = btnText;
  }
}

// ── Format chips (auto-select output format) ──────────────────────────────
const chips = document.querySelectorAll('.format-chips .chip:not(.chip-disabled)');
const convertFormatSelect = document.getElementById('convert-format');
chips.forEach(chip => {
  chip.addEventListener('click', () => {
    chips.forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    const to = chip.dataset.to.toLowerCase();
    // Map "jpg" → select value
    const val = to === 'jpeg' ? 'jpg' : to;
    if ([...convertFormatSelect.options].find(o => o.value === val)) {
      convertFormatSelect.value = val;
    }
  });
});

// ── TOOL 1 — Convert ──────────────────────────────────
let convertFile = null;
const convertDrop = document.getElementById('convert-drop');
const convertInput = document.getElementById('convert-file');
const convertPreview = document.getElementById('convert-preview');
const convertBtn = document.getElementById('convert-btn');
const convertStatus = document.getElementById('convert-status');

setupDrop(convertDrop, convertInput, files => {
  convertFile = files[0];
  showPreview(convertPreview, convertFile);
  convertBtn.disabled = false;
  convertStatus.classList.add('hidden');
});

convertBtn.addEventListener('click', () => {
  if (!convertFile) return;
  const fd = new FormData();
  fd.append('file', convertFile);
  fd.append('format', convertFormatSelect.value);
  submitForm('/api/convert', fd, convertStatus, convertBtn, '⚡');
});

// ── TOOL 2 — Compress ─────────────────────────────────
let compressFile = null;
const compressDrop = document.getElementById('compress-drop');
const compressInput = document.getElementById('compress-file');
const compressPreview = document.getElementById('compress-preview');
const compressBtn = document.getElementById('compress-btn');
const compressStatus = document.getElementById('compress-status');
const qualitySlider = document.getElementById('compress-quality');
const qualityVal = document.getElementById('quality-val');
const kbRow = document.getElementById('compress-kb-row');
const qualityRow = document.getElementById('compress-quality-row');
const kbInput = document.getElementById('compress-kb');

qualitySlider.addEventListener('input', () => { qualityVal.textContent = qualitySlider.value; });

document.querySelectorAll('.preset-chip').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.preset-chip').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const kb = btn.dataset.kb;
    if (kb) {
      kbInput.value = kb;
      kbRow.style.display = '';
      qualityRow.style.display = 'none';
    } else {
      kbInput.value = '';
      kbRow.style.display = 'none';
      qualityRow.style.display = '';
    }
  });
});

setupDrop(compressDrop, compressInput, files => {
  compressFile = files[0];
  showPreview(compressPreview, compressFile);
  compressBtn.disabled = false;
  compressStatus.classList.add('hidden');
});

compressBtn.addEventListener('click', () => {
  if (!compressFile) return;
  const fd = new FormData();
  fd.append('file', compressFile);
  if (kbInput.value) {
    fd.append('target_kb', kbInput.value);
  } else {
    fd.append('quality', qualitySlider.value);
  }
  submitForm('/api/compress', fd, compressStatus, compressBtn, '🗜️');
});

// ── TOOL 3 — Resize ───────────────────────────────────
let resizeFile = null;
const resizeDrop = document.getElementById('resize-drop');
const resizeInput = document.getElementById('resize-file');
const resizePreview = document.getElementById('resize-preview');
const resizeBtn = document.getElementById('resize-btn');
const resizeStatus = document.getElementById('resize-status');
const pctSlider = document.getElementById('resize-pct');
const pctVal = document.getElementById('pct-val');
let selectedPreset = null;

pctSlider.addEventListener('input', () => { pctVal.textContent = pctSlider.value; });

// Tabs — scoped ONLY to the resize section to avoid interfering with PDF/Edit/India tabs
const tabs = document.querySelectorAll('#resize .tab-group .tab');
const tabContents = document.querySelectorAll('.tab-content');
tabs.forEach(tab => {
  tab.addEventListener('click', () => {
    tabs.forEach(t => t.classList.remove('active'));
    tabContents.forEach(c => { c.classList.remove('active'); c.classList.add('hidden'); });
    tab.classList.add('active');
    const target = document.getElementById('tab-' + tab.dataset.tab);
    if (!target) return;
    target.classList.remove('hidden');
    target.classList.add('active');
  });
});

// Preset cards
document.querySelectorAll('.preset-card').forEach(card => {
  card.addEventListener('click', () => {
    document.querySelectorAll('.preset-card').forEach(c => c.classList.remove('selected'));
    card.classList.add('selected');
    selectedPreset = card.dataset.preset;
    document.getElementById('preset-val').textContent = selectedPreset;
    document.getElementById('preset-selected').classList.remove('hidden');
  });
});

setupDrop(resizeDrop, resizeInput, files => {
  resizeFile = files[0];
  showPreview(resizePreview, resizeFile);
  resizeBtn.disabled = false;
  resizeStatus.classList.add('hidden');
});

resizeBtn.addEventListener('click', () => {
  if (!resizeFile) return;
  const fd = new FormData();
  fd.append('file', resizeFile);

  const activeTab = document.querySelector('.tab.active').dataset.tab;
  fd.append('mode', activeTab);

  if (activeTab === 'dimensions') {
    fd.append('width', document.getElementById('resize-width').value || '');
    fd.append('height', document.getElementById('resize-height').value || '');
    fd.append('keep_ratio', document.getElementById('resize-ratio').checked ? 'true' : 'false');
  } else if (activeTab === 'percentage') {
    fd.append('percentage', pctSlider.value);
  } else if (activeTab === 'preset') {
    if (!selectedPreset) { showStatus(resizeStatus, 'error', 'Please select a preset'); return; }
    fd.append('preset', selectedPreset);
  }

  submitForm('/api/resize', fd, resizeStatus, resizeBtn, '📐');
});

// ── TOOL 4 — PDF ──────────────────────────────────────
let pdfFiles = [];
const pdfDrop = document.getElementById('pdf-drop');
const pdfInput = document.getElementById('pdf-file');
const pdfList = document.getElementById('pdf-list');
const pdfBtn = document.getElementById('pdf-btn');
const pdfStatus = document.getElementById('pdf-status');

function renderPdfList() {
  if (!pdfFiles.length) { pdfList.classList.add('hidden'); pdfBtn.disabled = true; return; }
  pdfList.innerHTML = pdfFiles.map((f, i) => `
    <div class="file-item">
      <span class="file-item-icon">🖼️</span>
      <span>${i + 1}. ${f.name}</span>
      <span class="file-item-size">${fmt(f.size)}</span>
    </div>`).join('');
  pdfList.classList.remove('hidden');
  pdfBtn.disabled = false;
}

setupDrop(pdfDrop, pdfInput, files => {
  pdfFiles = [...pdfFiles, ...files];
  renderPdfList();
  pdfStatus.classList.add('hidden');
});

pdfBtn.addEventListener('click', () => {
  if (!pdfFiles.length) return;
  const fd = new FormData();
  pdfFiles.forEach(f => fd.append('files', f));
  submitForm('/api/to-pdf', fd, pdfStatus, pdfBtn, '📄');
});

// ── TOOL 5 — Strip metadata ────────────────────────────
let stripFile = null;
const stripDrop = document.getElementById('strip-drop');
const stripInput = document.getElementById('strip-file');
const stripPreview = document.getElementById('strip-preview');
const stripBtn = document.getElementById('strip-btn');
const stripStatus = document.getElementById('strip-status');

setupDrop(stripDrop, stripInput, files => {
  stripFile = files[0];
  showPreview(stripPreview, stripFile);
  stripBtn.disabled = false;
  stripStatus.classList.add('hidden');
});

stripBtn.addEventListener('click', () => {
  if (!stripFile) return;
  const fd = new FormData();
  fd.append('file', stripFile);
  submitForm('/api/strip-metadata', fd, stripStatus, stripBtn, '🔒');
});

// ══════════════════════════════════════════════════════
// TOOL 6 — CROP & ROTATE  (100% client-side, Cropper.js)
// ══════════════════════════════════════════════════════
let cropper = null;
let cropFileName = 'image.png';

const cropDrop      = document.getElementById('crop-drop');
const cropInput     = document.getElementById('crop-file');
const cropWorkspace = document.getElementById('crop-workspace');
const cropImg       = document.getElementById('crop-img');
const circlToggle   = document.getElementById('circle-crop-toggle');

function initCropper(src, filename) {
  cropFileName = filename;
  cropImg.src  = src;
  cropDrop.classList.add('hidden');
  cropWorkspace.classList.remove('hidden');

  if (cropper) { cropper.destroy(); cropper = null; }

  cropper = new Cropper(cropImg, {
    viewMode: 1,
    autoCropArea: 0.85,
    movable: true,
    zoomable: true,
    rotatable: true,
    scalable: true,
    responsive: true,
  });
}

setupDrop(cropDrop, cropInput, files => {
  const file = files[0];
  const reader = new FileReader();
  reader.onload = e => initCropper(e.target.result, file.name);
  reader.readAsDataURL(file);
});

// Rotate / Flip buttons
document.getElementById('crop-rotate-left') .addEventListener('click', () => cropper && cropper.rotate(-90));
document.getElementById('crop-rotate-right').addEventListener('click', () => cropper && cropper.rotate(90));
document.getElementById('crop-rotate-180') .addEventListener('click', () => cropper && cropper.rotate(180));
document.getElementById('crop-flip-h').addEventListener('click', () => {
  if (!cropper) return;
  const d = cropper.getData(); cropper.scaleX(d.scaleX === -1 ? 1 : -1);
});
document.getElementById('crop-flip-v').addEventListener('click', () => {
  if (!cropper) return;
  const d = cropper.getData(); cropper.scaleY(d.scaleY === -1 ? 1 : -1);
});

// Aspect ratio buttons
document.querySelectorAll('.ratio-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.ratio-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const r = parseFloat(btn.dataset.ratio);
    if (cropper) cropper.setAspectRatio(isNaN(r) ? NaN : r);
  });
});

// Circle crop toggles 1:1 aspect ratio
circlToggle.addEventListener('change', () => {
  if (!cropper) return;
  if (circlToggle.checked) {
    cropper.setAspectRatio(1);
    document.querySelectorAll('.ratio-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('.ratio-btn[data-ratio="1"]').classList.add('active');
  }
});

// Reset
document.getElementById('crop-reset-btn').addEventListener('click', () => { if (cropper) cropper.reset(); });

// Change image
document.getElementById('crop-change-btn').addEventListener('click', () => {
  if (cropper) { cropper.destroy(); cropper = null; }
  cropWorkspace.classList.add('hidden');
  cropDrop.classList.remove('hidden');
  cropInput.value = '';
});

// Crop & Download
document.getElementById('crop-download-btn').addEventListener('click', () => {
  if (!cropper) return;
  const isCircle = circlToggle.checked;
  const stem = cropFileName.replace(/\.[^.]+$/, '');

  const canvas = cropper.getCroppedCanvas({ imageSmoothingQuality: 'high' });
  if (!canvas) return;

  if (isCircle) {
    // Draw circle mask onto a new canvas
    const cc = document.createElement('canvas');
    cc.width  = canvas.width;
    cc.height = canvas.height;
    const ctx = cc.getContext('2d');
    ctx.beginPath();
    ctx.arc(cc.width / 2, cc.height / 2, Math.min(cc.width, cc.height) / 2, 0, Math.PI * 2);
    ctx.clip();
    ctx.drawImage(canvas, 0, 0);
    cc.toBlob(blob => triggerDownload(blob, `${stem}_circle.png`), 'image/png');
  } else {
    const ext  = cropFileName.split('.').pop().toLowerCase();
    const mime = ext === 'png' ? 'image/png' : ext === 'webp' ? 'image/webp' : 'image/jpeg';
    canvas.toBlob(blob => triggerDownload(blob, `${stem}_cropped.${ext}`), mime, 0.92);
  }
});

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

// ══════════════════════════════════════════════════════
// TOOL 7 — EDIT & EFFECTS
// ══════════════════════════════════════════════════════
let editFile   = null;
let activeEffect = 'none';
let wmPosition = 'bottom-right';
let _wmContainerW = 0; // cached container width — no reflow on redraw

// CSS filter strings per effect (for live preview)
const FX_CSS = {
  none:         '',
  grayscale:    'grayscale(1)',
  sepia:        'sepia(1)',
  invert:       'invert(1)',
  vivid:        'saturate(2.2) contrast(1.2)',
  vintage:      'sepia(0.5) contrast(0.8) brightness(0.95) saturate(0.7)',
  cool:         'hue-rotate(25deg) saturate(1.3) brightness(1.05)',
  warm:         'sepia(0.25) saturate(1.6) brightness(1.05)',
  faded:        'contrast(0.65) brightness(1.2) saturate(0.6)',
  highcontrast: 'contrast(1.8) brightness(1.05)',
  dramatic:     'grayscale(1) contrast(1.5) brightness(0.85)',
  matte:        'contrast(0.8) brightness(1.1) saturate(0.8)',
};

const editDrop      = document.getElementById('edit-drop');
const editInput     = document.getElementById('edit-file');
const editWorkspace = document.getElementById('edit-workspace');
const editLiveImg   = document.getElementById('edit-live-img');
const editStatus    = document.getElementById('edit-status');
const editApplyBtn  = document.getElementById('edit-apply-btn');

// ── Upload ──
setupDrop(editDrop, editInput, files => {
  editFile = files[0];
  const reader = new FileReader();
  reader.onload = e => {
    editLiveImg.src = e.target.result;
    editLiveImg.onload = () => {
      updateLivePreview();
      updateWatermarkPreview();
    };
    editDrop.classList.add('hidden');
    editWorkspace.classList.remove('hidden');
  };
  reader.readAsDataURL(editFile);
  editStatus.classList.add('hidden');
});

// ── Change image ──
document.getElementById('edit-change-btn').addEventListener('click', () => {
  editFile = null;
  editWorkspace.classList.add('hidden');
  editDrop.classList.remove('hidden');
  editInput.value = '';
});

// ── Edit tabs ──
document.querySelectorAll('[data-etab]').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('[data-etab]').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.etab-content').forEach(c => { c.classList.remove('active'); c.classList.add('hidden'); });
    tab.classList.add('active');
    const target = document.getElementById('etab-' + tab.dataset.etab);
    target.classList.remove('hidden');
    target.classList.add('active');
    // Refresh watermark preview when switching to that tab
    if (tab.dataset.etab === 'watermark') updateWatermarkPreview();
  });
});

// ── Live CSS filter preview ──
function updateLivePreview() {
  const brightness = document.getElementById('sl-brightness').value;
  const contrast   = document.getElementById('sl-contrast').value;
  const saturation = document.getElementById('sl-saturation').value;
  const blur       = document.getElementById('sl-blur').value;
  // Start with effect filter, then layer adjustments on top
  const fxStr = FX_CSS[activeEffect] || '';
  let filter = `${fxStr} brightness(${brightness}) contrast(${contrast}) saturate(${saturation}) blur(${blur}px)`.trim();
  editLiveImg.style.filter = filter;
}

// ── Slider value display + live preview — rAF-throttled ──
const _throttledLivePreview = rafThrottle(() => updateLivePreview());
document.querySelectorAll('.edit-slider').forEach(slider => {
  const id   = slider.id.replace('sl-', '');
  const disp = document.getElementById('val-' + id);
  slider.addEventListener('input', () => {
    if (disp) {
      const v = parseFloat(slider.value);
      disp.textContent = Number.isInteger(v) ? v : v.toFixed(1);
    }
    _throttledLivePreview();
  });
});

// ── Reset Adjustments ──
function resetAdjustments() {
  const defaults = { 'sl-brightness': 1.0, 'sl-contrast': 1.0, 'sl-saturation': 1.0, 'sl-sharpness': 1.0, 'sl-blur': 0 };
  Object.entries(defaults).forEach(([id, val]) => {
    const el = document.getElementById(id);
    el.value = val;
    const disp = document.getElementById(id.replace('sl-', 'val-'));
    if (disp) disp.textContent = val;
  });
  updateLivePreview();
}
document.getElementById('reset-adjustments-btn').addEventListener('click', resetAdjustments);

// ── Per-slider ↺ reset ──
document.querySelectorAll('.sl-reset').forEach(btn => {
  btn.addEventListener('click', () => {
    const sliderId  = btn.dataset.for;
    const defVal    = parseFloat(btn.dataset.default);
    const slider    = document.getElementById(sliderId);
    const dispId    = sliderId.replace('sl-', 'val-');
    const disp      = document.getElementById(dispId);
    slider.value    = defVal;
    if (disp) disp.textContent = Number.isInteger(defVal) ? defVal : defVal.toFixed(1);
    updateLivePreview();
  });
});

// ── Effect cards (single-select) ──
document.querySelectorAll('.effect-card').forEach(card => {
  card.addEventListener('click', () => {
    const fx = card.dataset.fx;
    // Toggle off if already active
    activeEffect = (activeEffect === fx || fx === 'none') ? 'none' : fx;
    document.querySelectorAll('.effect-card').forEach(c => {
      c.classList.toggle('active', c.dataset.fx === activeEffect);
    });
    // Mark "Original" active when no effect
    if (activeEffect === 'none') {
      document.getElementById('fx-none')?.classList.add('active');
    }
    updateLivePreview();
  });
});
// Default: mark Original as active
document.getElementById('fx-none')?.classList.add('active');

// ── Reset Effects ──
function resetEffects() {
  activeEffect = 'none';
  document.querySelectorAll('.effect-card').forEach(c => c.classList.remove('active'));
  document.getElementById('fx-none')?.classList.add('active');
  updateLivePreview();
}
document.getElementById('reset-effects-btn').addEventListener('click', resetEffects);

// ── Watermark controls — rAF-throttled to prevent reflow on rapid slider drag ──
const _throttledWmPreview = rafThrottle(() => updateWatermarkPreview());
document.getElementById('wm-opacity').addEventListener('input', function () {
  document.getElementById('wm-opacity-val').textContent = this.value;
  _throttledWmPreview();
});

['wm-text', 'wm-size', 'wm-color'].forEach(id => {
  document.getElementById(id).addEventListener('input', _throttledWmPreview);
});
document.getElementById('wm-repeat').addEventListener('change', _throttledWmPreview);

document.querySelectorAll('.pos-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.pos-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    wmPosition = btn.dataset.pos;
    updateWatermarkPreview();
  });
});

// ── Canvas watermark live preview ──
const _wmCanvas = document.getElementById('wm-canvas');
if (_wmCanvas) {
  new ResizeObserver(entries => { _wmContainerW = entries[0].contentRect.width; }).observe(_wmCanvas.parentElement);
}

function updateWatermarkPreview() {
  if (!editFile) return;
  const canvas = document.getElementById('wm-canvas');
  const ctx    = canvas.getContext('2d');
  const src    = editLiveImg.src;
  if (!src || src === window.location.href) return;

  const img = new Image();
  img.onload = () => {
    const maxW  = Math.min((_wmContainerW || canvas.parentElement.clientWidth) - 4, 720);
    const maxH  = 300;
    const scale = Math.min(maxW / img.naturalWidth, maxH / img.naturalHeight, 1);
    canvas.width  = Math.round(img.naturalWidth  * scale);
    canvas.height = Math.round(img.naturalHeight * scale);

    // Draw base image
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    // Watermark params
    const text    = document.getElementById('wm-text').value  || 'Watermark';
    const rawSize = parseInt(document.getElementById('wm-size').value)  || 40;
    const color   = document.getElementById('wm-color').value || '#ffffff';
    const opacity = parseInt(document.getElementById('wm-opacity').value) / 100;
    const repeat  = document.getElementById('wm-repeat').checked;
    const fontSize = Math.max(8, Math.round(rawSize * scale));

    ctx.save();
    ctx.globalAlpha  = opacity;
    ctx.fillStyle    = color;
    ctx.font         = `bold ${fontSize}px Inter, Arial, sans-serif`;
    ctx.textBaseline = 'top';
    // Subtle shadow so text is visible on any background
    ctx.shadowColor  = (color === '#000000' || color === '#0000ff') ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.55)';
    ctx.shadowBlur   = Math.max(2, fontSize * 0.12);

    const tw  = ctx.measureText(text).width;
    const th  = fontSize * 1.2;
    const pad = Math.max(8, Math.min(canvas.width, canvas.height) * 0.03);
    const cw  = canvas.width;
    const ch  = canvas.height;

    const posMap = {
      'top-left':      [pad,              pad],
      'top-center':    [(cw - tw) / 2,    pad],
      'top-right':     [cw - tw - pad,    pad],
      'middle-left':   [pad,              (ch - th) / 2],
      'center':        [(cw - tw) / 2,    (ch - th) / 2],
      'middle-right':  [cw - tw - pad,    (ch - th) / 2],
      'bottom-left':   [pad,              ch - th - pad],
      'bottom-center': [(cw - tw) / 2,    ch - th - pad],
      'bottom-right':  [cw - tw - pad,    ch - th - pad],
    };

    if (repeat) {
      const stepX = tw + Math.max(40, 60 * scale);
      const stepY = th + Math.max(30, 50 * scale);
      for (let y = -th; y < ch + th; y += stepY) {
        for (let x = -tw; x < cw + tw; x += stepX) {
          ctx.fillText(text, x, y);
        }
      }
    } else {
      const [x, y] = posMap[wmPosition] || posMap['bottom-right'];
      ctx.fillText(text, x, y);
    }
    ctx.restore();
  };
  img.src = src;
}

// ── Reset Watermark ──
function resetWatermark() {
  document.getElementById('wm-text').value    = '© ImageKit';
  document.getElementById('wm-size').value    = 40;
  document.getElementById('wm-color').value   = '#ffffff';
  document.getElementById('wm-opacity').value = 70;
  document.getElementById('wm-opacity-val').textContent = '70';
  document.getElementById('wm-repeat').checked = false;
  wmPosition = 'bottom-right';
  document.querySelectorAll('.pos-btn').forEach(b => b.classList.remove('active'));
  document.querySelector('.pos-btn[data-pos="bottom-right"]')?.classList.add('active');
  updateWatermarkPreview();
}
document.getElementById('reset-watermark-btn').addEventListener('click', resetWatermark);

// ── Reset ALL ──
document.getElementById('reset-all-btn').addEventListener('click', () => {
  resetAdjustments();
  resetEffects();
  resetWatermark();
  editStatus.classList.add('hidden');
});

// ── Apply & Download ──
editApplyBtn.addEventListener('click', () => {
  if (!editFile) return;

  const activeTab = document.querySelector('[data-etab].active')?.dataset.etab || 'adjustments';

  if (activeTab === 'watermark') {
    const fd = new FormData();
    fd.append('file',      editFile);
    fd.append('text',      document.getElementById('wm-text').value || 'Watermark');
    fd.append('font_size', document.getElementById('wm-size').value);
    fd.append('color',     document.getElementById('wm-color').value);
    fd.append('opacity',   document.getElementById('wm-opacity').value);
    fd.append('position',  wmPosition);
    fd.append('repeat',    document.getElementById('wm-repeat').checked ? 'true' : 'false');
    submitForm('/api/watermark', fd, editStatus, editApplyBtn, '🎨');
  } else {
    const fd = new FormData();
    fd.append('file',       editFile);
    fd.append('brightness', document.getElementById('sl-brightness').value);
    fd.append('contrast',   document.getElementById('sl-contrast').value);
    fd.append('saturation', document.getElementById('sl-saturation').value);
    fd.append('sharpness',  document.getElementById('sl-sharpness').value);
    fd.append('blur',       document.getElementById('sl-blur').value);
    fd.append('effect',     activeEffect);
    submitForm('/api/edit', fd, editStatus, editApplyBtn, '🎨');
  }
});

// ══════════════════════════════════════════════════════
// TOOL 8 — ADD TEXT TO IMAGE (click-to-position canvas)
// ══════════════════════════════════════════════════════
let atFile = null;
let atImg  = new Image();
let atX = 50, atY = 50;   // percent
let atStyles = { bold: true, italic: false, shadow: false, bgbox: false };
let _atContainerW = 0;  // cached — updated by ResizeObserver, no reflow on redraw

const atDrop      = document.getElementById('at-drop');
const atInput     = document.getElementById('at-file');
const atWorkspace = document.getElementById('at-workspace');
const atCanvas    = document.getElementById('at-canvas');
const atCtx       = atCanvas?.getContext('2d');

if (atCanvas) {
  new ResizeObserver(entries => {
    _atContainerW = entries[0].contentRect.width;
  }).observe(atCanvas.parentElement);
}

setupDrop(atDrop, atInput, files => {
  atFile = files[0];
  const reader = new FileReader();
  reader.onload = e => {
    atImg.onload = () => {
      atDrop.classList.add('hidden');
      atWorkspace.classList.remove('hidden');
      drawAtCanvas();
    };
    atImg.src = e.target.result;
  };
  reader.readAsDataURL(atFile);
});

document.getElementById('at-change-btn').addEventListener('click', () => {
  atFile = null; atX = 50; atY = 50;
  atWorkspace.classList.add('hidden');
  atDrop.classList.remove('hidden');
  atInput.value = '';
});

// ↩ Reset all Add Text settings to defaults
document.getElementById('at-reset-btn').addEventListener('click', () => {
  atX = 50; atY = 50;
  document.getElementById('at-text').value  = 'Hello World';
  document.getElementById('at-size').value  = 60;
  document.getElementById('at-size-val').textContent = '60';
  document.getElementById('at-color').value = '#ffffff';
  document.getElementById('at-bg-color').value   = '#000000';
  document.getElementById('at-bg-opacity').value = 60;
  document.getElementById('at-bg-opacity-val').textContent = '60';
  // Reset style toggles
  atStyles = { bold: true, italic: false, shadow: false, bgbox: false };
  document.querySelectorAll('.at-style-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.style === 'bold');
  });
  document.getElementById('at-bgbox-controls').classList.add('hidden');
  drawAtCanvas();
});

function drawAtCanvas() {
  if (!atImg.naturalWidth) return;
  const maxW = Math.min((_atContainerW || atCanvas.parentElement.clientWidth) - 4, 800);
  const maxH = 360;
  const sc   = Math.min(maxW / atImg.naturalWidth, maxH / atImg.naturalHeight, 1);
  atCanvas.width  = Math.round(atImg.naturalWidth  * sc);
  atCanvas.height = Math.round(atImg.naturalHeight * sc);

  atCtx.clearRect(0, 0, atCanvas.width, atCanvas.height);
  atCtx.drawImage(atImg, 0, 0, atCanvas.width, atCanvas.height);

  const text    = document.getElementById('at-text').value  || ' ';
  const rawSize = parseInt(document.getElementById('at-size').value) || 60;
  const color   = document.getElementById('at-color').value || '#ffffff';
  const size    = Math.max(8, Math.round(rawSize * sc));
  const weight  = atStyles.bold ? 'bold' : 'normal';
  const style   = atStyles.italic ? 'italic' : 'normal';

  atCtx.save();
  atCtx.font         = `${style} ${weight} ${size}px Inter, Arial, sans-serif`;
  atCtx.textBaseline = 'middle';
  atCtx.textAlign    = 'center';

  if (atStyles.shadow) {
    atCtx.shadowColor = 'rgba(0,0,0,0.8)';
    atCtx.shadowBlur  = Math.max(3, size * 0.15);
    atCtx.shadowOffsetX = 2; atCtx.shadowOffsetY = 2;
  }

  const cx = atX / 100 * atCanvas.width;
  const cy = atY / 100 * atCanvas.height;

  if (atStyles.bgbox) {
    const m    = atCtx.measureText(text);
    const tw   = m.width; const th = size * 1.3;
    const pad  = Math.max(6, size * 0.15);
    const bgC  = document.getElementById('at-bg-color').value  || '#000000';
    const bgOp = parseInt(document.getElementById('at-bg-opacity').value) / 100;
    atCtx.save();
    atCtx.shadowColor = 'transparent';
    atCtx.globalAlpha = bgOp;
    atCtx.fillStyle   = bgC;
    atCtx.fillRect(cx - tw / 2 - pad, cy - th / 2 - pad, tw + pad * 2, th + pad * 2);
    atCtx.restore();
  }

  atCtx.fillStyle = color;
  atCtx.fillText(text, cx, cy);
  atCtx.restore();

  // Crosshair indicator
  atCtx.save();
  atCtx.strokeStyle = 'rgba(99,102,241,0.7)';
  atCtx.lineWidth   = 1;
  atCtx.setLineDash([4, 4]);
  atCtx.beginPath(); atCtx.moveTo(cx - 10, cy); atCtx.lineTo(cx + 10, cy); atCtx.stroke();
  atCtx.beginPath(); atCtx.moveTo(cx, cy - 10); atCtx.lineTo(cx, cy + 10); atCtx.stroke();
  atCtx.restore();
}

// Click on canvas to reposition text
atCanvas?.addEventListener('click', e => {
  const rect = atCanvas.getBoundingClientRect();
  atX = ((e.clientX - rect.left) / rect.width)  * 100;
  atY = ((e.clientY - rect.top)  / rect.height) * 100;
  drawAtCanvas();
});

// Redraw on any control change — rAF-throttled to prevent reflow on rapid slider drag
const _throttledDrawAt = rafThrottle(() => drawAtCanvas());
['at-text', 'at-color', 'at-bg-color'].forEach(id => {
  document.getElementById(id)?.addEventListener('input', _throttledDrawAt);
});
document.getElementById('at-size')?.addEventListener('input', function () {
  document.getElementById('at-size-val').textContent = this.value;
  _throttledDrawAt();
});
document.getElementById('at-bg-opacity')?.addEventListener('input', function () {
  document.getElementById('at-bg-opacity-val').textContent = this.value;
  _throttledDrawAt();
});

// Style toggle buttons
document.querySelectorAll('.at-style-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const s = btn.dataset.style;
    atStyles[s] = !atStyles[s];
    btn.classList.toggle('active', atStyles[s]);
    if (s === 'bgbox') {
      document.getElementById('at-bgbox-controls').classList.toggle('hidden', !atStyles[s]);
    }
    drawAtCanvas();
  });
});

// Download — send to server for full-res render
document.getElementById('at-download-btn').addEventListener('click', () => {
  if (!atFile) return;
  const fd = new FormData();
  fd.append('file',       atFile);
  fd.append('text',       document.getElementById('at-text').value || ' ');
  fd.append('x_pct',      atX);
  fd.append('y_pct',      atY);
  fd.append('font_size',  document.getElementById('at-size').value);
  fd.append('color',      document.getElementById('at-color').value);
  fd.append('bold',       atStyles.bold   ? 'true' : 'false');
  fd.append('bg_box',     atStyles.bgbox  ? 'true' : 'false');
  fd.append('bg_color',   document.getElementById('at-bg-color').value);
  fd.append('bg_opacity', document.getElementById('at-bg-opacity').value);

  // Use a temporary status div
  const st = document.createElement('div'); st.className = 'status-msg hidden';
  atCanvas.parentElement.parentElement.appendChild(st);
  submitForm('/api/add-text', fd, st, document.getElementById('at-download-btn'), '✍️');
});


// ══════════════════════════════════════════════════════
// TOOL 9 — INDIA GOVT TOOLS
// ══════════════════════════════════════════════════════

// ── Govt tabs ──
document.querySelectorAll('[data-gtab]').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('[data-gtab]').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.gtab-content').forEach(c => { c.classList.remove('active'); c.classList.add('hidden'); });
    tab.classList.add('active');
    const tgt = document.getElementById('gtab-' + tab.dataset.gtab);
    tgt.classList.remove('hidden'); tgt.classList.add('active');
  });
});

// ── 9a: Passport Photo ──
let ppFile = null;
setupDrop(document.getElementById('pp-drop'), document.getElementById('pp-file'), files => {
  ppFile = files[0];
  showPreview(document.getElementById('pp-preview'), ppFile);
  document.getElementById('pp-btn').disabled = false;
  document.getElementById('pp-status').classList.add('hidden');
});
document.getElementById('pp-bg-white').addEventListener('click', () => document.getElementById('pp-bg').value = '#ffffff');
document.getElementById('pp-bg-blue') .addEventListener('click', () => document.getElementById('pp-bg').value = '#a8c8f0');
document.getElementById('pp-btn').addEventListener('click', () => {
  if (!ppFile) return;
  const fd = new FormData();
  fd.append('file',     ppFile);
  fd.append('size',     document.getElementById('pp-size').value);
  fd.append('bg_color', document.getElementById('pp-bg').value);
  fd.append('sheet',    document.getElementById('pp-sheet').checked ? 'true' : 'false');
  submitForm('/api/passport-photo', fd, document.getElementById('ppdf-status'), document.getElementById('pp-btn'), '🪪');
});

// ── 9b: Signature Resize ──
let sigFile = null;
let sigPreset = 'ssc';
let sigDrawnFile = null;   // File created from drawing pad
let sigMode = 'upload';    // 'upload' | 'draw'

// ── Mode toggle ──
document.querySelectorAll('.sig-mode-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    sigMode = btn.dataset.mode;
    document.querySelectorAll('.sig-mode-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('sig-upload-panel').classList.toggle('hidden', sigMode !== 'upload');
    document.getElementById('sig-draw-panel').classList.toggle('hidden', sigMode !== 'draw');
    // Enable resize btn only if there's something to resize in current mode
    updateSigBtn();
  });
});

function updateSigBtn() {
  const ready = sigMode === 'upload' ? !!sigFile : !!sigDrawnFile;
  document.getElementById('sig-btn').disabled = !ready;
}

// ── Upload mode ──
setupDrop(document.getElementById('sig-drop'), document.getElementById('sig-file'), files => {
  sigFile = files[0];
  showPreview(document.getElementById('sig-preview'), sigFile);
  document.getElementById('sig-status').classList.add('hidden');
  updateSigBtn();
});

// ── Draw mode — Signature Pad ──
const sigPadCanvas  = document.getElementById('sig-pad-canvas');
const sigPadCtx     = sigPadCanvas?.getContext('2d');
const sigPadHint    = document.getElementById('sig-pad-hint');
const sigDownloadRawBtn = document.getElementById('sig-download-raw-btn');

let sigPadDrawing   = false;
let sigPadColor     = '#000000';
let sigPadThickness = 2;
let sigStrokes      = [];
let sigHasDrawn     = false;
let _sigPadContainerW = 0; // cached — no reflow in initSigPad

if (sigPadCanvas) {
  new ResizeObserver(entries => {
    _sigPadContainerW = entries[0].contentRect.width;
    initSigPad(); // re-init on resize
  }).observe(sigPadCanvas.parentElement);
}

// ── High-res init: canvas internal size = 3× display size ──
function initSigPad() {
  const displayW = (_sigPadContainerW || sigPadCanvas.parentElement.clientWidth) || 600;
  const displayH = Math.max(160, Math.round(displayW * 0.28));
  const DPR      = 3;
  const physW    = Math.round(displayW * DPR);
  const physH    = Math.round(displayH * DPR);

  if (sigPadCanvas.width === physW && sigPadCanvas.height === physH) return;

  // Save existing drawing before resize
  const saved = sigHasDrawn ? sigPadCanvas.toDataURL('image/png') : null;

  sigPadCanvas.width        = physW;
  sigPadCanvas.height       = physH;
  sigPadCanvas.style.width  = displayW + 'px';
  sigPadCanvas.style.height = displayH + 'px';

  sigPadCtx.fillStyle = '#ffffff';
  sigPadCtx.fillRect(0, 0, physW, physH);

  if (saved) {
    const img = new Image();
    img.onload = () => sigPadCtx.drawImage(img, 0, 0, physW, physH);
    img.src = saved;
  }
}

// ── Returns physical-pixel coords scaled from CSS pointer event ──
// rect and scale are passed in (cached at stroke start to avoid per-move reflow)
function sigPos(e, rect, scaleX, scaleY) {
  const src = e.touches ? e.touches[0] : e;
  return {
    x: (src.clientX - rect.left) * scaleX,
    y: (src.clientY - rect.top)  * scaleY,
  };
}

// Per-stroke cached values (set in sigStart, reused in sigMove)
let _sigRect = null, _sigScaleX = 1, _sigScaleY = 1;

function sigStart(e) {
  e.preventDefault();
  initSigPad();
  sigStrokes.push(sigPadCanvas.toDataURL('image/png')); // snapshot before stroke (for undo)
  sigPadDrawing = true;
  // Read layout ONCE here — before any writes — and cache for sigMove
  _sigRect   = sigPadCanvas.getBoundingClientRect();
  _sigScaleX = sigPadCanvas.width  / _sigRect.width;
  _sigScaleY = sigPadCanvas.height / _sigRect.height;
  const { x, y } = sigPos(e, _sigRect, _sigScaleX, _sigScaleY);
  sigPadCtx.beginPath();
  sigPadCtx.moveTo(x, y);
  sigPadCtx.strokeStyle = sigPadColor;
  sigPadCtx.lineWidth   = sigPadThickness * _sigScaleX;
  sigPadCtx.lineCap     = 'round';
  sigPadCtx.lineJoin    = 'round';
}

function sigMove(e) {
  if (!sigPadDrawing) return;
  e.preventDefault();
  const { x, y } = sigPos(e, _sigRect, _sigScaleX, _sigScaleY);
  sigPadCtx.lineTo(x, y);
  sigPadCtx.stroke();
  if (!sigHasDrawn) {
    sigHasDrawn = true;
    sigPadHint.classList.add('hidden-hint');
    sigDownloadRawBtn.classList.remove('hidden'); // show download button immediately
  }
}

function sigEnd(e) {
  if (!sigPadDrawing) return;
  e.preventDefault();
  sigPadDrawing = false;
  sigPadCtx.closePath();
}

// Mouse events
sigPadCanvas.addEventListener('mousedown',  sigStart);
sigPadCanvas.addEventListener('mousemove',  sigMove);
sigPadCanvas.addEventListener('mouseup',    sigEnd);
sigPadCanvas.addEventListener('mouseleave', sigEnd);

// Touch events (mobile / tablet)
sigPadCanvas.addEventListener('touchstart', sigStart, { passive: false });
sigPadCanvas.addEventListener('touchmove',  sigMove,  { passive: false });
sigPadCanvas.addEventListener('touchend',   sigEnd,   { passive: false });

// Ink color
document.querySelectorAll('.sig-color-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.sig-color-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    sigPadColor = btn.dataset.color;
  });
});

// Thickness
document.querySelectorAll('.sig-thick-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.sig-thick-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    sigPadThickness = parseFloat(btn.dataset.thick);
  });
});

// Undo
document.getElementById('sig-undo-btn').addEventListener('click', () => {
  if (!sigStrokes.length) return;
  const prev = sigStrokes.pop();
  const img = new Image();
  img.onload = () => {
    sigPadCtx.clearRect(0, 0, sigPadCanvas.width, sigPadCanvas.height);
    sigPadCtx.fillStyle = '#ffffff';
    sigPadCtx.fillRect(0, 0, sigPadCanvas.width, sigPadCanvas.height);
    sigPadCtx.drawImage(img, 0, 0, sigPadCanvas.width, sigPadCanvas.height);
    if (!sigStrokes.length) {
      sigHasDrawn = false;
      sigPadHint.classList.remove('hidden-hint');
      sigDownloadRawBtn.classList.add('hidden');
      sigDrawnFile = null;
      updateSigBtn();
      document.getElementById('sig-draw-confirm').classList.add('hidden');
    }
  };
  img.src = prev;
});

// Clear
document.getElementById('india-sig-clear-btn').addEventListener('click', () => {
  sigPadCtx.fillStyle = '#ffffff';
  sigPadCtx.fillRect(0, 0, sigPadCanvas.width, sigPadCanvas.height);
  sigStrokes   = [];
  sigHasDrawn  = false;
  sigDrawnFile = null;
  sigPadHint.classList.remove('hidden-hint');
  sigDownloadRawBtn.classList.add('hidden');
  updateSigBtn();
  document.getElementById('sig-draw-confirm').classList.add('hidden');
});

// ⬇️ Download raw drawn signature (full resolution PNG, no resize)
document.getElementById('sig-download-raw-btn').addEventListener('click', () => {
  if (!sigHasDrawn) return;
  sigPadCanvas.toBlob(blob => {
    const url = URL.createObjectURL(blob);
    const a   = document.createElement('a');
    a.href     = url;
    a.download = 'my_signature.png';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }, 'image/png');
});

// Use drawn signature → convert canvas to File
document.getElementById('sig-use-drawn-btn').addEventListener('click', () => {
  if (!sigHasDrawn) {
    alert('Please draw your signature first.');
    return;
  }
  sigPadCanvas.toBlob(blob => {
    sigDrawnFile = new File([blob], 'drawn_signature.png', { type: 'image/png' });
    updateSigBtn();
    document.getElementById('sig-draw-confirm').classList.remove('hidden');
  }, 'image/png');
});

// Init pad when switching to draw tab (resize canvas to fit)
document.getElementById('sig-mode-draw-btn').addEventListener('click', () => {
  setTimeout(initSigPad, 50);
});

// ── Shared: preset selector ──
document.querySelectorAll('.sig-preset').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.sig-preset').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    sigPreset = btn.dataset.sig;
    document.getElementById('sig-custom-row').classList.toggle('hidden', sigPreset !== 'custom');
  });
});

// ── Resize button ──
document.getElementById('sig-btn').addEventListener('click', () => {
  const file = sigMode === 'draw' ? sigDrawnFile : sigFile;
  if (!file) return;
  const fd = new FormData();
  fd.append('file',     file);
  fd.append('preset',   sigPreset);
  fd.append('width',    document.getElementById('sig-w').value);
  fd.append('height',   document.getElementById('sig-h').value);
  fd.append('white_bg', document.getElementById('sig-white-bg').checked ? 'true' : 'false');
  submitForm('/api/signature-resize', fd, document.getElementById('sig-status'), document.getElementById('sig-btn'), '✍️');
});

// ── 9c: Govt Compress (SSC/UPSC 20KB) ──
let gcFile = null; let gcKb = 20;
setupDrop(document.getElementById('gc-drop'), document.getElementById('gc-file'), files => {
  gcFile = files[0];
  showPreview(document.getElementById('gc-preview'), gcFile);
  document.getElementById('gc-btn').disabled = false;
  document.getElementById('gc-status').classList.add('hidden');
});
document.querySelectorAll('[data-gckb]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('[data-gckb]').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    gcKb = btn.dataset.gckb;
  });
});
document.getElementById('gc-btn').addEventListener('click', () => {
  if (!gcFile) return;
  const fd = new FormData();
  fd.append('file',      gcFile);
  fd.append('target_kb', gcKb);
  submitForm('/api/compress', fd, document.getElementById('gc-status'), document.getElementById('gc-btn'), '📋');
});

// ── 9d: Merge Photo + Signature ──
let mergePhoto = null; let mergeSig = null;
function updateMergeBtn() {
  document.getElementById('merge-btn').disabled = !(mergePhoto && mergeSig);
}
setupDrop(document.getElementById('merge-photo-drop'), document.getElementById('merge-photo-file'), files => {
  mergePhoto = files[0];
  showPreview(document.getElementById('merge-photo-preview'), mergePhoto);
  document.getElementById('merge-status').classList.add('hidden');
  updateMergeBtn();
});
setupDrop(document.getElementById('merge-sig-drop'), document.getElementById('merge-sig-file'), files => {
  mergeSig = files[0];
  showPreview(document.getElementById('merge-sig-preview'), mergeSig);
  document.getElementById('merge-status').classList.add('hidden');
  updateMergeBtn();
});
document.getElementById('merge-btn').addEventListener('click', () => {
  if (!mergePhoto || !mergeSig) return;
  const fd = new FormData();
  fd.append('photo',     mergePhoto);
  fd.append('signature', mergeSig);
  fd.append('layout',    document.getElementById('merge-layout').value);
  submitForm('/api/merge-photo-signature', fd, document.getElementById('merge-status'), document.getElementById('merge-btn'), '🔗');
});

// ══════════════════════════════════════════════════════
// TOOL 10 — PDF TOOLS
// ══════════════════════════════════════════════════════

// ── Helper: show PDF info bar ──
async function fetchPdfInfo(file, barEl) {
  const fd = new FormData();
  fd.append('file', file);
  try {
    const res  = await fetch('/api/pdf/info', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.pages) {
      barEl.innerHTML = `<span class="pdf-info-icon">📄</span>
        <span class="pdf-info-text">${data.pages} page${data.pages > 1 ? 's' : ''}</span>
        ${data.encrypted ? '<span class="pdf-info-sub">🔒 Password protected</span>' : ''}`;
      barEl.classList.remove('hidden');
    }
  } catch(e) { /* silent */ }
}

// ── Helper: pdf file list (multi-upload) ──
function renderPdfFileList(files, listEl, btnEl) {
  if (!files.length) { listEl.classList.add('hidden'); if(btnEl) btnEl.disabled = true; return; }
  listEl.innerHTML = [...files].map((f,i) => `
    <div class="file-item">
      <span class="file-item-icon">📄</span>
      <span>${i+1}. ${f.name}</span>
      <span class="file-item-size">${fmt(f.size)}</span>
    </div>`).join('');
  listEl.classList.remove('hidden');
  if (btnEl) btnEl.disabled = false;
}

// ── Category switching ──
document.querySelectorAll('.pdf-cat-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.pdf-cat-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.pdf-cat').forEach(c => { c.classList.remove('active'); c.classList.add('hidden'); });
    btn.classList.add('active');
    const cat = document.getElementById('pdfcat-' + btn.dataset.cat);
    cat.classList.remove('hidden');
    cat.classList.add('active');

    // Ensure the first tab in this category is correctly shown
    // (reset any hidden-class corruption from previous interactions)
    const firstTab = cat.querySelector('[data-pdftab]');
    if (firstTab) {
      cat.querySelectorAll('[data-pdftab]').forEach(t => t.classList.remove('active'));
      cat.querySelectorAll('.pdftab-content').forEach(c => { c.classList.remove('active'); c.classList.add('hidden'); });
      firstTab.classList.add('active');
      const firstContent = document.getElementById('pdftab-' + firstTab.dataset.pdftab);
      if (firstContent) { firstContent.classList.remove('hidden'); firstContent.classList.add('active'); }
    }
  });
});

// ── PDF sub-tab switching (shared for all categories) ──
document.querySelectorAll('[data-pdftab]').forEach(tab => {
  tab.addEventListener('click', () => {
    const parent = tab.closest('.pdf-cat');
    if (!parent) return;
    parent.querySelectorAll('[data-pdftab]').forEach(t => t.classList.remove('active'));
    parent.querySelectorAll('.pdftab-content').forEach(c => { c.classList.remove('active'); c.classList.add('hidden'); });
    tab.classList.add('active');
    const tgt = document.getElementById('pdftab-' + tab.dataset.pdftab);
    if (!tgt) return;
    tgt.classList.remove('hidden'); tgt.classList.add('active');
  });
});

// ── PDF Conversion quick-pick chips ──
function activatePdfTab(tabId) {
  // switch category to Convert
  document.querySelectorAll('.pdf-cat-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.pdf-cat').forEach(c => { c.classList.remove('active'); c.classList.add('hidden'); });
  const convertBtn = document.querySelector('[data-cat="convert"]');
  if (convertBtn) convertBtn.classList.add('active');
  const convertCat = document.getElementById('pdfcat-convert');
  if (convertCat) { convertCat.classList.remove('hidden'); convertCat.classList.add('active'); }
  const convertSection = document.getElementById('pdfcat-convert');
  convertSection.querySelectorAll('[data-pdftab]').forEach(t => t.classList.remove('active'));
  convertSection.querySelectorAll('.pdftab-content').forEach(c => { c.classList.remove('active'); c.classList.add('hidden'); });
  const targetTab = convertSection.querySelector(`[data-pdftab="${tabId}"]`);
  if (targetTab) targetTab.classList.add('active');
  const targetContent = document.getElementById('pdftab-' + tabId);
  if (targetContent) { targetContent.classList.remove('hidden'); targetContent.classList.add('active'); }
}

document.querySelectorAll('[data-pconv]').forEach(chip => {
  chip.addEventListener('click', () => {
    // update active chip
    document.querySelectorAll('[data-pconv]').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');

    const conv = chip.dataset.pconv;
    if (conv === 'jpg2pdf') {
      activatePdfTab('img2pdf');
      const hint = document.getElementById('i2p-hint');
      if (hint) hint.textContent = 'JPG files — multiple supported, order = upload order';
      const inp = document.getElementById('i2p-file');
      if (inp) inp.accept = 'image/jpeg,.jpg,.jpeg';
    } else if (conv === 'png2pdf') {
      activatePdfTab('img2pdf');
      const hint = document.getElementById('i2p-hint');
      if (hint) hint.textContent = 'PNG files — multiple supported, order = upload order';
      const inp = document.getElementById('i2p-file');
      if (inp) inp.accept = 'image/png,.png';
    } else if (conv === 'word2pdf') {
      activatePdfTab('word2pdf');
    } else if (conv === 'pdf2jpg') {
      activatePdfTab('pdf2img');
      const fmt = document.getElementById('p2i-fmt');
      if (fmt) fmt.value = 'jpg';
    } else if (conv === 'pdf2png') {
      activatePdfTab('pdf2img');
      const fmt = document.getElementById('p2i-fmt');
      if (fmt) fmt.value = 'png';
    }

    // scroll into view
    document.getElementById('pdf-tools').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
});

// ── 1. Images → PDF ──
let i2pFiles = [];
setupDrop(document.getElementById('i2p-drop'), document.getElementById('i2p-file'), files => {
  i2pFiles = [...i2pFiles, ...files];
  renderPdfFileList(i2pFiles, document.getElementById('i2p-list'), document.getElementById('i2p-btn'));
});
document.getElementById('i2p-btn').addEventListener('click', () => {
  if (!i2pFiles.length) return;
  const fd = new FormData();
  i2pFiles.forEach(f => fd.append('files', f));
  submitForm('/api/to-pdf', fd, document.getElementById('i2p-status'), document.getElementById('i2p-btn'), '📄');
});

// ── 2. PDF → Images ──
let p2iFile = null;
setupDrop(document.getElementById('p2i-drop'), document.getElementById('p2i-file'), files => {
  p2iFile = files[0];
  fetchPdfInfo(p2iFile, document.getElementById('p2i-info'));
  document.getElementById('p2i-btn').disabled = false;
  document.getElementById('p2i-status').classList.add('hidden');
});
document.getElementById('p2i-btn').addEventListener('click', () => {
  if (!p2iFile) return;
  const fd = new FormData();
  fd.append('file',   p2iFile);
  fd.append('format', document.getElementById('p2i-fmt').value);
  fd.append('dpi',    document.getElementById('p2i-dpi').value);
  fd.append('pages',  document.getElementById('p2i-pages').value || 'all');
  submitForm('/api/pdf/to-image', fd, document.getElementById('p2i-status'), document.getElementById('p2i-btn'), '📸');
});

// ── 3. Merge PDFs ──
let mergePdfFiles = [];
setupDrop(document.getElementById('merge-pdf-drop'), document.getElementById('merge-pdf-file'), files => {
  mergePdfFiles = [...mergePdfFiles, ...files];
  renderPdfFileList(mergePdfFiles, document.getElementById('merge-pdf-list'), document.getElementById('merge-pdf-btn'));
});
document.getElementById('merge-pdf-btn').addEventListener('click', () => {
  if (mergePdfFiles.length < 2) return;
  const fd = new FormData();
  mergePdfFiles.forEach(f => fd.append('files', f));
  submitForm('/api/pdf/merge', fd, document.getElementById('merge-pdf-status'), document.getElementById('merge-pdf-btn'), '🔗');
});

// ── 4. Split PDF ──
let splitFile = null;
setupDrop(document.getElementById('split-drop'), document.getElementById('del-file'), files => {
  splitFile = files[0];
  fetchPdfInfo(splitFile, document.getElementById('split-info'));
  document.getElementById('split-btn').disabled = false;
});
document.getElementById('split-type').addEventListener('change', function() {
  document.getElementById('split-range-row').classList.toggle('hidden', this.value !== 'range');
  document.getElementById('split-n-row').classList.toggle('hidden', this.value !== 'every_n');
});
document.getElementById('split-btn').addEventListener('click', () => {
  if (!splitFile) return;
  const fd = new FormData();
  fd.append('file',       splitFile);
  fd.append('split_type', document.getElementById('split-type').value);
  fd.append('ranges',     document.getElementById('split-ranges').value);
  fd.append('every_n',    document.getElementById('split-n').value);
  submitForm('/api/pdf/split', fd, document.getElementById('split-status'), document.getElementById('split-btn'), '✂️');
});

// ── 5. Delete Pages ──
let delFile = null;
setupDrop(document.getElementById('del-drop'), document.getElementById('del-file'), files => {
  delFile = files[0];
  fetchPdfInfo(delFile, document.getElementById('del-info'));
  document.getElementById('del-btn').disabled = false;
});
document.getElementById('del-btn').addEventListener('click', () => {
  if (!delFile) return;
  const fd = new FormData();
  fd.append('file',  delFile);
  fd.append('pages', document.getElementById('del-pages').value);
  submitForm('/api/pdf/delete-pages', fd, document.getElementById('del-status'), document.getElementById('del-btn'), '🗑️');
});

// ── 6. Rearrange Pages ──
let rearFile = null;
setupDrop(document.getElementById('rear-drop'), document.getElementById('rear-file'), files => {
  rearFile = files[0];
  fetchPdfInfo(rearFile, document.getElementById('rear-info'));
  document.getElementById('rear-btn').disabled = false;
});
document.getElementById('rear-btn').addEventListener('click', () => {
  if (!rearFile) return;
  const fd = new FormData();
  fd.append('file',  rearFile);
  fd.append('order', document.getElementById('rear-order').value);
  submitForm('/api/pdf/rearrange', fd, document.getElementById('rear-status'), document.getElementById('rear-btn'), '🔀');
});

// ── 7. Rotate PDF ──
let rpdfFile = null; let rpdfAngle = 90;
setupDrop(document.getElementById('rpdf-drop'), document.getElementById('rpdf-file'), files => {
  rpdfFile = files[0];
  fetchPdfInfo(rpdfFile, document.getElementById('rpdf-info'));
  document.getElementById('rpdf-btn').disabled = false;
});
document.querySelectorAll('.pdf-angle-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.pdf-angle-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    rpdfAngle = parseInt(btn.dataset.angle);
  });
});
document.getElementById('rpdf-btn').addEventListener('click', () => {
  if (!rpdfFile) return;
  const fd = new FormData();
  fd.append('file',  rpdfFile);
  fd.append('angle', rpdfAngle);
  fd.append('pages', document.getElementById('rpdf-pages').value || 'all');
  submitForm('/api/pdf/rotate', fd, document.getElementById('rpdf-status'), document.getElementById('rpdf-btn'), '🔄');
});

// ── 8. Compress PDF ──
let cpdfFile = null; let cpdfLevel = 'medium';
setupDrop(document.getElementById('cpdf-drop'), document.getElementById('cpdf-file'), files => {
  cpdfFile = files[0];
  showPreview(document.getElementById('cpdf-preview'), cpdfFile);
  document.getElementById('cpdf-btn').disabled = false;
});
document.querySelectorAll('.pdf-level-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.pdf-level-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    cpdfLevel = btn.dataset.level;
  });
});
document.getElementById('cpdf-btn').addEventListener('click', () => {
  if (!cpdfFile) return;
  const fd = new FormData();
  fd.append('file',  cpdfFile);
  fd.append('level', cpdfLevel);
  submitForm('/api/pdf/compress', fd, document.getElementById('cpdf-status'), document.getElementById('cpdf-btn'), '🗜️');
});

// ── 9. Protect PDF ──
let ppdfFile = null;
setupDrop(document.getElementById('ppdf-drop'), document.getElementById('ppdf-file'), files => {
  pwmFile = files[0];
  showPreview(document.getElementById('ppdf-preview'), ppdfFile);
  document.getElementById('ppdf-btn').disabled = false;
});
document.getElementById('ppdf-btn').addEventListener('click', () => {
  if (!ppdfFile) return;
  const p1 = document.getElementById('ppdf-pass').value;
  const p2 = document.getElementById('ppdf-pass2').value;
  const st = document.getElementById('ppdf-status');
  if (!p1) { showStatus(st, 'error', '❌ Please enter a password'); return; }
  if (p1 !== p2) { showStatus(st, 'error', '❌ Passwords do not match'); return; }
  const fd = new FormData();
  fd.append('file',     ppdfFile);
  fd.append('password', p1);
  submitForm('/api/pdf/protect', fd, st, document.getElementById('ppdf-btn'), '🔒');
});

// ── 10. Unlock PDF ──
let updfFile = null;
setupDrop(document.getElementById('updf-drop'), document.getElementById('updf-file'), files => {
  updfFile = files[0];
  showPreview(document.getElementById('updf-preview'), updfFile);
  document.getElementById('updf-btn').disabled = false;
});
document.getElementById('updf-btn').addEventListener('click', () => {
  if (!updfFile) return;
  const fd = new FormData();
  fd.append('file',     updfFile);
  fd.append('password', document.getElementById('updf-pass').value);
  submitForm('/api/pdf/unlock', fd, document.getElementById('updf-status'), document.getElementById('updf-btn'), '🔓');
});

// ── 11. PDF Watermark ──
let pwmFile = null;
setupDrop(document.getElementById('pwm-drop'), document.getElementById('pwm-file'), files => {
  pwmFile = files[0];
  showPreview(document.getElementById('pwm-preview'), pwmFile);
  document.getElementById('pwm-btn').disabled = false;
});
document.getElementById('pwm-opacity').addEventListener('input', function() {
  document.getElementById('pwm-opacity-val').textContent = this.value;
});
document.getElementById('pwm-btn').addEventListener('click', () => {
  if (!pwmFile) return;
  const fd = new FormData();
  fd.append('file',      pwmFile);
  fd.append('text',      document.getElementById('pwm-text').value || 'CONFIDENTIAL');
  fd.append('font_size', document.getElementById('pwm-size').value);
  fd.append('color',     document.getElementById('pwm-color').value);
  fd.append('opacity',   parseInt(document.getElementById('pwm-opacity').value) / 100);
  fd.append('diagonal',  document.getElementById('pwm-diagonal').checked ? 'true' : 'false');
  submitForm('/api/pdf/watermark', fd, document.getElementById('pwm-status'), document.getElementById('pwm-btn'), '💧');
});

// ── 12. Word → PDF ──
let w2pFile = null;
setupDrop(document.getElementById('w2p-drop'), document.getElementById('w2p-file'), files => {
  w2pFile = files[0];
  const info = document.getElementById('w2p-info');
  if (info) {
    info.classList.remove('hidden');
    info.textContent = `📄 ${w2pFile.name}  (${(w2pFile.size / 1024).toFixed(1)} KB)`;
  }
  document.getElementById('w2p-btn').disabled = false;
  document.getElementById('w2p-status').classList.add('hidden');
});
document.getElementById('w2p-btn').addEventListener('click', () => {
  if (!w2pFile) return;
  const fd = new FormData();
  fd.append('file', w2pFile);
  submitForm('/api/pdf/word-to-pdf', fd, document.getElementById('w2p-status'), document.getElementById('w2p-btn'), '📝');
});

// ══════════════════════════════════════════════════════════════
//  AI TOOLS
// ══════════════════════════════════════════════════════════════

// ── AI tab switching ──
document.querySelectorAll('[data-aitab]').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('[data-aitab]').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.aitab-content').forEach(c => { c.classList.remove('active'); c.classList.add('hidden'); });
    tab.classList.add('active');
    const tgt = document.getElementById('aitab-' + tab.dataset.aitab);
    if (!tgt) return;
    tgt.classList.remove('hidden'); tgt.classList.add('active');
  });
});

// ── 1. Remove Background ──
let rbgFile = null;
setupDrop(document.getElementById('rbg-drop'), document.getElementById('rbg-file'), files => {
  rbgFile = files[0];
  showPreview(document.getElementById('rbg-preview'), rbgFile);
  document.getElementById('rbg-btn').disabled = false;
  document.getElementById('rbg-status').classList.add('hidden');
});
document.getElementById('rbg-btn').addEventListener('click', () => {
  if (!rbgFile) return;
  const fd = new FormData();
  fd.append('file', rbgFile);
  submitForm('/api/ai/remove-bg', fd, document.getElementById('rbg-status'), document.getElementById('rbg-btn'), '🪄');
});

// ── 2. Upscale ──
let upsFile = null, upsScale = 2;
setupDrop(document.getElementById('ups-drop'), document.getElementById('ups-file'), files => {
  upsFile = files[0];
  showPreview(document.getElementById('ups-preview'), upsFile);
  document.getElementById('ups-btn').disabled = false;
  document.getElementById('ups-status').classList.add('hidden');
});
document.querySelectorAll('.scale-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.scale-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    upsScale = parseInt(btn.dataset.scale);
  });
});
document.getElementById('ups-btn').addEventListener('click', () => {
  if (!upsFile) return;
  const fd = new FormData();
  fd.append('file', upsFile);
  fd.append('scale', upsScale);
  submitForm('/api/ai/upscale', fd, document.getElementById('ups-status'), document.getElementById('ups-btn'), '🔍');
});

// ── 3. Cartoonify ──
let cartFile = null, cartStyle = 'cartoon';
setupDrop(document.getElementById('cart-drop'), document.getElementById('cart-file'), files => {
  cartFile = files[0];
  showPreview(document.getElementById('cart-preview'), cartFile);
  document.getElementById('cart-btn').disabled = false;
  document.getElementById('cart-status').classList.add('hidden');
});
document.querySelectorAll('.style-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.style-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    cartStyle = btn.dataset.style;
  });
});
document.getElementById('cart-btn').addEventListener('click', () => {
  if (!cartFile) return;
  const fd = new FormData();
  fd.append('file', cartFile);
  fd.append('style', cartStyle);
  submitForm('/api/ai/cartoonify', fd, document.getElementById('cart-status'), document.getElementById('cart-btn'), '🎨');
});

// ── 4. OCR ──
let ocrFile = null;
setupDrop(document.getElementById('ocr-drop'), document.getElementById('ocr-file'), files => {
  ocrFile = files[0];
  showPreview(document.getElementById('ocr-preview'), ocrFile);
  document.getElementById('ocr-btn').disabled = false;
  document.getElementById('ocr-status').classList.add('hidden');
  document.getElementById('ocr-result-wrap').classList.add('hidden');
});
document.getElementById('ocr-btn').addEventListener('click', async () => {
  if (!ocrFile) return;
  const btn = document.getElementById('ocr-btn');
  const st  = document.getElementById('ocr-status');
  const fd  = new FormData();
  fd.append('file', ocrFile);
  fd.append('lang', document.getElementById('ocr-lang').value);
  fd.append('output', 'text');

  showStatus(st, 'loading', '⏳ Extracting text… this may take a few seconds');
  btn.disabled = true;
  try {
    const res  = await fetch('/api/ai/ocr', { method: 'POST', body: fd });
    const data = await res.json();
    btn.disabled = false;
    if (data.error) { showStatus(st, 'error', '❌ ' + data.error); return; }
    st.classList.add('hidden');
    document.getElementById('ocr-text-area').value = data.text;
    document.getElementById('ocr-word-count').textContent =
      `${data.word_count.toLocaleString()} words · ${data.char_count.toLocaleString()} characters`;
    document.getElementById('ocr-result-wrap').classList.remove('hidden');
  } catch(e) {
    btn.disabled = false;
    showStatus(st, 'error', '❌ Network error: ' + e.message);
  }
});
document.getElementById('ocr-copy-btn').addEventListener('click', () => {
  const txt = document.getElementById('ocr-text-area').value;
  navigator.clipboard.writeText(txt).then(() => {
    const btn = document.getElementById('ocr-copy-btn');
    btn.textContent = '✅ Copied!';
    setTimeout(() => btn.textContent = '📋 Copy', 2000);
  });
});
document.getElementById('ocr-dl-btn').addEventListener('click', () => {
  const txt  = document.getElementById('ocr-text-area').value;
  const blob = new Blob([txt], { type: 'text/plain' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = (ocrFile ? ocrFile.name.replace(/\.[^.]+$/, '') : 'ocr') + '_text.txt';
  a.click(); URL.revokeObjectURL(url);
});

// ── 5. PDF → Text ──
let ptFile = null;
setupDrop(document.getElementById('pt-drop'), document.getElementById('pt-file'), files => {
  ptFile = files[0];
  fetchPdfInfo(ptFile, document.getElementById('pt-info'));
  document.getElementById('pt-btn').disabled = false;
  document.getElementById('pt-status').classList.add('hidden');
  document.getElementById('pt-result-wrap').classList.add('hidden');
});
document.getElementById('pt-btn').addEventListener('click', async () => {
  if (!ptFile) return;
  const btn = document.getElementById('pt-btn');
  const st  = document.getElementById('pt-status');
  const fd  = new FormData();
  fd.append('file', ptFile);
  fd.append('pages', document.getElementById('pt-pages').value || 'all');
  fd.append('page_labels', document.getElementById('pt-labels').checked ? 'true' : 'false');
  fd.append('output', 'text');

  showStatus(st, 'loading', '⏳ Extracting text from PDF…');
  btn.disabled = true;
  try {
    const res  = await fetch('/api/ai/pdf-to-text', { method: 'POST', body: fd });
    const data = await res.json();
    btn.disabled = false;
    if (data.error) { showStatus(st, 'error', '❌ ' + data.error); return; }
    st.classList.add('hidden');
    document.getElementById('pt-text-area').value = data.text;
    document.getElementById('pt-word-count').textContent =
      `${data.pages} page(s) · ${data.word_count.toLocaleString()} words · ${data.char_count.toLocaleString()} chars`;
    document.getElementById('pt-result-wrap').classList.remove('hidden');
  } catch(e) {
    btn.disabled = false;
    showStatus(st, 'error', '❌ Network error: ' + e.message);
  }
});
document.getElementById('pt-copy-btn').addEventListener('click', () => {
  const txt = document.getElementById('pt-text-area').value;
  navigator.clipboard.writeText(txt).then(() => {
    const btn = document.getElementById('pt-copy-btn');
    btn.textContent = '✅ Copied!';
    setTimeout(() => btn.textContent = '📋 Copy', 2000);
  });
});
document.getElementById('pt-dl-btn').addEventListener('click', () => {
  const txt  = document.getElementById('pt-text-area').value;
  const blob = new Blob([txt], { type: 'text/plain' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = (ptFile ? ptFile.name.replace(/\.[^.]+$/, '') : 'document') + '_text.txt';
  a.click(); URL.revokeObjectURL(url);
});

// ══════════════════════════════════════════════════════════════
//  DRESS SWAP / VIRTUAL TRY-ON
// ══════════════════════════════════════════════════════════════
let dsPersonFile  = null;
let dsGarmentFile = null;

function updateDsBtn() {
  document.getElementById('ds-btn').disabled = !(dsPersonFile && dsGarmentFile);
}

setupDrop(document.getElementById('ds-person-drop'), document.getElementById('ds-person-file'), files => {
  dsPersonFile = files[0];
  showPreview(document.getElementById('ds-person-preview'), dsPersonFile);
  document.getElementById('ds-status').classList.add('hidden');
  updateDsBtn();
});

setupDrop(document.getElementById('ds-garment-drop'), document.getElementById('ds-garment-file'), files => {
  dsGarmentFile = files[0];
  showPreview(document.getElementById('ds-garment-preview'), dsGarmentFile);
  document.getElementById('ds-status').classList.add('hidden');
  updateDsBtn();
});

document.getElementById('ds-btn')?.addEventListener('click', async () => {
  if (!dsPersonFile || !dsGarmentFile) return;

  const btn    = document.getElementById('ds-btn');
  const status = document.getElementById('ds-status');
  const result = document.getElementById('ds-result');

  const quality = document.getElementById('ds-quality').value;
  const waitMsg = quality === 'high'
    ? '⏳ Processing virtual try-on… using AI when available, local engine as fallback — up to 60s'
    : '⏳ Processing virtual try-on… using AI when available, local engine as fallback — up to 30s';

  btn.disabled = true;
  btn.querySelector('.btn-icon').textContent = '⏳';
  result.classList.add('hidden');
  showStatus(status, 'loading', waitMsg);

  const fd = new FormData();
  fd.append('person',      dsPersonFile);
  fd.append('garment',     dsGarmentFile);
  fd.append('description', document.getElementById('ds-desc').value);
  fd.append('category',    document.getElementById('ds-category').value);
  fd.append('quality',     quality);

  try {
    const res = await fetch('/api/ai/dress-swap', { method: 'POST', body: fd });


    if (!res.ok) {
      const data = await res.json().catch(() => ({ error: 'Unknown error' }));
      showStatus(status, 'error', '❌ ' + (data.error || res.statusText));
      return;
    }

    const blob   = await res.blob();
    const imgUrl = URL.createObjectURL(blob);
    const img    = document.getElementById('ds-result-img');
    img.src = imgUrl;
    document.getElementById('ds-download-btn').href = imgUrl;
    result.classList.remove('hidden');
    status.classList.add('hidden');

  } catch (e) {
    showStatus(status, 'error', '❌ Network error: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.querySelector('.btn-icon').textContent = '👗';
  }
});

// ══════════════════════════════════════════════════════════════
//  CHANGE BACKGROUND
// ══════════════════════════════════════════════════════════════
let cbgFile       = null;   // subject photo
let cbgBgFile     = null;   // custom bg image
let cbgType       = 'color';
let cbgDir        = 'horizontal';
let cbgColor      = '#ffffff';
let cbgPresetUrl  = null;   // selected scene preset URL
let cbgPresetName = '';

// ── Upload subject ──
setupDrop(document.getElementById('cbg-drop'), document.getElementById('cbg-file'), files => {
  cbgFile = files[0];
  showPreview(document.getElementById('cbg-preview'), cbgFile);
  document.getElementById('cbg-btn').disabled = false;
  document.getElementById('cbg-status').classList.add('hidden');
});

// ── BG type buttons ──
document.querySelectorAll('.cbg-type-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.cbg-type-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    cbgType = btn.dataset.bgtype;
    // Show/hide relevant option panels
    document.getElementById('cbg-opt-color').classList.toggle('hidden',    cbgType !== 'color');
    document.getElementById('cbg-opt-gradient').classList.toggle('hidden', cbgType !== 'gradient');
    document.getElementById('cbg-opt-blur').classList.toggle('hidden',     cbgType !== 'blur');
    document.getElementById('cbg-opt-preset').classList.toggle('hidden',   cbgType !== 'preset');
    document.getElementById('cbg-opt-image').classList.toggle('hidden',    cbgType !== 'image');
  });
});

// ── Scene preset cards ──
document.querySelectorAll('.cbg-scene-card').forEach(card => {
  card.addEventListener('click', () => {
    document.querySelectorAll('.cbg-scene-card').forEach(c => c.classList.remove('active'));
    card.classList.add('active');
    cbgPresetUrl  = card.dataset.url;
    cbgPresetName = card.dataset.scene;
    document.getElementById('cbg-scene-selected').textContent = '✅ Selected: ' + card.querySelector('span').textContent;
  });
});

// ── Color swatches ──
document.querySelectorAll('.cbg-swatch').forEach(sw => {
  sw.addEventListener('click', () => {
    document.querySelectorAll('.cbg-swatch').forEach(s => s.classList.remove('active'));
    sw.classList.add('active');
    cbgColor = sw.dataset.color;
    document.getElementById('cbg-color').value = cbgColor;
  });
});
document.getElementById('cbg-color').addEventListener('input', function () {
  cbgColor = this.value;
  document.querySelectorAll('.cbg-swatch').forEach(s => s.classList.remove('active'));
});

// ── Gradient direction ──
document.querySelectorAll('.cbg-dir-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.cbg-dir-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    cbgDir = btn.dataset.dir;
  });
});

// ── Blur strength slider ──
document.getElementById('cbg-blur-amt').addEventListener('input', function () {
  document.getElementById('cbg-blur-val').textContent = this.value;
});

// ── Custom BG image upload ──
setupDrop(document.getElementById('cbg-bg-drop'), document.getElementById('cbg-bg-file'), files => {
  cbgBgFile = files[0];
  showPreview(document.getElementById('cbg-bg-preview'), cbgBgFile);
});

// ── Submit ──
document.getElementById('cbg-btn').addEventListener('click', async () => {
  if (!cbgFile) return;
  if (cbgType === 'image' && !cbgBgFile) {
    showStatus(document.getElementById('cbg-status'), 'error', '❌ Please upload a background image first');
    return;
  }
  if (cbgType === 'preset' && !cbgPresetUrl) {
    showStatus(document.getElementById('cbg-status'), 'error', '❌ Please select a scene preset first');
    return;
  }

  // If preset, fetch the scene image and convert to a File blob
  let presetBgFile = null;
  if (cbgType === 'preset') {
    showStatus(document.getElementById('cbg-status'), 'info', '⏳ Loading scene image…');
    try {
      const resp = await fetch(cbgPresetUrl);
      if (!resp.ok) throw new Error('Failed to fetch scene image');
      const blob = await resp.blob();
      presetBgFile = new File([blob], cbgPresetName + '.jpg', { type: blob.type });
    } catch (e) {
      showStatus(document.getElementById('cbg-status'), 'error', '❌ Could not load scene image. Check your internet connection.');
      return;
    }
  }

  const fd = new FormData();
  fd.append('file',     cbgFile);
  fd.append('bg_type',  cbgType === 'preset' ? 'image' : cbgType);
  fd.append('bg_color', cbgType === 'color' ? cbgColor : document.getElementById('cbg-grad-color1').value);
  fd.append('bg_color2', document.getElementById('cbg-grad-color2').value);
  fd.append('grad_dir', cbgDir);
  fd.append('blur_amt', document.getElementById('cbg-blur-amt').value);
  if (cbgType === 'image' && cbgBgFile)   fd.append('bg_image', cbgBgFile);
  if (cbgType === 'preset' && presetBgFile) fd.append('bg_image', presetBgFile);

  submitForm('/api/ai/change-bg', fd, document.getElementById('cbg-status'), document.getElementById('cbg-btn'), '🖼️');
});

/* ═══════════════════════════════════════════════════════════════
   PDF EDITOR
═══════════════════════════════════════════════════════════════ */
(function () {
  try {
  let pdfedFile   = null;
  let pdfedPages  = [];
  let annotations = [];
  let activeTool  = 'text';
  let pendingClick = null;
  const _pageDims = new WeakMap(); // cache {pw, ph} per page wrapper — avoids offsetWidth/Height reflow

  // ── tool selection ──
  document.querySelectorAll('.pdfed-tool').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.pdfed-tool').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeTool = btn.dataset.tool;
    });
  });

  // ── file upload ──
  function setupPdfDrop(dropId, inputId) {
    const zone  = document.getElementById(dropId);
    const input = document.getElementById(inputId);
    if (!zone || !input) return;
    zone.addEventListener('click', e => {
      if (e.target.tagName === 'LABEL' || e.target.tagName === 'INPUT') return;
      input.click();
    });
    zone.addEventListener('dragover',  e => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', e => {
      e.preventDefault(); zone.classList.remove('drag-over');
      if (e.dataTransfer.files[0]) handlePdfEditorFile(e.dataTransfer.files[0]);
    });
    input.addEventListener('change', () => { if (input.files[0]) handlePdfEditorFile(input.files[0]); });
  }
  setupPdfDrop('pdfed-drop', 'pdfed-file');
  console.log('[PDF Editor] initialized, drop zone ready');

  async function handlePdfEditorFile(file) {
    console.log('[PDF Editor] file selected:', file?.name);
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      showPdfEdStatus('error', '❌ Please upload a PDF file'); return;
    }
    pdfedFile   = file;
    annotations = [];
    document.getElementById('pdfed-password-row').style.display = 'none';
    document.getElementById('pdfed-password').value = '';
    document.getElementById('pdfed-upload-card').style.display = '';
    document.getElementById('pdfed-workspace').classList.add('hidden');
    await loadPdfPreview('');
  }

  async function loadPdfPreview(password) {
    console.log('[PDF Editor] calling /api/pdf-editor/preview');
    showPdfEdStatus('info', '⏳ Loading PDF pages…');
    const fd = new FormData();
    fd.append('file', pdfedFile);
    if (password) fd.append('password', password);
    try {
      const res  = await fetch('/api/pdf-editor/preview', { method: 'POST', body: fd });
      const data = await res.json();
      console.log('[PDF Editor] preview response:', res.status, data.page_count ?? data.error ?? data);

      if (data.needs_password) {
        // Show password input
        document.getElementById('pdfed-password-row').style.display = 'flex';
        showPdfEdStatus('error', '🔒 PDF is password-protected — enter the password above');
        return;
      }
      if (data.error) { showPdfEdStatus('error', '❌ ' + data.error); return; }

      document.getElementById('pdfed-password-row').style.display = 'none';
      pdfedPages = data.pages;
      renderPages();
      // Hide upload card, show workspace, scroll into view
      document.getElementById('pdfed-upload-card').style.display = 'none';
      const ws = document.getElementById('pdfed-workspace');
      ws.classList.remove('hidden');
      ws.scrollIntoView({ behavior: 'smooth', block: 'start' });
      showPdfEdStatus('success', `✅ Loaded ${data.page_count} page(s) — click anywhere to annotate`);
    } catch (e) { showPdfEdStatus('error', '❌ ' + e.message); }
  }

  // Unlock button
  document.getElementById('pdfed-unlock-btn').addEventListener('click', async () => {
    const pw = document.getElementById('pdfed-password').value;
    if (!pw) { showPdfEdStatus('error', '❌ Please enter the password'); return; }
    await loadPdfPreview(pw);
  });
  // Also allow pressing Enter in the password field
  document.getElementById('pdfed-password').addEventListener('keydown', async e => {
    if (e.key === 'Enter') {
      const pw = e.target.value;
      if (pw) await loadPdfPreview(pw);
    }
  });

  function showPdfEdStatus(type, msg) {
    const el = document.getElementById('pdfed-status');
    el.className = 'status-msg ' + (type === 'error' ? 'status-error' : type === 'success' ? 'status-success' : 'status-info');
    el.textContent = msg;
    el.classList.remove('hidden');
  }

  // ── render pages ──
  function renderPages() {
    const container = document.getElementById('pdfed-pages');
    container.innerHTML = '';
    pdfedPages.forEach(pg => {
      const wrapper = document.createElement('div');
      wrapper.style.cssText = 'position:relative;display:inline-block;box-shadow:0 4px 20px rgba(0,0,0,0.4);border-radius:4px;overflow:visible';
      wrapper.dataset.page  = pg.index;

      const img = document.createElement('img');
      img.src   = 'data:image/png;base64,' + pg.img;
      img.style.cssText = 'display:block;max-width:900px;width:100%;height:auto;border-radius:4px';
      img.draggable = false;

      const label = document.createElement('div');
      label.textContent = `Page ${pg.index + 1}`;
      label.style.cssText = 'text-align:center;padding:0.4rem;color:var(--text-muted,#888);font-size:0.82rem';

      wrapper.appendChild(img);
      wrapper.appendChild(label);

      // Cache page dimensions once after image loads — avoids offsetWidth/offsetHeight reflow on every widget placement
      img.addEventListener('load', () => {
        _pageDims.set(wrapper, { pw: wrapper.offsetWidth, ph: img.offsetHeight });
      }, { once: true });

      wrapper.addEventListener('click', e => {
        if (e.target.closest('.pdfed-ann-widget')) return;
        const rect  = img.getBoundingClientRect();
        onPageClick(pg.index, (e.clientX - rect.left) / rect.width, (e.clientY - rect.top) / rect.height, wrapper, img);
      });

      container.appendChild(wrapper);
    });
    redrawAnnotationWidgets();
  }

  function onPageClick(pageIndex, x_pct, y_pct, wrapper, img) {
    if      (activeTool === 'text')      placeTextWidget(pageIndex, x_pct, y_pct, '', wrapper, img);
    else if (activeTool === 'signature') { pendingClick = { pageIndex, x_pct, y_pct }; openSigModal(); }
    else if (activeTool === 'checkbox')  placeCheckboxWidget(pageIndex, x_pct, y_pct, true, wrapper, img);
  }

  // Returns cached page dimensions, falling back to live read (and caching the result)
  function getPageDims(wrapper, img) {
    let d = _pageDims.get(wrapper);
    if (!d) { d = { pw: wrapper.offsetWidth, ph: img.offsetHeight }; _pageDims.set(wrapper, d); }
    return d;
  }

  // ════════════════════════════════════════
  // SHARED HELPERS — drag & resize
  // ════════════════════════════════════════

  function makeDraggable(widget, handle, wrapper, pageImg) {
    handle.addEventListener('mousedown', e => {
      if (e.target.tagName === 'BUTTON' || e.target.closest('[data-resize]')) return;
      e.preventDefault(); e.stopPropagation();
      const startX = e.clientX, startY = e.clientY;
      const startL = parseFloat(widget.style.left) || 0;
      const startT = parseFloat(widget.style.top)  || 0;
      // Read layout ONCE before any writes to avoid forced reflow on every mousemove
      const wrapW = wrapper.offsetWidth;
      const imgH  = pageImg.offsetHeight;
      widget.style.zIndex = '20';
      function onMove(ev) {
        const newL = startL + ev.clientX - startX;
        const newT = startT + ev.clientY - startY;
        widget.style.left = newL + 'px';
        widget.style.top  = newT + 'px';
        const ann = widget._ann;
        if (ann) {
          ann.x_pct = newL / wrapW;
          ann.y_pct = newT / imgH;
        }
      }
      function onUp() { widget.style.zIndex = '10'; document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); }
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup',   onUp);
    });
  }

  // getStart() → snapshot of sizes; applyDelta(snapshot, dx, dy) → resize
  function makeResizable(handle, getStart, applyDelta) {
    handle.dataset.resize = '1';
    handle.addEventListener('mousedown', e => {
      e.preventDefault(); e.stopPropagation();
      const startX = e.clientX, startY = e.clientY;
      const snap   = getStart();
      function onMove(ev) { applyDelta(snap, ev.clientX - startX, ev.clientY - startY); }
      function onUp()  { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); }
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup',   onUp);
    });
  }

  function resizeHandle() {
    const h = document.createElement('div');
    h.title = 'Drag to resize';
    h.innerHTML = '⌟';
    h.style.cssText = 'position:absolute;bottom:-7px;right:-7px;width:16px;height:16px;background:#6366f1;color:#fff;border-radius:3px;cursor:se-resize;display:flex;align-items:center;justify-content:center;font-size:11px;user-select:none;z-index:12;line-height:1';
    return h;
  }

  function deleteHandle(cb) {
    const d = document.createElement('button');
    d.textContent = '✕'; d.title = 'Remove';
    d.style.cssText = 'position:absolute;top:-8px;right:-8px;background:#ef4444;color:#fff;border:none;border-radius:50%;width:18px;height:18px;font-size:10px;cursor:pointer;line-height:1;padding:0;z-index:11';
    d.addEventListener('click', e => { e.stopPropagation(); cb(); });
    return d;
  }

  // Duplicate button — top-left of widget
  function duplicateHandle(getAnn) {
    const d = document.createElement('button');
    d.textContent = '⧉'; d.title = 'Duplicate';
    d.style.cssText = 'position:absolute;top:-8px;left:-8px;background:#10b981;color:#fff;border:none;border-radius:50%;width:18px;height:18px;font-size:11px;cursor:pointer;line-height:1;padding:0;z-index:11';
    d.addEventListener('click', e => {
      e.stopPropagation();
      const src = getAnn();
      if (!src) return;
      // Clone with small offset so it doesn't sit exactly on top
      const clone = Object.assign({}, src, { x_pct: src.x_pct + 0.03, y_pct: src.y_pct + 0.03 });
      annotations.push(clone);
      redrawAnnotationWidgets();
    });
    return d;
  }

  // ════════════════════════════════════════
  // TEXT WIDGET
  // ════════════════════════════════════════
  function placeTextWidget(pageIndex, x_pct, y_pct, initialText, wrapper, img, annIndex) {
    const fontSize = parseInt(document.getElementById('pdfed-fontsize').value) || 14;
    const color    = document.getElementById('pdfed-color').value;
    const { pw, ph } = getPageDims(wrapper, img);

    const widget = document.createElement('div');
    widget.className = 'pdfed-ann-widget';
    widget.style.cssText = `position:absolute;left:${x_pct*pw}px;top:${y_pct*ph}px;transform:translate(0,-50%);z-index:10;display:flex;align-items:center;gap:0;box-shadow:0 2px 8px rgba(0,0,0,0.18);border-radius:5px;overflow:visible`;

    const grip = document.createElement('div');
    grip.innerHTML = '⠿'; grip.title = 'Drag to move';
    grip.style.cssText = 'background:#f59e0b;color:#fff;padding:2px 5px;cursor:move;font-size:14px;border-radius:4px 0 0 4px;user-select:none;flex-shrink:0;line-height:1.6';

    const input = document.createElement('input');
    input.type = 'text'; input.value = initialText; input.placeholder = 'Type here…';
    input.style.cssText = `font-size:${fontSize}px;color:${color};background:rgba(255,255,200,0.95);border:1.5px dashed #f59e0b;border-left:none;border-radius:0 4px 4px 0;padding:2px 6px;width:130px;min-width:50px;outline:none;font-family:inherit;cursor:text`;

    const rh = resizeHandle();
    widget.appendChild(grip);
    widget.appendChild(input);
    widget.appendChild(deleteHandle(() => { annotations.splice(annIndex, 1); widget.remove(); updateAnnCount(); redrawAnnotationWidgets(); }));
    widget.appendChild(duplicateHandle(() => widget._ann));
    widget.appendChild(rh);
    wrapper.appendChild(widget);

    let ann;
    if (annIndex !== undefined) {
      ann = annotations[annIndex];
    } else {
      ann = { page: pageIndex, type: 'text', x_pct, y_pct, text: initialText, font_size: fontSize, color };
      annotations.push(ann);
      annIndex = annotations.length - 1;
    }
    widget._ann = ann;

    makeDraggable(widget, grip, wrapper, img);
    makeResizable(rh,
      () => ({ w: input.offsetWidth, fs: parseFloat(input.style.fontSize) || fontSize }),
      ({ w, fs }, dx, dy) => {
        input.style.width    = Math.max(50, w + dx) + 'px';
        const nfs = Math.max(6, Math.min(72, fs + dy * 0.25));
        input.style.fontSize = nfs + 'px';
        ann.font_size = nfs;
      }
    );

    input.addEventListener('input', () => { ann.text = input.value; updateAnnCount(); });
    input.focus();
    updateAnnCount();
  }

  // ════════════════════════════════════════
  // SIGNATURE WIDGET
  // ════════════════════════════════════════
  function placeSignatureWidget(pageIndex, x_pct, y_pct, imgData, wrapper) {
    const img = wrapper.querySelector('img');
    const { pw, ph } = getPageDims(wrapper, img);
    const initW = Math.round(pw * 0.25);

    const widget = document.createElement('div');
    widget.className = 'pdfed-ann-widget';
    widget.style.cssText = `position:absolute;left:${x_pct*pw}px;top:${y_pct*ph}px;transform:translate(0,-50%);z-index:10;display:inline-block;overflow:visible`;

    const sigImg = document.createElement('img');
    sigImg.src = imgData; sigImg.draggable = false;
    sigImg.style.cssText = `width:${initW}px;height:auto;border:1.5px dashed #6366f1;border-radius:4px;background:rgba(255,255,255,0.9);cursor:move;display:block`;

    const rh = resizeHandle();
    const ann = { page: pageIndex, type: 'signature', x_pct, y_pct, img_data: imgData, width_pct: 0.25, height_pct: 0.08 };
    annotations.push(ann);
    const annIndex = annotations.length - 1;
    widget._ann = ann;

    widget.appendChild(sigImg);
    widget.appendChild(deleteHandle(() => { annotations.splice(annIndex, 1); widget.remove(); updateAnnCount(); redrawAnnotationWidgets(); }));
    widget.appendChild(duplicateHandle(() => widget._ann));
    widget.appendChild(rh);
    wrapper.appendChild(widget);

    makeDraggable(widget, sigImg, wrapper, img);
    makeResizable(rh,
      () => ({ w: sigImg.offsetWidth }),
      ({ w }, dx) => {
        const nw = Math.max(30, w + dx);
        sigImg.style.width = nw + 'px';
        ann.width_pct  = nw / pw;
        ann.height_pct = ann.width_pct * 0.35;
      }
    );

    updateAnnCount();
  }

  // ════════════════════════════════════════
  // CHECKBOX WIDGET
  // ════════════════════════════════════════
  function placeCheckboxWidget(pageIndex, x_pct, y_pct, checked, wrapper, img, annIndex) {
    const { pw, ph } = getPageDims(wrapper, img);
    const initSize = (annIndex !== undefined && annotations[annIndex]?.size) ? annotations[annIndex].size : 22;

    const widget = document.createElement('div');
    widget.className = 'pdfed-ann-widget';
    widget.style.cssText = `position:absolute;left:${x_pct*pw}px;top:${y_pct*ph}px;transform:translate(-50%,-50%);z-index:10;display:inline-block;overflow:visible`;

    const box = document.createElement('div');
    box.title = 'Click to toggle';
    box.style.cssText = `width:${initSize}px;height:${initSize}px;border:2px solid #1e40af;border-radius:3px;background:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:${Math.round(initSize*0.72)}px;user-select:none;box-shadow:0 1px 4px rgba(0,0,0,0.18)`;
    box.textContent = checked ? '✔' : '';
    box.addEventListener('click', e => { e.stopPropagation(); ann.checked = !ann.checked; box.textContent = ann.checked ? '✔' : ''; });

    const rh = resizeHandle();

    let ann;
    if (annIndex !== undefined) {
      ann = annotations[annIndex];
    } else {
      ann = { page: pageIndex, type: 'checkbox', x_pct, y_pct, checked, size: initSize };
      annotations.push(ann);
      annIndex = annotations.length - 1;
    }
    widget._ann = ann;

    widget.appendChild(box);
    widget.appendChild(deleteHandle(() => { annotations.splice(annIndex, 1); widget.remove(); updateAnnCount(); redrawAnnotationWidgets(); }));
    widget.appendChild(duplicateHandle(() => widget._ann));
    widget.appendChild(rh);
    wrapper.appendChild(widget);

    makeDraggable(widget, box, wrapper, img);
    makeResizable(rh,
      () => ({ s: box.offsetWidth }),
      ({ s }, dx, dy) => {
        const ns = Math.max(12, Math.min(80, s + Math.max(dx, dy)));
        box.style.width    = ns + 'px';
        box.style.height   = ns + 'px';
        box.style.fontSize = Math.round(ns * 0.72) + 'px';
        ann.size = ns;
      }
    );

    updateAnnCount();
  }

  // ── build helpers for redraw ──
  function buildSigWidget(ann, annIndex, pageWrapper) {
    const img = pageWrapper.querySelector('img');
    const { pw, ph } = getPageDims(pageWrapper, img);
    const curW = Math.round(ann.width_pct * pw) || Math.round(pw * 0.25);

    const widget = document.createElement('div');
    widget.className = 'pdfed-ann-widget';
    widget.style.cssText = `position:absolute;left:${ann.x_pct*pw}px;top:${ann.y_pct*ph}px;transform:translate(0,-50%);z-index:10;display:inline-block;overflow:visible`;
    widget._ann = ann;

    const sigImg = document.createElement('img');
    sigImg.src = ann.img_data; sigImg.draggable = false;
    sigImg.style.cssText = `width:${curW}px;height:auto;border:1.5px dashed #6366f1;border-radius:4px;background:rgba(255,255,255,0.9);cursor:move;display:block`;

    const rh = resizeHandle();
    widget.appendChild(sigImg);
    widget.appendChild(deleteHandle(() => { annotations.splice(annIndex, 1); widget.remove(); updateAnnCount(); redrawAnnotationWidgets(); }));
    widget.appendChild(duplicateHandle(() => widget._ann));
    widget.appendChild(rh);

    makeDraggable(widget, sigImg, pageWrapper, img);
    makeResizable(rh,
      () => ({ w: sigImg.offsetWidth }),
      ({ w }, dx) => {
        const nw = Math.max(30, w + dx);
        sigImg.style.width = nw + 'px';
        ann.width_pct  = nw / pw;
        ann.height_pct = ann.width_pct * 0.35;
      }
    );
    return widget;
  }

  function buildCheckboxWidget(ann, annIndex, pageWrapper) {
    const img = pageWrapper.querySelector('img');
    const { pw, ph } = getPageDims(pageWrapper, img);
    const boxSize = ann.size || 22;

    const widget = document.createElement('div');
    widget.className = 'pdfed-ann-widget';
    widget.style.cssText = `position:absolute;left:${ann.x_pct*pw}px;top:${ann.y_pct*ph}px;transform:translate(-50%,-50%);z-index:10;display:inline-block;overflow:visible`;
    widget._ann = ann;

    const box = document.createElement('div');
    box.style.cssText = `width:${boxSize}px;height:${boxSize}px;border:2px solid #1e40af;border-radius:3px;background:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:${Math.round(boxSize*0.72)}px;user-select:none;box-shadow:0 1px 4px rgba(0,0,0,0.18)`;
    box.textContent = ann.checked ? '✔' : '';
    box.addEventListener('click', e => { e.stopPropagation(); ann.checked = !ann.checked; box.textContent = ann.checked ? '✔' : ''; });

    const rh = resizeHandle();
    widget.appendChild(box);
    widget.appendChild(deleteHandle(() => { annotations.splice(annIndex, 1); widget.remove(); updateAnnCount(); redrawAnnotationWidgets(); }));
    widget.appendChild(duplicateHandle(() => widget._ann));
    widget.appendChild(rh);

    makeDraggable(widget, box, pageWrapper, img);
    makeResizable(rh,
      () => ({ s: box.offsetWidth }),
      ({ s }, dx, dy) => {
        const ns = Math.max(12, Math.min(80, s + Math.max(dx, dy)));
        box.style.width    = ns + 'px';
        box.style.height   = ns + 'px';
        box.style.fontSize = Math.round(ns * 0.72) + 'px';
        ann.size = ns;
      }
    );
    return widget;
  }

  // ── redraw all annotations ──
  function redrawAnnotationWidgets() {
    document.querySelectorAll('.pdfed-ann-widget').forEach(w => w.remove());
    annotations.forEach((ann, i) => {
      const pw = document.querySelector(`[data-page="${ann.page}"]`);
      if (!pw) return;
      const img = pw.querySelector('img');
      if      (ann.type === 'text')      placeTextWidget(ann.page, ann.x_pct, ann.y_pct, ann.text, pw, img, i);
      else if (ann.type === 'signature') { const w = buildSigWidget(ann, i, pw); pw.appendChild(w); }
      else if (ann.type === 'checkbox')  { const w = buildCheckboxWidget(ann, i, pw); pw.appendChild(w); }
    });
    updateAnnCount();
  }

  function updateAnnCount() {
    const el = document.getElementById('pdfed-ann-count');
    if (el) el.textContent = annotations.length + ' annotation' + (annotations.length !== 1 ? 's' : '');
  }

  // ── change PDF ──
  document.getElementById('pdfed-change-btn').addEventListener('click', () => {
    pdfedFile = null;
    pdfedPages = [];
    annotations = [];
    document.getElementById('pdfed-workspace').classList.add('hidden');
    document.getElementById('pdfed-upload-card').style.display = '';
    document.getElementById('pdfed-status').classList.add('hidden');
    document.getElementById('pdfed-file').value = '';
    document.getElementById('pdfed-upload-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  // ── undo / clear ──
  document.getElementById('pdfed-undo-btn').addEventListener('click', () => {
    if (!annotations.length) return;
    annotations.pop();
    redrawAnnotationWidgets();
  });
  document.getElementById('pdfed-clear-btn').addEventListener('click', () => {
    annotations = [];
    redrawAnnotationWidgets();
  });

  // ── save / download ──
  document.getElementById('pdfed-save-btn').addEventListener('click', async () => {
    if (!pdfedFile) { showPdfEdStatus('error', '❌ No PDF loaded'); return; }
    // sync live input values
    document.querySelectorAll('.pdfed-ann-widget input[type=text]').forEach((inp, i) => {
      const textAnns = annotations.filter(a => a.type === 'text');
      if (textAnns[i]) textAnns[i].text = inp.value;
    });
    showPdfEdStatus('info', '⏳ Generating PDF…');
    const fd = new FormData();
    fd.append('file', pdfedFile);
    fd.append('annotations', JSON.stringify(annotations));
    const pw = document.getElementById('pdfed-password').value;
    if (pw) fd.append('password', pw);
    try {
      const res = await fetch('/api/pdf-editor/save', { method: 'POST', body: fd });
      if (!res.ok) { const err = await res.json(); showPdfEdStatus('error', '❌ ' + (err.error || 'Save failed')); return; }
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = pdfedFile.name.replace('.pdf', '_filled.pdf');
      a.click();
      URL.revokeObjectURL(a.href);
      showPdfEdStatus('success', '✅ PDF downloaded!');
    } catch (e) { showPdfEdStatus('error', '❌ ' + e.message); }
  });

  // ══════════════════════════════════════
  // SIGNATURE DRAW MODAL
  // ══════════════════════════════════════
  const sigModal  = document.getElementById('sig-modal');
  const sigCanvas = document.getElementById('sig-canvas');
  const sigCtx    = sigCanvas.getContext('2d');
  let sigDrawing  = false, sigLastX = 0, sigLastY = 0;

  function openSigModal() { sigCtx.clearRect(0, 0, sigCanvas.width, sigCanvas.height); sigModal.style.display = 'flex'; }

  document.getElementById('sig-cancel-btn').addEventListener('click', () => { sigModal.style.display = 'none'; pendingClick = null; });
  document.getElementById('sig-clear-btn') .addEventListener('click', () => { sigCtx.clearRect(0, 0, sigCanvas.width, sigCanvas.height); });
  document.getElementById('sig-confirm-btn').addEventListener('click', () => {
    const imgData = sigCanvas.toDataURL('image/png');
    sigModal.style.display = 'none';
    if (pendingClick) {
      const { pageIndex, x_pct, y_pct } = pendingClick; pendingClick = null;
      const pw = document.querySelector(`[data-page="${pageIndex}"]`);
      if (pw) placeSignatureWidget(pageIndex, x_pct, y_pct, imgData, pw);
    }
  });

  // Cached per-stroke values to avoid getBoundingClientRect on every move
  let _modalSigRect = null, _modalSigScaleX = 1, _modalSigScaleY = 1, _modalSigLineW = 3;

  function cacheSigRect() {
    _modalSigRect   = sigCanvas.getBoundingClientRect();
    _modalSigScaleX = sigCanvas.width  / _modalSigRect.width;
    _modalSigScaleY = sigCanvas.height / _modalSigRect.height;
    _modalSigLineW  = parseInt(document.getElementById('sig-pen-width').value) || 3;
  }
  function getSigPos(e) {
    const src = e.touches ? e.touches[0] : e;
    return {
      x: (src.clientX - _modalSigRect.left) * _modalSigScaleX,
      y: (src.clientY - _modalSigRect.top)  * _modalSigScaleY
    };
  }
  function sigDraw(e) {
    if (!sigDrawing) return;
    const p = getSigPos(e);
    sigCtx.beginPath(); sigCtx.moveTo(sigLastX, sigLastY); sigCtx.lineTo(p.x, p.y);
    sigCtx.strokeStyle = '#1a1a2e';
    sigCtx.lineWidth   = _modalSigLineW;
    sigCtx.lineCap = sigCtx.lineJoin = 'round';
    sigCtx.stroke();
    sigLastX = p.x; sigLastY = p.y;
  }
  sigCanvas.addEventListener('mousedown',  e => { cacheSigRect(); sigDrawing = true; const p = getSigPos(e); sigLastX = p.x; sigLastY = p.y; });
  sigCanvas.addEventListener('mousemove',  sigDraw);
  sigCanvas.addEventListener('mouseup',    () => sigDrawing = false);
  sigCanvas.addEventListener('mouseleave', () => sigDrawing = false);
  sigCanvas.addEventListener('touchstart', e => { e.preventDefault(); cacheSigRect(); sigDrawing = true; const p = getSigPos(e); sigLastX = p.x; sigLastY = p.y; }, { passive: false });
  sigCanvas.addEventListener('touchmove',  e => { e.preventDefault(); sigDraw(e); }, { passive: false });
  sigCanvas.addEventListener('touchend',   () => sigDrawing = false);

  } catch(e) { console.error('[PDF Editor] init error:', e); }
})(); // end PDF Editor IIFE


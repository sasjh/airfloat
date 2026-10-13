(function () {
  'use strict';

  // ---- bridge ----
  // window.airfloat 由主进程通过 contextBridge 暴露（见 CONTRACT.md 第 5 节）。
  // 纯浏览器打开时不存在，进入“预览模式”：不报错、展示占位提示。
  const api = (typeof window !== 'undefined' && window.airfloat) ? window.airfloat : null;

  // ---- element refs ----
  const $ = function (id) { return document.getElementById(id); };
  const els = {
    banner: $('preview-banner'),
    alias: $('self-alias'),
    reveal: $('reveal-cache'),
    switch: $('enabled-switch'),
    modeList: $('mode-list'),
    deviceList: $('device-list'),
    deviceEmpty: $('device-empty'),
    port: $('image-port'),
    grid: $('thumb-grid'),
    emptyState: $('empty-state'),
    progress: $('progress'),
    progressFill: $('progress-fill'),
    progressLabel: $('progress-label'),
    statusHint: $('status-hint'),
    receivedCount: $('received-count'),
    toast: $('toast'),
  };

  // ---- state ----
  const MODES = ['everyone', 'contacts', 'off'];
  const DEVICE_ICONS = {
    mobile: '📱',
    desktop: '🖥️',
    web: '🌐',
    headless: '🤖',
    server: '🗄️',
  };

  let state = { enabled: false, receiveMode: 'everyone', alias: '', fingerprint: '', ip: '', port: 0 };
  let devices = [];
  let selectedFingerprint = null;
  let receivedItems = [];
  let unsubscribe = null;
  let toastTimer = null;
  let progressTimer = null;
  let dragDepth = 0;

  // ---- helpers ----
  function fileToPath(file) {
    if (file && typeof file.path === 'string' && file.path) return file.path;
    if (api && typeof api.getPathForFile === 'function') {
      try { const p = api.getPathForFile(file); if (p) return p; } catch (e) {}
    }
    return null;
  }

  function toFileUrl(p) {
    if (!p) return '';
    let norm = String(p).replace(/\\/g, '/');
    if (/^[a-zA-Z]:/.test(norm)) norm = '/' + norm;
    if (norm.charAt(0) !== '/') norm = '/' + norm;
    return 'file://' + encodeURI(norm);
  }

  function selectedDevice() {
    return devices.find(function (d) { return d.fingerprint === selectedFingerprint; }) || null;
  }

  function deviceIcon(type) {
    return DEVICE_ICONS[type] || '📡';
  }

  function showToast(msg, kind) {
    els.toast.textContent = msg;
    els.toast.className = 'toast' + (kind ? ' ' + kind : '');
    els.toast.hidden = false;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { els.toast.hidden = true; }, 3200);
  }

  function setProgress(pct, label) {
    if (progressTimer) clearTimeout(progressTimer);
    els.progress.hidden = false;
    els.progressFill.style.width = Math.max(0, Math.min(100, pct)) + '%';
    els.progressLabel.textContent = label || '';
  }

  function hideProgressSoon() {
    if (progressTimer) clearTimeout(progressTimer);
    progressTimer = setTimeout(function () { els.progress.hidden = true; }, 1200);
  }

  // ---- renderers ----
  function renderBanner() {
    els.banner.hidden = !!api;
  }

  function renderSwitch() {
    els.switch.checked = !!state.enabled;
  }

  function renderModes() {
    const mode = state.receiveMode;
    const buttons = els.modeList.querySelectorAll('.option');
    buttons.forEach(function (btn) {
      btn.classList.toggle('active', btn.dataset.mode === mode);
    });
  }

  function renderDevices() {
    els.deviceList.innerHTML = '';
    if (!devices.length) {
      els.deviceList.hidden = true;
      els.deviceEmpty.hidden = false;
      return;
    }
    els.deviceList.hidden = false;
    els.deviceEmpty.hidden = true;

    const frag = document.createDocumentFragment();
    devices.forEach(function (d) {
      const li = document.createElement('li');
      li.className = 'device' + (d.fingerprint === selectedFingerprint ? ' selected' : '');
      li.dataset.fingerprint = d.fingerprint;
      li.title = (d.alias || '未知设备') + ' · ' + (d.deviceType || '');

      const icon = document.createElement('span');
      icon.className = 'device-icon';
      icon.textContent = deviceIcon(d.deviceType);

      const meta = document.createElement('span');
      meta.className = 'device-meta';

      const alias = document.createElement('span');
      alias.className = 'device-alias';
      alias.textContent = d.alias || '未知设备';

      const type = document.createElement('span');
      type.className = 'device-type';
      type.textContent = d.deviceType || '';

      meta.appendChild(alias);
      meta.appendChild(type);
      li.appendChild(icon);
      li.appendChild(meta);
      frag.appendChild(li);
    });
    els.deviceList.appendChild(frag);
  }

  function makeThumb(item) {
    const div = document.createElement('div');
    div.className = 'thumb';
    div.draggable = true;
    div.dataset.path = item.filePath || '';
    div.dataset.name = item.fileName || '';
    div.title = item.fileName || '';

    const img = document.createElement('img');
    img.alt = item.fileName || '';
    img.draggable = false;
    img.loading = 'lazy';
    img.src = toFileUrl(item.filePath);
    img.addEventListener('error', function () {
      img.classList.add('img-broken');
    });

    const name = document.createElement('span');
    name.className = 'thumb-name';
    name.textContent = item.fileName || '';

    div.appendChild(img);
    div.appendChild(name);
    return div;
  }

  function renderThumbs() {
    els.grid.innerHTML = '';
    const hasItems = receivedItems.length > 0;
    els.grid.hidden = !hasItems;
    els.emptyState.hidden = hasItems;
    if (!hasItems) return;

    const frag = document.createDocumentFragment();
    receivedItems.forEach(function (item) { frag.appendChild(makeThumb(item)); });
    els.grid.appendChild(frag);
  }

  function renderReceivedCount() {
    const n = receivedItems.length;
    els.receivedCount.hidden = n === 0;
    els.receivedCount.textContent = '已接收 ' + n + ' 张';
  }

  function renderAlias() {
    els.alias.textContent = state.alias ? ('· ' + state.alias) : '';
  }

  function renderStatus() {
    let hint;
    if (!api) {
      hint = '预览模式：交互为本地模拟';
    } else if (!state.enabled) {
      hint = '隔空投送已关闭';
    } else if (selectedDevice()) {
      hint = '将发送到：' + selectedDevice().alias;
    } else if (devices.length > 0) {
      hint = '点击左侧设备以选择发送目标';
    } else {
      hint = '未发现手机，请确认同一 WiFi';
    }
    els.statusHint.textContent = hint;
  }

  function render() {
    renderBanner();
    renderSwitch();
    renderModes();
    renderDevices();
    renderThumbs();
    renderReceivedCount();
    renderAlias();
    renderStatus();
  }

  // ---- event handlers ----
  function handleEvent(ev) {
    if (!ev || !ev.type) return;
    switch (ev.type) {
      case 'devices':
        devices = Array.isArray(ev.devices) ? ev.devices.slice() : [];
        if (selectedFingerprint && !devices.some(function (d) { return d.fingerprint === selectedFingerprint; })) {
          selectedFingerprint = null;
        }
        renderDevices();
        renderStatus();
        break;
      case 'received':
        if (ev.item) {
          receivedItems.push(ev.item);
          if (receivedItems.length > 500) receivedItems = receivedItems.slice(-500);
          renderThumbs();
          renderReceivedCount();
          showToast('已接收：' + (ev.item.fileName || '图片'), 'success');
        }
        break;
      case 'state':
        if (ev.state) {
          state = Object.assign({}, state, ev.state);
          renderSwitch();
          renderModes();
          renderAlias();
          renderStatus();
        }
        break;
      case 'progress':
        if (ev.ev) {
          const e = ev.ev;
          const total = e.totalBytes || 0;
          const sent = e.sentBytes || 0;
          const pct = total > 0 ? Math.round((sent / total) * 100) : 0;
          setProgress(pct, '正在传输 ' + (e.fileName || '') + ' ' + pct + '%');
          if (pct >= 100) hideProgressSoon();
        }
        break;
      default:
        break;
    }
  }

  function hasFiles(e) {
    if (!e.dataTransfer || !e.dataTransfer.types) return false;
    const types = Array.prototype.slice.call(e.dataTransfer.types);
    return types.indexOf('Files') !== -1;
  }

  async function onDropFiles(e) {
    e.preventDefault();
    dragDepth = 0;
    els.port.classList.remove('dragging');
    const files = Array.prototype.slice.call(e.dataTransfer.files || []);
    const paths = files.map(fileToPath).filter(Boolean);

    if (!paths.length) {
      showToast('无法读取文件路径', 'error');
      return;
    }
    const target = selectedDevice();
    if (!target) {
      showToast('请先在左侧选择要发送的设备', 'error');
      return;
    }
    if (!api || typeof api.sendFiles !== 'function') {
      showToast('预览模式：无法发送（未连接主进程）', 'error');
      return;
    }
    try {
      await api.sendFiles(target.fingerprint, paths);
      showToast('已发送 ' + paths.length + ' 张到 ' + target.alias, 'success');
      hideProgressSoon();
    } catch (err) {
      showToast('发送失败：' + ((err && err.message) || '未知错误'), 'error');
    }
  }

  // ---- wire-up ----
  function wire() {
    els.switch.addEventListener('change', function () {
      const enabled = els.switch.checked;
      if (api && typeof api.setEnabled === 'function') {
        api.setEnabled(enabled).catch(function (err) {
          showToast('操作失败：' + ((err && err.message) || '未知错误'), 'error');
          renderSwitch();
        });
      } else {
        // 预览模式：仅本地模拟
        state.enabled = enabled;
        renderStatus();
      }
    });

    els.modeList.addEventListener('click', function (e) {
      const btn = e.target.closest('.option');
      if (!btn) return;
      const mode = btn.dataset.mode;
      if (MODES.indexOf(mode) === -1) return;
      state.receiveMode = mode;
      renderModes();
      if (api && typeof api.setReceiveMode === 'function') {
        api.setReceiveMode(mode).catch(function (err) {
          showToast('操作失败：' + ((err && err.message) || '未知错误'), 'error');
        });
      }
    });

    els.deviceList.addEventListener('click', function (e) {
      const li = e.target.closest('.device');
      if (!li) return;
      selectedFingerprint = li.dataset.fingerprint || null;
      renderDevices();
      renderStatus();
    });

    els.reveal.addEventListener('click', function () {
      if (api && typeof api.revealCache === 'function') {
        api.revealCache().catch(function (err) {
          showToast('打开失败：' + ((err && err.message) || '未知错误'), 'error');
        });
      } else {
        showToast('预览模式：无法打开接收目录', 'error');
      }
    });

    // 拖图片文件进右栏 -> 发送
    els.port.addEventListener('dragenter', function (e) {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragDepth += 1;
      els.port.classList.add('dragging');
    });
    els.port.addEventListener('dragover', function (e) {
      if (!hasFiles(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
    });
    els.port.addEventListener('dragleave', function (e) {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0) els.port.classList.remove('dragging');
    });
    els.port.addEventListener('drop', onDropFiles);

    // 缩略图拖出浮窗 -> dragOut
    els.grid.addEventListener('dragstart', function (e) {
      const thumb = e.target.closest('.thumb');
      if (!thumb) return;
      const filePath = thumb.dataset.path;
      e.dataTransfer.setData('text/plain', thumb.dataset.name || filePath);
      e.dataTransfer.effectAllowed = 'copy';
      if (api && typeof api.dragOut === 'function') {
        try {
          api.dragOut(filePath);
        } catch (err) { /* 忽略，主进程接管真实拖拽 */ }
      }
    });

    // 右键图片口 -> 打开接收目录
    els.port.addEventListener('contextmenu', function (e) {
      e.preventDefault();
      els.reveal.click();
    });
  }

  // ---- init ----
  async function init() {
    if (api && typeof api.onEvent === 'function') {
      unsubscribe = api.onEvent(handleEvent);
    }

    if (api) {
      if (typeof api.getState === 'function') {
        try { state = Object.assign({}, state, await api.getState()); } catch (err) { /* 忽略 */ }
      }
      if (typeof api.getDevices === 'function') {
        try {
          const list = await api.getDevices();
          if (Array.isArray(list)) devices = list;
        } catch (err) { /* 忽略 */ }
      }
    }

    render();
  }

  wire();
  init();
})();

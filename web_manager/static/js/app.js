/**
 * HITOS Manager - Frontend JavaScript
 */

const CONFIG = {
    updateInterval: 1000,
    apiBase: '/api'
};

const ICONS = {
    logs:    `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
    stop:    `<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="3" width="18" height="18" rx="2"/></svg>`,
    restart: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>`,
    play:    `<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>`,
    spinner: `<svg class="spin" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="9" stroke-opacity="0.2"/><path d="M12 3a9 9 0 019 9"/></svg>`,
};

let isConnected = false;
let updateTimer = null;
let lastNetworkData = {};
let lastNetworkTime = Date.now();
let lastSensorData  = {};
const MAX_SPEED = 100 * 1024 * 1024; // 100 MB/s

const expandedSparklines = new Set();  // "group:name" keys
let sparklineModalKey = null;          // currently open sparkline key
let latestTopicsData  = {};            // snapshot for modal refresh

// ── Utilities ────────────────────────────────────────────────────────────────

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${type === 'success' ? '✓' : type === 'error' ? '✗' : 'ℹ'}</span>
        <span class="toast-message">${message}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

function updateDateTime() {
    const now = new Date();
    const opts = { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric' };
    const el = document.getElementById('datetime');
    if (el) el.textContent = now.toLocaleDateString('es-ES', opts);
}

function setConnectionStatus(connected) {
    isConnected = connected;
    const indicator = document.getElementById('connection-status');
    if (!indicator) return;
    indicator.className = `status-indicator ${connected ? 'connected' : 'disconnected'}`;
    indicator.querySelector('.text').textContent = connected ? 'Connected' : 'Disconnected';
}

function formatBytes(bytes) {
    if (bytes < 1024)        return bytes.toFixed(0) + ' B/s';
    if (bytes < 1048576)     return (bytes / 1024).toFixed(1) + ' KB/s';
    return (bytes / 1048576).toFixed(2) + ' MB/s';
}

function escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── API ───────────────────────────────────────────────────────────────────────

async function fetchWithTimeout(url, options = {}, timeout = 5000) {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), timeout);
    try {
        const resp = await fetch(url, { ...options, signal: ctrl.signal, cache: 'no-store' });
        clearTimeout(tid);
        return resp;
    } catch (e) {
        clearTimeout(tid);
        throw e;
    }
}

async function fetchStatus() {
    try {
        const resp = await fetchWithTimeout(`${CONFIG.apiBase}/status`, {}, 8000);
        if (!resp.ok) throw new Error('bad response');
        const data = await resp.json();
        setConnectionStatus(true);
        return data;
    } catch {
        if (isConnected) setConnectionStatus(false);
        return null;
    }
}

async function relaunchProcess(name) {
    try {
        const resp = await fetchWithTimeout(
            `${CONFIG.apiBase}/processes/${encodeURIComponent(name)}/relaunch`,
            { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' },
            30000);
        const result = await resp.json();
        showToast(result.message || (result.success ? 'Restarted' : 'Failed'),
                  result.success ? 'success' : 'error');
        return result;
    } catch { showToast(`Error restarting ${name}`, 'error'); return { success: false }; }
}

async function stopProcess(name) {
    try {
        const resp = await fetchWithTimeout(
            `${CONFIG.apiBase}/processes/${encodeURIComponent(name)}/stop`,
            { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' },
            90000);
        const result = await resp.json();
        showToast(result.message || (result.success ? 'Stopped' : 'Failed'),
                  result.success ? 'success' : 'error');
        return result;
    } catch { showToast(`Error stopping ${name}`, 'error'); return { success: false }; }
}

async function fetchLogs(name, lines = 150) {
    try {
        const resp = await fetchWithTimeout(
            `${CONFIG.apiBase}/processes/${encodeURIComponent(name)}/logs?lines=${lines}`);
        return await resp.json();
    } catch (e) { return { success: false, message: e.message, logs: '' }; }
}

async function toggleTopic(group, name) {
    try {
        const resp = await fetchWithTimeout(
            `${CONFIG.apiBase}/topics/${encodeURIComponent(group)}/${encodeURIComponent(name)}/toggle`,
            { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
        const result = await resp.json();
        showToast(result.success ? `${name}: ${result.value ? 'ON' : 'OFF'}` : result.message,
                  result.success ? 'success' : 'error');
        return result;
    } catch { showToast(`Error toggling ${name}`, 'error'); return { success: false }; }
}

async function handleToggle(group, name) {
    await toggleTopic(group, name);
    await updateDashboard();
}

// ── Log modal ────────────────────────────────────────────────────────────────

let currentLogProcess = null;

function showLogModal(name) {
    currentLogProcess = name;
    document.getElementById('log-modal-title').textContent = `📋 Logs: ${name}`;
    document.getElementById('log-modal-content').textContent = 'Loading logs...';
    document.getElementById('log-modal').classList.add('show');
    refreshLogs();
}

function closeLogModal() {
    document.getElementById('log-modal').classList.remove('show');
    currentLogProcess = null;
}

async function refreshLogs() {
    if (!currentLogProcess) return;
    const content = document.getElementById('log-modal-content');
    const result = await fetchLogs(currentLogProcess);
    if (result.success) {
        const lines = (result.logs || 'No logs available').split('\n');
        content.innerHTML = lines.map(line => {
            const safe = escHtml(line);
            if (/\[FATAL\]|\[ERROR\]/.test(line)) return `<span class="log-error">${safe}</span>`;
            if (/\[WARN\]/.test(line))             return `<span class="log-warn">${safe}</span>`;
            if (/\[DEBUG\]/.test(line))            return `<span class="log-debug">${safe}</span>`;
            return safe;
        }).join('\n');
        content.parentElement.scrollTop = content.parentElement.scrollHeight;
    } else {
        content.innerHTML = escHtml(`Error: ${result.message || 'Failed to fetch logs'}`);
    }
}

document.addEventListener('click', e => {
    if (e.target.id === 'log-modal') closeLogModal();
    if (e.target.id === 'shutdown-modal') closeShutdownModal();
    if (e.target.id === 'sparkline-modal') closeSparklineModal();
});
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeLogModal(); closeShutdownModal(); closeSparklineModal(); }
});

// ── Shutdown ──────────────────────────────────────────────────────────────────

function showShutdownModal() {
    document.getElementById('shutdown-modal').classList.add('show');
}

function closeShutdownModal() {
    document.getElementById('shutdown-modal').classList.remove('show');
}

async function confirmShutdown() {
    closeShutdownModal();
    const btn = document.querySelector('.btn-shutdown');
    if (btn) { btn.innerHTML = ICONS.spinner; btn.disabled = true; }
    try {
        const resp = await fetchWithTimeout(`${CONFIG.apiBase}/system/shutdown`, { method: 'POST' }, 5000);
        const result = await resp.json();
        if (result.success) {
            if (updateTimer) clearInterval(updateTimer);
            setConnectionStatus(false);
            showToast('Shutting down...', 'info');
        } else {
            showToast(`Shutdown failed: ${result.message}`, 'error');
            if (btn) { btn.innerHTML = '⏻'; btn.disabled = false; }
        }
    } catch {
        if (updateTimer) clearInterval(updateTimer);
        setConnectionStatus(false);
        showToast('Shutting down...', 'info');
    }
}

// ── Render: Processes ────────────────────────────────────────────────────────

function renderProcesses(processes) {
    const container = document.getElementById('processes-container');
    if (!processes || !Object.keys(processes).length) {
        container.innerHTML = '<div class="loading">No processes configured</div>';
        return;
    }
    let html = '<div class="process-list">';
    for (const [name, info] of Object.entries(processes)) {
        const active = info.active;
        const canStop    = info.can_relaunch && active;
        const canRelaunch = info.can_relaunch;
        const actionIcon  = active ? ICONS.restart : ICONS.play;
        const startTitle = active ? `Restart ${name}` : `Start ${name}`;
        html += `
        <div class="process-item ${active ? 'active' : ''}">
            <div class="process-info">
                <svg class="status-badge ${active ? 'active' : ''}" width="18" height="13" viewBox="0 0 18 13" title="${active ? 'Running' : 'Stopped'}"><rect width="18" height="13" rx="3"/><circle cx="9" cy="6.5" r="2.5"/></svg>
                <span class="process-name" title="${escHtml(info.description || '')}">${escHtml(name)}</span>
            </div>
            <div class="process-actions">
                <button class="btn btn-logs" onclick="showLogModal('${escHtml(name)}')" title="View logs"${!canRelaunch ? ' disabled' : ''}>${ICONS.logs}</button>
                <button class="btn btn-stop" onclick="handleStop('${escHtml(name)}', this)" title="Stop"${!canStop ? ' disabled' : ''}>${ICONS.stop}</button>
                <button class="btn btn-relaunch${active ? '' : ' btn-start'}" onclick="handleRelaunch('${escHtml(name)}', this)" title="${startTitle}"${!canRelaunch ? ' disabled' : ''}>${actionIcon}</button>
            </div>
        </div>`;
    }
    html += '</div>';
    container.innerHTML = html;
}

// ── Sparkline helpers ─────────────────────────────────────────────────────

const ICON_CHART = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>`;

function makeSvgSparkline(data, width, height, active, axes) {
    const color     = 'var(--pal-green)';
    const areaColor = 'var(--pal-green)';
    const fs     = axes ? 11 : 9;
    const pad    = axes ? 34 : 2;
    const topPad = axes ? 8 : pad;
    const botPad = axes ? 18 : pad;
    const w = width - pad - 2;
    const h = height - topPad - botPad;
    const yBot = topPad + h;

    const nonNullData = data ? data.filter(v => v !== null && v !== undefined) : [];

    // Empty / no-data state: flat dashed baseline
    // active=false → red (offline), active=true → gray (waiting for data)
    if (!data || nonNullData.length < 2) {
        const lineColor = active ? 'var(--clr-muted)' : 'var(--clr-danger)';
        const txtColor  = active ? 'var(--clr-muted)' : 'var(--clr-danger)';
        const zeroLabel = axes ? `<text x="${pad-3}" y="${yBot+1}" text-anchor="end" font-size="${fs}" fill="${txtColor}">0</text>` : '';
        const nowLabel  = axes ? `<text x="${pad+w+2}" y="${yBot+botPad-2}" text-anchor="end" font-size="${fs}" fill="var(--clr-muted)">now</text>` : '';
        return `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" style="width:100%;height:${height}px">
            ${zeroLabel}${nowLabel}
            <line x1="${pad}" y1="${yBot}" x2="${pad+w}" y2="${yBot}"
                  stroke="${lineColor}" stroke-width="1" stroke-dasharray="3,4" opacity="0.5"/>
        </svg>`;
    }

    const maxVal = Math.max(...nonNullData, 0.1);
    const n = data.length;

    // Split data into active segments (non-null runs) and N/A ranges (null runs)
    const activeSegments = [];  // arrays of "x,y" point strings
    const naRanges = [];        // [x1, x2] pixel pairs for N/A zones

    let currentPts = null;
    let naStart = null;

    for (let i = 0; i < n; i++) {
        const v = data[i];
        const x = n > 1 ? pad + (i / (n - 1)) * w : pad + w;
        const isNull = v === null || v === undefined;

        if (!isNull) {
            const y = topPad + (1 - v / maxVal) * h;
            if (currentPts === null) currentPts = [];
            currentPts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
            if (naStart !== null) {
                naRanges.push([naStart, x]);
                naStart = null;
            }
        } else {
            if (currentPts !== null) {
                activeSegments.push(currentPts);
                currentPts = null;
            }
            if (naStart === null) {
                // Start the null range slightly before this index for visual continuity
                naStart = i > 0 ? pad + ((i - 0.5) / (n - 1)) * w : x;
            }
        }
    }
    if (currentPts !== null) activeSegments.push(currentPts);
    if (naStart !== null) naRanges.push([naStart, pad + w]);

    const xN = pad + w;
    let gridHtml = '', axisHtml = '';

    if (axes) {
        // Y grid lines at 25 / 50 / 75 %
        for (const frac of [0.25, 0.5, 0.75]) {
            const yg   = (topPad + (1 - frac) * h).toFixed(1);
            const vLbl = (maxVal * frac) < 10 ? (maxVal * frac).toFixed(1) : Math.round(maxVal * frac);
            gridHtml += `<line x1="${pad}" y1="${yg}" x2="${xN}" y2="${yg}" stroke="var(--clr-border)" stroke-width="0.5" stroke-dasharray="2,4"/>`;
            gridHtml += `<text x="${pad-3}" y="${(+yg+4).toFixed(1)}" text-anchor="end" font-size="${fs}" fill="var(--clr-muted)">${vLbl}</text>`;
        }
        // X grid lines — step chosen by history length
        const xStep = n > 180 ? 60 : n > 60 ? 30 : 10;
        for (let secAgo = xStep; secAgo < n; secAgo += xStep) {
            const idx = n - 1 - secAgo;
            if (idx < 0) continue;
            const xg = (pad + (idx / (n - 1)) * w).toFixed(1);
            gridHtml += `<line x1="${xg}" y1="${topPad}" x2="${xg}" y2="${yBot}" stroke="var(--clr-border)" stroke-width="0.5" stroke-dasharray="2,4"/>`;
            gridHtml += `<text x="${xg}" y="${yBot+botPad-2}" text-anchor="middle" font-size="${fs}" fill="var(--clr-muted)">-${secAgo}s</text>`;
        }
        // Axis lines + corner labels
        axisHtml = `
        <line x1="${pad}" y1="${topPad}" x2="${pad}" y2="${yBot}" stroke="var(--clr-border)" stroke-width="1"/>
        <line x1="${pad}" y1="${yBot}" x2="${xN}" y2="${yBot}" stroke="var(--clr-border)" stroke-width="1"/>
        <text x="${pad-3}" y="${topPad+fs}" text-anchor="end" font-size="${fs}" fill="var(--clr-muted)">${maxVal < 10 ? maxVal.toFixed(1) : Math.round(maxVal)}</text>
        <text x="${pad-3}" y="${yBot}" text-anchor="end" font-size="${fs}" fill="var(--clr-muted)">0</text>
        <text x="${pad}" y="${yBot+botPad-2}" font-size="${fs}" fill="var(--clr-muted)">-${n}s</text>
        <text x="${xN}" y="${yBot+botPad-2}" text-anchor="end" font-size="${fs}" fill="var(--clr-muted)">now</text>`;
    } else {
        // Inline: max-Hz label top-right, "0" bottom-left
        const maxLbl = maxVal < 10 ? maxVal.toFixed(1) : Math.round(maxVal);
        axisHtml = `
        <text x="${xN}" y="${topPad+fs}" text-anchor="end" font-size="${fs}" fill="var(--clr-muted)" opacity="0.8">${maxLbl}</text>
        <text x="${pad}" y="${yBot-1}" font-size="${fs}" fill="var(--clr-muted)" opacity="0.6">0</text>`;
    }

    // N/A zones: red band at y=0 (zero-frequency level)
    let naHtml = '';
    const bandH = Math.max(3, Math.round(h * 0.05));
    for (const [x1, x2] of naRanges) {
        const rw = Math.max(1, x2 - x1).toFixed(1);
        naHtml += `<rect x="${x1.toFixed(1)}" y="${(yBot - bandH).toFixed(1)}" width="${rw}" height="${bandH}" fill="var(--clr-danger)" fill-opacity="0.7" rx="1"/>`;
    }

    // Active data segments
    let dataHtml = '';
    for (const pts of activeSegments) {
        if (pts.length < 2) continue;
        const x0s = pts[0].split(',')[0];
        const xNs = pts[pts.length - 1].split(',')[0];
        dataHtml += `<polygon points="${x0s},${yBot} ${pts.join(' ')} ${xNs},${yBot}" fill="${areaColor}" fill-opacity="0.12"/>`;
        dataHtml += `<polyline points="${pts.join(' ')}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>`;
    }

    return `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" style="width:100%;height:${height}px">
        ${gridHtml}${axisHtml}${naHtml}${dataHtml}
    </svg>`;
}

function toggleSparkline(group, name) {
    const key = `${group}:${name}`;
    if (expandedSparklines.has(key)) {
        expandedSparklines.delete(key);
    } else {
        expandedSparklines.add(key);
    }
    // Re-render only the affected topic item to avoid full redraw flicker
    const topics = latestTopicsData[group];
    if (topics && topics[name]) {
        const container = document.getElementById(`${group}-container`);
        if (container) renderTopics(latestTopicsData[group], group);
    }
}

function openSparklineModal(group, name) {
    sparklineModalKey = `${group}:${name}`;
    refreshSparklineModal();
    document.getElementById('sparkline-modal').classList.add('show');
}

function closeSparklineModal() {
    document.getElementById('sparkline-modal').classList.remove('show');
    sparklineModalKey = null;
}

function refreshSparklineModal() {
    if (!sparklineModalKey) return;
    const [group, name] = sparklineModalKey.split(':');
    const info = (latestTopicsData[group] || {})[name];
    if (!info) return;

    document.getElementById('sparkline-modal-title').textContent =
        `📈 ${name} — ${info.topic || ''}`;

    const history = info.history || [];
    const chartDiv = document.getElementById('sparkline-modal-chart');
    const chartW = Math.max(400, chartDiv.clientWidth || 640);
    chartDiv.innerHTML = makeSvgSparkline(history, chartW, 220, info.active, true);

    const hzEl = document.getElementById('sparkline-modal-hz');
    hzEl.textContent = info.value || 'N/A';
    hzEl.className = `sparkline-modal-hz ${info.active ? '' : 'inactive'}`;

    document.getElementById('sparkline-modal-range').textContent =
        `last ${history.length}s`;
}

// ── Render: Topics ───────────────────────────────────────────────────────────

function renderTopics(topics, group) {
    const container = document.getElementById(`${group}-container`);
    if (!container) return;
    if (!topics || !Object.keys(topics).length) {
        container.innerHTML = '<div class="loading">No topics configured</div>';
        return;
    }
    let html = '';
    for (const [name, info] of Object.entries(topics)) {
        const active = info.active;
        const hasHistory = info.show === 'hz' && Array.isArray(info.history);
        const key = `${group}:${name}`;
        const isExpanded = expandedSparklines.has(key);

        const extraFields = Object.entries(info).filter(([k]) =>
            !['name', 'topic', 'show', 'active', 'value', 'toggleable', 'history'].includes(k));

        let extraHtml = '';
        if (extraFields.length) {
            extraHtml = '<div class="topic-extra">';
            for (const [k, v] of extraFields) {
                extraHtml += `<div class="topic-extra-item"><span class="extra-label">${escHtml(k)}:</span> <span class="extra-value">${escHtml(String(v))}</span></div>`;
            }
            extraHtml += '</div>';
        }

        let sparklineHtml = '';
        if (hasHistory && isExpanded) {
            const recent = info.history ? info.history.slice(-60) : [];
            const svg = makeSvgSparkline(recent, 400, 44, active, false);
            sparklineHtml = `<div class="topic-sparkline-row">
                <div class="sparkline-svg" onclick="openSparklineModal('${group}','${escHtml(name)}')" title="Click to expand full history">${svg}</div>
            </div>`;
        }

        const chartBtn = hasHistory
            ? `<button class="btn-sparkline${isExpanded ? ' expanded' : ''}" onclick="toggleSparkline('${group}','${escHtml(name)}')" title="Toggle frequency history">${ICON_CHART}</button>`
            : '';

        const isBool = info.value === 'True' || info.value === 'False'
                    || info.value === true  || info.value === false;
        const boolOn = info.value === 'True' || info.value === true;
        let valueHtml;
        if (isBool) {
            valueHtml = `<div class="topic-toggle ${boolOn ? 'on' : 'off'}" onclick="handleToggle('${group}','${escHtml(name)}')">
                <span class="toggle-label">${boolOn ? 'ON' : 'OFF'}</span>
                <span class="toggle-switch"></span>
            </div>`;
        } else {
            valueHtml = `<div class="topic-value">${escHtml(info.value || 'N/A')}</div>`;
        }

        html += `
        <div class="topic-item ${active ? 'active' : ''}">
            <div class="topic-header">
                <svg class="status-badge ${active ? 'active' : ''}" width="14" height="13" viewBox="0 0 14 13"><rect width="14" height="13" rx="3"/><circle cx="7" cy="6.5" r="2.5"/></svg>
                <span class="topic-name">${escHtml(name)}</span>
                ${chartBtn}
            </div>
            <div class="topic-path">${escHtml(info.topic || '')}</div>
            ${valueHtml}
            ${extraHtml}
            ${sparklineHtml}
        </div>`;
    }
    container.innerHTML = html;
}

function renderAllTopics(topicsData) {
    latestTopicsData = topicsData;
    for (const [group, topics] of Object.entries(topicsData)) {
        renderTopics(topics, group);
    }
    if (sparklineModalKey) refreshSparklineModal();
}

// ── Render: Network ───────────────────────────────────────────────────────────

function renderNetwork(networkData) {
    const container = document.getElementById('network-container');
    if (!container || !networkData) return;
    const now = Date.now();
    const dt  = (now - lastNetworkTime) / 1000;

    let html = '<div class="network-list">';
    for (const [iface, info] of Object.entries(networkData)) {
        let rxSpeed = 0, txSpeed = 0;
        if (lastNetworkData[iface] && dt > 0) {
            rxSpeed = Math.max(0, (info.rx_bytes - lastNetworkData[iface].rx_bytes) / dt);
            txSpeed = Math.max(0, (info.tx_bytes - lastNetworkData[iface].tx_bytes) / dt);
        }
        const rxPct = rxSpeed > 0 ? Math.min(100, Math.log10(rxSpeed + 1) / Math.log10(MAX_SPEED) * 100) : 0;
        const txPct = txSpeed > 0 ? Math.min(100, Math.log10(txSpeed + 1) / Math.log10(MAX_SPEED) * 100) : 0;

        let sensorHtml = '';
        if (info.sensors) {
            sensorHtml = '<div class="network-sensors">';
            const sensorEntries = Object.entries(info.sensors);
            for (let si = 0; si < sensorEntries.length; si++) {
                const [ip, s] = sensorEntries[si];
                if (si > 0) sensorHtml += '<div class="sensor-separator"></div>';
                const prev = (lastSensorData[ip] || {});
                let srx = 0, stx = 0;
                if (prev.rx !== undefined && dt > 0) {
                    srx = Math.max(0, (s.rx_bytes - prev.rx) / dt);
                    stx = Math.max(0, (s.tx_bytes - prev.tx) / dt);
                }
                lastSensorData[ip] = { rx: s.rx_bytes, tx: s.tx_bytes };
                const srxPct = srx > 0 ? Math.min(100, Math.log10(srx + 1) / Math.log10(MAX_SPEED) * 100) : 0;
                const stxPct = stx > 0 ? Math.min(100, Math.log10(stx + 1) / Math.log10(MAX_SPEED) * 100) : 0;
                sensorHtml += `
                <div class="network-sensor-item">
                    <div class="network-sensor-header">
                        <span class="network-sensor-name">${escHtml(s.label)}</span>
                        <span class="network-sensor-ip">${escHtml(ip)}</span>
                    </div>
                    <div class="network-bars">
                        <div class="network-bar-row">
                            <span class="network-bar-label upload">↑</span>
                            <div class="network-bar-container">
                                <div class="network-bar upload" style="width:${stxPct.toFixed(1)}%"></div>
                            </div>
                            <span class="network-bar-value">${formatBytes(stx)}</span>
                        </div>
                        <div class="network-bar-row">
                            <span class="network-bar-label download">↓</span>
                            <div class="network-bar-container">
                                <div class="network-bar download" style="width:${srxPct.toFixed(1)}%"></div>
                            </div>
                            <span class="network-bar-value">${formatBytes(srx)}</span>
                        </div>
                    </div>
                </div>`;
            }
            sensorHtml += '</div>';
        }

        html += `
        <div class="network-item ${info.active ? 'active' : ''}">
            <div class="network-header">
                <span class="status-dot ${info.active ? 'active' : ''}"></span>
                <span class="network-name">${escHtml(iface)}:</span>
                <span class="network-label">${escHtml(info.label)}</span>
            </div>
            <div class="network-bars">
                <div class="network-bar-row">
                    <span class="network-bar-label upload">↑</span>
                    <div class="network-bar-container">
                        <div class="network-bar upload" style="width:${txPct.toFixed(1)}%"></div>
                    </div>
                    <span class="network-bar-value">${formatBytes(txSpeed)}</span>
                </div>
                <div class="network-bar-row">
                    <span class="network-bar-label download">↓</span>
                    <div class="network-bar-container">
                        <div class="network-bar download" style="width:${rxPct.toFixed(1)}%"></div>
                    </div>
                    <span class="network-bar-value">${formatBytes(rxSpeed)}</span>
                </div>
            </div>
            ${sensorHtml}
        </div>`;
    }
    html += '</div>';
    container.innerHTML = html;
    lastNetworkData = networkData;
    lastNetworkTime = now;
}

// ── Render: System metrics ────────────────────────────────────────────────────

function renderSystemMetrics(metrics) {
    if (!metrics) return '';
    const cpuCores = metrics.cpu_cores || [];
    const ram  = metrics.ram  || {};
    const swap = metrics.swap || {};

    function cpuItem(i) {
        const p = typeof cpuCores[i] === 'number' ? cpuCores[i] : 0;
        return `<div class="metric-cpu-item">
            <span class="metric-cpu-label">Core ${i}</span>
            <div class="metric-bar-track-long"><div class="metric-bar-fill cpu" style="width:${Math.min(100,p).toFixed(1)}%"></div></div>
            <span class="metric-pct-lbl">${p.toFixed(0)}%</span>
        </div>`;
    }

    function memItem(label, pct, barClass, sub) {
        const p = typeof pct === 'number' ? pct : 0;
        return `<div class="metric-mem-item">
            <div class="metric-mem-header">
                <span class="metric-cpu-label">${escHtml(label)}</span>
                ${sub ? `<span class="metric-sub">${escHtml(sub)}</span>` : ''}
            </div>
            <div class="metric-mem-bar-row">
                <div class="metric-bar-track-long"><div class="metric-bar-fill ${barClass}" style="width:${Math.min(100,p).toFixed(1)}%"></div></div>
                <span class="metric-pct-lbl">${p.toFixed(0)}%</span>
            </div>
        </div>`;
    }

    const ramSub  = ram.used_mb  != null
        ? `${(ram.used_mb/1024).toFixed(1)} / ${(ram.total_mb/1024).toFixed(1)} GB` : null;
    const swapSub = swap.used_mb != null
        ? `${swap.used_mb} / ${swap.total_mb} MB` : null;

    let html = '<div class="system-section"><div class="system-section-header">CPU</div>';
    html += '<div class="metric-grid-2col metric-grid-cpu">';
    for (let i = 0; i < 4; i++) html += cpuItem(i);
    html += '</div></div>';

    html += '<div class="system-section"><div class="system-section-header">Memory</div>';
    html += '<div class="metric-grid-2col">';
    html += memItem('RAM',  ram.pct  ?? 0, 'mem',  ramSub);
    html += memItem('Swap', swap.pct ?? 0, 'swap', swapSub);
    html += '</div></div>';

    return html;
}

// ── Render: System ────────────────────────────────────────────────────────────

function renderSystemInfo(systemData) {
    const container = document.getElementById('system-container');
    if (!container || !systemData) return;
    const sections = (systemData.env || {}).sections || [];

    let html = '<div class="system-info-list">';
    for (const section of sections) {
        html += `<div class="system-section">`;
        html += `<div class="system-section-header">${escHtml(section.title)}</div>`;
        for (const item of section.items) {
            const [label, value, ok] = item;
            const hasStatus = ok !== undefined && ok !== null;
            const dot = hasStatus
                ? `<span class="status-dot ${ok ? 'active' : ''}"></span>`
                : '';
            html += `<div class="system-info-item">
                <span class="system-info-label">${escHtml(label)}</span>
                <span class="system-info-value">${dot}${escHtml(value)}</span>
            </div>`;
        }
        html += `</div>`;
    }

    const ptpActive = systemData.ptp_active;
    html += `<div class="system-section">`;
    html += `<div class="system-section-header">PTP</div>`;
    html += `<div class="system-info-item">
        <span class="system-info-label">PTP Master</span>
        <span class="system-info-value">
            <span class="status-dot ${ptpActive ? 'active' : ''}"></span>
            ${ptpActive ? 'Active' : 'Not running'}
        </span>
    </div>`;
    if (ptpActive && systemData.ptp_offsets)
        for (const [iface, data] of Object.entries(systemData.ptp_offsets)) {
            html += `<div class="ptp-item">
                <span class="system-info-label">&nbsp;&nbsp;${escHtml(iface)} offset</span>
                <span class="ptp-value">${escHtml(data.offset)}</span>
            </div>`;
            html += `<div class="ptp-item">
                <span class="system-info-label">&nbsp;&nbsp;${escHtml(iface)} delay</span>
                <span class="ptp-value">${escHtml(data.delay)}</span>
            </div>`;
        }
    html += `</div>`;

    html += '</div>';   // close system-info-list
    html += `<div class="system-metrics-area">${renderSystemMetrics(systemData.metrics)}</div>`;
    container.innerHTML = html;
}

// ── Event handlers ────────────────────────────────────────────────────────────

async function handleRelaunch(name, btn) {
    const orig = btn.innerHTML;
    btn.innerHTML = ICONS.spinner; btn.disabled = true;
    await relaunchProcess(name);
    setTimeout(() => { btn.innerHTML = orig; btn.disabled = false; }, 1000);
}

async function handleStop(name, btn) {
    if (!confirm(`Stop "${name}"?`)) return;
    const orig = btn.innerHTML;
    btn.innerHTML = ICONS.spinner; btn.disabled = true;
    await stopProcess(name);
    setTimeout(() => { btn.innerHTML = orig; }, 1000);
    await updateDashboard();
}

// ── Masonry reorder ───────────────────────────────────────────────────────────

const COLUMN_LAYOUTS = {
    2: [
        ['processes', 'sensors', 'network'],
        ['fusion', 'cameras', 'system'],
    ],
    3: [
        ['processes', 'sensors', 'fusion'],
        ['cameras', 'system'],
        ['network'],
    ],
};

function reorderCardsForMasonry() {
    const container = document.getElementById('main-container');
    if (!container) return;
    const cols = parseInt(getComputedStyle(container).columnCount) || 3;
    const cards = Array.from(container.querySelectorAll('.card[data-section]'));
    const cardMap = Object.fromEntries(cards.map(c => [c.dataset.section, c]));

    cards.forEach(c => c.style.removeProperty('break-after'));

    const layout = COLUMN_LAYOUTS[cols] || COLUMN_LAYOUTS[3];
    const reordered = [];
    layout.forEach((col, ci) => {
        col.forEach(section => { if (cardMap[section]) reordered.push(cardMap[section]); });
        if (ci < layout.length - 1 && reordered.length)
            reordered[reordered.length - 1].style.breakAfter = 'column';
    });
    reordered.forEach(c => container.appendChild(c));
}

let resizeTimer;
window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(reorderCardsForMasonry, 150); });

// ── Main loop ─────────────────────────────────────────────────────────────────

async function updateDashboard() {
    const data = await fetchStatus();
    if (!data) return;
    const renders = [
        ['processes', () => renderProcesses(data.processes)],
        ['topics',    () => renderAllTopics(data.topics)],
        ['network',   () => renderNetwork(data.network)],
        ['system',    () => renderSystemInfo(data.system)],
    ];
    for (const [name, fn] of renders) {
        try { fn(); }
        catch(e) { console.error(`[HITOS] render ${name} failed:`, e); }
    }
}

function startUpdateLoop() {
    reorderCardsForMasonry();
    updateDashboard();
    updateDateTime();
    updateTimer = setInterval(updateDashboard, CONFIG.updateInterval);
    setInterval(updateDateTime, 1000);
}

// ── GUI links ─────────────────────────────────────────────────────────────────

function openGui(guiName) {
    const gui = (typeof GUI_LINKS !== 'undefined') ? GUI_LINKS[guiName] : null;
    if (!gui) { showToast(`Unknown GUI: ${guiName}`, 'error'); return; }
    const url = `${location.protocol}//${location.hostname}:${gui.port}${gui.path || '/'}`;
    window.open(url, `_${guiName}_gui`);
    showToast(`Opening ${gui.name}...`, 'info');
}

document.addEventListener('DOMContentLoaded', () => {
    console.log('HITOS Manager initializing...');
    if (window.SharedUiCore) SharedUiCore.initThemeToggle();
    startUpdateLoop();
});

window.addEventListener('beforeunload', () => { if (updateTimer) clearInterval(updateTimer); });

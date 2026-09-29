// ==================== 门禁管理页面 JS（香橙派人脸识别展示版）===========================
// 功能：接收香橙派推送的人脸识别结果，展示实时识别状态和事件记录

let facePollTimer = null;
let lastEventId = null;

document.addEventListener('DOMContentLoaded', () => {
    updateClock();
    setInterval(updateClock, 1000);
    loadPersons();
    loadAccessLogs();
    loadFaceEvents();
    startFacePolling();
});

// 时钟
function updateClock() {
    const now = new Date();
    const el = document.getElementById('currentTime');
    const locale = I18N.currentLang === 'zh' ? 'zh-CN' : 'en-US';
    if (el) el.textContent = now.toLocaleTimeString(locale, { hour12: false });
}

// 通知
function showNotification(message, type = 'info') {
    const el = document.getElementById('notification');
    if (!el) return;
    el.textContent = message;
    el.className = `notification ${type} show`;
    setTimeout(() => { el.className = 'notification hidden'; }, 3000);
}

// API
async function apiGet(url) {
    try {
        const res = await fetch(url);
        return await res.json();
    } catch (e) {
        console.error('API error:', e);
        return null;
    }
}

async function apiPost(url, data) {
    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    } catch (e) {
        console.error('API error:', e);
        return null;
    }
}

// ==================== 实时识别结果轮询 ====================

function startFacePolling() {
    // 每2秒轮询最新识别事件
    facePollTimer = setInterval(pollLatestFaceEvent, 2000);
}

async function pollLatestFaceEvent() {
    const event = await apiGet('/api/face/events/latest');
    if (!event || !event.id) return;

    // 只有新事件才更新UI
    if (lastEventId === event.id) return;
    lastEventId = event.id;

    updateFaceResultDisplay(event);
}

function updateFaceResultDisplay(event) {
    const waitingEl = document.getElementById('faceResultWaiting');
    const contentEl = document.getElementById('faceResultContent');
    const statusEl = document.getElementById('faceResultStatus');
    const nameEl = document.getElementById('faceResultName');
    const metaEl = document.getElementById('faceResultMeta');
    const iconEl = document.getElementById('faceResultIcon');

    // 隐藏等待状态，显示结果
    waitingEl.classList.add('hidden');
    contentEl.classList.remove('hidden');

    const isGranted = event.status === 'granted';
    const lang = I18N.currentLang;

    // 状态样式
    if (isGranted) {
        statusEl.className = 'face-result-status granted';
        iconEl.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="#00e676" stroke-width="2.5">
                <path d="M20 6L9 17l-5-5"/>
            </svg>`;
        nameEl.textContent = event.person_name || t('access.unknown');
        metaEl.textContent = lang === 'zh' ? '验证通过' : 'Access Granted';
        metaEl.style.color = '#00e676';
    } else {
        statusEl.className = 'face-result-status denied';
        iconEl.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="#ff1744" stroke-width="2.5">
                <circle cx="12" cy="12" r="10"/>
                <line x1="15" y1="9" x2="9" y2="15"/>
                <line x1="9" y1="9" x2="15" y2="15"/>
            </svg>`;
        nameEl.textContent = event.person_name || t('access.unknown');
        metaEl.textContent = lang === 'zh' ? '访问被拒绝' : 'Access Denied';
        metaEl.style.color = '#ff1744';
    }

    // 详细信息
    document.getElementById('faceResultId').textContent = event.face_id || '--';
    document.getElementById('faceResultConfidence').textContent =
        event.confidence ? (event.confidence * 100).toFixed(1) + '%' : '--';

    const dt = new Date(event.timestamp);
    const locale = lang === 'zh' ? 'zh-CN' : 'en-US';
    document.getElementById('faceResultTime').textContent =
        dt.toLocaleString(locale);
    document.getElementById('faceResultSource').textContent =
        event.device_source || 'orange_pi';

    // 通知
    const msg = isGranted
        ? (lang === 'zh' ? `${event.person_name} 已通过验证` : `${event.person_name} verified`)
        : (lang === 'zh' ? '未授权人员，访问被拒绝' : 'Unauthorized access denied');
    showNotification(msg, isGranted ? 'success' : 'error');

    // 刷新事件列表和门禁日志
    loadFaceEvents();
    loadAccessLogs();
}

// ==================== 模拟香橙派推送（测试用） ====================

async function simulatePush(faceId, confidence) {
    const resultEl = document.getElementById('accessResult');
    resultEl.textContent = t('access.pushing');
    resultEl.className = 'access-result';

    // 调用 /api/face/notify 模拟香橙派推送
    const res = await apiPost('/api/face/notify', {
        face_id: faceId,
        confidence: confidence,
        image_path: `/tmp/face_${faceId}.jpg`,
        device_source: 'orange_pi_test'
    });

    if (res) {
        if (res.granted) {
            resultEl.textContent = res.message;
            resultEl.className = 'access-result granted';
        } else {
            resultEl.textContent = res.message;
            resultEl.className = 'access-result denied';
        }
    }
}

// ==================== 人脸识别事件列表 ====================

async function loadFaceEvents() {
    const events = await apiGet('/api/face/events?limit=20');
    if (!events) return;

    const body = document.getElementById('faceEventBody');
    const lang = I18N.currentLang;

    if (events.length === 0) {
        body.innerHTML = `<tr><td colspan="6">${t('access.no_events')}</td></tr>`;
        return;
    }

    let html = '';
    events.forEach(evt => {
        const dt = new Date(evt.timestamp);
        const locale = lang === 'zh' ? 'zh-CN' : 'en-US';
        const timeStr = dt.toLocaleString(locale);

        const statusClass = evt.status === 'granted' ? 'granted' : 'denied';
        const statusText = evt.status === 'granted'
            ? (lang === 'zh' ? '已通过' : 'Granted')
            : (lang === 'zh' ? '已拒绝' : 'Denied');

        html += `
            <tr>
                <td>${timeStr}</td>
                <td>${evt.person_name || (lang === 'zh' ? '未知' : 'Unknown')}</td>
                <td>${evt.face_id || '--'}</td>
                <td>${evt.confidence ? (evt.confidence * 100).toFixed(1) + '%' : '--'}</td>
                <td><span class="status-tag ${statusClass}">${statusText}</span></td>
                <td>${evt.device_source || 'orange_pi'}</td>
            </tr>
        `;
    });

    body.innerHTML = html;
}

// ==================== 授权人员管理 ====================

async function loadPersons() {
    const persons = await apiGet('/api/access/persons');
    if (!persons) return;

    const listEl = document.getElementById('personList');
    let html = '';

    persons.forEach((p, i) => {
        const initial = p.name.charAt(0);
        const colors = ['#00e5ff', '#00e676', '#7c4dff', '#ff9100', '#ff1744'];
        const color = colors[i % colors.length];
        const faceIdDisplay = p.face_id || t('access.unset');
        html += `
            <div class="person-item">
                <div class="person-info">
                    <div class="person-avatar" style="background: ${color}">${initial}</div>
                    <div>
                        <div class="person-name">${p.name}</div>
                        <div class="person-rfid">${I18N.currentLang === 'zh' ? '人脸ID' : 'Face ID'}: ${faceIdDisplay}</div>
                    </div>
                </div>
            </div>
        `;
    });

    listEl.innerHTML = html || '<div class="loading">' + t('access.no_persons') + '</div>';
}

async function addPerson() {
    const nameInput = document.getElementById('newPersonName');
    const rfidInput = document.getElementById('newPersonRFID');
    const name = nameInput.value.trim();
    const faceId = rfidInput.value.trim();

    if (!name) {
        showNotification(t('notify.enter_name'), 'error');
        return;
    }

    const res = await apiPost('/api/access/persons', { name: name, face_id: faceId });
    if (res) {
        if (res.message) {
            const msg = I18N.currentLang === 'en' ? (res.message_en || res.message) : res.message;
            showNotification(msg, 'success');
            nameInput.value = '';
            rfidInput.value = '';
            loadPersons();
        } else if (res.error) {
            const err = I18N.currentLang === 'en' ? (res.error_en || res.error) : res.error;
            showNotification(err, 'error');
        }
    }
}

// ==================== 门禁日志 ====================

async function loadAccessLogs() {
    const logs = await apiGet('/api/access/logs');
    if (!logs) return;

    const body = document.getElementById('accessLogBody');
    let html = '';

    logs.forEach(log => {
        const dt = new Date(log.timestamp);
        const locale = I18N.currentLang === 'zh' ? 'zh-CN' : 'en-US';
        const timeStr = dt.toLocaleString(locale);
        const statusClass = log.status === 'granted' ? 'granted' : 'denied';
        const statusText = log.status === 'granted' ? t('access.log_granted') : t('access.log_denied');

        html += `
            <tr>
                <td>${timeStr}</td>
                <td>${log.person_name}</td>
                <td>${log.access_type.toUpperCase()}</td>
                <td><span class="status-tag ${statusClass}">${statusText}</span></td>
            </tr>
        `;
    });

    body.innerHTML = html || '<tr><td colspan="4">' + t('access.no_records') + '</td></tr>';
}

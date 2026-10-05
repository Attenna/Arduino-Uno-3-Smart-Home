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
    startFaceStream();
    selectMethod('face');
    // 语言切换后重渲染由 JS 生成的内容（入户方式详情、人员凭证、日志标签）
    document.addEventListener('i18n:changed', () => {
        renderMethodDetail();
        loadPersons();
        loadAccessLogs();
    });
});

// ==================== 摄像头实时画面 ====================
// 后端 /api/camera/stream 同源代理 camera_stream 的 MJPEG；断流自动重连。

let faceStreamRetry = null;

function startFaceStream() {
    const img = document.getElementById('faceLiveImg');
    const hint = document.getElementById('faceLiveHint');
    const badge = document.getElementById('camBadge');
    if (!img) return;

    img.onload = () => {
        // MJPEG 首帧到达即触发 load
        if (hint) hint.classList.add('hidden');
        if (badge) badge.classList.add('live');
    };
    img.onerror = () => {
        if (hint) {
            hint.classList.remove('hidden');
            hint.textContent = t('access.stream_unavailable');
        }
        if (badge) badge.classList.remove('live');
        clearTimeout(faceStreamRetry);
        faceStreamRetry = setTimeout(() => loadFaceStream(), 5000);
    };
    loadFaceStream();
}

function loadFaceStream() {
    const img = document.getElementById('faceLiveImg');
    if (!img) return;
    img.src = `/api/camera/stream?t=${Date.now()}`;
}

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

// 姓名 / 卡号等来自后端，插入 innerHTML 前先转义，避免 XSS
function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

// 入户方式：后端存的是 face / rfid / keypad，页面统一转成可读标签
function methodLabel(method) {
    const m = String(method || '').toLowerCase();
    if (m === 'rfid') return { cls: 'rfid', text: t('access.method_rfid') };
    if (m === 'keypad') return { cls: 'keypad', text: t('access.method_keypad') };
    return { cls: 'face', text: t('access.method_face') };
}

// ==================== 入户方式总览（可点击切换） ====================

let selectedMethod = 'face';
let personsCache = [];

const METHOD_ICONS = {
    face: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><circle cx="9" cy="10" r="1.2" fill="currentColor" stroke="none"/><circle cx="15" cy="10" r="1.2" fill="currentColor" stroke="none"/><path d="M8.5 15c1 1.2 2.2 1.8 3.5 1.8s2.5-.6 3.5-1.8"/></svg>',
    rfid: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18M7 15h4"/></svg>',
    keypad: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 7h1M11.5 7h1M15 7h1M8 11h1M11.5 11h1M15 11h1M8 15h1M11.5 15h1M15 15h1"/></svg>'
};

const METHOD_META = {
    face: { nameKey: 'access.method_face_name', descKey: 'access.method_face_desc' },
    rfid: { nameKey: 'access.method_rfid_name', descKey: 'access.method_rfid_desc' },
    keypad: { nameKey: 'access.method_keypad_name', descKey: 'access.method_keypad_desc' }
};

function selectMethod(method) {
    if (!METHOD_META[method]) return;
    selectedMethod = method;
    document.querySelectorAll('.method-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.method === method);
    });
    renderMethodDetail();
}

function renderMethodDetail() {
    const el = document.getElementById('methodDetail');
    if (!el) return;

    const meta = METHOD_META[selectedMethod];
    const faceCount = personsCache.filter(p => p.face_id).length;
    const cardCount = personsCache.filter(p => p.rfid_uid).length;

    let stat;
    if (selectedMethod === 'face') stat = t('access.method_face_stat', faceCount);
    else if (selectedMethod === 'rfid') stat = t('access.method_rfid_stat', cardCount);
    else stat = t('access.method_keypad_stat');

    let extra = '';
    if (selectedMethod === 'keypad') {
        extra = `
            <div class="keypad-block">
                <h4>${t('access.keypad_title')}</h4>
                <p class="keypad-hint">${t('access.keypad_hint')}</p>
                <div class="form-row">
                    <input type="password" id="keypadNewCode" class="input-field" maxlength="4" inputmode="numeric"
                           placeholder="${t('access.keypad_placeholder')}">
                    <button class="btn" onclick="resetKeypadCode()">${t('access.keypad_reset')}</button>
                </div>
            </div>`;
    } else if (selectedMethod === 'rfid') {
        extra = `<p class="method-note">${t('access.enroll_card_hint')}</p>`;
    }

    el.innerHTML = `
        <div class="method-detail-main">
            <div class="method-detail-icon">${METHOD_ICONS[selectedMethod]}</div>
            <div class="method-detail-text">
                <div class="method-detail-head">
                    <span class="method-detail-name">${t(meta.nameKey)}</span>
                    <span class="method-detail-stat">${stat}</span>
                </div>
                <p class="method-detail-desc">${t(meta.descKey)}</p>
            </div>
        </div>
        ${extra}`;
}

function updateMethodsLast(lastLog) {
    const el = document.getElementById('methodsLast');
    if (!el) return;
    if (!lastLog) { el.textContent = ''; return; }
    const m = methodLabel(lastLog.access_type);
    const sep = I18N.currentLang === 'zh' ? '：' : ': ';
    el.innerHTML = `${t('access.methods_last')}${sep}<span class="status-tag ${m.cls}">${m.text}</span>`;
}

// 键盘密码重置（前端演示：仅校验并提示，未改动硬件）
function resetKeypadCode() {
    const input = document.getElementById('keypadNewCode');
    if (!input) return;
    const code = input.value.trim();
    if (!/^\d{4}$/.test(code)) {
        showNotification(t('access.keypad_invalid'), 'error');
        return;
    }
    showNotification(t('access.keypad_ok'), 'success');
    input.value = '';
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
            <svg viewBox="0 0 24 24" fill="none" stroke="#4f6b48" stroke-width="2.5">
                <path d="M20 6L9 17l-5-5"/>
            </svg>`;
        nameEl.textContent = event.person_name || t('access.unknown');
        metaEl.textContent = lang === 'zh' ? '验证通过' : 'Access Granted';
        metaEl.style.color = '#4f6b48';
    } else {
        statusEl.className = 'face-result-status denied';
        iconEl.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="#b5544a" stroke-width="2.5">
                <circle cx="12" cy="12" r="10"/>
                <line x1="15" y1="9" x2="9" y2="15"/>
                <line x1="9" y1="9" x2="15" y2="15"/>
            </svg>`;
        nameEl.textContent = event.person_name || t('access.unknown');
        metaEl.textContent = lang === 'zh' ? '访问被拒绝' : 'Access Denied';
        metaEl.style.color = '#b5544a';
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
    personsCache = persons;

    const listEl = document.getElementById('personList');
    let html = '';

    persons.forEach((p, i) => {
        const initial = p.name.charAt(0);
        const colors = ['#f5b301', '#4f6b48', '#9a7aa0', '#b06a2c', '#b5544a'];
        const color = colors[i % colors.length];
        const faceChip = p.face_id
            ? `<span class="cred-chip on face">${t('access.cred_face')}</span>`
            : `<span class="cred-chip off">${t('access.face_none')}</span>`;
        const cardChip = p.rfid_uid
            ? `<span class="cred-chip on card">${t('access.card_enrolled')}</span>`
            : `<span class="cred-chip off">${t('access.card_none')}</span>`;
        html += `
            <div class="person-item">
                <div class="person-info">
                    <div class="person-avatar" style="background: ${color}">${esc(initial)}</div>
                    <div class="person-meta">
                        <div class="person-name">${esc(p.name)}</div>
                        <div class="person-cred">${faceChip}${cardChip}</div>
                    </div>
                </div>
                <button class="btn btn-sm enroll-btn" onclick="enrollCard(${p.id})">
                    ${t('access.enroll_card')}
                </button>
            </div>
        `;
    });

    listEl.innerHTML = html || '<div class="loading">' + t('access.no_persons') + '</div>';
    renderMethodDetail();
}

// ==================== 录入房卡（等待刷卡 + 轮询结果） ====================

let cardEnrollTimer = null;

async function enrollCard(personId) {
    const res = await apiPost(`/api/access/persons/${personId}/enroll/rfid`, {});
    if (!res || !res.session) {
        showNotification(t('access.enroll_error'), 'error');
        return;
    }
    showNotification(t('access.enroll_card_hint'), 'info');
    startCardEnrollPolling(res.session.id);
}

function startCardEnrollPolling(sid) {
    clearInterval(cardEnrollTimer);
    cardEnrollTimer = setInterval(async () => {
        const res = await apiGet(`/api/access/enroll/rfid/${sid}`);
        if (!res) {
            clearInterval(cardEnrollTimer);
            showNotification(t('access.enroll_card_expired'), 'error');
            return;
        }
        if (res.state === 'matched') {
            clearInterval(cardEnrollTimer);
            showNotification(t('access.enroll_card_ok'), 'success');
            loadPersons();
        } else if (res.state === 'expired') {
            clearInterval(cardEnrollTimer);
            showNotification(t('access.enroll_card_expired'), 'error');
        } else if (res.state === 'conflict') {
            clearInterval(cardEnrollTimer);
            showNotification(t('access.enroll_card_conflict'), 'error');
        } else if (res.state === 'error') {
            clearInterval(cardEnrollTimer);
            showNotification(res.error || t('access.enroll_error'), 'error');
        }
    }, 1500);
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
        const method = methodLabel(log.access_type);
        const statusClass = log.status === 'granted' ? 'granted' : 'denied';
        const statusText = log.status === 'granted' ? t('access.log_granted') : t('access.log_denied');

        html += `
            <tr>
                <td>${timeStr}</td>
                <td>${esc(log.person_name)}</td>
                <td><span class="status-tag ${method.cls}">${method.text}</span></td>
                <td><span class="status-tag ${statusClass}">${statusText}</span></td>
            </tr>
        `;
    });

    body.innerHTML = html || '<tr><td colspan="4">' + t('access.no_records') + '</td></tr>';

    updateMethodsLast(logs[0]);
}

// ==================== 门禁管理页 JS ====================
// 这一页只管「谁有什么凭证」和「把凭证录进来」：
//   录入人脸 —— 从同源代理的 MJPEG 实时画面截几帧，交给后端检脸入库；
//   录入房卡 —— 开一个等待会话，用户把卡贴到读卡器上，卡号从串口事件里取。
// 开门、延时关门、被拒报警都不在这里：鉴权结果广播成积木事件，由 /automation 决定。

let facePollTimer = null;
let lastEventId = null;
let persons = [];
// 识别哨兵的状态与体检结果缓存：语言切换与轮询都拿它重渲染，不重复请求
let diag = null;
const DIAG_INTERVAL_MS = 5000;

// 截帧数量与后端 face/engine.py 的 MAX_ENROLL_FRAMES 对齐
const ENROLL_MAX_FRAMES = 8;
const ENROLL_MIN_FRAMES = 1;
const BURST_INTERVAL_MS = 700;
// 截帧缩放上限：识别器自己会再缩放，传太大只是浪费请求体（后端限 4MB/帧）
const CAPTURE_MAX_WIDTH = 640;

let enroll = { personId: null, name: '', frames: [], burst: null };
let card = { sid: null, deadline: 0, timer: null };

document.addEventListener('DOMContentLoaded', () => {
    updateClock();
    setInterval(updateClock, 1000);
    loadPersons();
    loadAccessLogs();
    loadFaceEvents();
    startFacePolling();
    startFaceStream();
    setInterval(loadDiagnostics, DIAG_INTERVAL_MS);   // 首帧由 loadPersons() 带出来
    document.getElementById('personList').addEventListener('click', onPersonAction);
});

function esc(value) {
    return String(value === null || value === undefined ? '' : value)
        .replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
}

// ==================== 摄像头实时画面 ====================
// 后端 /api/camera/stream 同源代理 camera_stream 的 MJPEG；断流自动重连。
// 同源是「录入人脸」能截帧的前提：跨域画面会让 canvas 被污染，toDataURL 直接抛错。

let faceStreamRetry = null;

function startFaceStream() {
    const img = document.getElementById('faceLiveImg');
    const hint = document.getElementById('faceLiveHint');
    if (!img) return;

    img.onload = () => {
        // MJPEG 首帧到达即触发 load
        if (hint) hint.classList.add('hidden');
    };
    img.onerror = () => {
        if (hint) {
            hint.classList.remove('hidden');
            hint.textContent = t('access.stream_unavailable');
        }
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

async function apiSend(url, data, method = 'POST') {
    try {
        const res = await fetch(url, {
            method,
            headers: data === undefined ? {} : { 'Content-Type': 'application/json' },
            body: data === undefined ? null : JSON.stringify(data),
        });
        return await res.json();
    } catch (e) {
        console.error('API error:', e);
        return null;
    }
}

// 后端按 {error, error_en} / {message, message_en} 双语返回，这里按当前语言取
function pick(obj, kind) {
    const en = I18N.currentLang === 'en';
    if (kind === 'error') return (en ? (obj.error_en || obj.error) : obj.error) || '';
    return (en ? (obj.message_en || obj.message) : obj.message) || '';
}

function report(res, okType = 'success') {
    if (!res) { showNotification(t('access.net_error'), 'error'); return false; }
    if (res.error) { showNotification(pick(res, 'error'), 'error'); return false; }
    showNotification(pick(res, 'message'), okType);
    return true;
}

// ==================== 实时识别结果轮询 ====================

// 超过这个秒数的「最新事件」不再当实时判定用：面板宁可空着，也不能把昨天
// 测试脚本塞进库的假放行显示成「摄像头前有人被验证通过」。
const FACE_FRESH_WINDOW_S = 90;

function startFacePolling() {
    // 每2秒轮询最新识别事件
    facePollTimer = setInterval(() => pollLatestFaceEvent(), 2000);
}


function agoText(seconds) {
    const s = Math.max(0, Math.round(Number(seconds) || 0));
    if (s < 60) return t('access.ago_s', s);
    if (s < 3600) return t('access.ago_m', Math.round(s / 60));
    if (s < 86400) return t('access.ago_h', Math.round(s / 3600));
    return t('access.ago_d', Math.round(s / 86400));
}

async function pollLatestFaceEvent(silent) {
    const event = await apiGet('/api/face/events/latest');
    if (!event || !event.id) {
        showFaceWaiting();
        return;
    }

    // 只有新事件才更新UI
    if (lastEventId === event.id) return;
    lastEventId = event.id;

    if (typeof event.age_s === 'number' && event.age_s > FACE_FRESH_WINDOW_S) {
        // 陈旧事件：留在下面的事件表里，但不占住「刚刚发生了什么」这块面板
        showFaceWaiting(event);
        return;
    }

    updateFaceResultDisplay(event, silent);
}

function showFaceWaiting(event) {
    const waitingEl = document.getElementById('faceResultWaiting');
    const contentEl = document.getElementById('faceResultContent');
    if (!waitingEl || !contentEl) return;
    contentEl.classList.add('hidden');
    waitingEl.classList.remove('hidden');
    const title = document.getElementById('faceWaitingTitle');
    const sub = document.getElementById('faceWaitingSub');
    if (event && event.id) {
        if (title) title.textContent = t('access.waiting_stale');
        if (sub) sub.textContent = t('access.waiting_stale_sub', agoText(event.age_s));
    } else {
        if (title) title.textContent = t('access.waiting_push');
        if (sub) sub.textContent = t('access.waiting_sub');
    }
}

function updateFaceResultDisplay(event, silent) {
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
    const reason = reasonText(event.deny_reason);

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
        nameEl.textContent = event.person_name
            || (event.face_id ? t('access.unbound') : t('access.unknown_person'));
        metaEl.textContent = (lang === 'zh' ? '访问被拒绝' : 'Access Denied')
            + (reason ? '：' + reason : '');
        metaEl.style.color = '#ff1744';
    }

    // 详细信息
    document.getElementById('faceResultId').textContent = event.face_id || '--';
    document.getElementById('faceResultConfidence').textContent =
        event.confidence ? (event.confidence * 100).toFixed(1) + '%' : '--';

    const dt = serverDate(event.timestamp);
    const locale = lang === 'zh' ? 'zh-CN' : 'en-US';
    document.getElementById('faceResultTime').textContent =
        dt ? dt.toLocaleString(locale) : '--';
    document.getElementById('faceResultSource').textContent =
        sourceText(event.device_source);

    // 通知：把「为什么被拒」直接说出口，过去所有拒绝都只有一句话。
    // 语言切换后的重渲染传 silent，否则每切一次语言就再弹一次窗。
    if (!silent) {
        showNotification(isGranted
            ? t('notify.access_granted', event.person_name || t('access.unknown'))
            : t('notify.access_denied', reason || t('access.unknown')),
            isGranted ? 'success' : 'error');
    }

    // 刷新事件列表和门禁日志
    loadFaceEvents();
    loadAccessLogs();
}

// ==================== 识别哨兵状态 / 门禁体检 ====================
// 这一页过去只会写「等待香橙派推送识别结果」，用户分不清到底是没摄像头、没录脸、
// 门口没人还是识别器没起来。后端每轮判定都记在哨兵状态里，这里翻成一句人话。

async function loadDiagnostics() {
    const body = await apiGet('/api/access/diagnostics');
    if (!body || body.error) return;
    diag = body;
    renderWatcher();
    renderDiagnostics();
}

function tk(key, fallback) {
    const text = t(key);
    return text === key ? fallback : text;
}

function reasonText(code) {
    return code ? tk('access.reason_' + code, code) : '';
}

// 识别来源：内部标识直接显示时用户只会看到 face_watcher / orange_pi 这种词
function sourceText(src) {
    return src ? tk('access.source_' + src, src) : t('access.source_unknown');
}

// ok=正在识别 / wait=门控没开 / bad=干不了活 / off=没启动
function watcherTone() {
    const w = (diag && diag.watcher) || null;
    if (!w || !w.enabled || !w.running) return 'off';
    if (w.camera_error || !w.snapshot_url || !w.model_ready || !w.identities) return 'bad';
    return (w.gate || {}).open ? 'ok' : 'wait';
}

function watcherText() {
    const w = (diag && diag.watcher) || null;
    if (!w) return t('access.watcher_unknown');
    if (!w.enabled) return t('access.watcher_off');
    if (!w.running) return t('access.watcher_stopped');
    if (!w.snapshot_url) return t('access.watcher_no_camera');
    if (w.camera_error) return t('access.watcher_camera');
    if (!w.model_ready) return t('access.watcher_no_model');
    if (!w.identities) return t('access.watcher_no_identity');
    if (!(w.gate || {}).open) return t('access.watcher_wait_motion');
    return t('access.watcher_watch', w.interval);
}

function watcherSub() {
    const w = (diag && diag.watcher) || {};
    const parts = [];
    const last = w.last || null;
    if (last && last.kind) {
        let line = tk('access.last_' + last.kind, last.kind);
        if (last.person) line += '：' + last.person;
        else if (last.reason) line += '：' + reasonText(last.reason);
        if (typeof last.age_s === 'number') line = t('access.last_at', line,
                                                    Math.round(last.age_s));
        parts.push(line);
    }
    const c = w.counts || {};
    if (typeof c.granted === 'number') {
        parts.push(t('access.watcher_counts', c.granted, c.denied, c.strangers));
    }
    return parts.join(' · ');
}

function renderWatcher() {
    const bar = document.getElementById('watcherBar');
    if (!bar) return;
    bar.className = 'watcher-bar tone-' + watcherTone();
    document.getElementById('watcherText').textContent = watcherText();
    document.getElementById('watcherSub').textContent = watcherSub();
}

function diagItems() {
    const d = diag || {};
    const items = [];
    if (d.model_mismatch) {
        // 库与模型不匹配时一张脸都认不出，比个别人员缺照片严重，排在最前
        items.push(['bad', t('access.diag_model_block',
                             d.model_mismatch.library, d.model_mismatch.current)]);
    } else if (d.recognition_block) {
        items.push(['bad', d.recognition_block]);
    }
    (d.orphan_identities || []).forEach(name =>
        items.push(['warn', t('access.diag_orphan', name)]));
    (d.persons_without_photos || []).forEach(p =>
        items.push(['warn', t('access.diag_no_photo', p.name)]));
    (d.ambiguous_face_ids || []).forEach(id =>
        items.push(['bad', t('access.diag_ambiguous', id)]));
    if ((d.dead_aliases || []).length) {
        items.push(['muted', t('access.diag_aliases', d.dead_aliases.join(', '))]);
    }
    (d.recent_repeats || []).forEach(r => {
        if (r.repeats) {
            items.push(['muted', t('access.diag_repeat', r.credential, r.repeats)]);
        }
    });
    return items;
}

function renderDiagnostics() {
    const box = document.getElementById('accessDiag');
    if (!box) return;
    const items = diagItems();
    box.classList.toggle('hidden', !items.length);
    box.innerHTML = items.map(item =>
        `<div class="diag-item diag-${item[0]}">${esc(item[1])}</div>`).join('');
}

// ==================== 授权人员管理 ====================

async function loadPersons() {
    const list = await apiGet('/api/access/persons');
    if (!list) return;
    persons = list;
    renderPersons();
    renderTestPicker();
    // 录入/删除人员都会改变体检结论（有没有注册照、库里有没有孤儿），一起刷
    loadDiagnostics();
}

// 语言切换：人员条目与两张表都是 JS 渲染的，不在 data-i18n 覆盖范围内，
// 切完要立刻用缓存重渲染（表里还有 t() 文案，只能重新取一次）
function toggleAccessLang() {
    setLang(I18N.currentLang === 'zh' ? 'en' : 'zh');
    renderPersons();
    renderTestPicker();
    loadAccessLogs();
    loadFaceEvents();
    renderWatcher();          // 状态与体检是 JS 渲染的，用缓存立刻翻一次
    renderDiagnostics();
    lastEventId = null;       // 结果面板同理：重渲染最新事件，silent 免得再弹通知
    pollLatestFaceEvent(true);
}

function renderPersons() {
    const listEl = document.getElementById('personList');
    let html = '';
    const colors = ['#00e5ff', '#00e676', '#7c4dff', '#ff9100', '#ff1744'];

    persons.forEach((p, i) => {
        const faceTag = p.face_id
            ? `${t('access.face_ok')} ${p.face_images || 0}${t('access.faces_unit')}`
            : `<span class="cred-missing">${t('access.face_none')}</span>`;
        const cardTag = p.rfid_uid
            ? `${t('access.card_ok')} ${esc(p.rfid_uid)}`
            : `<span class="cred-missing">${t('access.card_none')}</span>`;
        const disabled = p.enabled ? '' : ' person-disabled';
        html += `
            <div class="person-item${disabled}" data-id="${p.id}">
                <div class="person-info">
                    <div class="person-avatar" style="background: ${colors[i % colors.length]}">${esc(p.name.charAt(0))}</div>
                    <div>
                        <div class="person-name">${esc(p.name)}${p.enabled ? '' : ` <span class="cred-missing">${t('access.disabled_tag')}</span>`}</div>
                        <div class="person-cred">${faceTag} · ${cardTag}</div>
                    </div>
                </div>
                <div class="person-actions">
                    <button class="btn btn-sm" data-act="face">${t('access.enroll_face')}</button>
                    <button class="btn btn-sm" data-act="card">${t('access.enroll_card')}</button>
                    <button class="btn btn-sm" data-act="toggle">${p.enabled ? t('access.disable') : t('access.enable')}</button>
                    <button class="btn btn-sm btn-danger" data-act="delete">${t('access.delete')}</button>
                </div>
            </div>
        `;
    });

    listEl.innerHTML = html || `<div class="loading">${t('access.no_persons')}</div>`;
}

async function onPersonAction(ev) {
    const btn = ev.target.closest('button[data-act]');
    if (!btn) return;
    const item = btn.closest('.person-item');
    const id = Number(item.dataset.id);
    const person = persons.find(p => p.id === id) || {};
    switch (btn.dataset.act) {
        case 'face': startFaceEnroll(id, person.name || ''); break;
        case 'card': startCardEnroll(id); break;
        case 'toggle':
            await setEnabled(id, !person.enabled); break;
        case 'delete': await removePerson(id, person.name || ''); break;
    }
}

async function addPerson() {
    const input = document.getElementById('newPersonName');
    const name = input.value.trim();
    if (!name) { showNotification(t('notify.enter_name'), 'error'); return; }
    const res = await apiSend('/api/access/persons', { name });
    if (report(res)) { input.value = ''; loadPersons(); }
}

async function setEnabled(id, enabled) {
    const res = await apiSend(`/api/access/persons/${id}/enabled`, { enabled });
    if (report(res)) loadPersons();
}

async function removePerson(id, name) {
    if (!confirm(t('access.confirm_delete') + '\n' + name)) return;
    const res = await apiSend(`/api/access/persons/${id}`, undefined, 'DELETE');
    if (report(res)) loadPersons();
}

// ==================== 录入人脸（浏览器截帧） ====================

function startFaceEnroll(personId, name) {
    stopBurst();
    enroll = { personId, name, frames: [], burst: null };
    document.getElementById('enrollWho').textContent = name || '--';
    document.getElementById('enrollFacePanel').classList.remove('hidden');
    renderEnrollFrames();
    showNotification(t('access.enroll_started'), 'info');
}

function cancelEnroll() {
    stopBurst();
    enroll = { personId: null, name: '', frames: [], burst: null };
    document.getElementById('enrollFacePanel').classList.add('hidden');
}

function captureEnrollFrame() {
    if (enroll.personId === null) { showNotification(t('access.enroll_none'), 'error'); return false; }
    if (enroll.frames.length >= ENROLL_MAX_FRAMES) {
        showNotification(t('access.enroll_full'), 'info');
        stopBurst();
        return false;
    }
    const img = document.getElementById('faceLiveImg');
    if (!img || !img.naturalWidth) { showNotification(t('access.no_frame'), 'error'); return false; }
    const scale = Math.min(1, CAPTURE_MAX_WIDTH / img.naturalWidth);
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(img.naturalWidth * scale);
    canvas.height = Math.round(img.naturalHeight * scale);
    canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
    let url;
    try {
        url = canvas.toDataURL('image/jpeg', 0.92);
    } catch (e) {
        // 画面不是同源时 canvas 会被污染，这里明确告诉用户而不是静默失败
        showNotification(t('access.canvas_blocked'), 'error');
        stopBurst();
        return false;
    }
    enroll.frames.push(url);
    renderEnrollFrames();
    return true;
}

function burstEnroll() {
    if (enroll.personId === null) { showNotification(t('access.enroll_none'), 'error'); return; }
    if (enroll.burst) { stopBurst(); return; }
    const btn = document.getElementById('burstBtn');
    btn.classList.add('btn-active');
    const tick = () => {
        if (!captureEnrollFrame() || enroll.frames.length >= ENROLL_MAX_FRAMES) stopBurst();
    };
    tick();
    enroll.burst = setInterval(tick, BURST_INTERVAL_MS);
}

function stopBurst() {
    if (enroll.burst) clearInterval(enroll.burst);
    enroll.burst = null;
    const btn = document.getElementById('burstBtn');
    if (btn) btn.classList.remove('btn-active');
}

function renderEnrollFrames() {
    document.getElementById('enrollCount').textContent =
        `${enroll.frames.length}/${ENROLL_MAX_FRAMES}`;
    document.getElementById('enrollThumbs').innerHTML = enroll.frames
        .map((src, i) => `<img class="enroll-thumb" src="${src}" alt="${i + 1}">`).join('');
    document.getElementById('submitBtn').disabled =
        enroll.frames.length < ENROLL_MIN_FRAMES;
}

async function submitEnrollFaces() {
    stopBurst();
    if (enroll.personId === null || !enroll.frames.length) {
        showNotification(t('access.enroll_none'), 'error');
        return;
    }
    const target = enroll.personId;
    const btn = document.getElementById('submitBtn');
    btn.disabled = true;
    btn.textContent = t('access.enrolling');
    const res = await apiSend(`/api/access/persons/${target}/enroll/face`,
        { images: enroll.frames });
    btn.textContent = t('access.submit');
    btn.disabled = false;
    if (res && !res.error) {
        cancelEnroll();
        loadPersons();
        const rejected = ((res.detail || {}).rejected || []);
        showNotification(pick(res, 'message')
            + (rejected.length ? t('access.enroll_rejected') + rejected.length : ''), 'success');
    } else {
        report(res);
    }
}

// ==================== 录入房卡（等待刷卡） ====================

async function startCardEnroll(personId) {
    if (card.sid) await cancelCardEnroll(true);
    const res = await apiSend(`/api/access/persons/${personId}/enroll/rfid`);
    if (!res || res.error || !res.session) { report(res); return; }
    card = {
        sid: res.session.id,
        deadline: Date.now() + (res.timeout_seconds || 45) * 1000,
        timer: null,
    };
    const bar = document.getElementById('cardBar');
    bar.classList.remove('hidden');
    tickCardBar();
    card.timer = setInterval(async () => {
        // 给服务端几秒钟返回带具体原因的 expired/error 状态；否则页面会在
        // 最后一次状态请求之前先报一个无法排障的通用超时。
        if (Date.now() > card.deadline + 3000) {
            stopCardPolling();
            document.getElementById('cardBar').classList.add('hidden');
            showNotification(t('access.card_timeout'), 'error');
            return;
        }
        tickCardBar();
        const st = await apiGet(`/api/access/enroll/rfid/${card.sid}`);
        if (!st) return;
        if (st.state === 'pending') return;
        stopCardPolling();
        bar.classList.add('hidden');
        if (st.state === 'matched') {
            showNotification(t('access.card_bound') + (st.uid || ''), 'success');
            loadPersons();
        } else if (st.state === 'conflict') {
            showNotification(st.error || t('access.card_conflict'), 'error');
            loadPersons();
        } else {
            showNotification(st.error || t('access.card_error'), 'error');
        }
    }, 1000);
}

function tickCardBar() {
    const left = Math.max(0, Math.ceil((card.deadline - Date.now()) / 1000));
    document.getElementById('cardBarText').textContent =
        `${t('access.card_waiting')} ${left}s`;
}

async function cancelCardEnroll(silent) {
    if (card.sid) await apiSend(`/api/access/enroll/rfid/${card.sid}`, undefined, 'DELETE');
    stopCardPolling();
    document.getElementById('cardBar').classList.add('hidden');
    if (!silent) showNotification(t('access.card_cancelled'), 'info');
}

function stopCardPolling() {
    if (card.timer) clearInterval(card.timer);
    card = { sid: null, deadline: 0, timer: null };
}

// ==================== 链路自测 ====================

function renderTestPicker() {
    const sel = document.getElementById('testPerson');
    const keep = sel.value;
    sel.innerHTML = persons.map(p =>
        `<option value="${p.id}">${esc(p.name)}</option>`).join('');
    // 语言切换会重渲染整条下拉，别把用户刚选的人跳回第一个
    if (keep && persons.some(p => String(p.id) === keep)) sel.value = keep;
    sel.disabled = !persons.length;
}

async function runAccessTest() {
    const id = Number(document.getElementById('testPerson').value);
    const method = document.getElementById('testMethod').value;
    const out = document.getElementById('accessResult');
    if (!id) { showNotification(t('access.pick_person'), 'error'); return; }
    out.classList.remove('hidden', 'granted', 'denied');
    out.textContent = t('access.verifying');
    const res = await apiSend('/api/access/test', { person_id: id, method });
    if (!res || res.error) { out.textContent = pick(res || {}, 'error'); report(res); return; }
    out.textContent = pick(res, 'message');
    out.classList.add(res.granted ? 'granted' : 'denied');
    loadAccessLogs();
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
        const dt = serverDate(evt.timestamp);
        const locale = lang === 'zh' ? 'zh-CN' : 'en-US';
        const timeStr = dt ? dt.toLocaleString(locale) : '--';

        const statusClass = evt.status === 'granted' ? 'granted' : 'denied';
        const statusText = evt.status === 'granted'
            ? (lang === 'zh' ? '已通过' : 'Granted')
            : (lang === 'zh' ? '已拒绝' : 'Denied');
        // 认出身份但名单里没有对应人时，「陌生人」是误导：脸录过，缺的是名单那一行
        const who = esc(evt.person_name)
            || (evt.face_id ? t('access.unbound') : t('access.unknown_person'));

        html += `
            <tr>
                <td>${timeStr}</td>
                <td>${who}</td>
                <td>${esc(evt.face_id) || t('access.unmatched')}</td>
                <td>${evt.confidence ? (evt.confidence * 100).toFixed(1) + '%' : '--'}</td>
                <td><span class="status-tag ${statusClass}">${statusText}</span>${
                    evt.deny_reason
                        ? `<div class="evt-reason">${esc(reasonText(evt.deny_reason))}</div>`
                        : ''}</td>
                <td class="evt-source">${esc(sourceText(evt.device_source))}</td>
            </tr>
        `;
    });

    body.innerHTML = html;
}

// ==================== 门禁日志 ====================

async function loadAccessLogs() {
    const logs = await apiGet('/api/access/logs');
    if (!logs) return;

    const body = document.getElementById('accessLogBody');
    const lang = I18N.currentLang;
    const locale = lang === 'zh' ? 'zh-CN' : 'en-US';
    let html = '';

    logs.forEach(log => {
        const dt = serverDate(log.timestamp);
        const timeStr = dt ? dt.toLocaleString(locale) : '--';
        const statusClass = log.status === 'granted' ? 'granted' : 'denied';
        const statusText = log.status === 'granted' ? t('access.log_granted') : t('access.log_denied');
        const method = (lang === 'zh' ? ACCESS_METHOD_ZH : ACCESS_METHOD_EN)[log.access_type]
            || log.access_type;

        html += `
            <tr>
                <td>${timeStr}</td>
                <td>${esc(log.person_name)}</td>
                <td>${esc(method)}</td>
                <td><span class="status-tag ${statusClass}">${statusText}</span></td>
                <td class="log-reason">${esc(log.status === 'granted'
                    ? '' : reasonText(log.deny_reason))}</td>
            </tr>
        `;
    });

    body.innerHTML = html || '<tr><td colspan="5">' + t('access.no_records') + '</td></tr>';
}

const ACCESS_METHOD_ZH = { face: '人脸识别', rfid: '刷房卡', keypad: '键盘密码' };
const ACCESS_METHOD_EN = { face: 'Face', rfid: 'Room card', keypad: 'Keypad' };

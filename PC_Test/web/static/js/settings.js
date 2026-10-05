// ==================== 家庭设置页 ====================
// 成员列表与偏好存本机浏览器（localStorage）；连接状态实时读后端接口。

const MEMBERS_KEY = 'smart_home_members';
const NOTIFY_KEY = 'smart_home_notify';
const TEMP_WARN_KEY = 'smart_home_temp_warn';
const QUIET_KEY = 'smart_home_quiet_hours';

const DEFAULT_MEMBERS = [
    { name: '张哲俊', role: 'owner', rfid: 'A1B2C3D4' },
    { name: '家人', role: 'member', rfid: 'E5F6A7B8' },
    { name: '访客', role: 'guest', rfid: '—' },
];

function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function notify(msg, kind) {
    const box = document.getElementById('notification');
    if (!box) { return; }
    box.textContent = msg;
    box.className = 'notification ' + (kind || 'success');
    setTimeout(() => { box.className = 'notification hidden'; }, 3200);
}

// ==================== 家庭成员 ====================

function loadMembers() {
    try {
        const raw = localStorage.getItem(MEMBERS_KEY);
        if (raw) return JSON.parse(raw);
    } catch (e) { /* ignore */ }
    return DEFAULT_MEMBERS.slice();
}

function saveMembers(list) {
    localStorage.setItem(MEMBERS_KEY, JSON.stringify(list));
}

function roleLabel(role) {
    const map = { owner: 'settings.role_owner', member: 'settings.role_member', guest: 'settings.role_guest' };
    return t(map[role] || 'settings.role_member');
}

function renderMembers() {
    const box = document.getElementById('memberList');
    if (!box) return;
    const list = loadMembers();
    box.innerHTML = list.map((m, i) => `
        <div class="person-item" style="display:flex;align-items:center;gap:12px;padding:10px;border:1px solid var(--border-color);border-radius:var(--radius-sm)">
            <div class="person-info">
                <div class="person-avatar">${esc((m.name || '?').slice(0, 1))}</div>
                <div>
                    <div class="person-name">${esc(m.name)}</div>
                    <div class="person-rfid">${esc(m.rfid || '—')} · ${esc(roleLabel(m.role))}</div>
                </div>
            </div>
            <button class="btn btn-sm btn-danger" style="margin-left:auto" onclick="removeMember(${i})">
                ${esc(t('settings.remove'))}
            </button>
        </div>`).join('');
}

function addMember() {
    const name = (prompt(t('settings.prompt_name')) || '').trim();
    if (!name) return;
    const list = loadMembers();
    list.push({ name, role: 'member', rfid: '—' });
    saveMembers(list);
    renderMembers();
}

function removeMember(index) {
    const list = loadMembers();
    if (!list[index]) return;
    list.splice(index, 1);
    saveMembers(list);
    renderMembers();
}

// ==================== 偏好设置 ====================

function saveLangPref() {
    const sel = document.getElementById('prefLang');
    if (sel) I18N.setLang(sel.value);
}

function saveNotifyPref() {
    const cb = document.getElementById('prefNotify');
    if (cb) localStorage.setItem(NOTIFY_KEY, cb.checked ? '1' : '0');
}

function saveAlertPrefs() {
    const warn = document.getElementById('prefTempWarn');
    const qs = document.getElementById('prefQuietStart');
    const qe = document.getElementById('prefQuietEnd');
    if (warn) localStorage.setItem(TEMP_WARN_KEY, String(warn.value || ''));
    if (qs && qe) localStorage.setItem(QUIET_KEY, JSON.stringify({ start: qs.value, end: qe.value }));
}

function loadQuiet() {
    try {
        const raw = localStorage.getItem(QUIET_KEY);
        if (raw) return JSON.parse(raw);
    } catch (e) { /* ignore */ }
    return { start: '23:00', end: '07:00' };
}

function initPrefs() {
    const sel = document.getElementById('prefLang');
    if (sel) sel.value = I18N.currentLang;
    const cb = document.getElementById('prefNotify');
    if (cb) cb.checked = localStorage.getItem(NOTIFY_KEY) === '1';
    const warn = document.getElementById('prefTempWarn');
    if (warn) warn.value = localStorage.getItem(TEMP_WARN_KEY) || '30';
    const q = loadQuiet();
    const qs = document.getElementById('prefQuietStart');
    const qe = document.getElementById('prefQuietEnd');
    if (qs) qs.value = q.start;
    if (qe) qe.value = q.end;
}

// ==================== 硬件与连接 ====================

async function apiGet(url) {
    const resp = await fetch(url, { headers: { 'Accept': 'application/json' } });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
    return data;
}

async function apiPost(url, body) {
    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
    return data;
}

function setConn(id, state, text) {
    const box = document.getElementById(id);
    if (!box) return;
    const dot = box.querySelector('.conn-dot');
    const txt = box.querySelector('.conn-text');
    if (dot) dot.className = 'conn-dot ' + state;
    if (txt) txt.textContent = text;
}

function connText(state) {
    return {
        online: t('settings.status_online'),
        offline: t('settings.status_offline'),
        disabled: t('settings.status_disabled'),
        unknown: t('settings.status_unknown'),
    }[state] || t('settings.status_unknown');
}

async function loadConnections() {
    // 主控（Arduino / 串口）
    try {
        const s = await apiGet('/api/status');
        const hb = s.hardware_bridge || {};
        if (hb.enabled === false) setConn('connController', 'disabled', connText('disabled'));
        else setConn('connController', hb.online ? 'online' : 'offline', connText(hb.online ? 'online' : 'offline'));
    } catch (e) { setConn('connController', 'unknown', connText('unknown')); }

    // Home Assistant
    try {
        const ha = await apiGet('/api/ha/connection');
        const ok = !!ha.connected;
        setConn('connHa', ok ? 'online' : 'offline', ok ? connText('online') : connText('offline'));
    } catch (e) { setConn('connHa', 'unknown', connText('unknown')); }

    // 摄像头
    try {
        const c = await apiGet('/api/camera/status');
        const cam = c.camera || {};
        if (!c.enabled) setConn('connCamera', 'disabled', connText('disabled'));
        else setConn('connCamera', cam.online ? 'online' : 'offline', connText(cam.online ? 'online' : 'offline'));
    } catch (e) { setConn('connCamera', 'unknown', connText('unknown')); }

    // 人脸识别
    try {
        const f = await apiGet('/api/face/status');
        const blocked = f.recognition && f.recognition.blocked;
        const mode = f.mode || '';
        if (blocked) setConn('connFace', 'offline', connText('offline'));
        else if (mode === 'simulation') setConn('connFace', 'disabled', connText('disabled'));
        else setConn('connFace', 'online', connText('online'));
    } catch (e) { setConn('connFace', 'unknown', connText('unknown')); }
}

// ==================== 系统维护 ====================

function exportConfig() {
    const payload = {
        exportedAt: new Date().toISOString(),
        members: loadMembers(),
        prefs: {
            language: I18N.currentLang,
            notify: localStorage.getItem(NOTIFY_KEY) === '1',
            tempWarn: localStorage.getItem(TEMP_WARN_KEY) || '',
            quietHours: loadQuiet(),
        },
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'smart-home-config.json';
    a.click();
    URL.revokeObjectURL(a.href);
    notify(t('settings.export_done'));
}

async function runSelfTest() {
    const box = document.getElementById('maintResult');
    if (box) box.textContent = t('settings.selftest_running');
    try {
        const r = await apiPost('/api/hardware/self_test', {});
        const st = r.selftest || {};
        const bits = [];
        if (st.fan_pwm !== undefined) bits.push('fan_pwm=' + st.fan_pwm);
        if (st.light_show !== undefined) bits.push('light_show=' + st.light_show);
        if (st.cmd_ok !== undefined) bits.push('cmd_ok=' + st.cmd_ok);
        if (box) box.textContent = bits.length
            ? t('settings.selftest_ok') + '：' + bits.join('，')
            : t('settings.selftest_ok');
        notify(t('settings.selftest_ok'));
    } catch (e) {
        if (box) box.textContent = t('settings.selftest_fail') + '：' + e.message;
        notify(e.message, 'error');
    }
}

function clearLocalPrefs() {
    if (!confirm(t('settings.clear_confirm'))) return;
    [MEMBERS_KEY, NOTIFY_KEY, TEMP_WARN_KEY, QUIET_KEY].forEach(k => localStorage.removeItem(k));
    renderMembers();
    initPrefs();
    notify(t('settings.clear_done'));
}

// ==================== 侧栏分区切换 ====================

function initSettingsNav() {
    const nav = document.getElementById('settingsNav');
    if (!nav) return;
    nav.addEventListener('click', e => {
        const item = e.target.closest('.settings-nav-item');
        if (!item) return;
        nav.querySelectorAll('.settings-nav-item').forEach(n => n.classList.toggle('active', n === item));
        const sec = item.dataset.sec;
        document.querySelectorAll('.settings-section').forEach(s =>
            s.classList.toggle('active', s.dataset.sec === sec));
    });
}

// ==================== 顶栏时钟 ====================

function updateClock() {
    const el = document.getElementById('currentTime');
    if (!el) return;
    const locale = I18N.currentLang === 'zh' ? 'zh-CN' : 'en-US';
    el.textContent = new Date().toLocaleTimeString(locale, { hour12: false });
}

document.addEventListener('DOMContentLoaded', () => {
    updateClock();
    setInterval(updateClock, 1000);
    renderMembers();
    initPrefs();
    initSettingsNav();
    loadConnections();
    // 语言切换后刷新由 JS 生成的内容（成员角色、连接状态文案）
    document.addEventListener('i18n:changed', () => {
        renderMembers();
        loadConnections();
    });
});
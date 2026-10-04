// ==================== 家庭设置页 ====================
// 成员列表存本机浏览器（localStorage）；偏好设置即时生效并持久化。

const MEMBERS_KEY = 'smart_home_members';
const NOTIFY_KEY = 'smart_home_notify';

const DEFAULT_MEMBERS = [
    { name: '张哲俊', role: 'owner', rfid: 'A1B2C3D4' },
    { name: '家人', role: 'member', rfid: 'E5F6A7B8' },
    { name: '访客', role: 'guest', rfid: '—' },
];

function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

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

function initPrefs() {
    const sel = document.getElementById('prefLang');
    if (sel) sel.value = I18N.currentLang;
    const cb = document.getElementById('prefNotify');
    if (cb) cb.checked = localStorage.getItem(NOTIFY_KEY) === '1';
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
});
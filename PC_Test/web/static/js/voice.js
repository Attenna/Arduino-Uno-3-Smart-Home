// ==================== 语音助手页面 ====================
// 通过 web 同源代理调用语音助手 HTTP 口（/api/voice/*），不跨端口直连。

let voiceTimer = null;
let liveES = null;

document.addEventListener('DOMContentLoaded', () => {
    updateClock();
    setInterval(updateClock, 1000);
    refreshVoiceStatus();
    voiceTimer = setInterval(refreshVoiceStatus, 3000);
    connectLive();
});

function updateClock() {
    const el = document.getElementById('currentTime');
    const locale = I18N.currentLang === 'zh' ? 'zh-CN' : 'en-US';
    if (el) el.textContent = new Date().toLocaleTimeString(locale, { hour12: false });
}

function showNotification(message, type = 'info') {
    const el = document.getElementById('notification');
    if (!el) return;
    el.textContent = message;
    el.className = `notification ${type} show`;
    setTimeout(() => { el.className = 'notification hidden'; }, 3000);
}

function setVoiceError(msg) {
    const line = document.getElementById('voiceErrorLine');
    const box = document.getElementById('voiceError');
    if (!line || !box) return;
    if (msg) {
        box.textContent = msg;
        line.style.display = '';
    } else {
        line.style.display = 'none';
    }
}

// ==================== 状态轮询 ====================
async function refreshVoiceStatus() {
    let data = null;
    try {
        const res = await fetch('/api/voice/status');
        data = await res.json();
    } catch (e) {
        data = { online: false, error: String(e) };
    }
    const dot = document.getElementById('voiceDot');
    const nav = document.getElementById('voiceNavText');
    const badge = document.getElementById('voiceStateBadge');
    const text = document.getElementById('voiceStateText');

    if (dot) dot.className = 'status-dot' + (data.online ? ' online' : '');
    if (nav) nav.textContent = data.online ? t('voice.online') : t('voice.offline');
    if (badge) {
        badge.textContent = data.state_label || '--';
        badge.className = 'card-badge'
            + (data.online ? (data.state === 'IDLE' ? '' : ' warning') : ' danger');
    }
    if (text) text.textContent = data.state_label || '--';
    setVoiceError(data.online ? '' : (data.error || ''));
}

// ==================== 唤醒 / 文本指令 ====================
async function wakeVoice() {
    const btn = document.getElementById('wakeBtn');
    if (btn) btn.disabled = true;
    try {
        const res = await fetch('/api/voice/wake', { method: 'POST' });
        const data = await res.json();
        if (data.ok) {
            showNotification(t('voice.woken'), 'success');
            setTimeout(refreshVoiceStatus, 300);
        } else {
            showNotification(data.error || t('voice.failed'), 'error');
        }
    } catch (e) {
        showNotification(String(e), 'error');
    } finally {
        if (btn) btn.disabled = false;
        refreshVoiceStatus();
    }
}

async function sayVoice() {
    const input = document.getElementById('sayText');
    const box = document.getElementById('sayResult');
    const text = (input && input.value || '').trim();
    if (!text) {
        showNotification(t('voice.text_empty'), 'error');
        return;
    }
    try {
        const res = await fetch('/api/voice/say', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text })
        });
        const data = await res.json();
        if (data.ok) {
            showNotification(t('voice.sent'), 'success');
            if (box) box.textContent = `> ${text}`;
            if (input) input.value = '';
        } else {
            showNotification(data.error || t('voice.failed'), 'error');
        }
    } catch (e) {
        showNotification(String(e), 'error');
    }
    refreshVoiceStatus();
}

// ==================== 对话实况（SSE，同源 /api/voice/events）====================
// 语音助手状态机 → 面板文案，与后端 STATE_LABELS 对齐；追问窗口 FOLLOWUP 用绿色。
const LIVE_STATE = {
    IDLE: '待唤醒', COMMAND: '聆听指令', THINKING: '思考中', FOLLOWUP: '可追问',
};

let liveCurBot = null;   // 当前正在流式追加的助手气泡节点

function liveBadge(text, cls) {
    const b = document.getElementById('liveBadge');
    if (!b) return;
    b.textContent = text;
    b.className = 'card-badge' + (cls ? ' ' + cls : '');
}

function addLive(cls, text) {
    const log = document.getElementById('liveLog');
    const partial = document.getElementById('livePartial');
    if (!log) return null;
    const d = document.createElement('div');
    d.className = cls;
    d.textContent = text;
    log.insertBefore(d, partial);   // 始终插在识别中占位行之前
    log.scrollTop = log.scrollHeight;
    return d;
}

function setLivePartial(text) {
    const p = document.getElementById('livePartial');
    if (!p) return;
    p.textContent = text || '';
    p.style.display = text ? 'block' : 'none';
}

// 处理一条事件（hello.history 里的历史事件也走这里，实现补发/重连对齐）
function renderLive(e) {
    switch (e.type) {
        case 'partial':
            setLivePartial(e.text);
            break;
        case 'user':
            setLivePartial('');
            liveCurBot = null;
            addLive('lv-user', e.text);
            break;
        case 'delta':
            setLivePartial('');
            if (!liveCurBot) liveCurBot = addLive('lv-bot', '');
            liveCurBot.textContent += e.text;
            document.getElementById('liveLog').scrollTop =
                document.getElementById('liveLog').scrollHeight;
            break;
        case 'turn_end':
            liveCurBot = null;
            break;
        case 'tool': {
            const args = JSON.stringify(e.arguments || {});
            const head = (e.ok ? '✓ ' : '✗ ') + e.name + ' ' + args;
            addLive('lv-tool ' + (e.ok ? 'ok' : 'err'),
                e.result ? head + '\n   → ' + e.result : head);
            break;
        }
        case 'system':
            addLive('lv-sys', e.text);
            break;
        default:
            break;
    }
}

// state 事件：既刷新实况徽标，也同步主状态徽标/导航点（与轮询一致）
function applyLiveState(state) {
    const label = LIVE_STATE[state] || state || '离线';
    const badge = document.getElementById('voiceStateBadge');
    const text = document.getElementById('voiceStateText');
    if (badge) {
        badge.textContent = label;
        badge.className = 'card-badge' + (state ? (state === 'IDLE' ? '' : ' warning') : ' danger');
    }
    if (text) text.textContent = label;
}

function handleLive(e) {
    if (e.type === 'hello') {
        liveBadge(t('voice.live_conn'), '');
        applyLiveState(e.state);
        for (const h of (e.history || [])) renderLive(h);
        return;
    }
    if (e.type === 'state') {
        applyLiveState(e.state);
        return;
    }
    renderLive(e);
}

function connectLive() {
    if (liveES) { try { liveES.close(); } catch (e) {} liveES = null; }
    if (typeof EventSource === 'undefined') {
        liveBadge(t('voice.live_na'), 'danger');
        return;
    }
    liveES = new EventSource('/api/voice/events');
    liveES.onopen = () => liveBadge(t('voice.live_conn'), 'success');
    liveES.onmessage = (m) => {
        let e = null;
        try { e = JSON.parse(m.data); } catch (err) { return; }
        handleLive(e);
    };
    liveES.onerror = () => {
        liveBadge(t('voice.live_reconnect'), 'warning');
        // EventSource 会自动重连；这里只标注状态，交给浏览器重试
    };
}
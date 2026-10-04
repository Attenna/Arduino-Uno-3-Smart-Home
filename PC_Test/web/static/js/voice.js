// ==================== 语音助手页面 ====================
// 通过 web 同源代理调用语音助手 HTTP 口（/api/voice/*），不跨端口直连。

let voiceTimer = null;

document.addEventListener('DOMContentLoaded', () => {
    updateClock();
    setInterval(updateClock, 1000);
    refreshVoiceStatus();
    voiceTimer = setInterval(refreshVoiceStatus, 3000);
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

// 后端 state_label 为中文，前端按当前语言本地化（离线/待唤醒/聆听指令中…）
function voiceStateLabel(data) {
    if (!data.online) return t('voice.state_offline');
    const map = {
        IDLE: 'voice.state_idle',
        COMMAND: 'voice.state_command',
        THINKING: 'voice.state_thinking',
        FOLLOWUP: 'voice.state_followup',
    };
    return t(map[data.state] || 'voice.state_unknown');
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
    const label = voiceStateLabel(data);

    if (dot) dot.className = 'status-dot' + (data.online ? ' online' : '');
    if (nav) nav.textContent = data.online ? t('voice.online') : t('voice.offline');
    if (badge) {
        badge.textContent = label;
        badge.className = 'card-badge'
            + (data.online ? (data.state === 'IDLE' ? '' : ' warning') : ' danger');
    }
    if (text) text.textContent = label;
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
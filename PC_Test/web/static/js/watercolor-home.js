// Reuse main.js polling, request sequencing, authentication and notifications.
(() => {
    const room = document.getElementById('watercolorRoom');
    if (!room) return;
    let snapshot = null;
    let receivedAt = 0;
    const pending = new Set();
    const controls = [...document.querySelectorAll('[data-wc-device]')];
    const names = { light: '主灯', fan: '风扇', door: '前门', window: '窗户', buzzer: '蜂鸣器' };
    const text = (id, value) => { document.getElementById(id).textContent = value; };
    const valueText = (value, suffix = '', digits = 0) =>
        typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) + suffix : '—';
    const connected = () => !!snapshot && Date.now() - receivedAt < 12000;
    const outputOnline = () => connected() && snapshot.output_online === true;
    // Module B only refreshes its last-seen time after commands. A live bridge
    // must allow a new command even when the previous ACK is older than 15 s.
    const canControl = () => connected() && !!snapshot.hardware_bridge &&
        snapshot.hardware_bridge.enabled === true && snapshot.hardware_bridge.online === true;

    function deviceOn(device) {
        if (!snapshot) return false;
        if (device === 'light') return snapshot.light_status === 'on';
        if (device === 'fan') return Number(snapshot.fan_speed) > 0;
        return snapshot[device + '_status'] === 'open';
    }

    function render() {
        const online = outputOnline();
        const data = snapshot || {};
        room.classList.toggle('light-on', online && deviceOn('light'));
        room.classList.toggle('fan-on', online && deviceOn('fan'));
        room.classList.toggle('door-open', online && deviceOn('door'));
        room.classList.toggle('window-open', online && deviceOn('window'));
        room.classList.toggle('wc-offline', !online);
        room.style.setProperty('--wc-fan-duration', (1.1 - Math.min(100, Number(data.fan_speed) || 0) * .008) + 's');
        room.style.setProperty('--wc-light-strength', String((Number(data.light_brightness) || 0) / 100));
        text('wcRoomStatus', online ? '客厅设备在线' : '设备离线 · 画面状态未确认');
        controls.forEach(button => {
            const device = button.dataset.wcDevice;
            button.disabled = !canControl() || pending.has(device);
            button.setAttribute('aria-busy', String(pending.has(device)));
            button.setAttribute('aria-pressed', String(online && deviceOn(device)));
            const label = pending.has(device) ? '执行中…' : !online ? (canControl() ? '等待确认' : '设备离线') :
                device === 'fan' ? (deviceOn(device) ? '已开启' : '已停止') :
                device === 'light' ? (deviceOn(device) ? data.light_brightness + '%' : '已关闭') :
                device === 'buzzer' ? '点击自检' : (deviceOn(device) ? '已打开' : '已关闭');
            const detail = button.querySelector('[data-wc-status], small');
            if (detail) detail.textContent = label;
            button.dataset.label = names[device] + ' · ' + label;
        });
        for (const [id, field, device, output] of [
            ['wcBrightness', 'light_brightness', 'light', 'wcBrightnessValue'],

        ]) {
            const slider = document.getElementById(id);
            slider.disabled = !canControl() || pending.has(device);
            if (document.activeElement !== slider) slider.value = Number(data[field]) || 0;
            text(output, online ? valueText(data[field], '%') : '—');
        }
        const fresh = connected() && data.sensor_online === true;
        text('wcFreshness', fresh ? '实时采样' : '数据未更新');
        text('wcTemperature', fresh ? valueText(data.temperature, '', 1) : '—');
        text('wcHumidity', fresh ? valueText(data.humidity) : '—');
        text('wcLightRaw', fresh ? valueText(data.light_raw) : '—');
        text('wcDistance', fresh ? valueText(data.distance, ' cm') : '—');
        for (const [id, field, yes, no] of [
            ['wcSmoke', 'smoke', '烟雾告警', '正常'],
            ['wcRain', 'rain', '有雨', '无雨'],
            ['wcMotion', 'motion', '有人', '无人'],
        ]) text(id, fresh && data[field] != null ? (data[field] ? yes : no) : '—');
        text('wcDataNote', fresh ? '环境读数来自传感器最新采样' : '传感器离线或数据过期，等待新采样');
    }

    async function command(device, body) {
        if (pending.has(device)) return;
        if (!canControl()) {
            showNotification('设备离线，请在硬件管理中检查连接', 'error');
            return;
        }
        pending.add(device);
        text('wcSceneFeedback', names[device] + '指令执行中…');
        render();
        try {
            const endpoint = device === 'buzzer' ? '/api/hardware/tool' : '/api/' + device;
            const result = await apiPost(endpoint, body);
            if (!result || result.ok === false) {
                const error = result && (result.error || result.message);
                text('wcSceneFeedback', error || '操作未完成，设备状态保持最后确认值');
                if (error) showNotification(error, 'error');
                return;
            }
            // No optimistic scene updates. Only the status endpoint can change the drawing.
            const previous = receivedAt;
            await loadStatus();
            const message = receivedAt > previous ? (getMessage(result) || '设备操作已确认') : '指令已确认，等待状态刷新';
            text('wcSceneFeedback', message);
            showNotification(message);
        } finally {
            pending.delete(device);
            render();
        }
    }

    controls.forEach(button => button.addEventListener('click', () => {
        const device = button.dataset.wcDevice;
        let body;
        if (device === 'light') body = { status: deviceOn(device) ? 'off' : 'on', brightness: deviceOn(device) ? 0 : 72, ...lightStyleFromStatus(snapshot || {}) };
        else if (device === 'fan') body = { speed: deviceOn(device) ? 0 : 100 };
        else if (device === 'buzzer') body = { name: 'buzzer', arguments: { action: 'beep', count: 2, on_ms: 180, off_ms: 180 } };
        else body = { status: deviceOn(device) ? 'closed' : 'open' };
        command(device, body);
    }));

    for (const [id, device, output] of [
        ['wcBrightness', 'light', 'wcBrightnessValue'],
    ]) {
        const slider = document.getElementById(id);
        slider.addEventListener('input', () => text(output, slider.value + '%'));
        slider.addEventListener('change', () => {
            const value = Number(slider.value);
            const body = device === 'fan' ? { speed: value } :
                { status: value > 0 ? 'on' : 'off', brightness: value, ...lightStyleFromStatus(snapshot || {}) };
            command(device, body);
        });
    }
    document.addEventListener('status:update', event => {
        if (!event.detail || event.detail.error) return;
        snapshot = event.detail;
        receivedAt = Date.now();
        render();
        if (!pending.size) text('wcSceneFeedback', outputOnline() ? '点击房间里的设备进行控制' : '设备离线，请在硬件管理中检查连接');
    });
    // Expire stale connection state even when every subsequent request fails.
    setInterval(render, 1000);
    render();

    async function loadEvents() {
        const box = document.getElementById('wcEvents');
        const data = await apiGet('/api/access/logs?limit=4');
        if (!data || data.error) { box.textContent = '通行记录暂不可用'; return; }
        const rows = Array.isArray(data) ? data : (data.logs || []);
        box.replaceChildren();
        if (!rows.length) { box.textContent = '暂无通行记录'; return; }
        rows.slice(0, 4).forEach(event => {
            const row = document.createElement('article');
            const label = document.createElement('span');
            const time = document.createElement('time');
            label.textContent = [event.person_name, event.access_type, event.status].filter(Boolean).join(' · ');
            time.textContent = String(event.timestamp || '').replace('T', ' ').slice(11, 16);
            row.append(label, time); box.append(row);
        });
    }
    loadEvents();
    setInterval(loadEvents, 20000);

    const notes = document.getElementById('wcNotes');
    const notesKey = 'orange-home-notes-v1';
    let savedNotes = [];
    try {
        const stored = JSON.parse(localStorage.getItem(notesKey) || '[]');
        if (Array.isArray(stored)) savedNotes = stored.filter(note => typeof note === 'string').slice(0, 20);
    } catch (_) { /* A disabled or invalid browser store starts an empty board. */ }
    function renderNotes() {
        const list = document.getElementById('wcNotesList'); list.replaceChildren();
        savedNotes.forEach(value => { const note = document.createElement('p'); note.textContent = value; list.append(note); });
        if (!savedNotes.length) list.textContent = '还没有留言';
    }
    document.getElementById('wcOpenNotes').addEventListener('click', () => { renderNotes(); notes.showModal(); });
    document.getElementById('wcNoteForm').addEventListener('submit', event => {
        event.preventDefault();
        const input = document.getElementById('wcNoteInput');
        const value = input.value.trim(); if (!value) return;
        const next = [value, ...savedNotes].slice(0, 20);
        try { localStorage.setItem(notesKey, JSON.stringify(next)); }
        catch (_) { showNotification('浏览器无法保存留言，请检查存储权限', 'error'); return; }
        savedNotes = next; input.value = ''; renderNotes();
    });
})();

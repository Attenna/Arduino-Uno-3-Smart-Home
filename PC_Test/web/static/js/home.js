// ==================== 「我的家」首页增量模块 ====================
// 复用 main.js 轮询出的 status 数据（status:update 事件），渲染房间实时示意、
// 环境摘要与最近事件，避免重复请求 /api/status。

(function () {
    function setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function updateRoomScene(d) {
        const lamp = document.getElementById('rsLamp');
        if (lamp) {
            const on = d.light_status === 'on';
            lamp.classList.toggle('on', on);
        }
        const fan = document.getElementById('rsFan');
        if (fan) {
            const spd = Number(d.fan_speed) || 0;
            fan.classList.toggle('on', spd > 0);
            fan.classList.toggle('spin-fast', spd >= 100);
            fan.classList.toggle('spin-medium', spd > 0 && spd < 100);
        }
        const win = document.getElementById('rsWindow');
        if (win) win.classList.toggle('open', d.window_status === 'open');
        const door = document.getElementById('rsDoor');
        if (door) door.classList.toggle('open', d.door_status === 'open');
    }

    function updateEnvChips(d) {
        setText('envTemp', d.temperature ? d.temperature.toFixed(1) + '°C' : '--');
        setText('envHum', d.humidity ? d.humidity.toFixed(0) + '%' : '--');
    }

    function updateMode(mode) {
        const pill = document.getElementById('homeModePill');
        const text = document.getElementById('homeModeText');
        if (!pill || !text) return;
        const away = mode === 'away';
        pill.classList.toggle('away', away);
        text.textContent = away ? t('home.mode_away') : t('home.mode_home');
    }

    async function loadMode() {
        try {
            const res = await fetch('/api/automation/home_mode');
            if (!res.ok) return;
            const cfg = await res.json();
            updateMode(cfg.mode);
        } catch (e) { /* 引擎未启动时保持默认 */ }
    }

    function eventRow(time, text, sub) {
        return `<div class="event-item"><span class="t">${time}</span>` +
               `<span class="d">${text}</span>` +
               (sub ? `<span class="s">${sub}</span>` : '') + `</div>`;
    }

    function hhmm(ts) {
        if (!ts) return '--:--';
        const s = String(ts).replace('T', ' ');
        const m = s.match(/(\d{2}:\d{2})/);
        return m ? m[1] : s.slice(-5);
    }

    async function loadEvents() {
        const box = document.getElementById('homeEvents');
        if (!box) return;
        const rows = [];
        try {
            const [logsRes, faceRes] = await Promise.all([
                fetch('/api/automation/logs?limit=5'),
                fetch('/api/face/events?limit=3'),
            ]);
            if (logsRes.ok) {
                const logs = (await logsRes.json()).logs || [];
                logs.forEach(l => {
                    const ok = l.success ? '✅' : '⚠️';
                    rows.push({ ts: l.timestamp || '', html: eventRow(hhmm(l.timestamp), `${ok} ${l.rule_name || l.rule_id || ''}`, l.reason || '') });
                });
            }
            if (faceRes.ok) {
                const evs = await faceRes.json();
                (Array.isArray(evs) ? evs : []).forEach(ev => {
                    const who = ev.person_name || t('access.unknown');
                    rows.push({ ts: ev.timestamp || '', html: eventRow(hhmm(ev.timestamp), `🚪 ${who}`, ev.confidence ? Math.round(ev.confidence) + '%' : '') });
                });
            }
        } catch (e) { /* ignore */ }

        rows.sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
        box.innerHTML = rows.length
            ? rows.slice(0, 6).map(r => r.html).join('')
            : `<div class="event-item"><span class="d">${t('home.no_event')}</span></div>`;
    }

    document.addEventListener('status:update', e => {
        updateRoomScene(e.detail);
        updateEnvChips(e.detail);
    });
    document.addEventListener('DOMContentLoaded', () => {
        loadMode();
        loadEvents();
        setInterval(loadMode, 10000);
        setInterval(loadEvents, 20000);
    });
})();
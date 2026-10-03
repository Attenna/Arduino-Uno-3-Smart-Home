// ==================== 「房间与设备」页 ====================
// 复用 main.js 的 status:update（5s 轮询），渲染设备卡状态、房间筛选与详情抽屉。

(function () {
    const REG = {
        light: {
            title: 'light.title',
            state: d => (d.light_status === 'on'
                ? (Number(d.light_brightness) || 0) + '%'
                : t('status.off')),
            on: d => d.light_status === 'on',
            meta: d => d.light_status === 'on' ? t('light.brightness') : '',
            actions: [
                ['light.full', "setLight('on',100)"],
                ['light.half', "setLight('on',50)"],
                ['light.night', "setLight('on',25)"],
                ['light.off', "setLight('off',0)"],
            ],
        },
        fan: {
            title: 'fan.title',
            state: d => {
                const s = Number(d.fan_speed) || 0;
                return s <= 0 ? t('status.off') : s + '%';
            },
            on: d => (Number(d.fan_speed) || 0) > 0,
            meta: d => d.rb_fan_speed === null || d.rb_fan_speed === undefined
                ? '' : t('fan.readback') + ' ' + d.rb_fan_speed + '%',
            actions: [
                ['fan.low', 'setFan(30)'],
                ['fan.medium', 'setFan(60)'],
                ['fan.high', 'setFan(100)'],
                ['fan.off', 'setFan(0)'],
            ],
        },
        ac: {
            title: 'ac.title',
            state: d => d.ac_status === 'on'
                ? Math.round(Number(d.ac_temperature) || 26) + '°C · ' + t('ac.mode_' + (d.ac_mode || 'auto'))
                : t('ac.off_hint'),
            on: d => d.ac_status === 'on',
            meta: d => d.ac_status === 'on' ? t('ac.fan') + ': ' + t('ac.fan_' + (d.ac_fan || 'auto')) : '',
            actions: [['ac.power_on', 'toggleAC()']],
        },
        sensor: {
            title: 'temp.title',
            state: d => (d.temperature ? d.temperature.toFixed(1) + '°C' : '--') +
                ' / ' + (d.humidity ? d.humidity.toFixed(0) + '%' : '--'),
            on: d => d.sensor_online === true,
            meta: d => d.sensor_online ? t('rooms.online') : t('rooms.offline'),
            actions: [],
        },
        door: {
            title: 'home.door',
            state: d => d.door_status === 'open' ? t('status.open') : t('status.closed'),
            on: d => d.door_status === 'open',
            warn: d => d.door_status === 'open',
            meta: () => '',
            actions: [['door.toggle', 'guardDoor()']],
        },
        camera: {
            title: 'sec.camera',
            state: d => (d.rb_seen_at ? t('access.live') : t('rooms.offline')),
            on: d => !!d.rb_seen_at,
            meta: () => '',
            actions: [['access.live', "location.href='/access'"]],
        },
        buzzer: {
            title: 'sec.buzzer',
            state: d => d.buzzer_status ? t('status.on') : t('status.off'),
            on: d => !!d.buzzer_status,
            warn: d => !!d.buzzer_status,
            meta: () => '',
            actions: [],
        },
        window: {
            title: 'door.window',
            state: d => d.window_status === 'open' ? t('status.open') : t('status.closed'),
            on: d => d.window_status === 'open',
            meta: () => '',
            actions: [['door.toggle', 'guardWindow()']],
        },
    };

    let lastStatus = {};

    function renderCard(card, d) {
        const key = card.dataset.dev;
        const def = REG[key];
        if (!def) return;
        const on = !!def.on(d);
        const warn = def.warn ? !!def.warn(d) : false;
        card.classList.toggle('on', on);
        card.classList.toggle('warn', warn);
        const stateEl = card.querySelector('.dc-state-text');
        if (stateEl) stateEl.textContent = def.state(d);
        const metaEl = card.querySelector('.dc-meta');
        if (metaEl) metaEl.textContent = def.meta ? def.meta(d) : '';
    }

    function renderAll() {
        document.querySelectorAll('.device-card').forEach(c => renderCard(c, lastStatus));
        if (drawerKey) fillDrawer(drawerKey);
    }

    // ---------- 房间筛选 ----------
    const filter = document.getElementById('roomFilter');
    if (filter) {
        filter.addEventListener('click', e => {
            const btn = e.target.closest('.room-tab');
            if (!btn) return;
            filter.querySelectorAll('.room-tab').forEach(b => b.classList.toggle('active', b === btn));
            const room = btn.dataset.room;
            document.querySelectorAll('.device-card').forEach(c => {
                c.style.display = (room === 'all' || c.dataset.room === room) ? '' : 'none';
            });
        });
    }

    // ---------- 详情抽屉 ----------
    let drawerKey = null;

    function fillDrawer(key) {
        const def = REG[key];
        if (!def) return;
        const card = document.querySelector(`.device-card[data-dev="${key}"]`);
        document.getElementById('drawerTitle').textContent = t(def.title);
        document.getElementById('drawerState').textContent = def.state(lastStatus);
        document.getElementById('drawerOnline').textContent = def.on(lastStatus) ? t('rooms.online') : t('rooms.offline');
        document.getElementById('drawerUpdated').textContent = lastStatus.last_updated
            ? String(lastStatus.last_updated).replace('T', ' ').slice(0, 19) : '—';
        document.getElementById('drawerSource').textContent = t('rooms.auto_manual');
        const icon = document.getElementById('drawerIcon');
        if (icon && card) icon.innerHTML = card.querySelector('.dc-icon').innerHTML;
        const box = document.getElementById('drawerActions');
        box.innerHTML = (def.actions || []).map(([label, fn]) =>
            `<button class="btn btn-sm" onclick="${fn}">${t(label)}</button>`).join('');
    }

    window.openDeviceDrawer = function (key) {
        drawerKey = key;
        fillDrawer(key);
        document.getElementById('deviceDrawer').classList.add('open');
        document.getElementById('drawerBackdrop').classList.add('open');
    };
    window.closeDeviceDrawer = function () {
        drawerKey = null;
        document.getElementById('deviceDrawer').classList.remove('open');
        document.getElementById('drawerBackdrop').classList.remove('open');
    };

    const grid = document.getElementById('deviceGrid');
    if (grid) {
        grid.addEventListener('click', e => {
            if (e.target.closest('button')) return;   // 卡片内按钮走各自逻辑
            const card = e.target.closest('.device-card');
            if (card) window.openDeviceDrawer(card.dataset.dev);
        });
    }

    document.addEventListener('status:update', e => {
        lastStatus = e.detail || {};
        renderAll();
    });
})();
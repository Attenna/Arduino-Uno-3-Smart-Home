// ==================== 历史数据页面 JS ====================
let historyChart = null;

document.addEventListener('DOMContentLoaded', () => {
    updateClock();
    setInterval(updateClock, 1000);
    initHistoryChart();
    loadHistory();
    // 与看板图表同频：历史页挂着也不能停在被打开那一刻的快照
    setInterval(loadHistory, 60000);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) loadHistory();
    });
});

// 时钟
function updateClock() {
    const now = new Date();
    const el = document.getElementById('currentTime');
    const locale = I18N.currentLang === 'zh' ? 'zh-CN' : 'en-US';
    if (el) el.textContent = now.toLocaleTimeString(locale, { hour12: false });
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

// 通知
function showNotification(message, type = 'info') {
    const el = document.getElementById('notification');
    if (!el) return;
    el.textContent = message;
    el.className = `notification ${type} show`;
    setTimeout(() => { el.className = 'notification hidden'; }, 3000);
}

// 初始化图表
function initHistoryChart() {
    const ctx = document.getElementById('historyChart');
    if (!ctx) return;
    
    historyChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: '温度',
                data: [],
                borderColor: '#00e5ff',
                backgroundColor: 'rgba(0, 229, 255, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4,
                pointRadius: 2,
                pointBackgroundColor: '#00e5ff'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: {
                        color: '#8ba4b8',
                        font: { size: 12 },
                        usePointStyle: true
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(15, 25, 35, 0.9)',
                    borderColor: '#2a4a5e',
                    borderWidth: 1,
                    titleColor: '#e8f0f8',
                    bodyColor: '#8ba4b8',
                    padding: 12
                }
            },
            scales: {
                x: {
                    ticks: { color: '#5a7a8e', maxTicksLimit: 12, font: { size: 10 } },
                    grid: { color: 'rgba(42, 74, 94, 0.3)' }
                },
                y: {
                    ticks: { color: '#5a7a8e', font: { size: 10 } },
                    grid: { color: 'rgba(42, 74, 94, 0.3)' }
                }
            }
        }
    });
}

// 各数据类型的统计块文案与单位：温湿度看极值，门窗/灯光看开关动作次数
const STAT_VIEWS = {
    temperature: {
        max: ['history.stat_max', '°C'],
        min: ['history.stat_min', '°C'],
        avg: ['history.stat_avg', '°C'],
        count: ['history.stat_count', '条']
    },
    humidity: {
        max: ['history.stat_max_humidity', '%'],
        min: ['history.stat_min_humidity', '%'],
        avg: ['history.stat_avg_humidity', '%'],
        count: ['history.stat_count', '条']
    },
    door_window: {
        max: ['history.stat_open_count', '次'],
        min: ['history.stat_close_count', '次'],
        avg: ['history.stat_changes', '次'],
        count: ['history.stat_records', '条']
    },
    light: {
        max: ['history.stat_open_count', '次'],
        min: ['history.stat_close_count', '次'],
        avg: ['history.stat_changes', '次'],
        count: ['history.stat_records', '条']
    }
};

// 统计概览区：按数据类型切换标签与单位
function applyStatView(dataType) {
    const view = STAT_VIEWS[dataType];
    if (!view) return;
    ['max', 'min', 'avg', 'count'].forEach(name => {
        const [key, unit] = view[name];
        const suffix = name.charAt(0).toUpperCase() + name.slice(1);
        const label = document.getElementById(`stat${suffix}Label`);
        if (label) {
            // 同步 i18n key，切换语言后 applyI18n 才会刷新到正确文案
            if (typeof label.setAttribute === 'function') label.setAttribute('data-i18n', key);
            label.textContent = t(key);
        }
        const unitEl = document.getElementById(`stat${suffix}Unit`);
        if (unitEl) unitEl.textContent = unit;
    });
}

// 显示 / 隐藏元素（同时处理 class 与内联样式，兼容测试用的简易 DOM）
function setVisible(el, visible) {
    if (!el) return;
    if (el.style) el.style.display = visible ? '' : 'none';
    if (el.classList && typeof el.classList.toggle === 'function') {
        el.classList.toggle('hidden', !visible);
    }
}

// HTML 转义
function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

// 生成一个状态段：开启与关闭用不同颜色
function segHTML(from, to, status, start, span, isLight) {
    const width = ((to - from) / span) * 100;
    if (width <= 0) return '';
    const left = ((from - start) / span) * 100;
    const on = isLight ? status === 'on' : status === 'open';
    const cls = on ? (isLight ? 'seg-on-light' : 'seg-on') : 'seg-off';
    return `<span class="tl-seg ${cls}" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%"></span>`;
}

// 状态时间轴：每个设备一行，开启/关闭用不同颜色，并延续查询开始前的最后状态
function renderStateTimeline(data, hours, dataType) {
    const wrap = document.getElementById('stateTimeline');
    const rowsEl = document.getElementById('timelineRows');
    const noteEl = document.getElementById('timelineNote');
    if (!wrap || !rowsEl) return;

    const isLight = dataType === 'light';
    const end = Date.now();
    const start = end - Number(hours) * 3600 * 1000;
    const span = Math.max(1, end - start);
    const locale = I18N.currentLang === 'zh' ? 'zh-CN' : 'en-US';

    // 按设备分组（时间升序）
    const devices = new Map();
    [...data].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp)).forEach(d => {
        const key = isLight ? (d.light_name || 'light') : `${d.device_type || ''}|${d.device_name || ''}`;
        if (!devices.has(key)) {
            devices.set(key, {
                label: isLight ? (d.light_name || 'light') : (d.device_name || d.device_type || key),
                events: []
            });
        }
        devices.get(key).events.push({ t: new Date(d.timestamp).getTime(), status: d.status });
    });

    if (devices.size === 0) {
        rowsEl.innerHTML = `<div class="tl-empty">${t('history.no_data')}</div>`;
    } else {
        let rowsHTML = '';
        devices.forEach(info => {
            // 接口只返回窗口内记录，窗口开始前的状态取首个事件的反状态
            const firstStatus = info.events.length ? info.events[0].status : 'closed';
            let prevState = isLight ? (firstStatus === 'on' ? 'off' : 'on')
                                    : (firstStatus === 'open' ? 'closed' : 'open');
            let cursor = start;
            let segs = '';
            info.events.forEach(ev => {
                if (ev.t <= start) { prevState = ev.status; return; }
                if (ev.t > cursor) {
                    segs += segHTML(cursor, Math.min(ev.t, end), prevState, start, span, isLight);
                    cursor = ev.t;
                }
                prevState = ev.status;
            });
            if (cursor < end) segs += segHTML(cursor, end, prevState, start, span, isLight);
            rowsHTML += `<div class="tl-row">` +
                `<span class="tl-label">${escapeHtml(info.label)}</span>` +
                `<span class="tl-track">${segs}</span></div>`;
        });
        rowsEl.innerHTML = rowsHTML;
    }

    const fmt = { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' };
    const startEl = document.getElementById('timelineStart');
    const endEl = document.getElementById('timelineEnd');
    if (startEl) startEl.textContent = new Date(start).toLocaleString(locale, fmt);
    if (endEl) endEl.textContent = new Date(end).toLocaleString(locale, fmt);
    if (noteEl) {
        const key = isLight ? 'history.timeline_note_light' : 'history.timeline_note_door';
        if (typeof noteEl.setAttribute === 'function') noteEl.setAttribute('data-i18n', key);
        noteEl.textContent = t(key);
    }
    setVisible(wrap, true);
}

// 加载历史数据
async function loadHistory() {
    const dataType = document.getElementById('dataType').value;
    const hours = document.getElementById('timeRange').value;

    applyStatView(dataType);
    
    let data = [];
    let title = '';
    let chartLabel = '';
    let chartColor = '#00e5ff';
    let chartBgColor = 'rgba(0, 229, 255, 0.1)';
    
    switch (dataType) {
        case 'temperature':
            data = await apiGet(`/api/temperature?hours=${hours}`);
            title = t('chart.temp_history');
            chartLabel = t('chart.temp');
            chartColor = '#00e5ff';
            chartBgColor = 'rgba(0, 229, 255, 0.1)';
            break;
        case 'humidity':
            data = await apiGet(`/api/temperature?hours=${hours}`);
            title = t('chart.humidity_history');
            chartLabel = t('chart.humidity');
            chartColor = '#00b4d8';
            chartBgColor = 'rgba(0, 180, 216, 0.1)';
            break;
        case 'door_window':
            data = await apiGet(`/api/door_window/history?hours=${hours}`);
            title = t('chart.door_history');
            chartLabel = t('chart.door_status');
            chartColor = '#00e676';
            chartBgColor = 'rgba(0, 230, 118, 0.1)';
            break;
        case 'light':
            data = await apiGet(`/api/light/history?hours=${hours}`);
            title = t('chart.light_history');
            chartLabel = t('chart.light_brightness');
            chartColor = '#ffea00';
            chartBgColor = 'rgba(255, 234, 0, 0.1)';
            break;
    }
    
    if (!data) return;
    
    document.getElementById('chartTitle').textContent = title;

    // 门窗/灯光：隐藏折线图，改用设备状态时间轴；温湿度反之
    const isTimeline = dataType === 'door_window' || dataType === 'light';
    setVisible(document.getElementById('historyChart'), !isTimeline);
    setVisible(document.getElementById('stateTimeline'), isTimeline);

    // 反转数据（时间升序）
    const reversed = [...data].reverse();
    
    // 更新图表（门窗/灯光用时间轴展示，不再画折线）
    if (historyChart && !isTimeline) {
        const labels = reversed.map(d => {
            const dt = serverDate(d.timestamp);
            const locale = I18N.currentLang === 'zh' ? 'zh-CN' : 'en-US';
            return dt ? dt.toLocaleString(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '--';
        });
        
        let values;
        if (dataType === 'temperature') {
            values = reversed.map(d => d.temperature);
        } else if (dataType === 'humidity') {
            values = reversed.map(d => d.humidity);
        } else if (dataType === 'door_window') {
            values = reversed.map(d => d.status === 'open' ? 1 : 0);
        } else if (dataType === 'light') {
            values = reversed.map(d => d.brightness);
        }
        
        historyChart.data.labels = labels;
        historyChart.data.datasets[0].data = values;
        historyChart.data.datasets[0].label = chartLabel;
        historyChart.data.datasets[0].borderColor = chartColor;
        historyChart.data.datasets[0].backgroundColor = chartBgColor;
        historyChart.data.datasets[0].pointBackgroundColor = chartColor;
        historyChart.update();
    }
    
    if (isTimeline) renderStateTimeline(data, hours, dataType);

    // 先清除旧窗口统计，空结果或全 NULL 时保持占位符。
    for (const id of ['statMax', 'statMin', 'statAvg']) {
        document.getElementById(id).textContent = '--';
    }
    // 更新统计
    if (dataType === 'temperature') {
        const temps = reversed.map(d => d.temperature).filter(v => v !== null && v !== undefined);
        if (temps.length > 0) {
            document.getElementById('statMax').textContent = Math.max(...temps).toFixed(1);
            document.getElementById('statMin').textContent = Math.min(...temps).toFixed(1);
            document.getElementById('statAvg').textContent = (temps.reduce((a, b) => a + b, 0) / temps.length).toFixed(1);
        }
        document.getElementById('statCount').textContent = reversed.length;
    } else if (dataType === 'humidity') {
        const hums = reversed.map(d => d.humidity).filter(v => v !== null && v !== undefined);
        if (hums.length > 0) {
            document.getElementById('statMax').textContent = Math.max(...hums).toFixed(1);
            document.getElementById('statMin').textContent = Math.min(...hums).toFixed(1);
            document.getElementById('statAvg').textContent = (hums.reduce((a, b) => a + b, 0) / hums.length).toFixed(1);
        }
        document.getElementById('statCount').textContent = reversed.length;
    } else if (dataType === 'door_window' || dataType === 'light') {
        // 门窗/灯光：开启次数、关闭次数、状态变化次数、记录条数
        const onKey = dataType === 'light' ? 'on' : 'open';
        const ons = reversed.filter(d => d.status === onKey).length;
        document.getElementById('statMax').textContent = ons;
        document.getElementById('statMin').textContent = reversed.length - ons;
        document.getElementById('statAvg').textContent = reversed.length;
        document.getElementById('statCount').textContent = reversed.length;
    } else {
        document.getElementById('statMax').textContent = '--';
        document.getElementById('statMin').textContent = '--';
        document.getElementById('statAvg').textContent = '--';
        document.getElementById('statCount').textContent = reversed.length;
    }
    
    // 更新表格
    updateTable(dataType, reversed);
}

// 入库列级容错后坏字段是 NULL（聚合均值也可能是），表格与统计都不能瞎
function num1(v) {
    return v === null || v === undefined || isNaN(v) ? '--' : Number(v).toFixed(1);
}

// 更新数据表格
function updateTable(dataType, data) {
    const header = document.getElementById('tableHeader');
    const body = document.getElementById('tableBody');
    document.getElementById('recordCount').textContent = t('history.records_count', data.length);
    
    let headerHTML = '<th>' + t('history.time') + '</th>';
    
    switch (dataType) {
        case 'temperature':
            headerHTML += '<th>' + t('chart.temp') + '</th><th>' + t('chart.humidity') + '</th>';
            break;
        case 'humidity':
            headerHTML += '<th>' + t('chart.humidity') + '</th><th>' + t('chart.temp') + '</th>';
            break;
        case 'door_window':
            headerHTML += '<th>' + t('history.device_type') + '</th><th>' + t('history.device_name') + '</th><th>' + t('history.status') + '</th>';
            break;
        case 'light':
            headerHTML += '<th>' + t('history.light_name') + '</th><th>' + t('history.status') + '</th><th>' + t('history.brightness') + '</th>';
            break;
    }
    header.innerHTML = headerHTML;
    
    // 只显示最近50条
    const displayData = data.slice(-50).reverse();
    let bodyHTML = '';
    
    displayData.forEach(d => {
        const dt = serverDate(d.timestamp);
        const locale = I18N.currentLang === 'zh' ? 'zh-CN' : 'en-US';
        const timeStr = dt ? dt.toLocaleString(locale) : '--';
        bodyHTML += `<tr><td>${timeStr}</td>`;
        
        switch (dataType) {
            case 'temperature':
                bodyHTML += `<td>${num1(d.temperature)}</td><td>${num1(d.humidity)}</td>`;
                break;
            case 'humidity':
                bodyHTML += `<td>${num1(d.humidity)}</td><td>${num1(d.temperature)}</td>`;
                break;
            case 'door_window':
                const dwStatus = d.status === 'open' ? '已打开' : '已关闭';
                const dwClass = d.status === 'open' ? 'granted' : 'denied';
                bodyHTML += `<td>${d.device_type}</td><td>${d.device_name}</td><td><span class="status-tag ${dwClass}">${dwStatus}</span></td>`;
                break;
            case 'light':
                const lStatus = d.status === 'on' ? '开启' : '关闭';
                const lClass = d.status === 'on' ? 'granted' : 'denied';
                bodyHTML += `<td>${d.light_name}</td><td><span class="status-tag ${lClass}">${lStatus}</span></td><td>${d.brightness}</td>`;
                break;
        }
        bodyHTML += '</tr>';
    });
    
    body.innerHTML = bodyHTML || '<tr><td colspan="5">' + t('history.no_data') + '</td></tr>';
}

// 切换语言后重绘本页动态内容（统计标签/单位、时间轴文案与时间格式）
(function () {
    if (typeof window === 'undefined' || typeof window.setLang !== 'function') return;
    const original = window.setLang;
    window.setLang = function (lang) {
        original(lang);
        const select = document.getElementById('dataType');
        if (!select) return;
        applyStatView(select.value);
        loadHistory();
    };
})();

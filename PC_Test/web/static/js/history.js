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
                borderColor: '#f5b301',
                backgroundColor: 'rgba(245, 179, 1, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4,
                pointRadius: 2,
                pointBackgroundColor: '#f5b301'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: {
                        color: '#7d7264',
                        font: { size: 12 },
                        usePointStyle: true
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(255, 251, 238, 0.97)',
                    borderColor: '#eedcb0',
                    borderWidth: 1,
                    titleColor: '#39362f',
                    bodyColor: '#7d7264',
                    padding: 12
                }
            },
            scales: {
                x: {
                    ticks: { color: '#b0a390', maxTicksLimit: 12, font: { size: 10 } },
                    grid: { color: 'rgba(184, 165, 138, 0.25)' }
                },
                y: {
                    ticks: { color: '#b0a390', font: { size: 10 } },
                    grid: { color: 'rgba(184, 165, 138, 0.25)' }
                }
            }
        }
    });
}

// 统计概览区：湿度显示湿度文案与 % 单位；门窗/灯光不显示这四个统计块
function applyStatView(dataType) {
    const grid = document.getElementById('statGrid');
    if (grid) {
        grid.style.display = (dataType === 'door_window' || dataType === 'light') ? 'none' : '';
    }
    const isHumidity = dataType === 'humidity';
    const unit = isHumidity ? '%' : '°C';
    ['max', 'min', 'avg'].forEach(name => {
        const suffix = name.charAt(0).toUpperCase() + name.slice(1);
        const key = isHumidity ? `history.stat_${name}_humidity` : `history.stat_${name}`;
        const label = document.getElementById(`stat${suffix}Label`);
        if (label) {
            label.setAttribute('data-i18n', key);
            label.textContent = t(key);
        }
        const unitEl = document.getElementById(`stat${suffix}Unit`);
        if (unitEl) unitEl.textContent = unit;
    });
}

// 加载历史数据
async function loadHistory() {
    const dataType = document.getElementById('dataType').value;
    const hours = document.getElementById('timeRange').value;

    applyStatView(dataType);
    
    let data = [];
    let title = '';
    let chartLabel = '';
    let chartColor = '#f5b301';
    let chartBgColor = 'rgba(245, 179, 1, 0.1)';
    
    switch (dataType) {
        case 'temperature':
            data = await apiGet(`/api/temperature?hours=${hours}`);
            title = t('chart.temp_history');
            chartLabel = t('chart.temp');
            chartColor = '#f5b301';
            chartBgColor = 'rgba(245, 179, 1, 0.1)';
            break;
        case 'humidity':
            data = await apiGet(`/api/temperature?hours=${hours}`);
            title = t('chart.humidity_history');
            chartLabel = t('chart.humidity');
            chartColor = '#476044';
            chartBgColor = 'rgba(71, 96, 68, 0.1)';
            break;
        case 'door_window':
            data = await apiGet(`/api/door_window/history?hours=${hours}`);
            title = t('chart.door_history');
            chartLabel = t('chart.door_status');
            chartColor = '#4f6b48';
            chartBgColor = 'rgba(79, 107, 72, 0.1)';
            break;
        case 'light':
            data = await apiGet(`/api/light/history?hours=${hours}`);
            title = t('chart.light_history');
            chartLabel = t('chart.light_brightness');
            chartColor = '#e0a300';
            chartBgColor = 'rgba(245, 179, 1, 0.1)';
            break;
    }
    
    if (!data) return;
    
    document.getElementById('chartTitle').textContent = title;
    
    // 反转数据（时间升序）
    const reversed = [...data].reverse();
    
    // 更新图表
    if (historyChart) {
        const labels = reversed.map(d => {
            const dt = new Date(d.timestamp);
            const locale = I18N.currentLang === 'zh' ? 'zh-CN' : 'en-US';
            return dt.toLocaleString(locale, { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
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
        const dt = new Date(d.timestamp);
        const locale = I18N.currentLang === 'zh' ? 'zh-CN' : 'en-US';
        const timeStr = dt.toLocaleString(locale);
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

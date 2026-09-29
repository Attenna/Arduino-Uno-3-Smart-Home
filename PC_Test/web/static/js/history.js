// ==================== 历史数据页面 JS ====================
let historyChart = null;

document.addEventListener('DOMContentLoaded', () => {
    updateClock();
    setInterval(updateClock, 1000);
    initHistoryChart();
    loadHistory();
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

// 加载历史数据
async function loadHistory() {
    const dataType = document.getElementById('dataType').value;
    const hours = document.getElementById('timeRange').value;
    
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
    
    // 更新统计
    if (dataType === 'temperature' && reversed.length > 0) {
        const temps = reversed.map(d => d.temperature);
        const max = Math.max(...temps);
        const min = Math.min(...temps);
        const avg = temps.reduce((a, b) => a + b, 0) / temps.length;
        document.getElementById('statMax').textContent = max.toFixed(1);
        document.getElementById('statMin').textContent = min.toFixed(1);
        document.getElementById('statAvg').textContent = avg.toFixed(1);
        document.getElementById('statCount').textContent = reversed.length;
    } else if (dataType === 'humidity' && reversed.length > 0) {
        const hums = reversed.map(d => d.humidity);
        document.getElementById('statMax').textContent = Math.max(...hums).toFixed(1);
        document.getElementById('statMin').textContent = Math.min(...hums).toFixed(1);
        document.getElementById('statAvg').textContent = (hums.reduce((a, b) => a + b, 0) / hums.length).toFixed(1);
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
                bodyHTML += `<td>${d.temperature.toFixed(1)}</td><td>${d.humidity.toFixed(1)}</td>`;
                break;
            case 'humidity':
                bodyHTML += `<td>${d.humidity.toFixed(1)}</td><td>${d.temperature.toFixed(1)}</td>`;
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

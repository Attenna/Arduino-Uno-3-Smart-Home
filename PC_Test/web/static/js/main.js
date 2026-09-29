// ==================== 主仪表盘 JS（稳定增强版）===========================
// 增强特性：fetch 超时控制、断线检测、请求防抖、优雅降级

let statusTimer = null;
let currentLang = localStorage.getItem('smart_home_lang') || 'zh';
let isOnline = true;           // 网络连接状态
let lastStatusUpdate = Date.now();
let pendingRequests = new Set(); // 跟踪进行中请求，防止并发堆积

// ==================== 增强型 Fetch 工具 ====================

async function fetchWithTimeout(url, options = {}, timeoutMs = 8000) {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), timeoutMs);
    const requestKey = url + JSON.stringify(options.body || '');

    // 防止相同请求并发堆积
    if (pendingRequests.has(requestKey)) {
        console.warn('Duplicate request blocked:', url);
        return null;
    }
    pendingRequests.add(requestKey);

    try {
        const response = await fetch(url, { ...options, signal: controller.signal });
        clearTimeout(id);

        // 标记网络已恢复
        if (!isOnline) {
            isOnline = true;
            updateConnectionStatus(true);
        }
        return response;
    } catch (error) {
        clearTimeout(id);
        if (error.name === 'AbortError') {
            console.warn('Request timeout:', url);
        } else {
            // 网络断开
            if (isOnline) {
                isOnline = false;
                updateConnectionStatus(false);
            }
        }
        return null;
    } finally {
        pendingRequests.delete(requestKey);
    }
}

async function apiGet(url, timeoutMs = 8000) {
    try {
        const response = await fetchWithTimeout(url, {}, timeoutMs);
        if (!response) return null;
        return await response.json();
    } catch (e) {
        console.error('API GET error:', e);
        return null;
    }
}

async function apiPost(url, data, timeoutMs = 8000) {
    try {
        const response = await fetchWithTimeout(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        }, timeoutMs);
        if (!response) return null;
        return await response.json();
    } catch (e) {
        console.error('API POST error:', e);
        return null;
    }
}

// ==================== 网络连接状态 ====================

function updateConnectionStatus(online) {
    const indicator = document.getElementById('connectionIndicator');
    if (!indicator) return;

    if (online) {
        indicator.innerHTML = '<span style="color:#00e676;">&#9679;</span> ' + t('system.online');
        indicator.className = 'connection-indicator online';
    } else {
        indicator.innerHTML = '<span style="color:#ff1744;">&#9679;</span> ' + t('system.offline');
        indicator.className = 'connection-indicator offline';
    }
}

// 监听浏览器网络状态
window.addEventListener('online', () => {
    isOnline = true;
    updateConnectionStatus(true);
    loadStatus(); // 断线恢复后立刻刷新数据
});
window.addEventListener('offline', () => {
    isOnline = false;
    updateConnectionStatus(false);
});

// ==================== 防抖工具 ====================

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// ==================== 初始化 ====================

document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    loadStatus();
    startStatusPolling();
    updateClock();
    setInterval(updateClock, 1000);
    initLanguageSwitch();
});

function startStatusPolling() {
    // 清理旧定时器，防止重复
    if (statusTimer) clearInterval(statusTimer);
    statusTimer = setInterval(loadStatus, 5000);
}

// ==================== 语言切换 ====================

function initLanguageSwitch() {
    const btn = document.getElementById('langSwitch');
    if (!btn) return;
    btn.addEventListener('click', () => {
        const newLang = currentLang === 'zh' ? 'en' : 'zh';
        I18N.setLang(newLang);
        currentLang = newLang;
        updateButtonLabel();
        loadStatus();
    });
    updateButtonLabel();
}

function updateButtonLabel() {
    const btn = document.getElementById('langSwitch');
    if (!btn) return;
    const span = btn.querySelector('span');
    if (span) span.textContent = currentLang === 'zh' ? 'EN' : '中文';
}

// ==================== 数据加载 ====================

async function loadStatus() {
    // 离线时不发请求，避免请求堆积
    if (!isOnline && !navigator.onLine) {
        console.log('Offline, skipping status poll');
        return;
    }

    const data = await apiGet('/api/status');
    if (!data) {
        // 请求失败但网络标记为在线时，降级为离线
        if (isOnline) {
            isOnline = false;
            updateConnectionStatus(false);
        }
        return;
    }

    lastStatusUpdate = Date.now();
    updateDashboard(data);
}

function updateDashboard(data) {
    // 温度
    const tempEl = document.getElementById('tempValue');
    if (tempEl) tempEl.textContent = data.temperature ? data.temperature.toFixed(1) : '--';

    const humEl = document.getElementById('humidityValue');
    if (humEl) humEl.textContent = data.humidity ? data.humidity.toFixed(0) : '--';

    // 风扇
    const fanEl = document.getElementById('fanSpeed');
    if (fanEl) fanEl.textContent = data.fan_speed || 0;

    // 门窗
    const doorEl = document.getElementById('doorStatus');
    if (doorEl) {
        const doorText = data.door_status === 'open' ? t('status.open') : t('status.closed');
        doorEl.textContent = doorText;
        doorEl.className = 'status-text ' + (data.door_status === 'open' ? 'warning' : 'normal');
    }

    const windowEl = document.getElementById('windowStatus');
    if (windowEl) {
        const windowText = data.window_status === 'open' ? t('status.open') : t('status.closed');
        windowEl.textContent = windowText;
        windowEl.className = 'status-text ' + (data.window_status === 'open' ? 'warning' : 'normal');
    }

    // 灯光
    const lightEl = document.getElementById('lightStatus');
    if (lightEl) {
        const lightText = data.light_status === 'on' ? t('status.on') : t('status.off');
        lightEl.textContent = lightText;
        lightEl.className = 'status-text ' + (data.light_status === 'on' ? 'active' : 'normal');
    }

    // 空调
    const acEl = document.getElementById('acStatus');
    if (acEl) {
        const acText = data.ac_status === 'on' ? t('status.ac_on') : t('status.ac_off');
        acEl.textContent = acText;
        acEl.className = 'status-text ' + (data.ac_status === 'on' ? 'active' : 'normal');
    }

    // 统计
    if (data.statistics) {
        updateStats(data.statistics);
    }
}

function updateStats(stats) {
    const temp24h = stats.temperature_24h || {};
    const avgTempEl = document.getElementById('avgTemp24h');
    if (avgTempEl) avgTempEl.textContent = temp24h.avg ? temp24h.avg.toFixed(1) + '\u00b0C' : '--';

    const access24h = stats.access_24h || {};
    const accessEl = document.getElementById('accessCount24h');
    if (accessEl) accessEl.textContent = access24h.total || 0;

    const light24h = stats.light_24h || {};
    const lightEl = document.getElementById('lightUsage24h');
    if (lightEl) lightEl.textContent = light24h.total_changes || 0;
}

// ==================== 控制操作（带防抖） ====================

async function toggleDoor() {
    const data = await apiGet('/api/door');
    const newStatus = (data && data.door_status === 'open') ? 'closed' : 'open';
    const result = await apiPost('/api/door', { status: newStatus });
    if (result) {
        showNotification(getMessage(result));
        loadStatus();
    }
}

async function toggleWindow() {
    const data = await apiGet('/api/window');
    const newStatus = (data && data.window_status === 'open') ? 'closed' : 'open';
    const result = await apiPost('/api/window', { status: newStatus });
    if (result) {
        showNotification(getMessage(result));
        loadStatus();
    }
}

async function toggleLight() {
    const data = await apiGet('/api/light');
    const newStatus = (data && data.light_status === 'on') ? 'off' : 'on';
    const brightness = document.getElementById('lightBrightness')?.value || 50;
    const result = await apiPost('/api/light', { status: newStatus, brightness: parseInt(brightness) });
    if (result) {
        showNotification(getMessage(result));
        loadStatus();
    }
}

async function setFanSpeed() {
    const speed = document.getElementById('fanSpeedControl')?.value || 0;
    const result = await apiPost('/api/fan', { speed: parseInt(speed) });
    if (result) {
        showNotification(getMessage(result));
        loadStatus();
    }
}

async function toggleAC() {
    const data = await apiGet('/api/ac');
    const newStatus = (data && data.ac_status === 'on') ? 'off' : 'on';
    const temp = document.getElementById('acTemperature')?.value || 26;
    const result = await apiPost('/api/ac', { status: newStatus, temperature: parseInt(temp) });
    if (result) {
        showNotification(getMessage(result));
        loadStatus();
    }
}

// ==================== 通知 ====================

function showNotification(message, type = 'info') {
    const el = document.getElementById('notification');
    if (!el) return;
    el.textContent = message;
    el.className = `notification ${type} show`;
    setTimeout(() => { el.className = 'notification hidden'; }, 3000);
}

function getMessage(result) {
    return currentLang === 'en' ? (result.message_en || result.message) : result.message;
}

// ==================== 时钟 ====================

function updateClock() {
    const now = new Date();
    const el = document.getElementById('currentTime');
    if (!el) return;
    const locale = currentLang === 'zh' ? 'zh-CN' : 'en-US';
    el.textContent = now.toLocaleTimeString(locale, { hour12: false });
}

// ==================== 图表 ====================

function initCharts() {
    loadTemperatureChart();
}

async function loadTemperatureChart() {
    const data = await apiGet('/api/temperature?hours=24');
    if (!data || data.length === 0) return;

    const ctx = document.getElementById('tempChart');
    if (!ctx) return;

    const labels = data.slice(0, 20).reverse().map(d => {
        const dt = new Date(d.timestamp);
        return dt.getHours() + ':' + dt.getMinutes().toString().padStart(2, '0');
    });
    const temps = data.slice(0, 20).reverse().map(d => d.temperature);
    const hums = data.slice(0, 20).reverse().map(d => d.humidity);

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: t('chart.temp'),
                    data: temps,
                    borderColor: '#00e5ff',
                    backgroundColor: 'rgba(0, 229, 255, 0.1)',
                    tension: 0.4,
                    fill: true
                },
                {
                    label: t('chart.humidity'),
                    data: hums,
                    borderColor: '#7c4dff',
                    backgroundColor: 'rgba(124, 77, 255, 0.1)',
                    tension: 0.4,
                    fill: true,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            plugins: {
                legend: {
                    labels: { color: '#b0b0b0' }
                }
            },
            scales: {
                x: {
                    ticks: { color: '#b0b0b0' },
                    grid: { color: 'rgba(255,255,255,0.05)' }
                },
                y: {
                    ticks: { color: '#b0b0b0' },
                    grid: { color: 'rgba(255,255,255,0.05)' },
                    title: { display: true, text: '\u00b0C', color: '#b0b0b0' }
                },
                y1: {
                    position: 'right',
                    ticks: { color: '#b0b0b0' },
                    grid: { display: false },
                    title: { display: true, text: '%', color: '#b0b0b0' }
                }
            }
        }
    });
}

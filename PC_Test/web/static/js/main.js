// ==================== 主仪表盘 JS（稳定增强版）===========================
// 增强特性：fetch 超时控制、断线检测、请求防抖、优雅降级

let statusTimer = null;
let currentLang = localStorage.getItem('smart_home_lang') || 'zh';
let isOnline = true;           // 网络连接状态
let lastStatusUpdate = Date.now();
let pendingRequests = new Set(); // 跟踪进行中请求，防止并发堆积

// 空调最后一次成功下发的状态（来自 /api/status 回显），供"合并式"操作补齐
let acState = { power: false, mode: 'auto', temperature: 26, fan: 'auto',
                swing_ud: false, swing_lr: false };

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

async function apiPost(url, data, timeoutMs = 15000) {
    try {
        const response = await fetchWithTimeout(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        }, timeoutMs);
        if (!response) {
            showNotification(currentLang === 'en'
                ? 'Request timeout or network error'
                : '请求超时或网络错误', 'error');
            return null;
        }
        let body = null;
        try { body = await response.json(); } catch (e) { body = null; }
        if (!response.ok) {
            // 硬件离线(503)/参数错误(400)/服务器错误(500)：把后端消息弹给用户
            const msg = (currentLang === 'en' ? (body && body.error_en) : (body && body.error))
                || (body && body.detail)
                || (currentLang === 'en' ? `Request failed (HTTP ${response.status})`
                                        : `操作失败（HTTP ${response.status}）`);
            showNotification(msg, 'error');
            return null;
        }
        return body;
    } catch (e) {
        console.error('API POST error:', e);
        showNotification(currentLang === 'en' ? 'Request failed' : '请求失败', 'error');
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
    initControlSliders();
});

// 滑块：拖动时只更新数值标签，松手(change)才下发硬件指令，避免串口刷屏
function initControlSliders() {
    const fanSlider = document.getElementById('fanSpeed');
    if (fanSlider) {
        const fanLabel = document.getElementById('fanSpeedValue');
        fanSlider.addEventListener('input', () => {
            if (fanLabel) fanLabel.textContent = fanSlider.value + '%';
        });
        fanSlider.addEventListener('change', () => setFan(parseInt(fanSlider.value)));
    }
    const brightSlider = document.getElementById('brightnessSlider');
    if (brightSlider) {
        const brightLabel = document.getElementById('brightnessValue');
        brightSlider.addEventListener('input', () => {
            if (brightLabel) brightLabel.textContent = brightSlider.value + '%';
        });
        brightSlider.addEventListener('change', () => {
            const v = parseInt(brightSlider.value);
            setLight(v > 0 ? 'on' : 'off', v);
        });
    }
    const acSlider = document.getElementById('acTempSlider');
    if (acSlider) {
        const acLabel = document.getElementById('acTempLabel');
        acSlider.addEventListener('input', () => {
            if (acLabel) acLabel.textContent = Number(acSlider.value).toFixed(1) + '\u00b0C';
        });
        acSlider.addEventListener('change', () => setACTemp(acSlider.value));
    }
}

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

    // 风扇（fanSpeed 是滑块 input，fanSpeedValue 是数值标签，扇叶按转速分档旋转）
    const fanSpeed = Number(data.fan_speed) || 0;
    const fanSlider = document.getElementById('fanSpeed');
    if (fanSlider && document.activeElement !== fanSlider) fanSlider.value = fanSpeed;
    const fanLabel = document.getElementById('fanSpeedValue');
    if (fanLabel) fanLabel.textContent = fanSpeed + '%';
    const blades = document.getElementById('fanBlades');
    if (blades) {
        blades.classList.remove('spinning', 'spinning-slow', 'spinning-medium', 'spinning-fast');
        if (fanSpeed > 0) {
            blades.classList.add(
                fanSpeed <= 40 ? 'spinning-slow' : fanSpeed <= 75 ? 'spinning-medium' : 'spinning-fast');
        }
    }

    // 灯光（灯泡高亮 + 指示点 + 亮度滑块回写，拖动时不抢焦点）
    const lightOn = data.light_status === 'on';
    const brightness = Number(data.light_brightness) || (lightOn ? 100 : 0);
    const bulb = document.getElementById('bulb');
    if (bulb) {
        bulb.classList.toggle('on', lightOn);
        bulb.style.opacity = lightOn ? String(0.35 + 0.65 * brightness / 100) : '';
    }
    const lightIndicator = document.getElementById('lightIndicator');
    if (lightIndicator) lightIndicator.classList.toggle('on', lightOn);
    const brightSlider = document.getElementById('brightnessSlider');
    if (brightSlider && document.activeElement !== brightSlider) brightSlider.value = brightness;
    const brightLabel = document.getElementById('brightnessValue');
    if (brightLabel) brightLabel.textContent = brightness + '%';

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

    // 空调（美的红外）：回写读数、滑块与各按钮选中态
    acState = {
        power: data.ac_status === 'on',
        mode: data.ac_mode || 'auto',
        temperature: Number(data.ac_temperature) || 26,
        fan: data.ac_fan || 'auto',
        swing_ud: !!data.ac_swing_ud,
        swing_lr: !!data.ac_swing_lr,
    };
    const acIndicator = document.getElementById('acIndicator');
    if (acIndicator) acIndicator.classList.toggle('on', acState.power);
    const acTempEl = document.getElementById('acTempValue');
    if (acTempEl) acTempEl.textContent = acState.power ? Math.round(acState.temperature) + '°C' : '--';
    const acModeEl = document.getElementById('acModeValue');
    if (acModeEl) acModeEl.textContent = acState.power ? t('ac.mode_' + acState.mode) : t('ac.off_hint');
    const acSliderEl = document.getElementById('acTempSlider');
    if (acSliderEl && document.activeElement !== acSliderEl) acSliderEl.value = acState.temperature;
    const acTempLabel = document.getElementById('acTempLabel');
    if (acTempLabel) acTempLabel.textContent = Math.round(acState.temperature) + '°C';
    document.querySelectorAll('#acModeButtons [data-ac-mode]').forEach(btn => {
        btn.classList.toggle('active', acState.power && btn.dataset.acMode === acState.mode);
    });
    document.querySelectorAll('#acFanButtons [data-ac-fan]').forEach(btn => {
        btn.classList.toggle('active', acState.power && btn.dataset.acFan === acState.fan);
    });
    [['acSwingUdBtn', 'swing_ud'], ['acSwingLrBtn', 'swing_lr']].forEach(([id, key]) => {
        const btn = document.getElementById(id);
        if (btn) btn.classList.toggle('active', acState[key]);
    });
    const acPowerBtn = document.getElementById('acPowerBtn');
    if (acPowerBtn) acPowerBtn.textContent = t(acState.power ? 'ac.power_off' : 'ac.power_on');

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

// 灯光卡片按钮：全亮/半亮/夜灯/关闭
async function setLight(status, brightness) {
    const result = await apiPost('/api/light', { status, brightness: Number(brightness) || 0 });
    if (result) {
        showNotification(getMessage(result));
        loadStatus();
    }
}

// 风扇卡片按钮：关闭/低速/中速/高速
async function setFan(speed) {
    const result = await apiPost('/api/fan', { speed: Number(speed) || 0 });
    if (result) {
        showNotification(getMessage(result));
        loadStatus();
    }
}

// ==================== 空调（美的红外）====================
// 空调每条指令都会带上完整状态（红外一帧就含开关/模式/温度/风速），
// 所以这里只传变化项，由后端按库里当前值补齐后整帧下发。

async function setAC(partial) {
    const body = { ...partial };
    // 未开机时改模式/温度/风速 → 自动带开机，避免"设置被忽略"这种哑路径
    if (body.power === undefined && !acState.power) body.power = true;
    const result = await apiPost('/api/ac', body);
    if (result) {
        showNotification(getMessage(result));
        loadStatus();
    }
}

function toggleAC() { setAC({ power: !acState.power }); }
function setACMode(mode) { setAC({ mode }); }
function setACTemp(value) { setAC({ temperature: Number(value) }); }
function setACFan(fan) { setAC({ fan }); }
function toggleACOption(key) { setAC({ [key]: !acState[key] }); }

// 远程控制面板：light_on/off、fan_on/off、door_open/close、ac_on/off
async function remoteControl(action) {
    const posts = {
        light_on:  ['/api/light', { status: 'on', brightness: 100 }],
        light_off: ['/api/light', { status: 'off', brightness: 0 }],
        fan_on:    ['/api/fan', { speed: 60 }],
        fan_off:   ['/api/fan', { speed: 0 }],
        door_open: ['/api/door', { status: 'open' }],
        door_close:['/api/door', { status: 'closed' }],
        ac_on:     ['/api/ac', { power: true }],
        ac_off:    ['/api/ac', { power: false }],
    };
    const target = posts[action];
    if (!target) return;
    const result = await apiPost(target[0], target[1]);
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

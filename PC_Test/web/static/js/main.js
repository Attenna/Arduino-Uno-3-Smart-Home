// ==================== 主仪表盘 JS（稳定增强版）===========================
// 增强特性：fetch 超时控制、断线检测、请求防抖、优雅降级

let statusTimer = null;
let currentLang = localStorage.getItem('smart_home_lang') || 'zh';
let isOnline = true;           // 网络连接状态
let lastStatusUpdate = Date.now();
let pendingRequests = new Set(); // 跟踪进行中请求，防止并发堆积
let lastStatus = null;         // 缓存最近一次 /api/status，供语言切换时重渲染指示器

// 空调最后一次成功下发的状态（来自 /api/status 回显），供"合并式"操作补齐
let acState = { power: false, mode: 'auto', temperature: 26, fan: 'auto',
                swing_ud: false, swing_lr: false };

// 最近一次 /api/status 回显的风扇/灯光状态：值没变就不下发，
// 屏蔽移动端滑块连续 change、重复点击造成的无意义指令
let lastKnownFanSpeed = null;
let lastKnownLight = null;   // { status: 'on'|'off', brightness: Number }

// 页面实例标识 + 单调命令序号：服务端据此识别「迟到的旧命令」并丢弃，
// 防止弱网下请求乱序到达（例如先关后开两请求颠倒 → 风扇关了又自己开）。
// 每个标签页/每次加载都是新实例，互不影响；序号只在本实例内比较。
const CLIENT_ID = 'cid-' + Math.random().toString(36).slice(2, 10)
    + '-' + Date.now().toString(36);
let cmdSeq = 0;

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
        // 所有控制类 POST 带页面实例标识与单调序号，服务端命令收口器据此
        // 丢弃迟到旧命令、合并连点；非设备接口会忽略这两个字段。
        const payload = { ...(data || {}), _cid: CLIENT_ID, _seq: ++cmdSeq };
        const response = await fetchWithTimeout(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
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
    function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    }
    // cancel()：页面隐藏/卸载时把「还在防抖窗口里」的调用丢掉。否则用户拖完滑块
    // 立刻切页/关页，300ms 后指令仍会在新页面上补发出去（表现为「进了别的页面
    // 风扇自己动了」）。
    executedFunction.cancel = () => {
        clearTimeout(timeout);
        timeout = undefined;
    };
    return executedFunction;
}

// 动作防连点：门/窗/空调经串口往返要数秒，手机上点击没有即时反馈时用户会
// 连点，移动端触摸还可能对同一元素双发 click。同名动作执行期间（+500ms）
// 忽略重复触发；风扇/灯光另有 300ms 防抖收口，不走这里。
const _tapsInFlight = new Set();
function tapGuard(key, fn, cooldownMs = 500) {
    if (_tapsInFlight.has(key)) return;
    _tapsInFlight.add(key);
    Promise.resolve()
        .then(fn)
        .catch(() => {})
        .finally(() => setTimeout(() => _tapsInFlight.delete(key), cooldownMs));
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

// 滑块：拖动时只更新数值标签，松手(change)才下发硬件指令，避免串口刷屏。
//
// 关键：**只有用户真的拖过这个滑块才允许下发**。服务端每 5s 轮询会用 loadStatus()
// 把滑块 value 程序化回写，而手机浏览器在「元素曾获焦 / 标签页被恢复」等情形下会对
// range 补发一次 change（change 的语义是"值被提交"，不等价于用户操作）。补发一次就
// 会把 DB 里的旧值当成用户指令发出去 → 表现为「没人碰它，风扇自己启动了」。
// 判据用 input 事件：程序化赋值 .value 不会触发 input，只有真实操作才会，可靠且无需
// 额外监听。三个滑块（风扇/灯光/空调）都是执行器，一律照此收口。
function bindActuatorSlider(slider, label, formatLabel, onCommit) {
    if (!slider) return;
    let userTouched = false;
    slider.addEventListener('input', () => {
        userTouched = true;                 // 真实操作过（程序化赋值不会触发 input）
        if (label) label.textContent = formatLabel(slider.value);
    });
    slider.addEventListener('change', () => {
        if (!userTouched) return;           // 浏览器/程序化补发的 change：不是用户操作
        userTouched = false;
        onCommit(slider.value);
    });
}

function initControlSliders() {
    bindActuatorSlider(document.getElementById('fanSpeed'),
                       document.getElementById('fanSpeedValue'),
                       v => v + '%',
                       v => setFan(parseInt(v)));
    bindActuatorSlider(document.getElementById('brightnessSlider'),
                       document.getElementById('brightnessValue'),
                       v => v + '%',
                       v => {
                           const n = parseInt(v);
                           setLight(n > 0 ? 'on' : 'off', n);
                       });
    bindActuatorSlider(document.getElementById('acTempSlider'),
                       document.getElementById('acTempLabel'),
                       v => Number(v).toFixed(1) + '\u00b0C',
                       v => setACTemp(v));
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
    lastStatus = data;
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
    lastKnownFanSpeed = fanSpeed;
    const fanSlider = document.getElementById('fanSpeed');
    if (fanSlider && document.activeElement !== fanSlider) fanSlider.value = fanSpeed;
    const fanLabel = document.getElementById('fanSpeedValue');
    if (fanLabel) fanLabel.textContent = fanSpeed + '%';
    // 风扇硬件回读（B 板真值）：仅在有回读时显示小号文字
    const fanRbRow = document.getElementById('fanReadback');
    const fanRbVal = document.getElementById('fanReadbackValue');
    if (fanRbRow && fanRbVal) {
        if (data.rb_fan_speed === null || data.rb_fan_speed === undefined) {
            fanRbRow.classList.add('hidden');
        } else {
            fanRbRow.classList.remove('hidden');
            fanRbVal.textContent = data.rb_fan_speed + '%';
        }
    }
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
    lastKnownLight = { status: lightOn ? 'on' : 'off', brightness };
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

    // 硬件回读一致性指示器
    updateMismatchIndicator(data);

    // 串口链路健康度（A/B 板连接、重连/复位/告警计数）
    updateSerialHealth(data);

    // 统计
    if (data.statistics) {
        updateStats(data.statistics);
    }
}

// ==================== 硬件回读一致性指示器 ====================
// B 板回读值 vs 命令下发值。后端已做防误报（回读过期/刚下发不判定），前端只负责
// 让不一致"一眼可见"：非空即告警，空且回读可见为轻量正常态，无回读则明确不可用。

// 门/窗用可读开合文案，风扇/灯光用百分比
function formatReadback(device, value) {
    if (device === 'door' || device === 'window') {
        return value === 'open' ? t('status.open') : t('status.closed');
    }
    return value + '%';
}

// 设备名走 i18n；未知设备回退后端下发的 label
function mismatchDeviceLabel(device, fallback) {
    const key = 'mismatch.dev_' + device;
    const text = t(key);
    return text === key ? (fallback || device) : text;
}

function updateMismatchIndicator(data) {
    const el = document.getElementById('mismatchIndicator');
    if (!el) return;
    const list = Array.isArray(data.device_mismatch) ? data.device_mismatch : [];

    if (list.length > 0) {
        // 告警态：逐条显示「⚠ 硬件与指令不一致：<设备> 指令 X / 回读 Y」
        el.className = 'mismatch-indicator danger';
        el.innerHTML = list.map(item => {
            const name = mismatchDeviceLabel(item.device, item.label);
            return '<div class="mismatch-row">\u26a0 ' + t('mismatch.title') + '：'
                + name + ' ' + t('mismatch.cmd') + ' ' + formatReadback(item.device, item.commanded)
                + ' / ' + t('mismatch.rb') + ' ' + formatReadback(item.device, item.readback)
                + '</div>';
        }).join('');
    } else if (data.rb_seen_at) {
        // 正常态：低调提示，不抢视觉
        el.className = 'mismatch-indicator ok';
        el.innerHTML = '<div class="mismatch-row">\u2713 ' + t('mismatch.ok') + '</div>';
    } else {
        // 无回读：无法判断一致性
        el.className = 'mismatch-indicator na';
        el.innerHTML = '<div class="mismatch-row">' + t('mismatch.unavailable') + '</div>';
    }
}

// ==================== 串口链路健康度 ====================
// 数据来自后端低频刷新的 get_serial_health：A/B 板是否连着，以及 B 板重连/复位/
// 告警/心跳失败计数。正常时低调一行；离线或出现重连/告警/心跳失败才高亮。
// 注意 reset_count > 0 是正常的（MCP 每次启动开串口都会复位一次 B 板），不当作异常。
function updateSerialHealth(data) {
    const el = document.getElementById('serialHealth');
    if (!el) return;
    const health = data.serial_health;
    if (!health || !health.b) {
        el.className = 'serial-health warn';
        el.textContent = t('serial.title') + '：' + t('serial.unavailable');
        return;
    }
    const a = health.a || {};
    const b = health.b || {};
    const reopens = Number(b.reopen_count) || 0;
    const alerts = Number(b.alert_count) || 0;
    const hbFails = Number(b.heartbeat_fails) || 0;
    const parts = [
        'A ' + t(a.connected ? 'serial.online' : 'serial.offline'),
        'B ' + t(b.connected ? 'serial.online' : 'serial.offline'),
        t('serial.reopen') + ' ' + reopens,
        t('serial.reset') + ' ' + (Number(b.reset_count) || 0),
        t('serial.alert') + ' ' + alerts,
        t('serial.hbfail') + ' ' + hbFails,
    ];
    const bad = !a.connected || !b.connected || reopens > 0 || alerts > 0 || hbFails > 0;
    el.className = 'serial-health ' + (bad ? 'warn' : 'ok');
    el.textContent = t('serial.title') + '：' + parts.join(' · ');
}

// 语言切换：切换后立即用缓存状态重渲染指示器，避免告警文案被 applyI18n 重置为默认值
function toggleDashboardLang() {
    setLang(I18N.currentLang === 'zh' ? 'en' : 'zh');
    if (lastStatus) {
        updateMismatchIndicator(lastStatus);
        updateSerialHealth(lastStatus);
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

function guardDoor() { tapGuard('door', toggleDoor); }

async function toggleWindow() {
    const data = await apiGet('/api/window');
    const newStatus = (data && data.window_status === 'open') ? 'closed' : 'open';
    const result = await apiPost('/api/window', { status: newStatus });
    if (result) {
        showNotification(getMessage(result));
        loadStatus();
    }
}

function guardWindow() { tapGuard('window', toggleWindow); }

// 灯光卡片按钮：全亮/半亮/夜灯/关闭
// 移动端浏览器拖动 range 时会连续触发 change（不像桌面端只在松手时触发一次），
// 直接下发会让滑块经过的每个中间值都打到串口。统一用 300ms 防抖收口，
// 连续操作只下发最后一次。
//
// 去重只认「本页正在下发的同一意图」，**绝不拿服务端回报的状态当依据**：web 是
// --no-serial，DB 里的 light_status/light_brightness 只是「上次命令值」，灯被 B 板
// 复位或外部关掉后它仍可能记着 on/100。拿它去重会把用户的点击静默吞掉——连请求都
// 不发、也没有任何提示，表现为「按下没反应」（后端 /api/light 同样已去掉 DB 幂等）。
let lightInflight = null;    // 正在飞的意图串 status/brightness
const postLightDebounced = debounce(async (status, brightness) => {
    brightness = Number(brightness) || 0;
    const target = status + '/' + brightness;
    if (lightInflight === target) {
        return;              // 同一意图已在飞（触摸双发/连点），其结果即本次结果
    }
    lightInflight = target;
    // 乐观更新：立即刷新本地显示，指令在飞期间界面不卡顿；
    // 失败时 loadStatus() 会用服务端真值回滚界面
    lastKnownLight = { status, brightness };
    const bSlider = document.getElementById('brightnessSlider');
    if (bSlider && document.activeElement !== bSlider) bSlider.value = brightness;
    const bLabel = document.getElementById('brightnessValue');
    if (bLabel) bLabel.textContent = brightness + '%';
    try {
        const result = await apiPost('/api/light', { status, brightness });
        if (result) {
            showNotification(getMessage(result));
        }
    } finally {
        if (lightInflight === target) lightInflight = null;
    }
    loadStatus();
}, 300);

function setLight(status, brightness) {
    postLightDebounced(status, Number(brightness) || 0);
}

// 风扇卡片按钮：关闭/低速/中速/高速（与灯光相同的防抖收口原因）
//
// 去重同样只认「本页正在下发的同一意图」，**绝不拿服务端回报的状态当依据**：web 是
// --no-serial，DB 里的 fan_speed 只是「上次命令值」，风扇被外部原因转起来或 B 板复位
// 后它仍可能记着 0。拿它去重，用户点「关闭」会被静默吞掉（连请求都不发、没有提示，
// 表现为「关了没反应 / 关不掉」）。后端 /api/fan 早已去掉 DB 幂等，前端这里补齐。
let fanInflight = null;      // 正在飞的转速
const postFanDebounced = debounce(async (speed) => {
    speed = Number(speed) || 0;
    if (fanInflight === speed) {
        return;              // 同一意图已在飞（触摸双发/连点），其结果即本次结果
    }
    fanInflight = speed;
    // 乐观更新：立即刷新本地显示，指令在飞期间界面不卡顿；
    // 失败时 loadStatus() 用服务端回滚
    lastKnownFanSpeed = speed;
    const fSlider = document.getElementById('fanSpeed');
    if (fSlider && document.activeElement !== fSlider) fSlider.value = speed;
    const fLabel = document.getElementById('fanSpeedValue');
    if (fLabel) fLabel.textContent = speed + '%';
    try {
        const result = await apiPost('/api/fan', { speed });
        if (result) {
            showNotification(getMessage(result));
        }
    } finally {
        if (fanInflight === speed) fanInflight = null;
    }
    loadStatus();
}, 300);

function setFan(speed) {
    postFanDebounced(Number(speed) || 0);
}

// 离开页面时取消未发出的执行器指令（风扇/灯光）。防抖窗口内的调用若在切页后
// 才落地，就等于「用户已经不在这个页面，硬件却动了」——这正是"进别的页面风扇
// 自己启动"最像的一条路径。pagehide 比 unload 可靠（移动端后台/页面恢复都触发）。
window.addEventListener('pagehide', () => {
    postFanDebounced.cancel();
    postLightDebounced.cancel();
});

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
function remoteControl(action) {
    // 风扇/灯光复用带防抖、乐观更新与"同值不下发"的收口，避免远程面板连点刷屏
    if (action === 'fan_on')  { setFan(60); return; }
    if (action === 'fan_off') { setFan(0); return; }
    if (action === 'light_on')  { setLight('on', 100); return; }
    if (action === 'light_off') { setLight('off', 0); return; }
    // 门/空调为秒级慢动作：同名动作在执行期间忽略重复点击（触摸双发/连点）
    tapGuard('rc-' + action, async () => {
        const posts = {
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
    });
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
        const dt = serverDate(d.timestamp);
        return dt ? dt.getHours() + ':' + dt.getMinutes().toString().padStart(2, '0') : '--';
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

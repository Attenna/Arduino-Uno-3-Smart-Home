// ==================== 硬件管理页面 JS ====================

document.addEventListener('DOMContentLoaded', () => {
    updateClock();
    setInterval(updateClock, 1000);
    loadHAConfig();
    loadMapping();
});

function updateClock() {
    const now = new Date();
    const locale = I18N.currentLang === 'zh' ? 'zh-CN' : 'en-US';
    const el = document.getElementById('currentTime');
    if (el) el.textContent = now.toLocaleTimeString(locale, { hour12: false });
}

function showNotification(message, type = 'info') {
    const el = document.getElementById('notification');
    if (!el) return;
    el.textContent = message;
    el.className = `notification ${type} show`;
    setTimeout(() => { el.className = 'notification hidden'; }, 3000);
}

async function apiGet(url) {
    try { return await (await fetch(url)).json(); }
    catch (e) { console.error('API GET error:', e); return null; }
}

async function apiPost(url, data) {
    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    } catch (e) { console.error('API POST error:', e); return null; }
}

// ==================== 测试HA连接 ====================
async function testConnection() {
    const url = document.getElementById('haUrl').value.trim();
    const token = document.getElementById('haToken').value.trim();
    const isZh = I18N.currentLang === 'zh';

    if (!url || !token) {
        showNotification(isZh ? '请填写HA地址和Token' : 'Please enter HA URL and Token', 'error');
        return;
    }

    const badge = document.getElementById('haStatus');
    badge.textContent = isZh ? '连接中...' : 'Connecting...';
    badge.className = 'ha-status-badge';

    // 先临时设置URL和Token
    ha_client.base_url = url;
    ha_client.token = token;

    const result = await apiGet('/api/ha/connection');
    const infoEl = document.getElementById('haInfo');

    if (result && result.connected) {
        badge.textContent = isZh ? '已连接' : 'Connected';
        badge.className = 'ha-status-badge connected';
        showNotification(isZh ? 'Home Assistant 连接成功' : 'Home Assistant connected successfully', 'success');

        // 获取详细信息
        const config = await apiGet('/api/ha/config');
        if (config && config.ha_config) {
            const c = config.ha_config;
            infoEl.innerHTML = isZh
                ? `HA 版本: <strong>${c.version || '--'}</strong> | ${c.location || ''} | ${c.timezone || ''}`
                : `HA Version: <strong>${c.version || '--'}</strong> | ${c.location || ''} | ${c.timezone || ''}`;
            infoEl.className = 'ha-info show';
        }
    } else {
        badge.textContent = isZh ? '连接失败' : 'Connection Failed';
        badge.className = 'ha-status-badge error';
        const errMsg = result?.message || (isZh ? '连接失败' : 'Connection failed');
        showNotification(isZh ? `连接失败: ${errMsg}` : `Connection failed: ${errMsg}`, 'error');
        infoEl.innerHTML = isZh ? `错误: ${errMsg}` : `Error: ${errMsg}`;
        infoEl.className = 'ha-info show';
    }
}

// ==================== 保存HA配置 ====================
async function saveConfig() {
    const url = document.getElementById('haUrl').value.trim();
    const token = document.getElementById('haToken').value.trim();
    const isZh = I18N.currentLang === 'zh';

    if (!url || !token) {
        showNotification(isZh ? '请填写HA地址和Token' : 'Please enter HA URL and Token', 'error');
        return;
    }

    const result = await apiPost('/api/ha/config', { ha_url: url, ha_token: token });
    const msg = I18N.currentLang === 'en' ? (result?.message_en || result?.message) : result?.message;
    showNotification(msg, result ? 'success' : 'error');
}

// ==================== 发现设备 ====================
async function discoverDevices() {
    const isZh = I18N.currentLang === 'zh';
    const tbody = document.getElementById('deviceListBody');
    tbody.innerHTML = `<tr><td colspan="5">${isZh ? '正在发现设备...' : 'Discovering devices...'}</td></tr>`;

    const devices = await apiGet('/api/ha/devices');

    if (devices && devices.length > 0) {
        tbody.innerHTML = '';
        devices.forEach(device => {
            const eid = device.entity_id;
            const name = device.friendly_name;
            const state = device.state;
            const domain = device.domain;
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><code style="font-size:12px">${eid}</code></td>
                <td>${name}</td>
                <td><span class="status-tag ${state === 'on' ? 'granted' : ''}">${state}</span></td>
                <td>${domain}</td>
                <td><button class="btn btn-sm" onclick="quickMap('${eid}')">${isZh ? '快速映射' : 'Quick Map'}</button></td>
            `;
            tbody.appendChild(tr);
        });
        document.getElementById('deviceCount').textContent = isZh ? `${devices.length} 个设备` : `${devices.length} devices`;
        showNotification(isZh ? `发现 ${devices.length} 个设备` : `Found ${devices.length} devices`, 'success');
    } else {
        tbody.innerHTML = `<tr><td colspan="5">${isZh ? '未发现设备，请检查HA连接' : 'No devices found'}</td></tr>`;
        showNotification(isZh ? '未发现设备' : 'No devices found', 'error');
    }
}

// ==================== 加载HA配置到输入框 ====================
async function loadHAConfig() {
    const result = await apiGet('/api/ha/config');
    if (!result) return;

    const urlEl = document.getElementById('haUrl');
    const tokenEl = document.getElementById('haToken');
    if (urlEl && result.ha_url) urlEl.value = result.ha_url;
    if (tokenEl && result.ha_token) tokenEl.value = result.ha_token;
}

// ==================== 加载设备映射表 ====================
async function loadMapping() {
    const isZh = I18N.currentLang === 'zh';
    const result = await apiGet('/api/ha/config');
    const tbody = document.getElementById('mappingBody');
    if (!tbody || !result) return;

    const mapping = result.device_mapping || {};
    tbody.innerHTML = '';

    const deviceTypes = [
        { key: 'temperature_sensor', label_zh: '温度传感器', label_en: 'Temperature Sensor' },
        { key: 'humidity_sensor', label_zh: '湿度传感器', label_en: 'Humidity Sensor' },
        { key: 'front_door', label_zh: '前门传感器', label_en: 'Front Door Sensor' },
        { key: 'living_window', label_zh: '窗户传感器', label_en: 'Window Sensor' },
        { key: 'main_light', label_zh: '灯光', label_en: 'Light' },
        { key: 'fan', label_zh: '风扇', label_en: 'Fan' },
        { key: 'ac', label_zh: '空调', label_en: 'AC' },
        { key: 'door_lock', label_zh: '门锁', label_en: 'Door Lock' },
        { key: 'camera', label_zh: '摄像头', label_en: 'Camera' },
    ];

    deviceTypes.forEach(dt => {
        const eid = mapping[dt.key] || '';
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${isZh ? dt.label_zh : dt.label_en}</strong></td>
            <td><code style="font-size:12px">${eid || (isZh ? '未映射' : 'Not mapped')}</code></td>
            <td></td>
            <td><button class="btn btn-sm" onclick="promptMapping('${dt.key}', '${isZh ? dt.label_zh : dt.label_en}')">${isZh ? '设置' : 'Set'}</button></td>
        `;
        tbody.appendChild(tr);
    });
}

async function promptMapping(deviceType, label) {
    const isZh = I18N.currentLang === 'zh';
    const eid = prompt(isZh ? `请输入 ${label} 的 HA 实体 ID (如 sensor.temperature):` : `Enter HA Entity ID for ${label}:`);
    if (!eid) return;

    const result = await apiPost('/api/ha/mapping', { device_type: deviceType, entity_id: eid });
    const msg = I18N.currentLang === 'en' ? (result?.message_en || result?.message) : result?.message;
    showNotification(msg, result ? 'success' : 'error');
    loadMapping();
}

async function quickMap(entityId) {
    const isZh = I18N.currentLang === 'zh';
    const deviceType = prompt(isZh ? `将 ${entityId} 映射到哪个设备类型？\n(temperature_sensor / humidity_sensor / front_door / living_window / main_light / fan / ac / door_lock / camera)` : `Map ${entityId} to which device type?\n(temperature_sensor / humidity_sensor / front_door / living_window / main_light / fan / ac / door_lock / camera)`);
    if (!deviceType) return;

    const result = await apiPost('/api/ha/mapping', { device_type: deviceType, entity_id: entityId });
    const msg = I18N.currentLang === 'en' ? (result?.message_en || result?.message) : result?.message;
    showNotification(msg, result ? 'success' : 'error');
    loadMapping();
}

// ==================== 快捷硬件控制 ====================
async function haAction(device, action) {
    const isZh = I18N.currentLang === 'zh';
    const labels = isZh
        ? { light_on: '开灯', light_off: '关灯', ac_on: '开空调', ac_off: '关空调', fan_on: '开风扇', fan_off: '关风扇', door_unlock: '开锁', door_lock: '上锁' }
        : { light_on: 'Light On', light_off: 'Light Off', ac_on: 'AC On', ac_off: 'AC Off', fan_on: 'Fan On', fan_off: 'Fan Off', door_unlock: 'Unlock', door_lock: 'Lock' };

    const key = `${device}_${action}`;
    showNotification(isZh ? `正在执行: ${labels[key] || key}` : `Executing: ${labels[key] || key}`, 'info');

    let result;
    switch (device) {
        case 'light':
            result = await apiPost('/api/ha/light', { action, brightness: action === 'on' ? 100 : 0 });
            break;
        case 'ac':
            result = await apiPost('/api/ha/ac', { mode: action === 'on' ? 'cool' : 'off' });
            break;
        case 'fan':
            result = await apiPost('/api/ha/fan', { speed: action === 'on' ? 100 : 0 });
            break;
        case 'door':
            result = await apiPost('/api/ha/door', { action });
            break;
    }

    if (result && result.success) {
        showNotification(`${labels[key]} - ${isZh ? '成功' : 'Success'}`, 'success');
    } else {
        showNotification(`${labels[key]} - ${isZh ? '失败' : 'Failed'}`, 'error');
    }
}

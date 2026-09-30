/* 自动化规则：Blockly 积木编辑器 <-> 规则 JSON <-> /api/automation
 * 积木约定：紫色规则块；橙色触发；蓝色条件；绿色执行。
 */
'use strict';

let workspace = null;
let CAPS = null;          // 后端能力清单
let SAVE_PENDING = false;

// ==================== 通用 UI ====================

function showNotification(message, type = 'info') {
    const el = document.getElementById('notification');
    if (!el) { alert(message); return; }
    el.textContent = message;
    el.className = `notification ${type}`;
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.add('hidden'), 3500);
}

async function api(url, options = {}) {
    const resp = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
    return data;
}

// ==================== 积木定义 ====================

function defineBlocks() {
    // ── 规则容器 ──
    Blockly.Blocks['rule_block'] = {
        init: function () {
            this.appendDummyInput()
                .appendField('🧩 规则名称')
                .appendField(new Blockly.FieldTextInput('新规则'), 'NAME')
                .appendField(new Blockly.FieldCheckbox('TRUE'), 'ENABLED')
                .appendField('启用');
            this.appendStatementInput('TRIGGER').setCheck('TRIG')
                .appendField('当（触发，放 1 个橙色块）');
            this.appendDummyInput()
                .appendField('如果（蓝色条件，可叠多个）需')
                .appendField(new Blockly.FieldDropdown([
                    ['满足全部条件（且）', 'all'], ['满足任一条件（或）', 'any']]), 'MATCH');
            this.appendStatementInput('CONDS').setCheck('COND').appendField('条件');
            this.appendStatementInput('DO').setCheck('ACT').appendField('那么依次执行');
            this.appendStatementInput('ELSE').setCheck('ACT')
                .appendField('否则执行（条件不满足时切换状态，可留空）');
            this.appendDummyInput()
                .appendField('两次触发最小间隔（冷却）')
                .appendField(new Blockly.FieldNumber(3, 0, 3600, 1), 'COOLDOWN')
                .appendField('秒');
            this.setColour(265);
            this.setTooltip('一条完整的自动化规则');
        },
    };

    // ── 触发：数值传感器越限 ──
    Blockly.Blocks['trig_num'] = {
        init: function () {
            this.appendDummyInput()
                .appendField('当')
                .appendField(new Blockly.FieldDropdown(numSourceOptions), 'SRC')
                .appendField(new Blockly.FieldDropdown(opOptions), 'OP')
                .appendField(new Blockly.FieldNumber(30, -1000, 100000, 1), 'VAL');
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
            this.setTooltip('数值跨过阈值的瞬间触发一次（上升沿）');
        },
    };

    // ── 触发：布尔传感器 ──
    Blockly.Blocks['trig_bool'] = {
        init: function () {
            this.appendDummyInput()
                .appendField('当')
                .appendField(new Blockly.FieldDropdown(boolSourceOptions), 'SRC')
                .appendField(new Blockly.FieldDropdown([
                    ['变为「是/触发」', 'true'], ['变为「否/恢复」', 'false']]), 'STATE');
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
        },
    };

    // ── 触发：设备状态 ──
    Blockly.Blocks['trig_status'] = {
        init: function () {
            this.appendDummyInput()
                .appendField('当')
                .appendField(new Blockly.FieldDropdown(statusOptions), 'PRED');
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
        },
    };

    // ── 触发：事件 ──
    Blockly.Blocks['trig_event'] = {
        init: function () {
            this.appendDummyInput()
                .appendField('当事件')
                .appendField(new Blockly.FieldDropdown(eventOptions), 'EVT');
            this.appendDummyInput()
                .appendField('  ▸ 键盘事件的按键：')
                .appendField(new Blockly.FieldTextInput('1'), 'KEY')
                .appendField('  红外事件的键码(hex)：')
                .appendField(new Blockly.FieldTextInput('0x45'), 'CMD');
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
            this.setTooltip('人体移动/人脸授权/矩阵键盘/红外遥控等离散事件');
        },
    };

    // ── 触发：周期/定时 ──
    Blockly.Blocks['trig_interval'] = {
        init: function () {
            this.appendDummyInput()
                .appendField('每隔')
                .appendField(new Blockly.FieldNumber(10, 2, 86400, 1), 'SECONDS')
                .appendField('秒触发一次');
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
        },
    };
    Blockly.Blocks['trig_time'] = {
        init: function () {
            this.appendDummyInput()
                .appendField('每天到')
                .appendField(new Blockly.FieldTextInput('08:00'), 'TIME')
                .appendField('触发（HH:MM）');
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
        },
    };

    // ── 条件（与触发同形，可堆叠）──
    Blockly.Blocks['cond_num'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(new Blockly.FieldDropdown(numSourceOptions), 'SRC')
                .appendField(new Blockly.FieldDropdown(opOptions), 'OP')
                .appendField(new Blockly.FieldNumber(30, -1000, 100000, 1), 'VAL');
            this.setPreviousStatement(true, 'COND');
            this.setNextStatement(true, 'COND');
            this.setColour(190);
        },
    };
    Blockly.Blocks['cond_bool'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(new Blockly.FieldDropdown(boolSourceOptions), 'SRC')
                .appendField('等于')
                .appendField(new Blockly.FieldDropdown([['是', 'true'], ['否', 'false']]), 'STATE');
            this.setPreviousStatement(true, 'COND');
            this.setNextStatement(true, 'COND');
            this.setColour(190);
        },
    };
    Blockly.Blocks['cond_status'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(new Blockly.FieldDropdown(statusOptions), 'PRED');
            this.setPreviousStatement(true, 'COND');
            this.setNextStatement(true, 'COND');
            this.setColour(190);
        },
    };

    // ── 执行器动作 ──
    Blockly.Blocks['act_door'] = {
        init: function () {
            this.appendDummyInput().appendField('🚪 门')
                .appendField(new Blockly.FieldDropdown([['打开', 'open'], ['关闭', 'close']]), 'STATUS');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    Blockly.Blocks['act_window'] = {
        init: function () {
            this.appendDummyInput().appendField('🪟 窗户')
                .appendField(new Blockly.FieldDropdown(
                    [['打开', 'open'], ['关闭', 'close'], ['半开 45°', 'normal']]), 'STATUS');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    Blockly.Blocks['act_light'] = {
        init: function () {
            this.appendDummyInput().appendField('💡 灯')
                .appendField(new Blockly.FieldDropdown([['打开', 'on'], ['关闭', 'off']]), 'STATUS')
                .appendField('亮度')
                .appendField(new Blockly.FieldNumber(100, 0, 100, 1), 'BRIGHTNESS')
                .appendField('%');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    Blockly.Blocks['act_fan'] = {
        init: function () {
            this.appendDummyInput().appendField('🌀 风扇转速设为')
                .appendField(new Blockly.FieldNumber(60, 0, 100, 1), 'SPEED')
                .appendField('%（0=关）');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    Blockly.Blocks['act_buzzer'] = {
        init: function () {
            this.appendDummyInput().appendField('🔔 蜂鸣器响')
                .appendField(new Blockly.FieldNumber(2, 1, 10, 1), 'COUNT').appendField('次，每声')
                .appendField(new Blockly.FieldNumber(200, 50, 2000, 10), 'ONMS').appendField('ms，间隔')
                .appendField(new Blockly.FieldNumber(200, 50, 2000, 10), 'OFFMS').appendField('ms');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    Blockly.Blocks['act_delay'] = {
        init: function () {
            this.appendDummyInput().appendField('⏳ 等待')
                .appendField(new Blockly.FieldNumber(3, 1, 300, 1), 'SECONDS')
                .appendField('秒（再执行后面的动作）');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    Blockly.Blocks['act_oled'] = {
        init: function () {
            // OLED 字库只有 ASCII：文案用英文/数字，汉字不会上屏
            this.appendDummyInput().appendField('🖥️ OLED 显示文本(仅英文)')
                .appendField(new Blockly.FieldTextInput('Temp {temperature}C'), 'TEXT');
            this.appendDummyInput()
                .appendField(new Blockly.FieldCheckbox('FALSE'), 'CLEAR')
                .appendField('清屏');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
}

// ==================== 下拉选项（来自后端能力清单） ====================

function sourceByKind(kind) {
    return CAPS.sources.filter(s => s.kind === kind);
}
function numSourceOptions() {
    return sourceByKind('number').map(s => [`${s.label}(${s.unit || ''})`, s.id]);
}
function boolSourceOptions() {
    return sourceByKind('bool').map(s => [s.label, s.id]);
}
function statusOptions() {
    const opts = [];
    for (const s of sourceByKind('enum')) {
        for (const choice of s.choices) {
            const label = s.choice_labels[choice] || choice;
            opts.push([`${s.label} = ${label}`, `${s.id}:${choice}`]);
        }
    }
    return opts;
}
function eventOptions() {
    return CAPS.events.map(e => {
        let label = e.label;
        if (e.param) label += `（参数：${e.param_label}）`;
        return [label, e.id];
    });
}
function opOptions() {
    return CAPS.comparators.map(c => [c.label, c.id]);
}

// ==================== 工具箱 & 注入 ====================

function buildToolbox() {
    const num = numSourceOptions();
    const bool = boolSourceOptions();
    const evt = eventOptions();
    return `<xml>
      <category name="🧩 规则">
        <block type="rule_block"></block>
      </category>
      <category name="① 当… 触发">
        <block type="trig_num">
          <field name="SRC">${num[0][1]}</field><field name="OP">&gt;</field><field name="VAL">30</field>
        </block>
        <block type="trig_bool"><field name="SRC">${bool[0][1]}</field><field name="STATE">true</field></block>
        <block type="trig_status"></block>
        <block type="trig_event"><field name="EVT">${evt[0][1]}</field></block>
        <block type="trig_interval"><field name="SECONDS">10</field></block>
        <block type="trig_time"><field name="TIME">08:00</field></block>
      </category>
      <category name="② 如果… 条件">
        <block type="cond_num">
          <field name="SRC">${num[0][1]}</field><field name="OP">&gt;</field><field name="VAL">30</field>
        </block>
        <block type="cond_bool"><field name="SRC">${bool[0][1]}</field><field name="STATE">true</field></block>
        <block type="cond_status"></block>
      </category>
      <category name="③ 执行… 动作">
        <block type="act_door"></block>
        <block type="act_window"></block>
        <block type="act_light"></block>
        <block type="act_fan"></block>
        <block type="act_buzzer"></block>
        <block type="act_oled"></block>
        <block type="act_delay"></block>
      </category>
    </xml>`;
}

function darkTheme() {
    return Blockly.Theme.defineTheme('smartdark', {
        name: 'smartdark',
        base: Blockly.Themes.Classic,
        componentStyles: {
            workspaceBackgroundColour: '#0f1923',
            toolboxBackgroundColour: '#162231',
            toolboxForegroundColour: '#e8f0f8',
            flyoutBackgroundColour: '#162231',
            flyoutForegroundColour: '#e8f0f8',
            flyoutOpacity: 0.98,
            scrollbarColour: '#2a4a5e',
            scrollbarOpacity: 0.6,
            insertionMarkerColour: '#00e5ff',
            insertionMarkerOpacity: 0.8,
            cursorColour: '#00e5ff',
            selectedGlowColour: '#00e5ff',
        },
    });
}

async function bootWorkspace() {
    CAPS = await api('/api/automation/capabilities');
    defineBlocks();
    workspace = Blockly.inject('blocklyDiv', {
        toolbox: buildToolbox(),
        theme: darkTheme(),
        grid: { spacing: 24, length: 3, colour: '#1c3142', snap: false },
        zoom: { controls: true, wheel: true, startScale: 0.95, maxScale: 2, minScale: 0.5 },
        trashcan: true,
        renderer: 'zelos',
        // 媒体资源走本地（内网/校园网无外网也能用），避免 blockly-demo.appspot.com 超时
        media: '/static/vendor/blockly/media/',
    });
    window.addEventListener('resize', () => Blockly.svgResize(workspace));
    const data = await api('/api/automation/rules');
    renderRules(data.rules || []);
    refreshPreview();
    refreshLogs();
    loadOledConfig();
    loadHomeMode();
    setInterval(refreshLogs, 5000);
    setInterval(loadHomeMode, 5000);
}

// ==================== 全屋模式（自动/手动/离家 + 强制覆盖） ====================

let HOME_MODE = null;

async function loadHomeMode() {
    try {
        HOME_MODE = await api('/api/automation/home_mode');
    } catch (e) { return; }
    const badge = document.getElementById('homeModeBadge');
    if (!badge) return;
    badge.textContent = '当前模式：' + (HOME_MODE.mode_label || HOME_MODE.mode);
    badge.className = 'mode-badge mode-' + HOME_MODE.mode;
    const fanBtn = document.getElementById('fanOverrideBtn');
    if (fanBtn) fanBtn.textContent = '🌀 风扇：' + HOME_MODE.fan_label;
    const lightBtn = document.getElementById('lightLevelBtn');
    if (lightBtn) lightBtn.textContent = '💡 灯光：' + HOME_MODE.light_label;
    const awayOnly = document.getElementById('awayOnlyChk');
    if (awayOnly) awayOnly.checked = !!HOME_MODE.auto_away_only;
    const detail = document.getElementById('homeModeDetail');
    if (detail) {
        const bits = [];
        if (HOME_MODE.person_present) bits.push('👤 有人在家');
        if (HOME_MODE.auto_paused) bits.push('⏸ 自动调节已暂停（人走后恢复）');
        if (HOME_MODE.pir_near_door) bits.push('门口有人 ' + HOME_MODE.pir_dwell_seconds + 's');
        if (HOME_MODE.door_close_in > 0) bits.push('关门倒计时 ' + HOME_MODE.door_close_in + 's');
        if (HOME_MODE.smoke_active) bits.push('⚠️ 烟雾报警中');
        if (HOME_MODE.rain_wet) bits.push('🌧 检测到雨水');
        if (HOME_MODE.last_reason) bits.push(HOME_MODE.last_reason);
        detail.textContent = bits.join('　|　');
    }
}

async function putHomeMode(body) {
    try {
        const r = await api('/api/automation/home_mode', {
            method: 'PUT', body: JSON.stringify(body),
        });
        HOME_MODE = r.config;
        loadHomeMode();
        showNotification(r.message || '全屋模式设置已生效', 'success');
    } catch (e) {
        showNotification(e.message, 'error');
    }
}

function setHomeMode(mode) {
    putHomeMode({ mode, reason: '页面切换全屋模式' });
}

function setAwayOnly(on) {
    putHomeMode({ auto_away_only: !!on,
                  reason: on ? '页面开启「仅无人在家时自动调节」'
                             : '页面关闭「仅无人在家时自动调节」（有人也自动调节）' });
}

function cycleFanOverride() {
    const cur = HOME_MODE ? HOME_MODE.fan_override : null;
    const next = cur === null ? 'off' : (cur === 'off' ? 'on' : null);
    putHomeMode({ fan_override: next, reason: '页面切换风扇覆盖' });
}

function cycleLightLevel() {
    const order = ['hold', 'dark', 'half', 'bright', 'auto'];
    const cur = HOME_MODE ? HOME_MODE.light_level : 'auto';
    const idx = order.indexOf(cur);
    putHomeMode({ light_level: order[(idx + 1) % order.length],
                  reason: '页面切换灯光档位' });
}

// ==================== OLED 轮播设置 ====================

async function loadOledConfig() {
    const on = document.getElementById('oledEnabled');
    const iv = document.getElementById('oledInterval');
    const st = document.getElementById('oledStatus');
    if (!on || !iv) return;
    try {
        const cfg = await api('/api/automation/oled');
        on.checked = !!cfg.enabled;
        iv.value = cfg.interval || 5;
        if (st) st.textContent = cfg.enabled ? '✅ 已开，每 ' + (cfg.interval || 5) + ' 秒切页' : '⏸ 已关闭';
    } catch (e) {
        if (st) st.textContent = '接口暂不可用（引擎未启动）';
    }
}

async function saveOledConfig() {
    const iv = document.getElementById('oledInterval');
    const body = {
        enabled: !!document.getElementById('oledEnabled').checked,
        interval: Number(iv.value) || 5,
    };
    try {
        const r = await api('/api/automation/oled', {
            method: 'PUT', body: JSON.stringify(body),
        });
        const st = document.getElementById('oledStatus');
        if (st) st.textContent = r.config.enabled ? '✅ 已开启，每 ' + r.config.interval + ' 秒切页' : '⏸ 已关闭';
        showNotification(r.message || 'OLED 轮播配置已保存', 'success');
    } catch (e) {
        showNotification(e.message, 'error');
    }
}

// ==================== 积木 -> JSON ====================

function chainBlocks(first) {
    const out = [];
    let b = first;
    while (b) { out.push(b); b = b.getNextBlock(); }
    return out;
}

function triggerToJson(b) {
    switch (b.type) {
        case 'trig_num':
            return { kind: 'sensor', sensor: b.getFieldValue('SRC'),
                     op: b.getFieldValue('OP'), value: Number(b.getFieldValue('VAL')) };
        case 'trig_bool':
            return { kind: 'sensor', sensor: b.getFieldValue('SRC'),
                     op: '==', value: b.getFieldValue('STATE') === 'true' };
        case 'trig_status': {
            const [sensor, value] = b.getFieldValue('PRED').split(':');
            return { kind: 'sensor', sensor, op: '==', value };
        }
        case 'trig_event': {
            const evt = b.getFieldValue('EVT');
            const json = { kind: 'event', event: evt };
            if (evt === 'keypad') json.key = b.getFieldValue('KEY').trim() || '1';
            if (evt === 'ir') json.command = b.getFieldValue('CMD').trim() || '0x45';
            return json;
        }
        case 'trig_interval':
            return { kind: 'interval', seconds: Number(b.getFieldValue('SECONDS')) };
        case 'trig_time':
            return { kind: 'time', hhmm: b.getFieldValue('TIME').trim() };
        default:
            return null;
    }
}

function conditionToJson(b) {
    switch (b.type) {
        case 'cond_num':
            return { sensor: b.getFieldValue('SRC'), op: b.getFieldValue('OP'),
                     value: Number(b.getFieldValue('VAL')) };
        case 'cond_bool':
            return { sensor: b.getFieldValue('SRC'), op: '==',
                     value: b.getFieldValue('STATE') === 'true' };
        case 'cond_status': {
            const [sensor, value] = b.getFieldValue('PRED').split(':');
            return { sensor, op: '==', value };
        }
        default:
            return null;
    }
}

function actionToJson(b) {
    switch (b.type) {
        case 'act_door':   return { device: 'door', status: b.getFieldValue('STATUS') };
        case 'act_window': return { device: 'window', status: b.getFieldValue('STATUS') };
        case 'act_light':  return { device: 'light', status: b.getFieldValue('STATUS'),
                                    brightness: Number(b.getFieldValue('BRIGHTNESS')) };
        case 'act_fan':    return { device: 'fan', speed: Number(b.getFieldValue('SPEED')) };
        case 'act_buzzer': return { device: 'buzzer',
                                    count: Number(b.getFieldValue('COUNT')),
                                    on_ms: Number(b.getFieldValue('ONMS')),
                                    off_ms: Number(b.getFieldValue('OFFMS')) };
        case 'act_delay':  return { device: 'delay',
                                    seconds: Number(b.getFieldValue('SECONDS')) };
        case 'act_oled':
            if (b.getFieldValue('CLEAR') === 'TRUE') return { device: 'oled', clear: true };
            return { device: 'oled', text: b.getFieldValue('TEXT') };
        default: return null;
    }
}

function collectRules() {
    const rules = [];
    for (const rb of workspace.getTopBlocks(true)) {
        if (rb.type !== 'rule_block') continue;
        const trigBlock = rb.getInputTargetBlock('TRIGGER');
        if (!trigBlock) throw new Error(`规则「${rb.getFieldValue('NAME')}」缺少「当」触发块`);
        const trigger = triggerToJson(trigBlock);
        const conditions = chainBlocks(rb.getInputTargetBlock('CONDS')).map(conditionToJson);
        const actions = chainBlocks(rb.getInputTargetBlock('DO')).map(actionToJson);
        if (actions.length === 0) {
            throw new Error(`规则「${rb.getFieldValue('NAME')}」的「那么执行」至少放 1 个绿色动作块`);
        }
        rules.push({
            id: rb.ruleId || null,
            name: rb.getFieldValue('NAME').trim(),
            enabled: rb.getFieldValue('ENABLED') === 'TRUE',
            trigger,
            match: rb.getFieldValue('MATCH'),
            conditions: conditions.filter(Boolean),
            actions: actions.filter(Boolean),
            else_actions: chainBlocks(rb.getInputTargetBlock('ELSE')).map(actionToJson).filter(Boolean),
            cooldown: Number(rb.getFieldValue('COOLDOWN')),
        });
    }
    if (rules.length === 0) throw new Error('工作区里还没有规则块（从左侧「🧩 规则」拖一个出来）');
    return rules;
}

// ==================== JSON -> 积木 ====================

function sourceKind(sensorId) {
    const s = CAPS.sources.find(x => x.id === sensorId);
    return s ? s.kind : 'number';
}

function createTyped(type) {
    const b = workspace.newBlock(type);
    b.initSvg();
    return b;
}

function fillTrigger(trig) {
    if (trig.kind === 'interval') {
        const b = createTyped('trig_interval');
        b.setFieldValue(String(trig.seconds), 'SECONDS');
        return b;
    }
    if (trig.kind === 'time') {
        const b = createTyped('trig_time');
        b.setFieldValue(trig.hhmm, 'TIME');
        return b;
    }
    if (trig.kind === 'event') {
        const b = createTyped('trig_event');
        b.setFieldValue(trig.event, 'EVT');
        if (trig.key) b.setFieldValue(trig.key, 'KEY');
        if (trig.command) b.setFieldValue(trig.command, 'CMD');
        return b;
    }
    // sensor
    const kind = sourceKind(trig.sensor);
    if (kind === 'bool') {
        const b = createTyped('trig_bool');
        b.setFieldValue(trig.sensor, 'SRC');
        b.setFieldValue(trig.value === true || trig.value === 'true' ? 'true' : 'false', 'STATE');
        return b;
    }
    if (kind === 'enum') {
        const b = createTyped('trig_status');
        b.setFieldValue(`${trig.sensor}:${trig.value}`, 'PRED');
        return b;
    }
    const b = createTyped('trig_num');
    b.setFieldValue(trig.sensor, 'SRC');
    b.setFieldValue(trig.op || '>', 'OP');
    b.setFieldValue(String(trig.value), 'VAL');
    return b;
}

function fillCondition(c) {
    const kind = sourceKind(c.sensor);
    if (kind === 'bool') {
        const b = createTyped('cond_bool');
        b.setFieldValue(c.sensor, 'SRC');
        b.setFieldValue(c.value === true || c.value === 'true' ? 'true' : 'false', 'STATE');
        return b;
    }
    if (kind === 'enum') {
        const b = createTyped('cond_status');
        b.setFieldValue(`${c.sensor}:${c.value}`, 'PRED');
        return b;
    }
    const b = createTyped('cond_num');
    b.setFieldValue(c.sensor, 'SRC');
    b.setFieldValue(c.op || '>', 'OP');
    b.setFieldValue(String(c.value), 'VAL');
    return b;
}

function fillAction(a) {
    let b;
    switch (a.device) {
        case 'door':   b = createTyped('act_door'); b.setFieldValue(a.status, 'STATUS'); break;
        case 'window': b = createTyped('act_window'); b.setFieldValue(a.status, 'STATUS'); break;
        case 'light':
            b = createTyped('act_light');
            b.setFieldValue(a.status || 'on', 'STATUS');
            b.setFieldValue(String(a.brightness ?? 100), 'BRIGHTNESS');
            break;
        case 'fan': b = createTyped('act_fan'); b.setFieldValue(String(a.speed ?? 60), 'SPEED'); break;
        case 'buzzer':
            b = createTyped('act_buzzer');
            b.setFieldValue(String(a.count ?? 2), 'COUNT');
            b.setFieldValue(String(a.on_ms ?? 200), 'ONMS');
            b.setFieldValue(String(a.off_ms ?? 200), 'OFFMS');
            break;
        case 'delay': b = createTyped('act_delay'); b.setFieldValue(String(a.seconds ?? 3), 'SECONDS'); break;
        case 'oled':
            b = createTyped('act_oled');
            b.setFieldValue(a.clear ? 'TRUE' : 'FALSE', 'CLEAR');
            b.setFieldValue(a.text ?? 'Temp {temperature}C', 'TEXT');
            break;
        default: return null;
    }
    return b;
}

function connectStack(ruleBlock, inputName, blocks) {
    if (!blocks.length) return;
    blocks[0].render();
    ruleBlock.getInput(inputName).connection.connect(blocks[0].previousConnection);
    for (let i = 1; i < blocks.length; i++) {
        blocks[i].render();
        blocks[i - 1].nextConnection.connect(blocks[i].previousConnection);
    }
}

function renderRules(rules) {
    workspace.clear();
    rules.forEach(rule => {
        const rb = workspace.newBlock('rule_block');
        rb.initSvg();
        rb.render();
        rb.ruleId = rule.id;
        rb.setFieldValue(rule.name || '新规则', 'NAME');
        rb.setFieldValue(rule.enabled === false ? 'FALSE' : 'TRUE', 'ENABLED');
        rb.setFieldValue(rule.match === 'any' ? 'any' : 'all', 'MATCH');
        rb.setFieldValue(String(rule.cooldown ?? 3), 'COOLDOWN');
        const trig = fillTrigger(rule.trigger);
        trig.render();
        rb.getInput('TRIGGER').connection.connect(trig.previousConnection);
        connectStack(rb, 'CONDS', (rule.conditions || []).map(fillCondition).filter(Boolean));
        connectStack(rb, 'DO', (rule.actions || []).map(fillAction).filter(Boolean));
        connectStack(rb, 'ELSE', (rule.else_actions || []).map(fillAction).filter(Boolean));
    });
    if (!rules.length) addRuleBlock();
}

// ==================== 交互 ====================

function addRuleBlock() {
    const rb = workspace.newBlock('rule_block');
    rb.initSvg();
    rb.render();
    const trig = createTyped('trig_num');
    trig.setFieldValue('temperature', 'SRC');
    trig.render();
    rb.getInput('TRIGGER').connection.connect(trig.previousConnection);
    const fan = createTyped('act_fan');
    fan.render();
    rb.getInput('DO').connection.connect(fan.previousConnection);
    rb.select();
    workspace.centerOnBlock(rb.id);
}

async function saveAll() {
    if (SAVE_PENDING) return;
    let rules;
    try {
        rules = collectRules();
    } catch (e) { showNotification(e.message, 'error'); return; }
    SAVE_PENDING = true;
    try {
        const saved = await api('/api/automation/rules', {
            method: 'PUT', body: JSON.stringify({ rules }),
        });
        renderRules(saved.rules);
        showNotification(saved.message || '规则已保存并立即生效', 'success');
        refreshPreview();
    } catch (e) {
        showNotification(e.message, 'error');
    } finally {
        SAVE_PENDING = false;
    }
}

async function runRule(id) {
    try {
        const r = await api(`/api/automation/rules/${encodeURIComponent(id)}/run`,
                            { method: 'POST' });
        showNotification(r.message || '已提交执行', r.ok ? 'success' : 'error');
        setTimeout(refreshLogs, 2500);
    } catch (e) {
        showNotification(e.message, 'error');
    }
}

function sourceLabel(id) {
    const s = CAPS.sources.find(x => x.id === id);
    return s ? s.label : id;
}

async function refreshPreview() {
    if (!CAPS) return;
    let data;
    try {
        data = await api('/api/automation/preview');
    } catch (e) { return; }
    const box = document.getElementById('previewList');
    if (!data.preview.length) {
        box.innerHTML = '<span style="color:var(--text-secondary);font-size:13px">还没有规则。</span>';
        return;
    }
    box.innerHTML = '';
    for (const p of data.preview) {
        const div = document.createElement('div');
        div.className = 'preview-item';
        let badge;
        if (!p.enabled) badge = '<span class="badge disabled">已停用</span>';
        else if (p.trigger_now === true) badge = '<span class="badge on">触发条件成立</span>';
        else if (p.trigger_now === false) badge = '<span class="badge off">触发未成立</span>';
        else badge = '<span class="badge evt">事件/定时驱动</span>';
        const conds = (p.conditions || []).map(c => {
            const cur = c.current === null || c.current === undefined ? '无数据' : c.current;
            return `<div class="${c.hold ? 'yes' : 'no'}">${c.hold ? '✓' : '✗'} ` +
                   `${sourceLabel(c.sensor)} ${c.op} ${c.value}（当前: ${cur}）</div>`;
        }).join('');
        div.innerHTML =
            `<div class="pv-title"><span class="pv-name">${p.name}</span>${badge}</div>` +
            (conds ? `<div class="pv-conds">${conds}</div>` : '') +
            `<div style="margin-top:8px"><button class="btn mini-btn" data-id="${p.id}">▶ 立即测试</button></div>`;
        div.querySelector('button').onclick = () => runRule(p.id);
        box.appendChild(div);
    }
}

async function refreshLogs() {
    let data;
    try {
        data = await api('/api/automation/logs?limit=20');
    } catch (e) { return; }
    const tbody = document.getElementById('autoLogBody');
    tbody.innerHTML = (data.logs || []).map(r => {
        const icon = r.success ? '✅' : (r.triggered ? '⚠️' : '•');
        const ts = (r.timestamp || '').replace('T', ' ').slice(0, 19);
        return `<tr><td>${ts}</td><td>${r.rule_name}</td>` +
               `<td>${icon} ${r.reason || ''}<br>` +
               `<span style="color:var(--text-muted)">${r.conditions_hold ? '走「那么」' : '走「否则」'}</span></td></tr>`;
    }).join('');
}

// 时钟（与其他页面一致）
setInterval(() => {
    const el = document.getElementById('currentTime');
    if (el) el.textContent = new Date().toLocaleTimeString('zh-CN', { hour12: false });
}, 1000);

document.addEventListener('DOMContentLoaded', () => {
    if (typeof Blockly === 'undefined') {
        document.getElementById('blocklyMissing')?.classList.remove('hidden');
        return;
    }
    bootWorkspace().catch(e => showNotification('初始化失败：' + e.message, 'error'));
});

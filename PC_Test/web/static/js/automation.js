/* 自动化规则（iOS 快捷指令式交互）
 * 视图一：规则列表 —— 每条规则一张卡片，卡片自带 ⋮ 菜单（运行/编辑/重命名/复制/停用/删除）
 * 视图二：单条规则编辑器 —— 画布中只放当前这一条规则，左侧工具箱拖积木
 * 数据源始终是后端规则 JSON（GET/PUT /api/automation/rules，PUT 为整表替换）。
 */
'use strict';

// ==================== 双语辅助 ====================
// 自动化页动态文案与积木标签统一走 L()；积木标签在 block init 时求值，
// 切换语言后重建工作区即可生效（见文件末尾的 i18n:changed 监听）。
function isEN() {
    return typeof I18N !== 'undefined' && I18N.currentLang === 'en';
}
function L(zh, en) {
    return isEN() ? en : zh;
}

// 后端能力清单（CAPS）只给中文标签，这里补英文映射
const EN_SOURCE_LABELS = {
    temperature: 'Temperature', humidity: 'Humidity', light: 'Light',
    smoke: 'Smoke alarm', rain: 'Rain sensor', touch: 'Touch sensor',
    motion: 'Motion (PIR)', door_status: 'Door status', window_status: 'Window status',
    light_status: 'Light status', light_brightness: 'Light brightness',
    fan_speed: 'Fan speed', ac_status: 'AC power', ac_mode: 'AC mode',
    ac_temperature: 'AC setpoint', home_mode: 'Home mode',
    home_enabled: 'Auto-adjust enabled', home_fan: 'Home fan level',
    home_light: 'Home light level', person_present: 'Someone home',
    sensor_online: 'Sensor board online', output_online: 'Actuator board online',
};
const EN_CHOICE_LABELS = {
    open: 'Open', closed: 'Closed', normal: 'Half 45°', on: 'On', off: 'Off',
    auto: 'Auto', cool: 'Cool', heat: 'Heat', dry: 'Dry', fan: 'Fan',
    manual: 'Manual', away: 'Away', hold: 'Hold', dark: 'Dim',
    half: 'Half', bright: 'Full',
};
const EN_EVENT_LABELS = {
    touch_on: 'Touch: pressed', touch_off: 'Touch: released',
    smoke_on: 'Smoke: alarm', smoke_off: 'Smoke: cleared',
    rain_on: 'Rain: detected', rain_off: 'Rain: stopped',
    motion_on: 'Motion: detected', motion_off: 'Motion: ended',
    rfid: 'RFID: card tapped', face_granted: 'Face: authorized',
    keypad: 'Keypad: key pressed', ir: 'IR remote: key pressed',
};
const EN_PARAM_LABELS = { '卡号': 'Card ID', '按键': 'Key' };
const EN_COMPARATOR_LABELS = { '>': '>', '>=': '>=', '<': '<', '<=': '<=', '==': '=', '!=': '≠' };

// 内置预设规则名（后端按 preset 写死中文名；仅在用户未改名时按此表翻译）
const EN_PRESET_NAMES = {
    '授权人脸通过 → 开门': 'Authorized face → open door',
    '门禁通过：全屋自动 + 10秒后关门': 'Access granted: whole-home auto + close door in 10s',
    '检测到人后开门 → 全屋自动（判定进门）': 'Door opened with someone home → auto (entering)',
    '无人在家时开门 → 离家（判定出门）': 'Door opened with nobody home → away (leaving)',
    '自动模式·无人在家：温度高于25°C开风扇': 'Auto · nobody home: fan on when temp > 25°C',
    '自动模式·无人在家：温度不高于25°C关风扇': 'Auto · nobody home: fan off when temp ≤ 25°C',
    '自动模式·无人在家：光照偏暗(≤200)灯全亮': 'Auto · nobody home: dim (≤200) → lights full',
    '自动模式·无人在家：光照中等(200~500)灯半亮': 'Auto · nobody home: mid light (200~500) → lights half',
    '自动模式·无人在家：光照充足(>500)关灯': 'Auto · nobody home: bright (>500) → lights off',
    '检测到雨水关窗，雨停恢复45°': 'Rain detected: close window; restore 45° when it stops',
    '检测到烟雾：蜂鸣器报警': 'Smoke detected: buzzer alarm',
    '离家时有人逗留30秒未通过门禁 → 蜂鸣器': 'Away: dwell 30s without access → buzzer',
    '触摸传感器：手动↔自动 切换': 'Touch sensor: toggle manual ↔ auto',
    '红外键1：风扇档位循环【默认停用】': 'IR key 1: cycle fan level [disabled by default]',
    '红外键1：风扇开/关切换（按一次开、再按关）【默认停用】': 'IR key 1: fan on/off toggle [disabled by default]',
    '红外键2：灯光档位循环【默认停用】': 'IR key 2: cycle light level [disabled by default]',
    '红外键3：灯光档位循环【默认停用】': 'IR key 3: cycle light level [disabled by default]',
    '切到离家：关闭全屋设备（灯/风扇/窗）': 'Switch to away: turn off whole-home devices (lights/fan/window)',
};

function ruleDisplayName(r) {
    if (!r) return '';
    if (isEN() && r.name && EN_PRESET_NAMES[r.name]) return EN_PRESET_NAMES[r.name];
    return r.name || '';
}

// 后端执行记录的 reason 是中文动态文本，这里做尽力而为的英译
function translateReason(reason) {
    if (!reason || !isEN() || !CAPS) return reason || '';
    let out = String(reason);
    out = out.replace(/每\s*([\d.]+)\s*秒/g, (m, n) => `Every ${n}s`);
    out = out.replace(/定时\s*(\d{1,2}:\d{2})/g, (m, t) => `Daily ${t}`);
    out = out.replace(/已恢复/g, 'recovered');
    out = out.replace(/持续\s*([\d.]+)\s*秒/g, (m, n) => `held ${n}s`);
    out = out.replace(/显示页/g, 'display page');
    const evts = (CAPS.events || []).slice().sort((a, b) => b.label.length - a.label.length);
    for (const e of evts) out = out.split(e.label).join(evtLabel(e));
    const srcs = (CAPS.sources || []).slice().sort((a, b) => b.label.length - a.label.length);
    for (const s of srcs) out = out.split(s.label).join(srcLabel(s));
    for (const s of srcs) {
        const cl = s.choice_labels || {};
        for (const k of Object.keys(cl).sort((a, b) => cl[b].length - cl[a].length)) {
            out = out.split(cl[k]).join(choiceLabel(s, k));
        }
    }
    return out;
}

function srcLabel(s) { return isEN() ? (EN_SOURCE_LABELS[s.id] || s.label) : s.label; }
function choiceLabel(s, c) {
    const zh = (s.choice_labels || {})[c] || c;
    return isEN() ? (EN_CHOICE_LABELS[c] || zh) : zh;
}
function evtLabel(e) { return isEN() ? (EN_EVENT_LABELS[e.id] || e.label) : e.label; }
function evtParamLabel(e) { return isEN() ? (EN_PARAM_LABELS[e.param_label] || e.param_label) : e.param_label; }
function cmpLabel(c) { return isEN() ? (EN_COMPARATOR_LABELS[c.id] || c.label) : c.label; }
// 红外按键名（上/下/左/右）来自后端键码表，英文模式需就地翻译
const EN_IR_KEY_LABELS = { '上': 'Up', '下': 'Down', '左': 'Left', '右': 'Right' };
function irChoiceLabel(label) {
    if (!isEN()) return label;
    return String(label)
        .replace(/上|下|左|右/g, ch => EN_IR_KEY_LABELS[ch])
        .replace(/（/g, ' (').replace(/）/g, ')');
}


let workspace = null;      // Blockly 工作区（懒加载，只在编辑器视图里创建）
let CAPS = null;           // 后端能力清单
let RULES = [];            // 全量规则（唯一数据源）
let GATING_PRESETS = [];   // 「门控维护预设」id（后端下发；停用它们会让联动静默失效，#77）
let PREVIEW = {};          // rule_id -> preview 条目（卡片上的实时状态）
let editingIndex = -1;     // 正在编辑的规则在 RULES 中的下标（-1=新规则）
let editingRule = null;    // 正在编辑的规则副本
let EDIT_KIND = 'rule';    // 编辑器现在编辑什么：'rule' 规则 / 'state' 全局状态条目
let editingVar = null;     // state 模式下正在改的变量定义（null=新建）
let DIRTY = false;         // 编辑器是否有未保存改动
let LOADING = false;       // 正在程序化灌积木（忽略 change 事件）
let SAVE_PENDING = false;
let MENU_INDEX = -1;       // ⋮ 菜单当前作用的卡片下标
let MENU_KIND = 'rule';    // ⋮ 菜单当前作用于哪一类卡片
let RENAMING = false;      // 卡片内联重命名进行中

// ==================== 通用 UI ====================

function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

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

// 灯的颜色预设（B 板 8 颗 WS2812 整条同色）——延迟求值，切语言重建工作区即刷新
function lightColorOptions() {
    return [[L('红', 'Red'), 'red'], [L('绿', 'Green'), 'green'], [L('蓝', 'Blue'), 'blue'],
            [L('黄', 'Yellow'), 'yellow'], [L('紫', 'Purple'), 'purple'], [L('青', 'Cyan'), 'cyan']];
}

// 触发块共用的「持续 N 秒」（0 = 跨阈值立刻触发）
function appendHoldInput(block) {
    block.appendDummyInput()
        .appendField(L('持续', 'Hold'))
        .appendField(new Blockly.FieldNumber(0, 0, 86400, 1), 'HOLD')
        .appendField(L('秒', 's'));
}

// 「等待事件」积木共用的超时输入：必填，1~3600 秒（与后端 DELAY_MAX_SECONDS 同口径）。
// 等待必须有上界，避免规则动作线程被无限占用（#100）。
function appendWaitTimeout(block) {
    block.appendDummyInput()
        .appendField(L('最长', 'Max'))
        .appendField(new Blockly.FieldNumber(60, 1, 3600, 1), 'TIMEOUT')
        .appendField(L('秒（超时则本次结束）', 's (this run ends on timeout)'));
}

function defineBlocks() {
    // ── 规则容器（Scratch 式短标签：当 / 如果 / 那么 / 否则）──
    Blockly.Blocks['rule_block'] = {
        init: function () {
            this.appendDummyInput()
                .appendField('🧩')
                .appendField(new Blockly.FieldTextInput(L('新规则', 'New rule')), 'NAME')
                .appendField(new Blockly.FieldCheckbox('TRUE'), 'ENABLED');
            this.appendStatementInput('TRIGGER').setCheck('TRIG').appendField(L('当', 'When'));
            this.appendDummyInput()
                .appendField(L('如果', 'If'))
                .appendField(new Blockly.FieldDropdown([
                    [L('全部满足', 'All'), 'all'], [L('任一满足', 'Any'), 'any']]), 'MATCH');
            this.appendStatementInput('CONDS').setCheck('COND');
            this.appendStatementInput('DO').setCheck('ACT').appendField(L('那么', 'Then'));
            this.appendStatementInput('ELSE').setCheck('ACT').appendField(L('否则', 'Else'));
            this.appendDummyInput()
                .appendField(L('冷却', 'Cooldown'))
                .appendField(new Blockly.FieldNumber(3, 0, 3600, 1), 'COOLDOWN')
                .appendField(L('秒', 's'));
            this.setColour(265);
            this.setTooltip(L('一条规则 = 当触发 → 如果条件 → 那么执行（否则可留空）', 'A rule = When trigger → If conditions → Then actions (Else optional)'));
        },
    };

    // ── 触发：数值传感器越限 ──
    Blockly.Blocks['trig_num'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('当', 'When'))
                .appendField(new Blockly.FieldDropdown(numSourceOptions), 'SRC')
                .appendField(new Blockly.FieldDropdown(opOptions), 'OP')
                .appendField(new Blockly.FieldNumber(30, -1000, 100000, 1), 'VAL');
            appendHoldInput(this);
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
            this.setTooltip(L('跨过阈值瞬间触发；「持续 N 秒」用于逗留报警这类需连续保持的场景', 'Fires the moment the threshold is crossed; "Hold N s" suits scenarios that must stay true, like a dwell alarm'));
        },
    };

    // ── 触发：布尔传感器 ──
    Blockly.Blocks['trig_bool'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('当', 'When'))
                .appendField(new Blockly.FieldDropdown(boolSourceOptions), 'SRC')
                .appendField(new Blockly.FieldDropdown([
                    [L('变为是', 'becomes true'), 'true'], [L('变为否', 'becomes false'), 'false']]), 'STATE');
            appendHoldInput(this);
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
            this.setTooltip(L('状态变化时触发；配「否则」动作后，恢复（如雨停）会走否则分支', 'Fires on state change; with an Else action, recovery (e.g. rain stops) takes the Else branch'));
        },
    };

    // ── 触发：设备状态 ──
    Blockly.Blocks['trig_status'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('当', 'When'))
                .appendField(new Blockly.FieldDropdown(statusOptions), 'PRED');
            appendHoldInput(this);
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
        },
    };

    // ── 触发：事件类（每种输入各自一块，参数行只在自己块里出现）──
    Blockly.Blocks['trig_touch'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('当 👆 触摸', 'When 👆 Touch'))
                .appendField(new Blockly.FieldDropdown([
                    [L('按下', 'Pressed'), 'touch_on'], [L('松开', 'Released'), 'touch_off']]), 'EVT');
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
        },
    };
    Blockly.Blocks['trig_keypad'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('当 ⌨️ 键盘按下', 'When ⌨️ keypad pressed'))
                .appendField(new Blockly.FieldDropdown(keypadOptions), 'KEY');
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
        },
    };
    Blockly.Blocks['trig_ir'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('当 📡 红外遥控', 'When 📡 IR remote'))
                .appendField(new Blockly.FieldDropdown(irKeyOptions), 'CMD');
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
        },
    };
    Blockly.Blocks['trig_rfid'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('当 🪪 RFID 刷卡', 'When 🪪 RFID tap'))
                .appendField(new Blockly.FieldTextInput(''), 'UID')
                .appendField(L('（卡号留空=任意卡片）', ' (blank Card ID = any card)'));
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
            this.setTooltip(L('卡号格式与门禁管理页一致（如 AA BB CC DD）', 'Same format as the access page (e.g. AA BB CC DD)'));
        },
    };
    Blockly.Blocks['trig_manual'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('当 ✋ 手动操作', 'When ✋ Manual'))
                .appendField(new Blockly.FieldDropdown(manualDeviceOptions), 'DEV')
                .appendField(L('（面板/语音）', ' (panel/voice)'));
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
            this.setTooltip(L('设备刚被人在面板或语音里手动设置时触发；「手动优先冷却」类仲裁由积木规则自己表达', 'Fires when a device is just set manually from the panel or voice; manual-priority arbitration is expressed by block rules themselves'));
        },
    };
    // 门禁通过/被拒各一块，「验证方式」留空 = 任意方式（access_guard 统一广播，
    // 人脸/刷卡/键盘都走同一条规则；只想要人脸时选「人脸识别」即可）
    Blockly.Blocks['trig_access'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('当 🚪 门禁验证通过', 'When 🚪 Access granted'))
                .appendField(new Blockly.FieldDropdown(accessMethodOptions), 'M')
                .appendField(L('（不筛方式=人脸/刷卡/键盘任一）', ' (any method: face/card/keypad)'));
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
            this.setTooltip(L('白名单命中后广播；开门、延时关门这些动作都由规则自己决定', 'Broadcasts when the whitelist matches; opening the door and delayed closing are decided by your own rules'));
        },
    };
    Blockly.Blocks['trig_access_denied'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('当 🚪 门禁被拒绝', 'When 🚪 Access denied'))
                .appendField(new Blockly.FieldDropdown(accessMethodOptions), 'M');
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
            this.setTooltip(L('凭证不在白名单（含陌生人脸/未登记卡）时广播，可用来拉蜂鸣器、拍照留证', 'Broadcasts when the credential is not whitelisted (unknown face / unregistered card); use it to drive the buzzer or take a snapshot'));
        },
    };
    Blockly.Blocks['trig_event_other'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('当 🔔', 'When 🔔'))
                .appendField(new Blockly.FieldDropdown(otherEventOptions), 'EVT');
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
        },
    };

    // ── 触发：周期/定时 ──
    Blockly.Blocks['trig_interval'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('每隔', 'Every'))
                .appendField(new Blockly.FieldNumber(10, 2, 86400, 1), 'SECONDS')
                .appendField(L('秒', 's'));
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
        },
    };
    Blockly.Blocks['trig_time'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('每天', 'Daily'))
                .appendField(new Blockly.FieldTextInput('08:00'), 'TIME');
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
        },
    };

    // ── 条件（可堆叠）──
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
                .appendField(new Blockly.FieldDropdown([[L('是', 'yes'), 'true'], [L('否', 'no'), 'false']]), 'STATE');
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

    // ── 条件：全局状态（专用积木；同一条 JSON 也能从通用条件下拉里选到，
    //    这里只是让它不必去传感器列表里翻）──
    Blockly.Blocks['cond_state_bool'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('📌 状态', '📌 States'))
                .appendField(new Blockly.FieldDropdown(
                    () => orPlaceholder(stateSourceOptions('bool'), newStateHint())), 'SRC')
                .appendField(new Blockly.FieldDropdown([[L('是', 'yes'), 'true'], [L('否', 'no'), 'false']]), 'STATE');
            this.setPreviousStatement(true, 'COND');
            this.setNextStatement(true, 'COND');
            this.setColour(190);
            this.setTooltip(L('判断「是/否」类全局状态；变量在列表页的「📌 全局状态」条目里建立', 'Tests a Yes/No global state; variables are created in the "📌 Global states" entry on the list page'));
        },
    };
    Blockly.Blocks['cond_state_num'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('📌 状态', '📌 States'))
                .appendField(new Blockly.FieldDropdown(
                    () => orPlaceholder(stateSourceOptions('number'), newStateHint())), 'SRC')
                .appendField(new Blockly.FieldDropdown(opOptions), 'OP')
                .appendField(new Blockly.FieldNumber(0, -100000, 100000, 1), 'VAL');
            this.setPreviousStatement(true, 'COND');
            this.setNextStatement(true, 'COND');
            this.setColour(190);
        },
    };
    Blockly.Blocks['cond_state_enum'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('📌 状态', '📌 States'))
                .appendField(new Blockly.FieldDropdown(
                    () => orPlaceholder(condStateEnumOptions(), newStateHint())), 'PRED');
            this.setPreviousStatement(true, 'COND');
            this.setNextStatement(true, 'COND');
            this.setColour(190);
            this.setTooltip(L('判断「选项」类全局状态取值（如 全屋模式 = 自动）', 'Tests the value of an Enum global state (e.g. Home mode = Auto)'));
        },
    };

    // ── 执行器动作 ──
    Blockly.Blocks['act_door'] = {
        init: function () {
            this.appendDummyInput().appendField(L('🚪 门', '🚪 Door'))
                .appendField(new Blockly.FieldDropdown([[L('打开', 'Open'), 'open'], [L('关闭', 'Close'), 'close']]), 'STATUS');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    Blockly.Blocks['act_window'] = {
        init: function () {
            this.appendDummyInput().appendField(L('🪟 窗', '🪟 Window'))
                .appendField(new Blockly.FieldDropdown(
                    [[L('打开', 'Open'), 'open'], [L('关闭', 'Close'), 'close'], [L('半开', 'Half'), 'normal']]), 'STATUS');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    Blockly.Blocks['act_light'] = {
        init: function () {
            this.appendDummyInput().appendField(L('💡 灯', '💡 Light'))
                .appendField(new Blockly.FieldDropdown([[L('打开', 'Open'), 'on'], [L('关闭', 'Close'), 'off']]), 'STATUS')
                .appendField(new Blockly.FieldNumber(100, 0, 100, 1), 'BRIGHTNESS')
                .appendField('%');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip(L('白光，亮度按百分比；关灯时忽略亮度', 'White light, brightness in percent; brightness is ignored when turning off'));
        },
    };
    // 彩色预设（B 板 8 颗 WS2812 整条同色；彩色不接受亮度参数）
    Blockly.Blocks['act_light_color'] = {
        init: function () {
            this.appendDummyInput().appendField(L('🎨 灯颜色', '🎨 Light color'))
                .appendField(new Blockly.FieldDropdown(lightColorOptions), 'COLOR');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip(L('整条灯带换成指定颜色（满亮）', 'Set the whole strip to a color (full brightness)'));
        },
    };
    Blockly.Blocks['act_light_rgb'] = {
        init: function () {
            this.appendDummyInput().appendField(L('🎨 灯 RGB', '🎨 Light RGB'))
                .appendField(new Blockly.FieldNumber(255, 0, 255, 1), 'R').appendField('R')
                .appendField(new Blockly.FieldNumber(0, 0, 255, 1), 'G').appendField('G')
                .appendField(new Blockly.FieldNumber(0, 0, 255, 1), 'B').appendField('B');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    Blockly.Blocks['act_fan'] = {
        init: function () {
            const opField = new Blockly.FieldDropdown([
                [L('设置转速', 'Set speed'), 'set'], [L('开启', 'Turn on'), 'on'], [L('关闭', 'Close'), 'off'],
                [L('切换开/关（同一键再按一次反转）', 'Toggle on/off (same key flips)'), 'toggle']]);
            this.appendDummyInput().appendField(L('🌀 风扇', '🌀 Fan')).appendField(opField, 'OP');
            this.appendDummyInput('SPEEDROW')
                .appendField(L('转速', 'Speed')).appendField(new Blockly.FieldNumber(60, 0, 100, 1), 'SPEED')
                .appendField(L('%（填 0 = 用上次转速）', '% (0 = last speed)'));
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip(L('切换开/关：同一个触发（如遥控器同一个键）按一次开、再按关。', 'Toggle: the same trigger (e.g. one remote key) turns it on, then off, on each press.'));
            // 关闭动作不需要转速，隐藏转速行
            opField.setValidator((v) => {
                this.getInput('SPEEDROW').setVisible(v !== 'off');
                return v;
            });
        },
    };
    Blockly.Blocks['act_buzzer'] = {
        init: function () {
            this.appendDummyInput().appendField(L('🔔 响', '🔔 Beep'))
                .appendField(new Blockly.FieldNumber(2, 1, 10, 1), 'COUNT').appendField(L('声', 'x'))
                .appendField(new Blockly.FieldNumber(200, 50, 2000, 10), 'ONMS').appendField('ms')
                .appendField(new Blockly.FieldNumber(200, 50, 2000, 10), 'OFFMS').appendField('ms');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    // 持续响 / 停：报警需要长鸣时用
    Blockly.Blocks['act_buzzer_switch'] = {
        init: function () {
            this.appendDummyInput().appendField(L('🔔 蜂鸣器', '🔔 Buzzer'))
                .appendField(new Blockly.FieldDropdown([[L('持续响', 'Continuous'), 'on'], [L('停', 'Stop'), 'off']]), 'STATE');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip(L('持续响会一直叫到被「停」或断电，注意别把规则写成自激', 'Continuous sounds until stopped or power is cut — avoid making a self-triggering rule'));
        },
    };
    Blockly.Blocks['act_delay'] = {
        init: function () {
            this.appendDummyInput().appendField(L('⏳ 等', '⏳ Wait'))
                .appendField(new Blockly.FieldNumber(3, 1, 3600, 1), 'SECONDS')
                .appendField(L('秒', 's'));
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    // ── 动作：等待事件（等到条件成立再继续；#100）──
    // 源与比较符和「条件」块完全一致（可选传感器或 g: 全局状态），按源类型分三种块。
    // 超时必填：等待不得让规则动作线程无限挂起。
    Blockly.Blocks['act_wait_num'] = {
        init: function () {
            this.appendDummyInput().appendField(L('⏳ 等到', '⏳ Wait until'))
                .appendField(new Blockly.FieldDropdown(numSourceOptions), 'SRC')
                .appendField(new Blockly.FieldDropdown(opOptions), 'OP')
                .appendField(new Blockly.FieldNumber(30, -1000, 100000, 1), 'VAL')
                .appendField(L('成立', 'met'));
            appendWaitTimeout(this);
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip(L('等到条件成立后继续；超过「最长」秒仍未成立则本次执行失败，不会无限挂起', 'Continues once the condition holds; if it does not hold within "Max" seconds this run fails — it never hangs forever'));
        },
    };
    Blockly.Blocks['act_wait_bool'] = {
        init: function () {
            this.appendDummyInput().appendField(L('⏳ 等到', '⏳ Wait until'))
                .appendField(new Blockly.FieldDropdown(boolSourceOptions), 'SRC')
                .appendField(new Blockly.FieldDropdown([[L('是', 'yes'), 'true'], [L('否', 'no'), 'false']]), 'STATE')
                .appendField(L('成立', 'met'));
            appendWaitTimeout(this);
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip(L('等到布尔条件成立后继续；超过「最长」秒仍未成立则本次执行失败', 'Continues once the boolean condition holds; if it does not within "Max" seconds this run fails'));
        },
    };
    Blockly.Blocks['act_wait_status'] = {
        init: function () {
            this.appendDummyInput().appendField(L('⏳ 等到', '⏳ Wait until'))
                .appendField(new Blockly.FieldDropdown(statusOptions), 'PRED')
                .appendField(L('成立', 'met'));
            appendWaitTimeout(this);
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip(L('等到「设备状态 / 选项类全局状态」成立后继续；超过「最长」秒仍未成立则本次执行失败', 'Continues once the device state / Enum global state holds; if it does not within "Max" seconds this run fails'));
        },
    };
    Blockly.Blocks['act_oled'] = {
        init: function () {
            // OLED 字库只有 ASCII：文案用英文/数字
            this.appendDummyInput().appendField('🖥️ OLED')
                .appendField(new Blockly.FieldTextInput('Temp {temperature}C'), 'TEXT');
            this.appendDummyInput()
                .appendField(new Blockly.FieldCheckbox('FALSE'), 'CLEAR')
                .appendField(L('清屏', 'Clear'));
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    // 指定行直发（不按换行拆分），一行只能放一行文本
    Blockly.Blocks['act_oled_line'] = {
        init: function () {
            this.appendDummyInput().appendField(L('🖥️ OLED 第', '🖥️ OLED line '))
                .appendField(new Blockly.FieldNumber(0, 0, 7, 1), 'LINE')
                .appendField(L('行', ''))
                .appendField(new Blockly.FieldTextInput('Temp {temperature}C'), 'TEXT');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip(L('只写这一行（0-7），其余行不动；文本里可用 {temperature} 等占位符', 'Writes only this line (0-7), leaving others intact; {temperature} and similar placeholders are supported'));
        },
    };
    // 红外发射：直接选键位（复用 A 板实测的 NEC 键码表），或填自定义 32 位码
    Blockly.Blocks['act_ir'] = {
        init: function () {
            this.appendDummyInput().appendField(L('📡 红外发射', '📡 IR send'))
                .appendField(new Blockly.FieldDropdown(irKeyOptions), 'CMD');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip(L('等价于「按下遥控器这个键」；本系统不支持红外自学习/回环转发', 'Same as pressing that key on the remote; IR self-learning / loop-back is not supported'));
        },
    };
    Blockly.Blocks['act_ir_code'] = {
        init: function () {
            this.appendDummyInput().appendField(L('📡 红外发射 自定义码', '📡 IR send (custom code)'))
                .appendField(new Blockly.FieldNumber(16729530, 0, 4294967295, 1), 'CODE');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip(L('十进制 32 位 NEC 码（bit31 先发，不是 LSB-first 那套值）', 'Decimal 32-bit NEC code (bit31 first, not LSB-first)'));
        },
    };
    // 空调（美的红外）：每项都能选"不改"，只下发选过的项
    Blockly.Blocks['act_ac'] = {
        init: function () {
            this.appendDummyInput()
                .appendField(L('❄️ 空调', '❄️ AC'))
                .appendField(new Blockly.FieldDropdown(acSwitchOptions), 'POWER');
            this.appendDummyInput()
                .appendField(L('模式', 'mode'))
                .appendField(new Blockly.FieldDropdown(acModeOptions), 'MODE')
                .appendField(L('温度', 'Temp'))
                .appendField(new Blockly.FieldDropdown(acTempOptions), 'TEMP')
                .appendField(L('风速', 'Fan'))
                .appendField(new Blockly.FieldDropdown(acFanOptions), 'FAN');
            this.appendDummyInput()
                .appendField(L('上下', 'Swing V'))
                .appendField(new Blockly.FieldDropdown(acSwitchOptions), 'SWING_UD')
                .appendField(L('左右', 'Swing H'))
                .appendField(new Blockly.FieldDropdown(acSwitchOptions), 'SWING_LR');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip(L('美的空调红外遥控。"不改"的项保持原设定；', 'Midea AC IR remote. Items set to "No change" keep their current setting; ')
                + L('未开机时给温度/模式/风速会自动先开机', 'Setting temperature/mode/fan while powered off turns it on first'));
        },
    };
    // HTTP 出站（webhook）：把事件/状态推给外部系统，二次开发的主出站通道
    Blockly.Blocks['act_http'] = {
        init: function () {
            this.appendDummyInput().appendField('🌐 HTTP')
                .appendField(new Blockly.FieldDropdown([
                    ['POST', 'post'], ['GET', 'get']]), 'METHOD');
            this.appendDummyInput().appendField('URL')
                .appendField(new Blockly.FieldTextInput('http://127.0.0.1:'), 'URL');
            this.appendDummyInput().appendField(L('内容', 'Content'))
                .appendField(new Blockly.FieldTextInput(''), 'TEXT');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip(L('推给外部系统（NAS/HA/MQTT 网关/自建服务）。', 'Push to an external system (NAS/HA/MQTT gateway/custom service).')
                + L('URL 与内容都支持 {temperature} 这类占位符；内容以 { 或 [ 开头按 JSON 发。', 'URL and content both support placeholders like {temperature}; content starting with { or [ is sent as JSON.')
                + L('默认只允许本机与内网地址，公网目标要在 web_config.yaml 的 ', 'By default only localhost and intranet addresses are allowed; public targets must be registered in web_config.yaml\'s ')
                + L('automation.http_allowed_hosts 登记；不发认证头、不跟随跳转。', 'automation.http_allowed_hosts; no auth header is sent and redirects are not followed.'));
        },
    };
    // 语音联动：按键触发后免唤醒词直接说话
    Blockly.Blocks['act_camera'] = {
        init: function () {
            this.appendDummyInput().appendField(L('📷 门口拍照并存储', '📷 Doorway snapshot'));
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    Blockly.Blocks['act_voice'] = {
        init: function () {
            this.appendDummyInput().appendField(L('🎙️ 语音', '🎙️ Voice'))
                .appendField(new Blockly.FieldDropdown([
                    [L('唤醒', 'Wake'), 'wake'], [L('播报', 'Announce'), 'say']]), 'ACT');
            this.appendDummyInput().appendField(new Blockly.FieldTextInput(''), 'TEXT');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };

    // ── 全局状态写入（按类型拆块：下拉选项在 init 期定死，无法随所选变量动态换）──
    Blockly.Blocks['act_state_bool'] = {
        init: function () {
            this.appendDummyInput().appendField(L('📌 状态', '📌 States'))
                .appendField(new Blockly.FieldDropdown(
                    () => noVarOptions(stateVars('bool'))), 'NAME')
                .appendField(new Blockly.FieldDropdown([
                    [L('设为 是', 'Set true'), 'true'], [L('设为 否', 'Set false'), 'false']]), 'VALUE');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip(L('写「是/否」类全局状态；值在重启后保留', 'Writes a Yes/No global state; the value survives restart'));
        },
    };
    Blockly.Blocks['act_state_toggle'] = {
        init: function () {
            this.appendDummyInput().appendField(L('📌 状态', '📌 States'))
                .appendField(new Blockly.FieldDropdown(
                    () => noVarOptions(stateToggleVars())), 'NAME')
                .appendField(L('⇆ 切换', '⇆ Toggle'));
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip(L('是/否 取反；两项选项状态在两值间切换', 'Flips a Yes/No state; a two-option Enum state toggles between its values'));
        },
    };
    Blockly.Blocks['act_state_num'] = {
        init: function () {
            this.appendDummyInput().appendField(L('📌 状态', '📌 States'))
                .appendField(new Blockly.FieldDropdown(
                    () => noVarOptions(stateVars('number'))), 'NAME')
                .appendField(new Blockly.FieldDropdown([
                    [L('设为', 'Set to'), 'set'], [L('加减', 'Add/sub'), 'add']]), 'OP')
                .appendField(new Blockly.FieldNumber(0, -100000, 100000, 1), 'VAL');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    Blockly.Blocks['act_state_enum'] = {
        init: function () {
            this.appendDummyInput().appendField(L('📌 状态', '📌 States'))
                .appendField(new Blockly.FieldDropdown(stateEnumPredOptions), 'PRED');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip(L('把「选项」类状态设为某个选项值（如 全屋模式 = 自动）', 'Sets an Enum state to one of its options (e.g. Home mode = Auto)'));
        },
    };
    Blockly.Blocks['act_state_text'] = {
        init: function () {
            this.appendDummyInput().appendField(L('📌 状态', '📌 States'))
                .appendField(new Blockly.FieldDropdown(
                    () => noVarOptions(stateVars('text'))), 'NAME')
                .appendField(L('设为', 'Set to'))
                .appendField(new Blockly.FieldTextInput(''), 'TEXT');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip(L('文本状态只用于记录与状态条目卡片展示，不能作为触发/条件比较', 'Text states are only for records and state cards; they cannot be compared in triggers/conditions'));
        },
    };

    // ── 全局状态「定义」积木：列表页的一条状态条目就是这一坨，与规则并列 ──
    // 类型只在新建时可选（后端不支持改类型），改值行随类型切换——与 act_fan
    // 隐藏转速行同一套 getInput().setVisible() 手法。
    Blockly.Blocks['state_def'] = {
        init: function () {
            const self = this;
            this.appendDummyInput()
                .appendField('📌')
                .appendField(new Blockly.FieldTextInput(L('新状态', 'New state')), 'NAME');
            this.appendDummyInput('TYPEROW')
                .appendField(L('类型', 'Type'))
                .appendField(new Blockly.FieldDropdown(stateTypeOptions), 'TYPE');
            this.appendDummyInput('TYPETEXT')
                .appendField(L('类型', 'Type'))
                .appendField(new Blockly.FieldLabel(''), 'TYPELABEL');
            this.appendDummyInput('CHOICESROW')
                .appendField(L('选项（逗号分隔）', 'Options (comma-separated)'))
                .appendField(new Blockly.FieldTextInput(''), 'CHOICES');
            this.appendDummyInput('VALBOOL')
                .appendField(L('当前值', 'Current value'))
                .appendField(new Blockly.FieldDropdown([[L('是', 'yes'), 'true'], [L('否', 'no'), 'false']]), 'VB');
            this.appendDummyInput('VALNUM')
                .appendField(L('当前值', 'Current value'))
                .appendField(new Blockly.FieldNumber(0, -100000, 100000, 1), 'VN');
            this.appendDummyInput('VALENUM')
                .appendField(L('当前值', 'Current value'))
                .appendField(new Blockly.FieldDropdown(
                    () => orPlaceholder(stateDefChoices(self), L('（先填选项）', ' (fill options first)'))), 'VE');
            this.appendDummyInput('VALTEXT')
                .appendField(L('当前值', 'Current value'))
                .appendField(new Blockly.FieldTextInput(''), 'VT');
            this.setColour(265);
            this.setTooltip(L('一条全局状态 = 名字 + 类型 + 当前值。保存这条定义时写入一次当前值，', 'A global state = name + type + current value. Saving this definition writes the value once,')
                + L('之后由规则里的「设置全局状态」积木维护。', ' after which the "Set global state" block in rules maintains it.'));
            this.getField('TYPE').setValidator((v) => { showStateTypeRows(self, v); return v; });
            showStateTypeRows(this, 'bool');
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
            const label = (s.choice_labels || {})[choice] || choice;
            opts.push([`${s.label} = ${label}`, `${s.id}:${choice}`]);
        }
    }
    return opts;
}
function eventOptions() {
    return CAPS.events.map(e => {
        let label = e.label;
        if (e.param) label += `${L('（参数：', ' (param: ')}${e.param_label}${L('）', ')')}`;
        return [label, e.id];
    });
}
// 已拆成专用积木的事件；其余（烟雾/雨水/人体红外的沿）留在通用「事件」块里
const DEDICATED_EVENTS = ['touch_on', 'touch_off', 'keypad', 'ir', 'rfid',
                          'manual_control', 'access_granted', 'access_denied'];
function otherEventOptions() {
    const opts = eventOptions().filter(o => !DEDICATED_EVENTS.includes(o[1]));
    return opts.length ? opts : [[L('（无其它事件）', ' (no other events)'), '']];
}
function manualDeviceOptions() {
    const e = CAPS.events.find(x => x.id === 'manual_control');
    const opts = ((e && e.choices) || []).map(c => [c.label, c.id]);
    return opts.length ? opts : [[L('风扇', 'Fan'), 'fan']];
}
// 门禁「验证方式」下拉：首项是「不筛方式」，与后端 access_granted{method} 可选过滤一致
function accessMethodOptions() {
    const e = CAPS.events.find(x => x.id === 'access_granted');
    const opts = [[L('不筛方式', 'Any method'), '']];
    for (const c of ((e && e.choices) || [])) opts.push([c.label, c.id]);
    return opts.length > 1 ? opts : [[L('不筛方式', 'Any method'), ''], [L('人脸识别', 'Face recognition'), 'face'],
                                     [L('刷房卡', 'Card tap'), 'rfid'], [L('键盘密码', 'Keypad code'), 'keypad']];
}

// ── 全局状态积木的下拉（变量清单是运行期的，来自 CAPS.state_vars）──
function stateVars(type) {
    return (CAPS.state_vars || []).filter(v => v.type === type)
        .map(v => [v.label || v.name, v.id]);
}
function stateToggleVars() {
    // bool 与「两项 enum」可切换（与后端 GlobalStateStore.toggle 一致）
    return (CAPS.state_vars || [])
        .filter(v => v.type === 'bool' || (v.type === 'enum' && (v.choices || []).length === 2))
        .map(v => [v.label || v.name, v.id]);
}
function stateEnumPredOptions() {
    const opts = [];
    for (const v of (CAPS.state_vars || [])) {
        if (v.type !== 'enum') continue;
        for (const c of (v.choices || [])) {
            const label = (v.choice_labels || {})[c] || c;
            opts.push([`${v.label || v.name} = ${label}`, `${v.id}:${c}`]);
        }
    }
    return opts.length ? opts : [[L('（先新建选项类状态）', ' (create an Enum state first)'), '']];
}
function noVarOptions(fallback) {
    return fallback.length ? fallback : [[newStateHint(), '']];
}

// ── 全局状态条目：定义积木的行切换 + 状态条件积木的下拉 ──

function newStateHint() { return L('（先新建「📌 状态」条目）', ' (create a "📌 State" entry first)'); }
function stateTypeOptions() {
    return [[L('是/否', 'Yes/No'), 'bool'], [L('数字', 'Number'), 'number'],
            [L('选项', 'Options'), 'enum'], [L('文本', 'Text'), 'text']];
}
function stateTypeLabel(t) {
    const m = stateTypeOptions().reduce((o, x) => (o[x[1]] = x[0], o), {});
    return m[t] || t;
}

function orPlaceholder(opts, hint) {
    return opts.length ? opts : [[hint, '']];
}
function parseChoices(raw) {
    return String(raw || '').split(/[,，]/).map(s => s.trim()).filter(Boolean);
}
// 「状态·xxx」是后端 global_state_sources() 给条件源加的标签前缀；专用积木自己
// 已经写了「📌 状态」，这里把前缀去掉，避免读成「📌 状态 状态·全屋模式」。
function stateNameOf(source) {
    return String(source.label || '').replace(/^状态·/, '');
}
function stateSourceOptions(kind) {
    return sourceByKind(kind).filter(s => String(s.id).startsWith('g:'))
        .map(s => [stateNameOf(s), s.id]);
}
function condStateEnumOptions() {
    const opts = [];
    for (const s of sourceByKind('enum')) {
        if (!String(s.id).startsWith('g:')) continue;
        for (const c of (s.choices || [])) {
            opts.push([`${stateNameOf(s)} = ${(s.choice_labels || {})[c] || c}`,
                       `${s.id}:${c}`]);
        }
    }
    return opts;
}
// 定义积木的「当前值」候选：跟着同一块上的「选项」输入实时变。
// 显示名用后端给的 choice_labels（全屋模式显示「自动」而不是「auto」），值仍是原始 id。
function stateDefChoices(block) {
    const labels = (block && block._choiceLabels) || {};
    return parseChoices(block.getFieldValue('CHOICES'))
        .map(c => [labels[c] || c, c]);
}
// 类型只在新建时可选（后端没有改类型这条路），已有变量改成只读展示
function showStateTypeRows(block, type) {
    const isEnum = type === 'enum';
    block.getInput('TYPEROW').setVisible(!block._existing);
    block.getInput('TYPETEXT').setVisible(!!block._existing);
    block.getInput('CHOICESROW').setVisible(isEnum);
    block.getInput('VALBOOL').setVisible(type === 'bool');
    block.getInput('VALNUM').setVisible(type === 'number');
    block.getInput('VALENUM').setVisible(isEnum);
    block.getInput('VALTEXT').setVisible(type === 'text');
}
function opOptions() {
    return CAPS.comparators.map(c => [c.label, c.id]);
}
// 按键类事件的键位下拉（键名来自后端键码表，用户不用记十六进制）
function eventChoices(evtId) {
    const e = CAPS.events.find(x => x.id === evtId);
    return (e && e.choices) ? e.choices : [];
}
function keypadOptions() {
    const opts = eventChoices('keypad').map(c => [c.label, c.id]);
    return opts.length ? opts : [['1', '1']];
}
function irKeyOptions() {
    const opts = eventChoices('ir').map(c => [c.label, c.id]);
    return opts.length ? opts : [[L('1（0x45）', '1 (0x45)'), '0x45']];
}
// 下拉里没有该值时退回默认，避免 setFieldValue 静默失败
function optionValue(options, value, fallback) {
    return options.some(o => o[1] === value) ? value : fallback;
}

// 空调积木下拉：值与后端 midea_ac.apply_overrides 的取值一致，空串 = 该项不改
// 延迟求值，切语言重建工作区即刷新
function acSwitchOptions() {
    return [[L('不改', 'No change'), ''], [L('开', ' on'), 'on'], [L('关', ' off'), 'off']];
}
function acModeOptions() {
    return [[L('不改', 'No change'), ''], [L('自动', 'Auto'), 'auto'], [L('制冷', 'Cool'), 'cool'],
            [L('制热', 'Heat'), 'heat'], [L('抽湿', 'Dry'), 'dry'], [L('送风', 'Fan'), 'fan']];
}
function acFanOptions() {
    return [[L('不改', 'No change'), ''], [L('自动', 'Auto'), 'auto'], [L('低', 'Low'), 'low'],
            [L('中', 'Mid'), 'mid'], [L('高', 'High'), 'high']];
}
function acTempOptions() {
    // 真遥控器 RN02G(X) 只有整数度，没有半度档
    const opts = [[L('不改', 'No change'), '']];
    for (let t = 17; t <= 30; t += 1) {
        opts.push([t + '°C', String(t)]);
    }
    return opts;
}

// ==================== 工具箱 & 主题 ====================

function buildToolbox() {
    const num = numSourceOptions();
    const bool = boolSourceOptions();
    const evt = otherEventOptions();
    const stBool = noVarOptions(stateVars('bool'));
    const stNum = noVarOptions(stateVars('number'));
    const stEnum = stateEnumPredOptions();
    const stText = noVarOptions(stateVars('text'));
    const stToggle = noVarOptions(stateToggleVars());
    const stCondBool = orPlaceholder(stateSourceOptions('bool'), newStateHint());
    const stCondNum = orPlaceholder(stateSourceOptions('number'), newStateHint());
    const stCondEnum = orPlaceholder(condStateEnumOptions(), newStateHint());
    // 扁平工具箱：只有四个顶层分类，积木一律直接可见，不再套子分类（点开两层才能找到动作）
    return `<xml>
      <category name="${L('规则', 'Rules')}" colour="265">
        <block type="rule_block"></block>
      </category>
      <category name="${L('触发', 'Triggers')}" colour="30">
        <block type="trig_num">
          <field name="SRC">${num[0][1]}</field><field name="OP">&gt;</field><field name="VAL">30</field>
        </block>
        <block type="trig_bool"><field name="SRC">${bool[0][1]}</field><field name="STATE">true</field></block>
        <block type="trig_status"></block>
        <block type="trig_interval"><field name="SECONDS">10</field></block>
        <block type="trig_time"><field name="TIME">08:00</field></block>
        <sep gap="14"></sep>
        <block type="trig_touch"><field name="EVT">touch_on</field></block>
        <block type="trig_keypad"></block>
        <block type="trig_ir"></block>
        <block type="trig_rfid"></block>
        <block type="trig_manual"></block>
        <block type="trig_access"></block>
        <block type="trig_access_denied"></block>
        <block type="trig_event_other"><field name="EVT">${evt[0][1]}</field></block>
      </category>
      <category name="${L('条件', 'Conditions')}" colour="190">
        <block type="cond_num">
          <field name="SRC">${num[0][1]}</field><field name="OP">&gt;</field><field name="VAL">30</field>
        </block>
        <block type="cond_bool"><field name="SRC">${bool[0][1]}</field><field name="STATE">true</field></block>
        <block type="cond_status"></block>
        <sep gap="14"></sep>
        <block type="cond_state_bool">
          <field name="SRC">${stCondBool[0][1]}</field><field name="STATE">true</field>
        </block>
        <block type="cond_state_num">
          <field name="SRC">${stCondNum[0][1]}</field><field name="OP">&gt;</field><field name="VAL">0</field>
        </block>
        <block type="cond_state_enum"><field name="PRED">${stCondEnum[0][1]}</field></block>
      </category>
      <category name="${L('动作', 'Actions')}" colour="120">
        <block type="act_door"></block>
        <block type="act_window"></block>
        <block type="act_light"></block>
        <block type="act_light_color"></block>
        <block type="act_light_rgb"></block>
        <block type="act_fan"></block>
        <block type="act_ac"></block>
        <block type="act_camera"></block>
        <block type="act_voice"></block>
        <block type="act_http"></block>
        <block type="act_ir"></block>
        <block type="act_ir_code"></block>
        <block type="act_buzzer"></block>
        <block type="act_buzzer_switch"></block>
        <block type="act_oled"></block>
        <block type="act_oled_line"></block>
        <block type="act_delay"></block>
        <block type="act_wait_num">
          <field name="SRC">${num[0][1]}</field><field name="OP">&gt;</field>
          <field name="VAL">30</field><field name="TIMEOUT">60</field>
        </block>
        <block type="act_wait_bool">
          <field name="SRC">${bool[0][1]}</field><field name="STATE">true</field>
          <field name="TIMEOUT">60</field>
        </block>
        <block type="act_wait_status"><field name="TIMEOUT">60</field></block>
        <sep gap="14"></sep>
        <block type="act_state_bool">
          <field name="NAME">${stBool[0][1]}</field><field name="VALUE">true</field>
        </block>
        <block type="act_state_toggle"><field name="NAME">${stToggle[0][1]}</field></block>
        <block type="act_state_num">
          <field name="NAME">${stNum[0][1]}</field><field name="OP">set</field><field name="VAL">0</field>
        </block>
        <block type="act_state_enum"><field name="PRED">${stEnum[0][1]}</field></block>
        <block type="act_state_text">
          <field name="NAME">${stText[0][1]}</field><field name="TEXT"></field>
        </block>
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

// ==================== 卡片摘要文案 ====================

const SENSOR_ICONS = {
    temperature: '🌡️', humidity: '💧', light: '☀️', smoke: '💨', rain: '🌧️',
    touch: '👆', motion: '🚶', door_status: '🚪', window_status: '🪟',
    light_status: '💡', fan_speed: '🌀',
};

function triggerIcon(trig) {
    if (!trig) return '❓';
    if (trig.kind === 'event') return '🔔';
    if (trig.kind === 'interval') return '⏱️';
    if (trig.kind === 'time') return '🕐';
    if (String(trig.sensor || '').startsWith('g:')) return '📌';
    return SENSOR_ICONS[trig.sensor] || '📈';
}

function triggerKindClass(trig) {
    if (!trig) return 'sensor';
    if (trig.kind === 'event') return 'evt';
    if (trig.kind === 'interval' || trig.kind === 'time') return 'time';
    return 'sensor';
}

function summarizeTrigger(t) {
    if (!t || !t.kind) return L('（未设置触发）', '(no trigger)');
    if (t.kind === 'interval') return `${L('每隔 ', 'Every ')}${t.seconds}${L(' 秒', 's')}`;
    if (t.kind === 'time') return `${L('每天 ', 'Daily ')}${t.hhmm}`;
    if (t.kind === 'event') {
        const e = CAPS.events.find(x => x.id === t.event);
        let label = e ? e.label : t.event;
        if (t.key) label += `${L(' · 键 ', ' · key ')}${t.key}`;
        if (t.command) {
            const c = ((e && e.choices) || []).find(x => x.id === t.command);
            label += ` · ${c ? c.label : t.command}`;
        }
        if (t.device) {
            const d = ((e && e.choices) || []).find(x => x.id === t.device);
            label += ` · ${d ? d.label : t.device}`;
        }
        if (t.method) {
            const m = ((e && e.choices) || []).find(x => x.id === t.method);
            label += ` · ${m ? m.label : t.method}`;
        }
        if (t.uid) label += `${L(' · 卡 ', ' · card ')}${t.uid}`;
        return label;
    }
    const s = CAPS.sources.find(x => x.id === t.sensor);
    const label = s ? s.label : t.sensor;
    const hold = t.hold_sec ? `${L('（持续 ', ' (hold ')}${t.hold_sec}${L('s）', 's)')}` : '';
    if (s && s.kind === 'enum') {
        return `${label} = ${(s.choice_labels || {})[t.value] || t.value}${hold}`;
    }
    if (s && s.kind === 'bool') {
        return `${label} = ${(t.value === true || t.value === 'true') ? L('是', 'yes') : L('否', 'no')}${hold}`;
    }
    const op = (CAPS.comparators.find(c => c.id === t.op) || {}).label || t.op;
    return `${label} ${op} ${t.value}${(s && s.unit) ? s.unit : ''}${hold}`;
}

function summarizeAction(a) {
    if (!a) return '';
    switch (a.device) {
        case 'door':   return a.status === 'open' ? L('开门', 'Open door') : L('关门', 'Close door');
        case 'window': return L('窗', 'Window ') + ({ open: L('打开', 'Open'), close: L('关闭', 'Close'), normal: L('半开', 'Half') }[a.status] || '');
        case 'light': {
            if (a.color === 'rgb') return `${L('灯 RGB(', 'Light RGB(')}${a.r},${a.g},${a.b})`;
            if (a.color && a.color !== 'white') {
                const c = lightColorOptions().find(x => x[1] === a.color);
                return L('灯 ', 'Light ') + (c ? c[0] : a.color);
            }
            return L('灯', 'Light') + (a.status === 'on' ? L('开', ' on') : L('关', ' off'))
                   + (a.brightness !== undefined ? ` ${a.brightness}%` : '');
        }
        case 'fan': {
            const fanOp = a.op || 'set';
            const fanAt = Number(a.speed) > 0 ? `${a.speed}%` : L('上次转速', 'last speed');
            if (fanOp === 'off') return L('风扇 关闭', 'Fan off');
            if (fanOp === 'on') return `${L('风扇 开启 ', 'Fan on ')}${fanAt}`;
            if (fanOp === 'toggle') return `${L('风扇 切换开/关（开时 ', 'Fan toggle (on at ')}${fanAt}${L('）', ')')}`;
            return `${L('风扇 ', 'Fan ')}${a.speed}%`;
        }
        case 'buzzer':
            if (a.mode === 'on') return L('蜂鸣器 持续响', 'Buzzer continuous');
            if (a.mode === 'off') return L('蜂鸣器 停', 'Buzzer stop');
            return `${L('蜂鸣 ', 'Buzzer ')}${a.count}${L(' 声', ' beeps')}`;
        case 'delay':  return `${L('等待 ', 'Wait ')}${a.seconds}s`;
        case 'wait': {
            const s = CAPS.sources.find(x => x.id === a.sensor);
            const label = s ? s.label : a.sensor;
            let desc;
            if (s && s.kind === 'enum') {
                desc = `${label} = ${(s.choice_labels || {})[a.value] || a.value}`;
            } else if (s && s.kind === 'bool') {
                desc = `${label} = ${(a.value === true || a.value === 'true') ? L('是', 'yes') : L('否', 'no')}`;
            } else {
                const op = (CAPS.comparators.find(c => c.id === a.op) || {}).label || a.op;
                desc = `${label} ${op} ${a.value}${(s && s.unit) ? s.unit : ''}`;
            }
            return `${L('等到 ', 'Wait until ')}${desc}${L('（≤', ' (≤')}${a.timeout_sec}${L('s）', 's)')}`;
        }
        case 'oled':
            if (a.clear) return L('OLED 清屏', 'OLED clear');
            return (a.line === undefined || a.line === null)
                ? L('OLED 显示', 'OLED show') : `${L('OLED 第', 'OLED line ')}${a.line}${L('行', '')}`;
        case 'ac': {
            const bits = [];
            if (a.power !== undefined) bits.push(a.power ? L('开机', 'On') : L('关机', 'Off'));
            if (a.mode) {
                bits.push({ auto: L('自动', 'Auto'), cool: L('制冷', 'Cool'), heat: L('制热', 'Heat'),
                            dry: L('抽湿', 'Dry'), fan: L('送风', 'Fan') }[a.mode] || a.mode);
            }
            if (a.temperature !== undefined) bits.push(a.temperature + '°C');
            if (a.fan) bits.push(L('风', 'fan ') + ({ auto: L('自动', 'Auto'), low: L('低', 'Low'), mid: L('中', 'Mid'), high: L('高', 'High') }[a.fan] || a.fan));
            if (a.swing_ud) bits.push(L('上下扫风', 'Swing V'));
            if (a.swing_lr) bits.push(L('左右扫风', 'Swing H'));
            return L('空调', 'AC') + (bits.length ? ' ' + bits.join(' ') : '');
        }
        case 'ir': {
            if (a.address !== undefined && a.command !== undefined) {
                const hex = '0x' + Number(a.command).toString(16).toUpperCase().padStart(2, '0');
                const k = irKeyOptions().find(x => x[1] === hex);
                return L('红外发射 ', 'IR send ') + (k ? k[0] : hex);
            }
            return `${L('红外发射 ', 'IR send ')}${a.code}`;
        }
        case 'state': {
            const v = (CAPS.state_vars || []).find(x => x.id === a.name);
            const label = v ? (v.label || v.name) : String(a.name || '').replace(/^g:/, '');
            if (a.op === 'toggle') return `${L('状态「', 'State "')}${label}${L('」⇆切换', '" toggle')}`;
            let val = a.value;
            if (v && v.type === 'enum') val = (v.choice_labels || {})[val] || val;
            else if (typeof val === 'boolean') val = val ? L('是', 'yes') : L('否', 'no');
            if (a.op === 'add') {
                const n = Number(val) || 0;
                return `${L('状态「', 'State "')}${label}${L('」', '"')}${n >= 0 ? '+' : ''}${n}`;
            }
            return `${L('状态「', 'State "')}${label}${L('」= ', '" = ')}${val}`;
        }
        case 'camera': return L('门口拍照并存储', 'Doorway snapshot');
        case 'voice':  return a.action === 'say' ? L('语音播报', 'Voice announce') : L('唤醒语音', 'Wake voice');
        case 'http':   return `HTTP ${String(a.method || 'post').toUpperCase()} `
                            + String(a.url || '').replace(/^https?:\/\//, '').slice(0, 40);
        default:       return a.device;
    }
}

function summarizeActionList(actions) {
    return (actions || []).map(summarizeAction).filter(Boolean);
}

// 条件与传感器触发同形（{sensor, op, value}），直接复用触发的标签换算
function summarizeCondition(c) {
    if (!c || !c.sensor) return '';
    return summarizeTrigger(Object.assign({ kind: 'sensor' }, c));
}

function summarizeConditions(conditions) {
    return (conditions || []).map(summarizeCondition).filter(Boolean);
}

// ==================== 视图切换 ====================

function showEditor() {
    document.getElementById('listView').classList.add('hidden');
    document.getElementById('editorView').classList.remove('hidden');
    if (!workspace) initWorkspace();
    Blockly.svgResize(workspace);
    workspace.clear();
    LOADING = true;
    const isState = EDIT_KIND === 'state';
    ['editorEnabledWrap', 'editorRunBtn'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.classList.toggle('hidden', isState);
    });
    if (isState) {
        buildStateBlock(editingVar);
        document.getElementById('editorName').value =
            editingVar ? (editingVar.name || '') : L('新状态', 'New state');
    } else {
        const trig = (editingRule.trigger && editingRule.trigger.kind)
            ? editingRule.trigger
            : { kind: 'sensor', sensor: 'temperature', op: '>', value: 30 };
        buildRuleBlock(Object.assign({}, editingRule, { trigger: trig }));
        document.getElementById('editorName').value = editingRule.name || L('新规则', 'New rule');
        document.getElementById('editorEnabled').checked = editingRule.enabled !== false;
    }
    LOADING = false;
    DIRTY = false;
    setTimeout(() => { fitWorkspace(); Blockly.svgResize(workspace); }, 60);
}

function closeEditor() {
    if (DIRTY && !confirm(L('这里有未保存的改动，确定放弃？', 'You have unsaved changes. Discard them?'))) return;
    document.getElementById('editorView').classList.add('hidden');
    document.getElementById('listView').classList.remove('hidden');
    editingIndex = -1;
    editingRule = null;
    editingVar = null;
    EDIT_KIND = 'rule';
    DIRTY = false;
    refreshPreview();
}

// ==================== 规则列表 ====================

function renderRuleList() {
    const grid = document.getElementById('ruleGrid');
    const count = document.getElementById('ruleCount');
    if (count) count.textContent = `${L('共 ', '')}${RULES.length}${L(' 条规则 · ', ' rules · ')}${GS_VARS.length}${L(' 个全局状态', ' global states')}`;
    if (!grid) return;
    const states = GS_VARS.length
        ? `<div class="grid-section">${L('📌 全局状态', '📌 Global states')} · ${GS_VARS.length}</div>`
          + GS_VARS.map(stateCardHtml).join('')
        : '';
    const rules = RULES.length
        ? `<div class="grid-section">${L('🧩 自动化规则', '🧩 Automation rules')} · ${RULES.length}</div>`
          + RULES.map(ruleCardHtml).join('')
        : L('<div class="empty-rules">还没有规则，点右上角「＋ 新建规则」开始。</div>', '<div class="empty-rules">No rules yet. Click "＋ New rule" at the top-right to start.</div>');
    grid.innerHTML = gatingBannerHtml() + states + rules;
}

// 「门控维护预设」被停用 → 依赖它们的联动会静默失效，给醒目提示（#77）
function gatingDisabledRules() {
    if (!GATING_PRESETS.length) return [];
    return RULES.filter((r) => r.preset && GATING_PRESETS.includes(r.preset)
                               && r.enabled === false);
}

function gatingBannerHtml() {
    const off = gatingDisabledRules();
    if (!off.length) return '';
    const names = off.map((r) => esc(r.name)).join('、');
    return L('<div class="gating-warn">⚠️ 基础门控预设被停用：', '<div class="gating-warn">⚠️ Base gating presets disabled: ') + names
        + L('。依赖它们的联动（有人/无人判定、手动优先解除）不会报错，只会静默失效；', '. The automations that depend on them (presence detection, manual-priority release) will not error - they will silently stop working; ')
        + L('点右上角「♻️ 恢复内置」可一键补回。</div>', 'click "♻️ Restore built-ins" at the top-right to bring them back.</div>');
}

function ruleCardHtml(r, i) {
    const trig = r.trigger;
    const pv = r.id ? PREVIEW[r.id] : null;
    let statusBadge = '';
    if (r.enabled === false) {
        const gating = r.preset && GATING_PRESETS.includes(r.preset);
        statusBadge = gating
            ? L('<span class="badge disabled">已停用 · ⚠ 门控预设</span>', '<span class="badge disabled">Disabled · ⚠ gating preset</span>')
            : L('<span class="badge disabled">已停用</span>', '<span class="badge disabled">Disabled</span>');
    }
    else if (pv && pv.trigger_now === true) statusBadge = L('<span class="badge on">条件成立</span>', '<span class="badge on">Condition met</span>');
    else if (pv && pv.trigger_now === false) statusBadge = L('<span class="badge off">未成立</span>', '<span class="badge off">Not met</span>');
    else if (pv) statusBadge = L('<span class="badge evt">事件驱动</span>', '<span class="badge evt">Event-driven</span>');
    const conds = summarizeConditions(r.conditions);
    const acts = summarizeActionList(r.actions);
    const elses = summarizeActionList(r.else_actions);
    // 一条一个 chip：条件/动作各占一格，长列表靠换行 + 行内滚动消化，不做「等 N 项」折叠
    const chips = [];
    if (conds.length) {
        chips.push(`<span class="chip label">${L('如果', 'If')}${r.match === 'any' ? L('任一', 'Any') : L('全部', 'All')}</span>`);
        conds.forEach(c => chips.push(`<span class="chip cond">${esc(c)}</span>`));
    }
    chips.push('<span class="chip arrow">→</span>');
    if (acts.length) {
        acts.forEach(a => chips.push(`<span class="chip act">${esc(a)}</span>`));
    } else {
        chips.push(L('<span class="chip act none">（无动作）</span>', '<span class="chip act none">(no actions)</span>'));
    }
    if (elses.length) {
        chips.push(L('<span class="chip label">否则</span>', '<span class="chip label">Else</span>'));
        elses.forEach(a => chips.push(`<span class="chip act">${esc(a)}</span>`));
    }
    return `<div class="rule-card ${r.enabled === false ? 'disabled' : ''}" data-kind="rule" data-index="${i}">
      <div class="rc-icon ${triggerKindClass(trig)}">${triggerIcon(trig)}</div>
      <div class="rc-main">
        <div class="rc-name">${esc(r.name)}</div>
        <div class="rc-sub">${L('当 ', 'When ')}${esc(summarizeTrigger(trig))}</div>
        <div class="rc-flow">${chips.join('')}</div>
        <div class="rc-meta">
          ${statusBadge}
          ${r.preset ? `<span class="badge evt">${L('内置', 'Built-in')}</span>` : ''}
          <span>${conds.length ? conds.length + L(' 条件', ' conditions') : L('无条件', 'No conditions')}</span>
          <span>${acts.length + elses.length}${L(' 动作', ' actions')}</span>
          <span>${L('冷却 ', 'Cooldown ')}${r.cooldown === undefined ? 3 : r.cooldown}s</span>
        </div>
      </div>
      <div class="rc-actions">
        <button class="icon-btn" data-act="run" title="${L('运行一次', 'Run once')}"${r.id ? '' : ' disabled'}>▶</button>
        <button class="icon-btn" data-act="menu" title="${L('更多', 'More')}">⋮</button>
      </div>
    </div>`;
}

// ---- 卡片 ⋮ 菜单 ----

function openCardMenu(kind, i, btn) {
    MENU_KIND = kind;
    MENU_INDEX = i;
    const menu = document.getElementById('cardMenu');
    if (kind === 'state') {
        if (!GS_VARS[i]) return;
        // 状态条目没有「运行一次/复制/停用」这些规则才有的动作
        menu.innerHTML =
            L('<button data-m="edit">✏️ 编辑</button>', '<button data-m="edit">✏️ Edit</button>') +
            '<div class="sep"></div>' +
            L('<button data-m="del" class="danger">🗑 删除</button>', '<button data-m="del" class="danger">🗑 Delete</button>');
    } else {
        const r = RULES[i];
        if (!r) return;
        menu.innerHTML =
            `<button data-m="run"${r.id ? '' : ' disabled'}>▶ ${L('运行一次', 'Run once')}</button>` +
            L('<button data-m="edit">✏️ 编辑</button>', '<button data-m="edit">✏️ Edit</button>') +
            L('<button data-m="rename">🏷 重命名</button>', '<button data-m="rename">🏷 Rename</button>') +
            L('<button data-m="dup">📄 复制</button>', '<button data-m="dup">📄 Duplicate</button>') +
            `<button data-m="toggle">${r.enabled === false ? L('⏻ 启用', '⏻ Enable') : L('⏻ 停用', '⏻ Disable')}</button>` +
            '<div class="sep"></div>' +
            L('<button data-m="del" class="danger">🗑 删除</button>', '<button data-m="del" class="danger">🗑 Delete</button>');
    }
    const rect = btn.getBoundingClientRect();
    menu.classList.remove('hidden');
    const w = menu.offsetWidth, h = menu.offsetHeight;
    let left = rect.right - w;
    let top = rect.bottom + 6;
    if (top + h > window.innerHeight - 8) top = rect.top - h - 6;
    menu.style.left = Math.max(8, Math.min(left, window.innerWidth - w - 8)) + 'px';
    menu.style.top = Math.max(8, top) + 'px';
}

function closeCardMenu() {
    document.getElementById('cardMenu').classList.add('hidden');
    MENU_INDEX = -1;
}

async function cardMenuAction(m, i) {
    if (MENU_KIND === 'state') {
        if (m === 'edit') openStateEditor(i);
        else if (m === 'del') await deleteGlobalVar(i);
        return;
    }
    const r = RULES[i];
    if (!r) return;
    if (m === 'run') return runRule(r.id);
    if (m === 'edit') return openEditor(i);
    if (m === 'rename') return startInlineRename(i);
    if (m === 'dup') return duplicateRule(i);
    if (m === 'toggle') {
        r.enabled = r.enabled === false;
        return persistRules(`${L('已', '')}${r.enabled ? L('启用', 'Enable') : L('停用', 'Disable')}${L('「', '"')}${r.name}${L('」', '"')}`);
    }
    if (m === 'del') {
        if (!confirm(`${L('删除规则「', 'Delete rule "')}${r.name}${L('」？', '" ?')}`)) return;
        RULES.splice(i, 1);
        return persistRules(`${L('已删除「', 'Deleted "')}${r.name}${L('」', '"')}`);
    }
}

// ---- 规则操作 ----

async function persistRules(msg) {
    try {
        const saved = await api('/api/automation/rules', {
            method: 'PUT', body: JSON.stringify({ rules: RULES }),
        });
        RULES = saved.rules || RULES;
        await refreshPreview();
        renderRuleList();
        if (msg) showNotification(msg, 'success');
    } catch (e) {
        showNotification(e.message, 'error');
        await reloadRules();
    }
}

function createDoorwayRule() {
    EDIT_KIND = 'rule';
    editingIndex = -1;
    editingRule = {
        id: null, name: L('门口靠近拍照', 'Doorway proximity snapshot'), enabled: true,
        trigger: { kind: 'sensor', sensor: 'distance_cm', op: '<', value: 50, hold_sec: 2 },
        match: 'all', conditions: [], actions: [{ device: 'camera', action: 'snapshot' }],
        else_actions: [], cooldown: 3,
    };
    showEditor();
}

function createRule() {
    EDIT_KIND = 'rule';
    editingIndex = -1;
    editingRule = {
        id: null, name: L('新规则', 'New rule'), enabled: true,
        trigger: { kind: 'sensor', sensor: 'temperature', op: '>', value: 30 },
        match: 'all', conditions: [],
        actions: [{ device: 'fan', speed: 60 }], else_actions: [], cooldown: 3,
    };
    showEditor();
}

function openEditor(i) {
    EDIT_KIND = 'rule';
    editingIndex = i;
    editingRule = JSON.parse(JSON.stringify(RULES[i]));
    showEditor();
}

// ---- 全局状态条目：新建/编辑走同一个 Blockly 编辑器 ----

function createState() {
    EDIT_KIND = 'state';
    editingVar = null;
    showEditor();
}

function openStateEditor(i) {
    EDIT_KIND = 'state';
    editingVar = JSON.parse(JSON.stringify(GS_VARS[i] || null));
    showEditor();
}

function buildStateBlock(v) {
    const b = workspace.newBlock('state_def');
    b._existing = !!v;
    b._choiceLabels = (v && v.choice_labels) || {};
    b.initSvg();
    b.render();
    b.setFieldValue(v ? (v.name || v.label || '') : L('新状态', 'New state'), 'NAME');
    b.setFieldValue(v ? v.type : 'bool', 'TYPE');
    if (v) b.setFieldValue(gsTypeLabel(v.type), 'TYPELABEL');
    if (v && v.type === 'enum') b.setFieldValue((v.choices || []).join(','), 'CHOICES');
    if (v) fillStateValue(b, v);
    showStateTypeRows(b, v ? v.type : 'bool');
    return b;
}

function fillStateValue(b, v) {
    if (v.type === 'bool') b.setFieldValue(v.value ? 'true' : 'false', 'VB');
    else if (v.type === 'number') b.setFieldValue(String(v.value === undefined ? 0 : v.value), 'VN');
    else if (v.type === 'enum') {
        // VE 的选项是按 CHOICES 现算的，Blockly 校验 setFieldValue 时用的是 init 期
        // （CHOICES 还空着）生成的缓存，不先重算就把当前值判成非法：卡片显示
        // 「（先填选项）」，保存时静默落到第一个选项，等于偷偷改了全屋模式。
        b.getField('VE').getOptions(false);
        b.setFieldValue(String(v.value || ''), 'VE');
    } else b.setFieldValue(String(v.value || ''), 'VT');
}

function collectStateDef() {
    const b = workspace.getTopBlocks(false).find(x => x.type === 'state_def');
    if (!b) throw new Error(L('画布里没有状态块', 'No state block on the canvas'));
    const name = (document.getElementById('editorName').value || '').trim()
        || (b.getFieldValue('NAME') || '').trim();
    if (!name) throw new Error(L('请填写状态名字（1~24 字，不含空格与冒号）', 'Enter a state name (1-24 chars, no spaces or colons)'));
    const type = b.getFieldValue('TYPE') || 'bool';
    const out = { name, type };
    if (type === 'bool') {
        out.value = b.getFieldValue('VB') === 'true';
    } else if (type === 'number') {
        out.value = Number(b.getFieldValue('VN') || 0);
    } else if (type === 'enum') {
        const choices = parseChoices(b.getFieldValue('CHOICES'));
        if (!choices.length) throw new Error(L('「选项」类型需要至少 1 个选项值（逗号分隔）', 'The "Options" type needs at least 1 option value (comma-separated)'));
        out.choices = choices;
        const picked = b.getFieldValue('VE');
        out.value = choices.includes(picked) ? picked : choices[0];
    } else {
        out.value = String(b.getFieldValue('VT') || '');
    }
    return out;
}

async function saveStateDef() {
    let def;
    try {
        def = collectStateDef();
    } catch (e) {
        showNotification(e.message, 'error');
        return;
    }
    if (editingVar) {
        if (def.type !== editingVar.type) {
            showNotification(L('状态类型不能修改：请删除这条再新建', 'A state\'s type cannot be changed: delete this one and create a new one'), 'error');
            return;
        }
        // 选项值可能被改；名字同理（后端会自动改写规则里的引用）
        const body = { name: def.name, value: def.value };
        if (def.type === 'enum') body.choices = def.choices;
        await gsApi(`/api/automation/global_state/${encodeURIComponent(editingVar.id)}`,
                    { method: 'PUT', body: JSON.stringify(body) });
        return;
    }
    await gsApi('/api/automation/global_state', { method: 'POST', body: JSON.stringify(def) });
}

async function gsApi(url, options) {
    if (SAVE_PENDING) return;
    SAVE_PENDING = true;
    try {
        const r = await api(url, options);
        afterGsChange(r);
        DIRTY = false;
        closeEditor();
        showNotification(r.message || L('已保存', 'Saved'), 'success');
    } catch (e) {
        showNotification(e.message, 'error');
    } finally {
        SAVE_PENDING = false;
    }
}

async function duplicateRule(i) {
    const src = RULES[i];
    const copy = JSON.parse(JSON.stringify(src));
    copy.id = null;
    delete copy.preset;
    copy.name = `${src.name}${L(' 副本', ' copy')}`;
    RULES.splice(i + 1, 0, copy);
    await persistRules(`${L('已复制「', 'Duplicated "')}${src.name}${L('」', '"')}`);
}

function startInlineRename(i) {
    const card = document.querySelector(`.rule-card[data-kind="rule"][data-index="${i}"]`);
    if (!card || RENAMING) return;
    const nameEl = card.querySelector('.rc-name');
    const old = RULES[i].name;
    const input = document.createElement('input');
    input.className = 'rc-name-input';
    input.value = old;
    nameEl.replaceWith(input);
    input.focus();
    input.select();
    RENAMING = true;
    let done = false;
    const commit = async (ok) => {
        if (done) return;
        done = true;
        RENAMING = false;
        const val = input.value.trim();
        if (!ok || !val || val === old) { renderRuleList(); return; }
        RULES[i].name = val;
        await persistRules(`${L('已重命名为「', 'Renamed to "')}${val}${L('」', '"')}`);
    };
    input.addEventListener('blur', () => commit(true));
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); commit(true); }
        else if (e.key === 'Escape') { e.preventDefault(); commit(false); }
    });
}

async function runRule(id) {
    if (!id) { showNotification(L('请先保存这条规则', 'Please save this rule first'), 'error'); return; }
    try {
        const r = await api(`/api/automation/rules/${encodeURIComponent(id)}/run`, { method: 'POST' });
        showNotification(r.message || L('已提交执行', 'Run submitted'), r.ok ? 'success' : 'error');
        setTimeout(refreshLogs, 2500);
    } catch (e) {
        showNotification(e.message, 'error');
    }
}

async function restorePresets() {
    if (!confirm(L('把被删掉的内置默认规则补回来？（你自己添加或改过的规则不受影响）', 'Restore deleted built-in rules? (Your own added or edited rules are unaffected)'))) return;
    try {
        const r = await api('/api/automation/rules/restore', { method: 'POST' });
        RULES = r.rules || [];
        await refreshPreview();
        renderRuleList();
        showNotification(r.message || L('内置规则已恢复', 'Built-in rules restored'), 'success');
    } catch (e) {
        showNotification(e.message, 'error');
    }
}

// ==================== 编辑器 ====================

function initWorkspace() {
    workspace = Blockly.inject('blocklyDiv', {
        toolbox: buildToolbox(),
        theme: darkTheme(),
        grid: { spacing: 24, length: 3, colour: '#1c3142', snap: false },
        zoom: { controls: true, wheel: true, startScale: 1, maxScale: 2, minScale: 0.3 },
        trashcan: true,
        renderer: 'zelos',
        // 媒体资源走本地（内网/校园网无外网也能用）
        media: '/static/vendor/blockly/media/',
    });
    // 顶部名称框与画布里的名字双向同步（规则块和状态定义块共用这一条通道）
    workspace.addChangeListener((e) => {
        if (!e || !e.blockId) return;
        if (e.name === 'NAME') {
            const b = workspace.getBlockById(e.blockId);
            const inp = document.getElementById('editorName');
            if (b && isTopBlock(b) && inp) {
                const v = b.getFieldValue('NAME') || '';
                if (inp.value !== v) inp.value = v;
            }
        }
        // 画布里的「启用」勾选框与工具栏开关是同一个状态的两个入口：画布改动同步回开关，
        // 否则用户在画布上勾选后保存会被忽略（#77 的「误置 enabled」入口之一）。
        if (e.name === 'ENABLED') {
            const b = workspace.getBlockById(e.blockId);
            const cb = document.getElementById('editorEnabled');
            if (b && b.type === 'rule_block' && cb) {
                cb.checked = b.getFieldValue('ENABLED') === 'TRUE';
            }
        }
        if (!LOADING && e.isUiEvent === false) DIRTY = true;
    });
    document.getElementById('fitViewBtn')?.addEventListener('click', fitWorkspace);
    document.getElementById('editorName')?.addEventListener('input', (ev) => {
        const rb = workspace.getTopBlocks(false).find(isTopBlock);
        if (rb) rb.setFieldValue(ev.target.value, 'NAME');
    });
    // 反向：工具栏开关改动同步到画布（保存以开关为准，见 collectEditor）
    document.getElementById('editorEnabled')?.addEventListener('change', (ev) => {
        const rb = workspace.getTopBlocks(false).find((b) => b.type === 'rule_block');
        if (rb) rb.setFieldValue(ev.target.checked ? 'TRUE' : 'FALSE', 'ENABLED');
    });
}

function isTopBlock(b) {
    return b.type === 'rule_block' || b.type === 'state_def';
}

// 只编辑一条规则：块贴左上角，超出画布时才缩放
function fitWorkspace() {
    if (!workspace) return;
    const rb = workspace.getTopBlocks(false).find(isTopBlock);
    if (!rb) return;
    const p = rb.getRelativeToSurfaceXY();
    if (Math.round(p.x) !== 24 || Math.round(p.y) !== 24) rb.moveBy(24 - p.x, 24 - p.y);
    const hw = rb.getHeightWidth();
    const m = workspace.getMetrics();
    const need = Math.min((m.viewWidth - 40) / hw.width, (m.viewHeight - 40) / hw.height);
    if (need >= 1) {
        workspace.setScale(1);
        workspace.scroll(0, 0);
    } else {
        workspace.zoomToFit();
    }
}

function buildRuleBlock(rule) {
    const rb = workspace.newBlock('rule_block');
    rb.initSvg();
    rb.render();
    rb.setFieldValue(rule.name || L('新规则', 'New rule'), 'NAME');
    rb.setFieldValue(rule.enabled === false ? 'FALSE' : 'TRUE', 'ENABLED');
    rb.setFieldValue(rule.match === 'any' ? 'any' : 'all', 'MATCH');
    rb.setFieldValue(String(rule.cooldown === undefined ? 3 : rule.cooldown), 'COOLDOWN');
    const trig = fillTrigger(rule.trigger);
    trig.render();
    rb.getInput('TRIGGER').connection.connect(trig.previousConnection);
    connectStack(rb, 'CONDS', (rule.conditions || []).map(fillCondition).filter(Boolean));
    connectStack(rb, 'DO', (rule.actions || []).map(fillAction).filter(Boolean));
    connectStack(rb, 'ELSE', (rule.else_actions || []).map(fillAction).filter(Boolean));
    return rb;
}

function collectEditor() {
    const rb = workspace.getTopBlocks(false).find(b => b.type === 'rule_block');
    if (!rb) throw new Error(L('画布里没有规则块', 'No rule block on the canvas'));
    const trigBlock = rb.getInputTargetBlock('TRIGGER');
    if (!trigBlock) throw new Error(L('请先把橙色「当…」触发块放进规则', 'Add the orange "When…" trigger block into the rule first'));
    const actions = chainBlocks(rb.getInputTargetBlock('DO')).map(actionToJson).filter(Boolean);
    if (!actions.length) throw new Error(L('「那么」里至少放 1 个绿色动作块', 'Put at least 1 green action block in "Then"'));
    const name = (document.getElementById('editorName').value || '').trim() || L('未命名规则', 'Untitled rule');
    const rule = {
        id: editingRule && editingRule.id ? editingRule.id : null,
        name,
        enabled: document.getElementById('editorEnabled').checked,
        trigger: triggerToJson(trigBlock),
        match: rb.getFieldValue('MATCH'),
        conditions: chainBlocks(rb.getInputTargetBlock('CONDS')).map(conditionToJson).filter(Boolean),
        actions,
        else_actions: chainBlocks(rb.getInputTargetBlock('ELSE')).map(actionToJson).filter(Boolean),
        cooldown: Number(rb.getFieldValue('COOLDOWN')),
    };
    if (editingRule && editingRule.preset) rule.preset = editingRule.preset;
    return rule;
}

async function saveEditor(runAfter) {
    if (SAVE_PENDING) return;
    if (EDIT_KIND === 'state') return saveStateDef();
    let rule;
    try {
        rule = collectEditor();
    } catch (e) {
        showNotification(e.message, 'error');
        return;
    }
    const next = RULES.slice();
    let idx = editingIndex;
    if (idx >= 0 && next[idx]) {
        next[idx] = rule;
    } else {
        next.push(rule);
        idx = next.length - 1;
    }
    SAVE_PENDING = true;
    try {
        const saved = await api('/api/automation/rules', {
            method: 'PUT', body: JSON.stringify({ rules: next }),
        });
        // 后端按原顺序返回并补全 id，故下标保持不变
        RULES = saved.rules || next;
        editingIndex = idx;
        editingRule = RULES[idx] ? JSON.parse(JSON.stringify(RULES[idx])) : rule;
        DIRTY = false;
        await refreshPreview();
        renderRuleList();
        showNotification(saved.message || L('已保存', 'Saved'), 'success');
        if (runAfter) {
            await runRule(RULES[idx] && RULES[idx].id);
        } else {
            closeEditor();
        }
    } catch (e) {
        showNotification(e.message, 'error');
    } finally {
        SAVE_PENDING = false;
    }
}

function runEditing() {
    saveEditor(true);
}

// ==================== 积木 <-> JSON ====================

function chainBlocks(first) {
    const out = [];
    let b = first;
    while (b) { out.push(b); b = b.getNextBlock(); }
    return out;
}

// 传感器触发块可带「持续 N 秒」（0 表示不写进 JSON，即跨阈值立刻触发）
function withHold(block, json) {
    const hold = Number(block.getFieldValue('HOLD') || 0);
    if (hold > 0) json.hold_sec = hold;
    return json;
}

// 「状态 = 取值」类下拉把 id 和值拼在一个 field 里（如 door_status:open、
// g:全屋模式:auto）。全局状态 id 自带一个冒号，所以只能按「第二个冒号」切一次，
// 用 split(':') 会把 id 切成 "g"、条件永远存不进去。
function splitPred(raw) {
    const s = String(raw || '');
    const i = s.startsWith('g:') ? s.indexOf(':', 2) : s.indexOf(':');
    return i < 0 ? [s, ''] : [s.slice(0, i), s.slice(i + 1)];
}

function triggerToJson(b) {
    switch (b.type) {
        case 'trig_num':
            return withHold(b, { kind: 'sensor', sensor: b.getFieldValue('SRC'),
                     op: b.getFieldValue('OP'), value: Number(b.getFieldValue('VAL')) });
        case 'trig_bool':
            return withHold(b, { kind: 'sensor', sensor: b.getFieldValue('SRC'),
                     op: '==', value: b.getFieldValue('STATE') === 'true' });
        case 'trig_status': {
            const [sensor, value] = splitPred(b.getFieldValue('PRED'));
            return withHold(b, { kind: 'sensor', sensor, op: '==', value });
        }
        case 'trig_touch':
            return { kind: 'event', event: b.getFieldValue('EVT') };
        case 'trig_keypad':
            return { kind: 'event', event: 'keypad',
                     key: b.getFieldValue('KEY') || '1' };
        case 'trig_ir':
            return { kind: 'event', event: 'ir',
                     command: b.getFieldValue('CMD') || '0x45' };
        case 'trig_rfid': {
            const json = { kind: 'event', event: 'rfid' };
            const uid = (b.getFieldValue('UID') || '').trim();
            if (uid) json.uid = uid;      // 留空 = 任意卡片都触发
            return json;
        }
        case 'trig_manual': {
            const json = { kind: 'event', event: 'manual_control' };
            const dev = b.getFieldValue('DEV');
            if (dev) json.device = dev;   // 空 = 任意设备的手动操作
            return json;
        }
        case 'trig_access': {
            const json = { kind: 'event', event: 'access_granted' };
            const m = b.getFieldValue('M');
            if (m) json.method = m;       // 空 = 任意验证方式都算通过
            return json;
        }
        case 'trig_access_denied': {
            const json = { kind: 'event', event: 'access_denied' };
            const m = b.getFieldValue('M');
            if (m) json.method = m;
            return json;
        }
        case 'trig_event_other': {
            const evt = b.getFieldValue('EVT');
            if (!evt) return null;
            return { kind: 'event', event: evt };
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
            const [sensor, value] = splitPred(b.getFieldValue('PRED'));
            return { sensor, op: '==', value };
        }
        case 'cond_state_bool':
            return { sensor: b.getFieldValue('SRC'), op: '==',
                     value: b.getFieldValue('STATE') === 'true' };
        case 'cond_state_num':
            return { sensor: b.getFieldValue('SRC'), op: b.getFieldValue('OP'),
                     value: Number(b.getFieldValue('VAL')) };
        case 'cond_state_enum': {
            const [sensor, value] = splitPred(b.getFieldValue('PRED'));
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
        case 'act_light_color':
            return { device: 'light', status: 'on', brightness: 100,
                     color: b.getFieldValue('COLOR') };
        case 'act_light_rgb':
            return { device: 'light', status: 'on', brightness: 100, color: 'rgb',
                     r: Number(b.getFieldValue('R')), g: Number(b.getFieldValue('G')),
                     b: Number(b.getFieldValue('B')) };
        case 'act_fan':    return { device: 'fan', op: b.getFieldValue('OP') || 'set',
                                    speed: Number(b.getFieldValue('SPEED')) };
        case 'act_buzzer': return { device: 'buzzer', mode: 'beep',
                                    count: Number(b.getFieldValue('COUNT')),
                                    on_ms: Number(b.getFieldValue('ONMS')),
                                    off_ms: Number(b.getFieldValue('OFFMS')) };
        case 'act_buzzer_switch':
            return { device: 'buzzer', mode: b.getFieldValue('STATE') };
        case 'act_ir': {
            // 键位表给的是 command(0xNN)，遥控器 address 固定 0x00
            const hex = b.getFieldValue('CMD') || '0x45';
            return { device: 'ir', address: 0, command: parseInt(hex, 16) };
        }
        case 'act_ir_code':
            return { device: 'ir', code: Number(b.getFieldValue('CODE')) };
        case 'act_ac': {
            const a = { device: 'ac' };
            const power = b.getFieldValue('POWER');
            if (power) a.power = power === 'on';
            const mode = b.getFieldValue('MODE');
            if (mode) a.mode = mode;
            const temp = b.getFieldValue('TEMP');
            if (temp) a.temperature = Number(temp);
            const fan = b.getFieldValue('FAN');
            if (fan) a.fan = fan;
            [['SWING_UD', 'swing_ud'], ['SWING_LR', 'swing_lr']].forEach(([field, key]) => {
                const v = b.getFieldValue(field);
                if (v) a[key] = v === 'on';
            });
            return a;
        }
        case 'act_delay':  return { device: 'delay',
                                    seconds: Number(b.getFieldValue('SECONDS')) };
        case 'act_wait_num':
            return { device: 'wait', sensor: b.getFieldValue('SRC'),
                     op: b.getFieldValue('OP'),
                     value: Number(b.getFieldValue('VAL')),
                     timeout_sec: Number(b.getFieldValue('TIMEOUT')) };
        case 'act_wait_bool':
            return { device: 'wait', sensor: b.getFieldValue('SRC'), op: '==',
                     value: b.getFieldValue('STATE') === 'true',
                     timeout_sec: Number(b.getFieldValue('TIMEOUT')) };
        case 'act_wait_status': {
            const [sensor, value] = splitPred(b.getFieldValue('PRED'));
            if (!sensor || value === '') return null;
            return { device: 'wait', sensor, op: '==', value,
                     timeout_sec: Number(b.getFieldValue('TIMEOUT')) };
        }
        case 'act_oled':
            if (b.getFieldValue('CLEAR') === 'TRUE') return { device: 'oled', clear: true };
            return { device: 'oled', text: b.getFieldValue('TEXT') };
        case 'act_oled_line':
            return { device: 'oled', line: Number(b.getFieldValue('LINE')),
                     text: b.getFieldValue('TEXT') };
        case 'act_state_bool': {
            const name = b.getFieldValue('NAME');
            if (!name) return null;
            return { device: 'state', name, op: 'set',
                     value: b.getFieldValue('VALUE') === 'true' };
        }
        case 'act_state_toggle': {
            const name = b.getFieldValue('NAME');
            if (!name) return null;
            return { device: 'state', name, op: 'toggle' };
        }
        case 'act_state_num': {
            const name = b.getFieldValue('NAME');
            if (!name) return null;
            return { device: 'state', name, op: b.getFieldValue('OP') || 'set',
                     value: Number(b.getFieldValue('VAL')) };
        }
        case 'act_state_enum': {
            const [name, value] = splitPred(b.getFieldValue('PRED'));
            if (!name || value === '') return null;
            return { device: 'state', name, op: 'set', value };
        }
        case 'act_state_text': {
            const name = b.getFieldValue('NAME');
            if (!name) return null;
            return { device: 'state', name, op: 'set',
                     value: b.getFieldValue('TEXT') || '' };
        }
        case 'act_camera': return { device: 'camera', action: 'snapshot' };
        case 'act_voice': {
            const json = { device: 'voice', action: b.getFieldValue('ACT') || 'wake' };
            const text = (b.getFieldValue('TEXT') || '').trim();
            if (text) json.text = text;
            return json;
        }
        case 'act_http': {
            const url = (b.getFieldValue('URL') || '').trim();
            if (!url) return null;
            const json = { device: 'http',
                           method: b.getFieldValue('METHOD') || 'post', url };
            const text = (b.getFieldValue('TEXT') || '').trim();
            if (text) json.text = text;
            return json;
        }
        default: return null;
    }
}

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
        const evt = trig.event;
        let b;
        if (evt === 'touch_on' || evt === 'touch_off') {
            b = createTyped('trig_touch');
            b.setFieldValue(evt, 'EVT');
        } else if (evt === 'keypad') {
            b = createTyped('trig_keypad');
            if (trig.key) b.setFieldValue(optionValue(keypadOptions(), trig.key, '1'), 'KEY');
        } else if (evt === 'ir') {
            b = createTyped('trig_ir');
            if (trig.command) b.setFieldValue(optionValue(irKeyOptions(), trig.command, '0x45'), 'CMD');
        } else if (evt === 'rfid') {
            b = createTyped('trig_rfid');
            if (trig.uid) b.setFieldValue(trig.uid, 'UID');
        } else if (evt === 'manual_control') {
            b = createTyped('trig_manual');
            if (trig.device) b.setFieldValue(optionValue(manualDeviceOptions(), trig.device, 'fan'), 'DEV');
        } else if (evt === 'access_granted' || evt === 'access_denied') {
            b = createTyped(evt === 'access_granted' ? 'trig_access' : 'trig_access_denied');
            if (trig.method) {
                b.setFieldValue(optionValue(accessMethodOptions(), trig.method, ''), 'M');
            }
        } else {
            b = createTyped('trig_event_other');
            b.setFieldValue(optionValue(otherEventOptions(), evt, ''), 'EVT');
        }
        return b;
    }
    // sensor
    const kind = sourceKind(trig.sensor);
    let b;
    if (kind === 'bool') {
        b = createTyped('trig_bool');
        b.setFieldValue(trig.sensor, 'SRC');
        b.setFieldValue(trig.value === true || trig.value === 'true' ? 'true' : 'false', 'STATE');
    } else if (kind === 'enum') {
        b = createTyped('trig_status');
        b.setFieldValue(`${trig.sensor}:${trig.value}`, 'PRED');
    } else {
        b = createTyped('trig_num');
        b.setFieldValue(trig.sensor, 'SRC');
        b.setFieldValue(trig.op || '>', 'OP');
        b.setFieldValue(String(trig.value), 'VAL');
    }
    b.setFieldValue(String(trig.hold_sec || 0), 'HOLD');
    return b;
}

function fillCondition(c) {
    const kind = sourceKind(c.sensor);
    // 全局状态回填到专用积木，编辑时看到的和拖出来的一致
    if (String(c.sensor || '').startsWith('g:')) {
        if (kind === 'bool') {
            const b = createTyped('cond_state_bool');
            b.setFieldValue(c.sensor, 'SRC');
            b.setFieldValue(c.value === true || c.value === 'true' ? 'true' : 'false', 'STATE');
            return b;
        }
        if (kind === 'enum') {
            const b = createTyped('cond_state_enum');
            b.setFieldValue(`${c.sensor}:${c.value}`, 'PRED');
            return b;
        }
        const b = createTyped('cond_state_num');
        b.setFieldValue(c.sensor, 'SRC');
        b.setFieldValue(c.op || '>', 'OP');
        b.setFieldValue(String(c.value), 'VAL');
        return b;
    }
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
            if (a.color === 'rgb') {
                b = createTyped('act_light_rgb');
                b.setFieldValue(String(a.r === undefined ? 255 : a.r), 'R');
                b.setFieldValue(String(a.g === undefined ? 0 : a.g), 'G');
                b.setFieldValue(String(a.b === undefined ? 0 : a.b), 'B');
            } else if (a.color && a.color !== 'white') {
                b = createTyped('act_light_color');
                b.setFieldValue(optionValue(lightColorOptions(), a.color, 'red'), 'COLOR');
            } else {
                b = createTyped('act_light');
                b.setFieldValue(a.status || 'on', 'STATUS');
                b.setFieldValue(String(a.brightness === undefined ? 100 : a.brightness), 'BRIGHTNESS');
            }
            break;
        case 'fan': {
            b = createTyped('act_fan');
            const fanOp = a.op || 'set';
            b.setFieldValue(fanOp, 'OP');
            b.setFieldValue(String(a.speed === undefined ? 60 : a.speed), 'SPEED');
            b.getInput('SPEEDROW').setVisible(fanOp !== 'off');
            break;
        }
        case 'buzzer':
            if (a.mode === 'on' || a.mode === 'off') {
                b = createTyped('act_buzzer_switch');
                b.setFieldValue(a.mode, 'STATE');
            } else {
                b = createTyped('act_buzzer');
                b.setFieldValue(String(a.count === undefined ? 2 : a.count), 'COUNT');
                b.setFieldValue(String(a.on_ms === undefined ? 200 : a.on_ms), 'ONMS');
                b.setFieldValue(String(a.off_ms === undefined ? 200 : a.off_ms), 'OFFMS');
            }
            break;
        case 'ir':
            if (a.code !== undefined && a.code !== null
                && (a.address === undefined || a.command === undefined)) {
                b = createTyped('act_ir_code');
                b.setFieldValue(String(a.code), 'CODE');
            } else {
                b = createTyped('act_ir');
                const hex = '0x' + Number(a.command === undefined ? 0x45 : a.command)
                    .toString(16).toUpperCase().padStart(2, '0');
                b.setFieldValue(optionValue(irKeyOptions(), hex, '0x45'), 'CMD');
            }
            break;
        case 'ac': {
            b = createTyped('act_ac');
            b.setFieldValue(a.power === undefined ? '' : (a.power ? 'on' : 'off'), 'POWER');
            b.setFieldValue(a.mode || '', 'MODE');
            b.setFieldValue(a.temperature === undefined ? '' : Number(a.temperature).toFixed(1), 'TEMP');
            b.setFieldValue(a.fan || '', 'FAN');
            [['SWING_UD', 'swing_ud'], ['SWING_LR', 'swing_lr'],
             ['ECO', 'eco'], ['FZC', 'fzc']].forEach(([field, key]) => {
                b.setFieldValue(a[key] === undefined ? '' : (a[key] ? 'on' : 'off'), field);
            });
            break;
        }
        case 'delay': b = createTyped('act_delay'); b.setFieldValue(String(a.seconds === undefined ? 3 : a.seconds), 'SECONDS'); break;
        case 'wait': {
            const kind = sourceKind(a.sensor);
            if (kind === 'bool') {
                b = createTyped('act_wait_bool');
                b.setFieldValue(a.sensor, 'SRC');
                b.setFieldValue(a.value === true || a.value === 'true' ? 'true' : 'false', 'STATE');
            } else if (kind === 'enum') {
                b = createTyped('act_wait_status');
                b.setFieldValue(`${a.sensor}:${a.value}`, 'PRED');
            } else {
                b = createTyped('act_wait_num');
                b.setFieldValue(a.sensor, 'SRC');
                b.setFieldValue(a.op || '>', 'OP');
                b.setFieldValue(String(a.value), 'VAL');
            }
            b.setFieldValue(String(a.timeout_sec === undefined ? 60 : a.timeout_sec), 'TIMEOUT');
            break;
        }
        case 'oled':
            if (a.clear) {
                b = createTyped('act_oled');
                b.setFieldValue('TRUE', 'CLEAR');
                b.setFieldValue('Temp {temperature}C', 'TEXT');
            } else if (a.line !== undefined && a.line !== null) {
                b = createTyped('act_oled_line');
                b.setFieldValue(String(a.line), 'LINE');
                b.setFieldValue(a.text === undefined ? '' : a.text, 'TEXT');
            } else {
                b = createTyped('act_oled');
                b.setFieldValue('FALSE', 'CLEAR');
                b.setFieldValue(a.text === undefined ? 'Temp {temperature}C' : a.text, 'TEXT');
            }
            break;
        case 'state': {
            // 按变量类型回填到对应积木；变量已被删除时按值类型尽力还原
            const v = (CAPS.state_vars || []).find(x => x.id === a.name);
            const type = v ? v.type
                : (typeof a.value === 'boolean' ? 'bool'
                   : typeof a.value === 'number' ? 'number' : 'enum');
            if (a.op === 'toggle') {
                b = createTyped('act_state_toggle');
                b.setFieldValue(a.name || '', 'NAME');
            } else if (type === 'bool') {
                b = createTyped('act_state_bool');
                b.setFieldValue(a.name || '', 'NAME');
                b.setFieldValue(a.value === false ? 'false' : 'true', 'VALUE');
            } else if (type === 'number') {
                b = createTyped('act_state_num');
                b.setFieldValue(a.name || '', 'NAME');
                b.setFieldValue(a.op === 'add' ? 'add' : 'set', 'OP');
                b.setFieldValue(String(a.value === undefined ? 0 : a.value), 'VAL');
            } else if (type === 'text') {
                b = createTyped('act_state_text');
                b.setFieldValue(a.name || '', 'NAME');
                b.setFieldValue(String(a.value || ''), 'TEXT');
            } else {
                b = createTyped('act_state_enum');
                b.setFieldValue(`${a.name || ''}:${a.value === undefined ? '' : a.value}`, 'PRED');
            }
            break;
        }
        case 'camera': b = createTyped('act_camera'); break;
        case 'voice':
            b = createTyped('act_voice');
            b.setFieldValue(a.action || 'wake', 'ACT');
            b.setFieldValue(a.text || '', 'TEXT');
            break;
        case 'http':
            b = createTyped('act_http');
            b.setFieldValue(a.method || 'post', 'METHOD');
            b.setFieldValue(a.url || '', 'URL');
            b.setFieldValue(a.text || '', 'TEXT');
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

// ==================== 全局状态条目（与规则并列的一种积木条目） ====================

let GS_VARS = [];   // 后端 definitions()：[{id,name,label,type,value,...}]

function gsTypeLabel(t) {
    return stateTypeLabel(t);
}

function gsValueText(v) {
    if (v.type === 'bool') return v.value ? L('是', 'yes') : L('否', 'no');
    if (v.type === 'enum') return (v.choice_labels || {})[v.value] || v.value;
    if (v.type === 'number') return `${v.value}${v.unit ? ' ' + esc(v.unit) : ''}`;
    return String(v.value || '') || L('（空）', '(empty)');
}

// 状态条目卡片：只显示当前值和「最后一次是谁写的」，不放手动改值控件——
// 值归积木规则维护，要改值就改这条定义或写一条规则。
function stateCardHtml(v, i) {
    const choices = v.type === 'enum' && (v.choices || []).length
        ? `<span>${L('选项 ', 'Options ')}${esc(v.choices.map(c => (v.choice_labels || {})[c] || c).join(' / '))}</span>`
        : '';
    return `<div class="rule-card state-card" data-kind="state" data-index="${i}">
      <div class="rc-icon state">📌</div>
      <div class="rc-main">
        <div class="rc-name">${esc(v.label || v.name)}<span class="gs-type">${gsTypeLabel(v.type)}</span></div>
        <div class="rc-sub">${L('当前值 ', 'Current value ')}<b class="gs-value">${esc(gsValueText(v))}</b></div>
        <div class="rc-meta">
          <span class="badge state">${L('全局状态', 'Global state')}</span>
          <span>${esc(v.source || '')}${v.updated_at ? ' · ' + esc(String(v.updated_at).slice(5, 16)) : ''}</span>
          ${choices}
        </div>
      </div>
      <div class="rc-actions">
        <button class="icon-btn" data-act="menu" title="${L('更多', 'More')}">⋮</button>
      </div>
    </div>`;
}

async function loadGlobalState() {
    try {
        const data = await api('/api/automation/global_state');
        GS_VARS = data.vars || [];
    } catch (e) { return; }
    refreshListViews();
}

function afterGsChange(r) {
    if (r && r.vars) GS_VARS = r.vars;
    refreshListViews();
    // 积木下拉在 init 时读 CAPS：刷新能力清单，新状态立刻可被新拖出的积木选到
    api('/api/automation/capabilities')
        .then(c => { CAPS = c; })
        .catch(() => {});
}

async function deleteGlobalVar(i) {
    const v = GS_VARS[i];
    if (!v) return;
    if (!confirm(`${L('删除全局状态「', 'Delete global state "')}${v.label || v.name}${L('」？引用它的规则条件将不再成立。', '" ? Rules referencing it will no longer match.')}`)) return;
    try {
        const r = await api(`/api/automation/global_state/${encodeURIComponent(v.id)}`,
                            { method: 'DELETE' });
        afterGsChange(r);
        showNotification(r.message || L('已删除', 'Deleted'), 'success');
    } catch (e) { showNotification(e.message, 'error'); }
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
        iv.value = cfg.interval || 15;
        if (st) st.textContent = cfg.enabled ? L('✅ 已开，每 ', '✅ On, every ') + (cfg.interval || 15) + L(' 秒切页', 's/page') : L('⏸ 已关闭', '⏸ Off');
    } catch (e) {
        if (st) st.textContent = L('接口暂不可用（引擎未启动）', 'API unavailable (engine not running)');
    }
}

async function saveOledConfig() {
    const iv = document.getElementById('oledInterval');
    const body = {
        enabled: !!document.getElementById('oledEnabled').checked,
        interval: Math.max(15, Number(iv.value) || 15),
    };
    try {
        const r = await api('/api/automation/oled', {
            method: 'PUT', body: JSON.stringify(body),
        });
        const st = document.getElementById('oledStatus');
        if (st) st.textContent = r.config.enabled ? L('✅ 已开启，每 ', '✅ On, every ') + r.config.interval + L(' 秒切页', 's/page') : L('⏸ 已关闭', '⏸ Off');
        showNotification(r.message || L('OLED 轮播配置已保存', 'OLED carousel config saved'), 'success');
    } catch (e) {
        showNotification(e.message, 'error');
    }
}

// ==================== 实时状态 & 执行记录 ====================

async function refreshPreview() {
    try {
        const data = await api('/api/automation/preview');
        PREVIEW = {};
        for (const p of (data.preview || [])) PREVIEW[p.id] = p;
    } catch (e) { return; }
    refreshListViews();
}

// 列表页两堆卡片一起刷新；编辑器开着或正在内联重命名时不动，避免打断操作
function refreshListViews() {
    if (document.getElementById('editorView').classList.contains('hidden') && !RENAMING) {
        renderRuleList();
    }
}

async function refreshLogs() {
    let data;
    try {
        data = await api('/api/automation/logs?limit=20');
    } catch (e) { return; }
    const tbody = document.getElementById('autoLogBody');
    if (!tbody) return;
    tbody.innerHTML = (data.logs || []).map(r => {
        const icon = r.success ? '✅' : (r.triggered ? '⚠️' : '•');
        const when = serverDate(r.timestamp);
        const ts = when ? when.toLocaleString(I18N.currentLang === 'zh' ? 'zh-CN' : 'en-US') : '';
        return `<tr><td>${esc(ts)}</td><td>${esc(r.rule_name)}</td>` +
               `<td>${icon} ${esc(r.reason || '')}<br>` +
               `<span style="color:var(--text-muted)">${r.conditions_hold ? L('走「那么」', 'then branch') : L('走「否则」', 'else branch')}</span></td></tr>`;
    }).join('');
}

// ==================== 启动 ====================

async function reloadRules() {
    const data = await api('/api/automation/rules');
    RULES = data.rules || [];
    GATING_PRESETS = data.gating_presets || [];
    await refreshPreview();
    renderRuleList();
    // 旧规则迁移提示（后端只在迁移后的首个拉带给一次）
    const m = data.migration;
    if (m) {
        const bits = [];
        if (m.migrated) bits.push(`${L('已自动改写 ', 'Rewrote ')}${m.migrated}${L(' 条', ' item(s)')}`);
        if ((m.dropped || []).length) bits.push(`${L('删除 ', 'Removed ')}${m.dropped.length}${L(' 条无法映射的（原文件已备份）', ' unmappable item(s) (original file backed up)')}`);
        if ((m.invalid || []).length) bits.push(`${L('跳过 ', 'Skipped ')}${m.invalid.length}${L(' 条不合法的', ' invalid item(s)')}`);
        showNotification(`${L('旧规则迁移到全局状态：', 'Migrated old rules to global states: ')}${bits.join('，') || L('完成', 'Done')}${L('。可在执行记录/备份文件里核对', '. Check the run log / backup file to verify.')}`, 'info');
    }
}

async function boot() {
    CAPS = await api('/api/automation/capabilities');
    defineBlocks();

    // 卡片点击（事件委托，只需绑定一次）
    const grid = document.getElementById('ruleGrid');
    grid.addEventListener('click', (ev) => {
        const card = ev.target.closest('.rule-card');
        if (!card) return;
        const kind = card.dataset.kind || 'rule';
        const i = Number(card.dataset.index);
        if (ev.target.closest('[data-act="run"]')) { runRule(RULES[i] && RULES[i].id); return; }
        if (ev.target.closest('[data-act="menu"]')) {
            openCardMenu(kind, i, ev.target.closest('[data-act="menu"]'));
            return;
        }
        if (kind === 'state') openStateEditor(i); else openEditor(i);
    });

    // ⋮ 菜单点击
    document.getElementById('cardMenu').addEventListener('click', (ev) => {
        const btn = ev.target.closest('button[data-m]');
        if (!btn || MENU_INDEX < 0) return;
        const idx = MENU_INDEX;
        closeCardMenu();
        cardMenuAction(btn.dataset.m, idx);
    });

    // 点空白处 / 滚动 / Esc 关闭菜单
    document.addEventListener('click', (ev) => {
        if (!ev.target.closest('#cardMenu') && !ev.target.closest('[data-act="menu"]')) closeCardMenu();
    });
    window.addEventListener('scroll', closeCardMenu, true);
    document.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape') {
            closeCardMenu();
            if (!document.getElementById('editorView').classList.contains('hidden')) closeEditor();
        }
    });

    // 窗口尺寸变化时重排画布
    window.addEventListener('resize', () => {
        if (workspace) Blockly.svgResize(workspace);
    });

    await reloadRules();
    loadGlobalState();
    loadOledConfig();
    refreshLogs();
    setInterval(refreshLogs, 5000);
    setInterval(loadGlobalState, 5000);
    setInterval(refreshPreview, 10000);
}

// 语言切换：静态文案由 lang.js 处理，这里刷新动态内容与积木工作区
document.addEventListener('i18n:changed', () => {
    if (typeof CAPS === 'undefined' || !CAPS) return;
    renderRuleList();
    loadGlobalState();
    loadOledConfig();
    refreshLogs();
    if (workspace) {
        const editorOpen = !document.getElementById('editorView').classList.contains('hidden');
        let snapshot = editingRule ? JSON.parse(JSON.stringify(editingRule)) : null;
        if (editorOpen) { try { snapshot = collectEditor(); } catch (e) { /* 保留上次快照 */ } }
        workspace.dispose();
        workspace = null;
        if (editorOpen && snapshot) { editingRule = snapshot; showEditor(); }
    }
});

// 时钟（与其他页面一致）
setInterval(() => {
    const el = document.getElementById('currentTime');
    if (el) el.textContent = new Date().toLocaleTimeString(isEN() ? 'en-GB' : 'zh-CN', { hour12: false });
}, 1000);

document.addEventListener('DOMContentLoaded', () => {
    if (typeof Blockly === 'undefined') {
        document.getElementById('blocklyMissing')?.classList.remove('hidden');
        const grid = document.getElementById('ruleGrid');
        if (grid) grid.innerHTML = L('<div class="empty-rules">积木引擎加载失败，请 Ctrl+F5 强制刷新。</div>', '<div class="empty-rules">Blockly engine failed to load. Press Ctrl+F5 to force refresh.</div>');
        return;
    }
    boot().catch(e => showNotification(L('初始化失败：', 'Init failed: ') + e.message, 'error'));
});

/* 自动化规则（iOS 快捷指令式交互）
 * 视图一：规则列表 —— 每条规则一张卡片，卡片自带 ⋮ 菜单（运行/编辑/重命名/复制/停用/删除）
 * 视图二：单条规则编辑器 —— 画布中只放当前这一条规则，左侧工具箱拖积木
 * 数据源始终是后端规则 JSON（GET/PUT /api/automation/rules，PUT 为整表替换）。
 */
'use strict';

let workspace = null;      // Blockly 工作区（懒加载，只在编辑器视图里创建）
let CAPS = null;           // 后端能力清单
let RULES = [];            // 全量规则（唯一数据源）
let PREVIEW = {};          // rule_id -> preview 条目（卡片上的实时状态）
let editingIndex = -1;     // 正在编辑的规则在 RULES 中的下标（-1=新规则）
let editingRule = null;    // 正在编辑的规则副本
let DIRTY = false;         // 编辑器是否有未保存改动
let LOADING = false;       // 正在程序化灌积木（忽略 change 事件）
let SAVE_PENDING = false;
let MENU_INDEX = -1;       // ⋮ 菜单当前作用的卡片下标
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

// 灯的颜色预设（B 板 8 颗 WS2812 整条同色）
const LIGHT_COLORS = [['红', 'red'], ['绿', 'green'], ['蓝', 'blue'],
                      ['黄', 'yellow'], ['紫', 'purple'], ['青', 'cyan']];

// 触发块共用的「持续 N 秒」（0 = 跨阈值立刻触发）
function appendHoldInput(block) {
    block.appendDummyInput()
        .appendField('持续')
        .appendField(new Blockly.FieldNumber(0, 0, 86400, 1), 'HOLD')
        .appendField('秒');
}

function defineBlocks() {
    // ── 规则容器（Scratch 式短标签：当 / 如果 / 那么 / 否则）──
    Blockly.Blocks['rule_block'] = {
        init: function () {
            this.appendDummyInput()
                .appendField('🧩')
                .appendField(new Blockly.FieldTextInput('新规则'), 'NAME')
                .appendField(new Blockly.FieldCheckbox('TRUE'), 'ENABLED');
            this.appendStatementInput('TRIGGER').setCheck('TRIG').appendField('当');
            this.appendDummyInput()
                .appendField('如果')
                .appendField(new Blockly.FieldDropdown([
                    ['全部满足', 'all'], ['任一满足', 'any']]), 'MATCH');
            this.appendStatementInput('CONDS').setCheck('COND');
            this.appendStatementInput('DO').setCheck('ACT').appendField('那么');
            this.appendStatementInput('ELSE').setCheck('ACT').appendField('否则');
            this.appendDummyInput()
                .appendField('冷却')
                .appendField(new Blockly.FieldNumber(3, 0, 3600, 1), 'COOLDOWN')
                .appendField('秒');
            this.setColour(265);
            this.setTooltip('一条规则 = 当触发 → 如果条件 → 那么执行（否则可留空）');
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
            appendHoldInput(this);
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
            this.setTooltip('跨过阈值瞬间触发；「持续 N 秒」用于逗留报警这类需连续保持的场景');
        },
    };

    // ── 触发：布尔传感器 ──
    Blockly.Blocks['trig_bool'] = {
        init: function () {
            this.appendDummyInput()
                .appendField('当')
                .appendField(new Blockly.FieldDropdown(boolSourceOptions), 'SRC')
                .appendField(new Blockly.FieldDropdown([
                    ['变为是', 'true'], ['变为否', 'false']]), 'STATE');
            appendHoldInput(this);
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
            this.setTooltip('状态变化时触发；配「否则」动作后，恢复（如雨停）会走否则分支');
        },
    };

    // ── 触发：设备状态 ──
    Blockly.Blocks['trig_status'] = {
        init: function () {
            this.appendDummyInput()
                .appendField('当')
                .appendField(new Blockly.FieldDropdown(statusOptions), 'PRED');
            appendHoldInput(this);
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
        },
    };

    // ── 触发：事件 ──
    Blockly.Blocks['trig_event'] = {
        init: function () {
            this.appendDummyInput()
                .appendField('当')
                .appendField(new Blockly.FieldDropdown(eventOptions), 'EVT');
            this.appendDummyInput()
                .appendField('键盘')
                .appendField(new Blockly.FieldDropdown(keypadOptions), 'KEY')
                .appendField('红外')
                .appendField(new Blockly.FieldDropdown(irKeyOptions), 'CMD');
            // RFID 卡号用文本框（下拉会静默回落）；不填 = 任意卡片都触发
            this.appendDummyInput()
                .appendField('卡号')
                .appendField(new Blockly.FieldTextInput(''), 'UID');
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
            this.setTooltip('人体/人脸/键盘/红外/RFID 等事件；只取与所选事件对应的参数（卡号留空=任意卡片）');
        },
    };

    // ── 触发：周期/定时 ──
    Blockly.Blocks['trig_interval'] = {
        init: function () {
            this.appendDummyInput()
                .appendField('每隔')
                .appendField(new Blockly.FieldNumber(10, 2, 86400, 1), 'SECONDS')
                .appendField('秒');
            this.setPreviousStatement(true, 'TRIG');
            this.setNextStatement(false);
            this.setColour(30);
        },
    };
    Blockly.Blocks['trig_time'] = {
        init: function () {
            this.appendDummyInput()
                .appendField('每天')
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
            this.appendDummyInput().appendField('🪟 窗')
                .appendField(new Blockly.FieldDropdown(
                    [['打开', 'open'], ['关闭', 'close'], ['半开', 'normal']]), 'STATUS');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    Blockly.Blocks['act_light'] = {
        init: function () {
            this.appendDummyInput().appendField('💡 灯')
                .appendField(new Blockly.FieldDropdown([['打开', 'on'], ['关闭', 'off']]), 'STATUS')
                .appendField(new Blockly.FieldNumber(100, 0, 100, 1), 'BRIGHTNESS')
                .appendField('%');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip('白光，亮度按百分比；关灯时忽略亮度');
        },
    };
    // 彩色预设（B 板 8 颗 WS2812 整条同色；彩色不接受亮度参数）
    Blockly.Blocks['act_light_color'] = {
        init: function () {
            this.appendDummyInput().appendField('🎨 灯颜色')
                .appendField(new Blockly.FieldDropdown(LIGHT_COLORS), 'COLOR');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip('整条灯带换成指定颜色（满亮）');
        },
    };
    Blockly.Blocks['act_light_rgb'] = {
        init: function () {
            this.appendDummyInput().appendField('🎨 灯 RGB')
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
                ['设置转速', 'set'], ['开启', 'on'], ['关闭', 'off'],
                ['切换开/关（同一键再按一次反转）', 'toggle']]);
            this.appendDummyInput().appendField('🌀 风扇').appendField(opField, 'OP');
            this.appendDummyInput('SPEEDROW')
                .appendField('转速').appendField(new Blockly.FieldNumber(60, 0, 100, 1), 'SPEED')
                .appendField('%（填 0 = 用上次转速）');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip('切换开/关：同一个触发（如遥控器同一个键）按一次开、再按关。');
            // 关闭动作不需要转速，隐藏转速行
            opField.setValidator((v) => {
                this.getInput('SPEEDROW').setVisible(v !== 'off');
                return v;
            });
        },
    };
    Blockly.Blocks['act_buzzer'] = {
        init: function () {
            this.appendDummyInput().appendField('🔔 响')
                .appendField(new Blockly.FieldNumber(2, 1, 10, 1), 'COUNT').appendField('声')
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
            this.appendDummyInput().appendField('🔔 蜂鸣器')
                .appendField(new Blockly.FieldDropdown([['持续响', 'on'], ['停', 'off']]), 'STATE');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip('持续响会一直叫到被「停」或断电，注意别把规则写成自激');
        },
    };
    Blockly.Blocks['act_delay'] = {
        init: function () {
            this.appendDummyInput().appendField('⏳ 等')
                .appendField(new Blockly.FieldNumber(3, 1, 300, 1), 'SECONDS')
                .appendField('秒');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    Blockly.Blocks['act_oled'] = {
        init: function () {
            // OLED 字库只有 ASCII：文案用英文/数字
            this.appendDummyInput().appendField('🖥️ OLED')
                .appendField(new Blockly.FieldTextInput('Temp {temperature}C'), 'TEXT');
            this.appendDummyInput()
                .appendField(new Blockly.FieldCheckbox('FALSE'), 'CLEAR')
                .appendField('清屏');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
        },
    };
    // 指定行直发（不按换行拆分），一行只能放一行文本
    Blockly.Blocks['act_oled_line'] = {
        init: function () {
            this.appendDummyInput().appendField('🖥️ OLED 第')
                .appendField(new Blockly.FieldNumber(0, 0, 7, 1), 'LINE')
                .appendField('行')
                .appendField(new Blockly.FieldTextInput('Temp {temperature}C'), 'TEXT');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip('只写这一行（0-7），其余行不动；文本里可用 {temperature} 等占位符');
        },
    };
    // 红外发射：直接选键位（复用 A 板实测的 NEC 键码表），或填自定义 32 位码
    Blockly.Blocks['act_ir'] = {
        init: function () {
            this.appendDummyInput().appendField('📡 红外发射')
                .appendField(new Blockly.FieldDropdown(irKeyOptions), 'CMD');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip('等价于「按下遥控器这个键」；本系统不支持红外自学习/回环转发');
        },
    };
    Blockly.Blocks['act_ir_code'] = {
        init: function () {
            this.appendDummyInput().appendField('📡 红外发射 自定义码')
                .appendField(new Blockly.FieldNumber(16729530, 0, 4294967295, 1), 'CODE');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip('十进制 32 位 NEC 码（bit31 先发，不是 LSB-first 那套值）');
        },
    };
    // 空调（美的红外）：每项都能选"不改"，只下发选过的项
    Blockly.Blocks['act_ac'] = {
        init: function () {
            this.appendDummyInput()
                .appendField('❄️ 空调')
                .appendField(new Blockly.FieldDropdown(AC_SWITCH_OPTIONS), 'POWER');
            this.appendDummyInput()
                .appendField('模式')
                .appendField(new Blockly.FieldDropdown(AC_MODE_OPTIONS), 'MODE')
                .appendField('温度')
                .appendField(new Blockly.FieldDropdown(acTempOptions), 'TEMP')
                .appendField('风速')
                .appendField(new Blockly.FieldDropdown(AC_FAN_OPTIONS), 'FAN');
            this.appendDummyInput()
                .appendField('上下')
                .appendField(new Blockly.FieldDropdown(AC_SWITCH_OPTIONS), 'SWING_UD')
                .appendField('左右')
                .appendField(new Blockly.FieldDropdown(AC_SWITCH_OPTIONS), 'SWING_LR');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip('美的空调红外遥控。"不改"的项保持原设定；'
                + '未开机时给温度/模式/风速会自动先开机');
        },
    };
    // 全屋模式：进门切自动 / 触摸切手动 / 红外循环档位
    Blockly.Blocks['act_home_mode'] = {
        init: function () {
            this.appendDummyInput().appendField('🏠 模式')
                .appendField(new Blockly.FieldDropdown([
                    ['不改', ''], ['自动', 'auto'],
                    ['手动', 'manual'], ['离家', 'away'],
                    ['翻转', 'toggle']]), 'MODE');
            this.appendDummyInput().appendField('风扇')
                .appendField(new Blockly.FieldDropdown([
                    ['不改', ''], ['开', 'on'],
                    ['关', 'off'], ['自动', 'auto'],
                    ['循环', 'cycle']]), 'FAN');
            this.appendDummyInput().appendField('灯光')
                .appendField(new Blockly.FieldDropdown([
                    ['不改', ''], ['自动', 'auto'], ['保持', 'hold'],
                    ['暗', 'dark'], ['半亮', 'half'], ['全亮', 'bright'],
                    ['循环', 'cycle']]), 'LIGHT');
            // 状态机自身参数：勾选才生效（避免 0 秒被当成「不改」）
            this.appendDummyInput()
                .appendField(new Blockly.FieldCheckbox('FALSE'), 'SET_ENABLED')
                .appendField('自动调节')
                .appendField(new Blockly.FieldDropdown([['开', 'true'], ['关', 'false']]), 'ENABLED');
            this.appendDummyInput()
                .appendField(new Blockly.FieldCheckbox('FALSE'), 'SET_HOLD')
                .appendField('存在判定保持')
                .appendField(new Blockly.FieldNumber(1200, 0, 86400, 60), 'HOLD')
                .appendField('秒');
            this.appendDummyInput()
                .appendField(new Blockly.FieldCheckbox('FALSE'), 'SET_GRACE')
                .appendField('手动冷却')
                .appendField(new Blockly.FieldNumber(30, 1, 3600, 1), 'GRACE')
                .appendField('秒');
            this.setPreviousStatement(true, 'ACT');
            this.setNextStatement(true, 'ACT');
            this.setColour(120);
            this.setTooltip('只改非「不改」的项；离线也能生效（纯状态机，不碰硬件）');
        },
    };
    // 语音联动：按键触发后免唤醒词直接说话
    Blockly.Blocks['act_voice'] = {
        init: function () {
            this.appendDummyInput().appendField('🎙️ 语音')
                .appendField(new Blockly.FieldDropdown([
                    ['唤醒', 'wake'], ['播报', 'say']]), 'ACT');
            this.appendDummyInput().appendField(new Blockly.FieldTextInput(''), 'TEXT');
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
            const label = (s.choice_labels || {})[choice] || choice;
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
    return opts.length ? opts : [['1（0x45）', '0x45']];
}
// 下拉里没有该值时退回默认，避免 setFieldValue 静默失败
function optionValue(options, value, fallback) {
    return options.some(o => o[1] === value) ? value : fallback;
}

// 空调积木下拉：值与后端 midea_ac.apply_overrides 的取值一致，空串 = 该项不改
const AC_SWITCH_OPTIONS = [['不改', ''], ['开', 'on'], ['关', 'off']];
const AC_MODE_OPTIONS = [['不改', ''], ['自动', 'auto'], ['制冷', 'cool'],
                         ['制热', 'heat'], ['抽湿', 'dry'], ['送风', 'fan']];
const AC_FAN_OPTIONS = [['不改', ''], ['自动', 'auto'], ['低', 'low'],
                        ['中', 'mid'], ['高', 'high']];
function acTempOptions() {
    // 真遥控器 RN02G(X) 只有整数度，没有半度档
    const opts = [['不改', '']];
    for (let t = 17; t <= 30; t += 1) {
        opts.push([t + '°C', String(t)]);
    }
    return opts;
}

// ==================== 工具箱 & 主题 ====================

function buildToolbox() {
    const num = numSourceOptions();
    const bool = boolSourceOptions();
    const evt = eventOptions();
    return `<xml>
      <category name="规则" colour="265">
        <block type="rule_block"></block>
      </category>
      <category name="触发" colour="30">
        <block type="trig_num">
          <field name="SRC">${num[0][1]}</field><field name="OP">&gt;</field><field name="VAL">30</field>
        </block>
        <block type="trig_bool"><field name="SRC">${bool[0][1]}</field><field name="STATE">true</field></block>
        <block type="trig_status"></block>
        <block type="trig_event"><field name="EVT">${evt[0][1]}</field></block>
        <block type="trig_interval"><field name="SECONDS">10</field></block>
        <block type="trig_time"><field name="TIME">08:00</field></block>
      </category>
      <category name="条件" colour="190">
        <block type="cond_num">
          <field name="SRC">${num[0][1]}</field><field name="OP">&gt;</field><field name="VAL">30</field>
        </block>
        <block type="cond_bool"><field name="SRC">${bool[0][1]}</field><field name="STATE">true</field></block>
        <block type="cond_status"></block>
      </category>
      <category name="动作" colour="120">
        <block type="act_door"></block>
        <block type="act_window"></block>
        <block type="act_light"></block>
        <block type="act_light_color"></block>
        <block type="act_light_rgb"></block>
        <block type="act_fan"></block>
        <block type="act_ac"></block>
        <block type="act_home_mode"></block>
        <block type="act_voice"></block>
        <block type="act_ir"></block>
        <block type="act_ir_code"></block>
        <block type="act_buzzer"></block>
        <block type="act_buzzer_switch"></block>
        <block type="act_oled"></block>
        <block type="act_oled_line"></block>
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

// ==================== 卡片摘要文案 ====================

const SENSOR_ICONS = {
    temperature: '🌡️', humidity: '💧', light: '☀️', smoke: '💨', rain: '🌧️',
    touch: '👆', motion: '🚶', door_status: '🚪', window_status: '🪟',
    home_mode: '🏠', person_present: '👤', light_status: '💡', fan_speed: '🌀',
};

function triggerIcon(trig) {
    if (!trig) return '❓';
    if (trig.kind === 'event') return '🔔';
    if (trig.kind === 'interval') return '⏱️';
    if (trig.kind === 'time') return '🕐';
    return SENSOR_ICONS[trig.sensor] || '📈';
}

function triggerKindClass(trig) {
    if (!trig) return 'sensor';
    if (trig.kind === 'event') return 'evt';
    if (trig.kind === 'interval' || trig.kind === 'time') return 'time';
    return 'sensor';
}

function summarizeTrigger(t) {
    if (!t || !t.kind) return '（未设置触发）';
    if (t.kind === 'interval') return `每隔 ${t.seconds} 秒`;
    if (t.kind === 'time') return `每天 ${t.hhmm}`;
    if (t.kind === 'event') {
        const e = CAPS.events.find(x => x.id === t.event);
        let label = e ? e.label : t.event;
        if (t.key) label += ` · 键 ${t.key}`;
        if (t.command) {
            const c = ((e && e.choices) || []).find(x => x.id === t.command);
            label += ` · ${c ? c.label : t.command}`;
        }
        if (t.uid) label += ` · 卡 ${t.uid}`;
        return label;
    }
    const s = CAPS.sources.find(x => x.id === t.sensor);
    const label = s ? s.label : t.sensor;
    const hold = t.hold_sec ? `（持续 ${t.hold_sec}s）` : '';
    if (s && s.kind === 'enum') {
        return `${label} = ${(s.choice_labels || {})[t.value] || t.value}${hold}`;
    }
    if (s && s.kind === 'bool') {
        return `${label} = ${(t.value === true || t.value === 'true') ? '是' : '否'}${hold}`;
    }
    const op = (CAPS.comparators.find(c => c.id === t.op) || {}).label || t.op;
    return `${label} ${op} ${t.value}${(s && s.unit) ? s.unit : ''}${hold}`;
}

function summarizeAction(a) {
    if (!a) return '';
    switch (a.device) {
        case 'door':   return a.status === 'open' ? '开门' : '关门';
        case 'window': return '窗' + ({ open: '打开', close: '关闭', normal: '半开' }[a.status] || '');
        case 'light': {
            if (a.color === 'rgb') return `灯 RGB(${a.r},${a.g},${a.b})`;
            if (a.color && a.color !== 'white') {
                const c = LIGHT_COLORS.find(x => x[1] === a.color);
                return '灯 ' + (c ? c[0] : a.color);
            }
            return '灯' + (a.status === 'on' ? '开' : '关')
                   + (a.brightness !== undefined ? ` ${a.brightness}%` : '');
        }
        case 'fan': {
            const fanOp = a.op || 'set';
            const fanAt = Number(a.speed) > 0 ? `${a.speed}%` : '上次转速';
            if (fanOp === 'off') return '风扇 关闭';
            if (fanOp === 'on') return `风扇 开启 ${fanAt}`;
            if (fanOp === 'toggle') return `风扇 切换开/关（开时 ${fanAt}）`;
            return `风扇 ${a.speed}%`;
        }
        case 'buzzer':
            if (a.mode === 'on') return '蜂鸣器 持续响';
            if (a.mode === 'off') return '蜂鸣器 停';
            return `蜂鸣 ${a.count} 声`;
        case 'delay':  return `等待 ${a.seconds}s`;
        case 'oled':
            if (a.clear) return 'OLED 清屏';
            return (a.line === undefined || a.line === null)
                ? 'OLED 显示' : `OLED 第${a.line}行`;
        case 'ac': {
            const bits = [];
            if (a.power !== undefined) bits.push(a.power ? '开机' : '关机');
            if (a.mode) {
                bits.push({ auto: '自动', cool: '制冷', heat: '制热',
                            dry: '抽湿', fan: '送风' }[a.mode] || a.mode);
            }
            if (a.temperature !== undefined) bits.push(a.temperature + '°C');
            if (a.fan) bits.push('风' + ({ auto: '自动', low: '低', mid: '中', high: '高' }[a.fan] || a.fan));
            if (a.swing_ud) bits.push('上下扫风');
            if (a.swing_lr) bits.push('左右扫风');
            return '空调' + (bits.length ? ' ' + bits.join(' ') : '');
        }
        case 'ir': {
            if (a.address !== undefined && a.command !== undefined) {
                const hex = '0x' + Number(a.command).toString(16).toUpperCase().padStart(2, '0');
                const k = irKeyOptions().find(x => x[1] === hex);
                return '红外发射 ' + (k ? k[0] : hex);
            }
            return `红外发射 ${a.code}`;
        }
        case 'home_mode': {
            const bits = [];
            if (a.mode) bits.push('模式');
            if (a.fan_override) bits.push('风扇档');
            if (a.light_level) bits.push('灯光档');
            if (a.enabled !== undefined) bits.push('自动调节');
            if (a.presence_hold_sec !== undefined) bits.push('存在判定');
            if (a.manual_grace_s !== undefined) bits.push('手动冷却');
            return '全屋' + (bits.length ? '（' + bits.join('/') + '）' : '');
        }
        case 'voice':  return a.action === 'say' ? '语音播报' : '唤醒语音';
        default:       return a.device;
    }
}

function summarizeActions(actions) {
    const list = actions || [];
    if (!list.length) return '（无动作）';
    const first = summarizeAction(list[0]);
    return list.length > 1 ? `${first} 等 ${list.length} 项` : first;
}

// ==================== 视图切换 ====================

function showEditor() {
    document.getElementById('listView').classList.add('hidden');
    document.getElementById('editorView').classList.remove('hidden');
    if (!workspace) initWorkspace();
    Blockly.svgResize(workspace);
    workspace.clear();
    LOADING = true;
    const trig = (editingRule.trigger && editingRule.trigger.kind)
        ? editingRule.trigger
        : { kind: 'sensor', sensor: 'temperature', op: '>', value: 30 };
    buildRuleBlock(Object.assign({}, editingRule, { trigger: trig }));
    document.getElementById('editorName').value = editingRule.name || '新规则';
    document.getElementById('editorEnabled').checked = editingRule.enabled !== false;
    LOADING = false;
    DIRTY = false;
    setTimeout(() => { fitWorkspace(); Blockly.svgResize(workspace); }, 60);
}

function closeEditor() {
    if (DIRTY && !confirm('这条规则有未保存的修改，确定放弃？')) return;
    document.getElementById('editorView').classList.add('hidden');
    document.getElementById('listView').classList.remove('hidden');
    editingIndex = -1;
    editingRule = null;
    DIRTY = false;
    refreshPreview();
}

// ==================== 规则列表 ====================

function renderRuleList() {
    const grid = document.getElementById('ruleGrid');
    const count = document.getElementById('ruleCount');
    if (count) count.textContent = `共 ${RULES.length} 条`;
    if (!grid) return;
    if (!RULES.length) {
        grid.innerHTML = '<div class="empty-rules">还没有规则，点右上角「＋ 新建规则」开始。</div>';
        return;
    }
    grid.innerHTML = RULES.map(ruleCardHtml).join('');
}

function ruleCardHtml(r, i) {
    const trig = r.trigger;
    const pv = r.id ? PREVIEW[r.id] : null;
    let statusBadge = '';
    if (r.enabled === false) statusBadge = '<span class="badge disabled">已停用</span>';
    else if (pv && pv.trigger_now === true) statusBadge = '<span class="badge on">条件成立</span>';
    else if (pv && pv.trigger_now === false) statusBadge = '<span class="badge off">未成立</span>';
    else if (pv) statusBadge = '<span class="badge evt">事件驱动</span>';
    const nCond = (r.conditions || []).length;
    const nAct = (r.actions || []).length;
    return `<div class="rule-card ${r.enabled === false ? 'disabled' : ''}" data-index="${i}">
      <div class="rc-icon ${triggerKindClass(trig)}">${triggerIcon(trig)}</div>
      <div class="rc-main">
        <div class="rc-name">${esc(r.name)}</div>
        <div class="rc-sub">当 ${esc(summarizeTrigger(trig))} → ${esc(summarizeActions(r.actions))}</div>
        <div class="rc-meta">
          ${statusBadge}
          ${r.preset ? '<span class="badge evt">内置</span>' : ''}
          <span>${nCond ? nCond + ' 条件' : '无条件'}</span>
          <span>${nAct} 动作</span>
          <span>冷却 ${r.cooldown === undefined ? 3 : r.cooldown}s</span>
        </div>
      </div>
      <div class="rc-actions">
        <button class="icon-btn" data-act="run" title="运行一次"${r.id ? '' : ' disabled'}>▶</button>
        <button class="icon-btn" data-act="menu" title="更多">⋮</button>
      </div>
    </div>`;
}

// ---- 卡片 ⋮ 菜单 ----

function openCardMenu(i, btn) {
    MENU_INDEX = i;
    const r = RULES[i];
    const menu = document.getElementById('cardMenu');
    menu.innerHTML =
        `<button data-m="run"${r.id ? '' : ' disabled'}>▶ 运行一次</button>` +
        '<button data-m="edit">✏️ 编辑</button>' +
        '<button data-m="rename">🏷 重命名</button>' +
        '<button data-m="dup">📄 复制</button>' +
        `<button data-m="toggle">${r.enabled === false ? '⏻ 启用' : '⏻ 停用'}</button>` +
        '<div class="sep"></div>' +
        '<button data-m="del" class="danger">🗑 删除</button>';
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
    const r = RULES[i];
    if (!r) return;
    if (m === 'run') return runRule(r.id);
    if (m === 'edit') return openEditor(i);
    if (m === 'rename') return startInlineRename(i);
    if (m === 'dup') return duplicateRule(i);
    if (m === 'toggle') {
        r.enabled = r.enabled === false;
        return persistRules(`已${r.enabled ? '启用' : '停用'}「${r.name}」`);
    }
    if (m === 'del') {
        if (!confirm(`删除规则「${r.name}」？`)) return;
        RULES.splice(i, 1);
        return persistRules(`已删除「${r.name}」`);
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

function createRule() {
    editingIndex = -1;
    editingRule = {
        id: null, name: '新规则', enabled: true,
        trigger: { kind: 'sensor', sensor: 'temperature', op: '>', value: 30 },
        match: 'all', conditions: [],
        actions: [{ device: 'fan', speed: 60 }], else_actions: [], cooldown: 3,
    };
    showEditor();
}

function openEditor(i) {
    editingIndex = i;
    editingRule = JSON.parse(JSON.stringify(RULES[i]));
    showEditor();
}

async function duplicateRule(i) {
    const src = RULES[i];
    const copy = JSON.parse(JSON.stringify(src));
    copy.id = null;
    delete copy.preset;
    copy.name = `${src.name} 副本`;
    RULES.splice(i + 1, 0, copy);
    await persistRules(`已复制「${src.name}」`);
}

function startInlineRename(i) {
    const card = document.querySelector(`.rule-card[data-index="${i}"]`);
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
        await persistRules(`已重命名为「${val}」`);
    };
    input.addEventListener('blur', () => commit(true));
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); commit(true); }
        else if (e.key === 'Escape') { e.preventDefault(); commit(false); }
    });
}

async function runRule(id) {
    if (!id) { showNotification('请先保存这条规则', 'error'); return; }
    try {
        const r = await api(`/api/automation/rules/${encodeURIComponent(id)}/run`, { method: 'POST' });
        showNotification(r.message || '已提交执行', r.ok ? 'success' : 'error');
        setTimeout(refreshLogs, 2500);
    } catch (e) {
        showNotification(e.message, 'error');
    }
}

async function restorePresets() {
    if (!confirm('把被删掉的内置默认规则补回来？（你自己添加或改过的规则不受影响）')) return;
    try {
        const r = await api('/api/automation/rules/restore', { method: 'POST' });
        RULES = r.rules || [];
        await refreshPreview();
        renderRuleList();
        showNotification(r.message || '内置规则已恢复', 'success');
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
    // 规则名称双向同步：画布积木里的 NAME 改了，顶部输入框跟着变
    workspace.addChangeListener((e) => {
        if (!e || !e.blockId) return;
        if (e.name === 'NAME') {
            const b = workspace.getBlockById(e.blockId);
            const inp = document.getElementById('editorName');
            if (b && b.type === 'rule_block' && inp) {
                const v = b.getFieldValue('NAME') || '';
                if (inp.value !== v) inp.value = v;
            }
        }
        if (!LOADING && e.isUiEvent === false) DIRTY = true;
    });
    document.getElementById('fitViewBtn')?.addEventListener('click', fitWorkspace);
    document.getElementById('editorName')?.addEventListener('input', (ev) => {
        const rb = workspace.getTopBlocks(false).find(b => b.type === 'rule_block');
        if (rb) rb.setFieldValue(ev.target.value, 'NAME');
    });
}

// 只编辑一条规则：块贴左上角，超出画布时才缩放
function fitWorkspace() {
    if (!workspace) return;
    const rb = workspace.getTopBlocks(false).find(b => b.type === 'rule_block');
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
    rb.setFieldValue(rule.name || '新规则', 'NAME');
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
    if (!rb) throw new Error('画布里没有规则块');
    const trigBlock = rb.getInputTargetBlock('TRIGGER');
    if (!trigBlock) throw new Error('请先把橙色「当…」触发块放进规则');
    const actions = chainBlocks(rb.getInputTargetBlock('DO')).map(actionToJson).filter(Boolean);
    if (!actions.length) throw new Error('「那么」里至少放 1 个绿色动作块');
    const name = (document.getElementById('editorName').value || '').trim() || '未命名规则';
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
        showNotification(saved.message || '已保存', 'success');
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

function triggerToJson(b) {
    switch (b.type) {
        case 'trig_num':
            return withHold(b, { kind: 'sensor', sensor: b.getFieldValue('SRC'),
                     op: b.getFieldValue('OP'), value: Number(b.getFieldValue('VAL')) });
        case 'trig_bool':
            return withHold(b, { kind: 'sensor', sensor: b.getFieldValue('SRC'),
                     op: '==', value: b.getFieldValue('STATE') === 'true' });
        case 'trig_status': {
            const [sensor, value] = b.getFieldValue('PRED').split(':');
            return withHold(b, { kind: 'sensor', sensor, op: '==', value });
        }
        case 'trig_event': {
            const evt = b.getFieldValue('EVT');
            const json = { kind: 'event', event: evt };
            if (evt === 'keypad') json.key = b.getFieldValue('KEY') || '1';
            if (evt === 'ir') json.command = b.getFieldValue('CMD') || '0x45';
            if (evt === 'rfid') {
                const uid = (b.getFieldValue('UID') || '').trim();
                if (uid) json.uid = uid;      // 留空 = 任意卡片都触发
            }
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
        case 'act_oled':
            if (b.getFieldValue('CLEAR') === 'TRUE') return { device: 'oled', clear: true };
            return { device: 'oled', text: b.getFieldValue('TEXT') };
        case 'act_oled_line':
            return { device: 'oled', line: Number(b.getFieldValue('LINE')),
                     text: b.getFieldValue('TEXT') };
        case 'act_home_mode': {
            const json = { device: 'home_mode' };
            const mode = b.getFieldValue('MODE');
            const fan = b.getFieldValue('FAN');
            const light = b.getFieldValue('LIGHT');
            if (mode) json.mode = mode;
            if (fan) json.fan_override = fan;
            if (light) json.light_level = light;
            // 状态机参数：勾选才写进 JSON（0 秒是合法值，不能用 0 当「不改」）
            if (b.getFieldValue('SET_ENABLED') === 'TRUE') {
                json.enabled = b.getFieldValue('ENABLED') === 'true';
            }
            if (b.getFieldValue('SET_HOLD') === 'TRUE') {
                json.presence_hold_sec = Number(b.getFieldValue('HOLD'));
            }
            if (b.getFieldValue('SET_GRACE') === 'TRUE') {
                json.manual_grace_s = Number(b.getFieldValue('GRACE'));
            }
            return json;
        }
        case 'act_voice': {
            const json = { device: 'voice', action: b.getFieldValue('ACT') || 'wake' };
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
        const b = createTyped('trig_event');
        b.setFieldValue(trig.event, 'EVT');
        if (trig.key) b.setFieldValue(optionValue(keypadOptions(), trig.key, '1'), 'KEY');
        if (trig.command) b.setFieldValue(optionValue(irKeyOptions(), trig.command, '0x45'), 'CMD');
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
                b.setFieldValue(optionValue(LIGHT_COLORS, a.color, 'red'), 'COLOR');
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
        case 'home_mode':
            b = createTyped('act_home_mode');
            b.setFieldValue(a.mode || '', 'MODE');
            b.setFieldValue(a.fan_override || '', 'FAN');
            b.setFieldValue(a.light_level || '', 'LIGHT');
            if (a.enabled !== undefined) {
                b.setFieldValue('TRUE', 'SET_ENABLED');
                b.setFieldValue(a.enabled ? 'true' : 'false', 'ENABLED');
            }
            if (a.presence_hold_sec !== undefined) {
                b.setFieldValue('TRUE', 'SET_HOLD');
                b.setFieldValue(String(a.presence_hold_sec), 'HOLD');
            }
            if (a.manual_grace_s !== undefined) {
                b.setFieldValue('TRUE', 'SET_GRACE');
                b.setFieldValue(String(a.manual_grace_s), 'GRACE');
            }
            break;
        case 'voice':
            b = createTyped('act_voice');
            b.setFieldValue(a.action || 'wake', 'ACT');
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

// ==================== 全屋模式 ====================

let HOME_MODE = null;

const GRACE_LABEL = { light: '💡 灯', fan: '🌀 风扇', window: '🪟 窗', door: '🚪 门' };

function renderManualGrace(graces) {
    const box = document.getElementById('manualGraceChips');
    if (!box) return;
    graces = (graces || []).filter(d => GRACE_LABEL[d]);
    if (!graces.length) {
        box.innerHTML = '<span class="grace-chip empty">无</span>';
        return;
    }
    box.innerHTML = graces.map(d => `<span class="grace-chip">${GRACE_LABEL[d]} 手动优先中</span>`).join('');
}

async function loadHomeMode() {
    try {
        HOME_MODE = await api('/api/automation/home_mode');
    } catch (e) { return; }
    renderManualGrace(HOME_MODE.manual_graces);
    const badge = document.getElementById('homeModeBadge');
    if (!badge) return;
    badge.textContent = '当前模式：' + (HOME_MODE.mode_label || HOME_MODE.mode);
    badge.className = 'mode-badge mode-' + HOME_MODE.mode;
    const fanBtn = document.getElementById('fanOverrideBtn');
    if (fanBtn) {
        if (HOME_MODE.fan_override === 'on') {
            // 历史/API 遗留的「强制开」：硬策略下不会真正开风扇，提示点此取消
            fanBtn.textContent = '🌀 风扇：强制开（点此取消）';
        } else {
            fanBtn.textContent = '🌀 风扇：' + HOME_MODE.fan_label;
        }
    }
    const lightBtn = document.getElementById('lightLevelBtn');
    if (lightBtn) lightBtn.textContent = '💡 灯光：' + HOME_MODE.light_label;
    const detail = document.getElementById('homeModeDetail');
    if (detail) {
        const bits = [];
        if (HOME_MODE.person_present) bits.push('👤 判定有人在家');
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

function cycleFanOverride() {
    // 页面只暴露「自动 ↔ 强制关」两档：没有「强制开」——自动化硬策略禁止
    // 自动开风扇（风扇只能在风扇卡片上手动开）。若档位被 API/积木设成了
    // 历史值「强制开」，点一下回到「自动」。
    const cur = HOME_MODE ? HOME_MODE.fan_override : null;
    const next = cur === 'off' ? null : 'off';
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

// ==================== 实时状态 & 执行记录 ====================

async function refreshPreview() {
    try {
        const data = await api('/api/automation/preview');
        PREVIEW = {};
        for (const p of (data.preview || [])) PREVIEW[p.id] = p;
    } catch (e) { return; }
    // 编辑器视图 / 内联重命名进行中时不刷新列表，避免打断操作
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
        const ts = (r.timestamp || '').replace('T', ' ').slice(0, 19);
        return `<tr><td>${esc(ts)}</td><td>${esc(r.rule_name)}</td>` +
               `<td>${icon} ${esc(r.reason || '')}<br>` +
               `<span style="color:var(--text-muted)">${r.conditions_hold ? '走「那么」' : '走「否则」'}</span></td></tr>`;
    }).join('');
}

// ==================== 启动 ====================

async function reloadRules() {
    const data = await api('/api/automation/rules');
    RULES = data.rules || [];
    await refreshPreview();
    renderRuleList();
}

async function boot() {
    CAPS = await api('/api/automation/capabilities');
    defineBlocks();

    // 卡片点击（事件委托，只需绑定一次）
    const grid = document.getElementById('ruleGrid');
    grid.addEventListener('click', (ev) => {
        const card = ev.target.closest('.rule-card');
        if (!card) return;
        const i = Number(card.dataset.index);
        if (ev.target.closest('[data-act="run"]')) { runRule(RULES[i] && RULES[i].id); return; }
        if (ev.target.closest('[data-act="menu"]')) {
            openCardMenu(i, ev.target.closest('[data-act="menu"]'));
            return;
        }
        openEditor(i);
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
    loadHomeMode();
    loadOledConfig();
    refreshLogs();
    setInterval(refreshLogs, 5000);
    setInterval(loadHomeMode, 5000);
    setInterval(refreshPreview, 10000);
}

// 时钟（与其他页面一致）
setInterval(() => {
    const el = document.getElementById('currentTime');
    if (el) el.textContent = new Date().toLocaleTimeString('zh-CN', { hour12: false });
}, 1000);

document.addEventListener('DOMContentLoaded', () => {
    if (typeof Blockly === 'undefined') {
        document.getElementById('blocklyMissing')?.classList.remove('hidden');
        const grid = document.getElementById('ruleGrid');
        if (grid) grid.innerHTML = '<div class="empty-rules">积木引擎加载失败，请 Ctrl+F5 强制刷新。</div>';
        return;
    }
    boot().catch(e => showNotification('初始化失败：' + e.message, 'error'));
});
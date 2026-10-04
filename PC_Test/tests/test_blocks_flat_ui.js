const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const web = path.join(__dirname, '../web');
const src = fs.readFileSync(path.join(web, 'static/js/automation.js'), 'utf8');

// automation.js 只靠 CAPS（后端能力清单）+ 浏览器宿主对象，积木注册和卡片渲染都能在
// 桩化的 Blockly 之外跑，所以这里只喂一份最小 capabilities fixture。
const CAPS = {
    sources: [
        { id: 'temperature', label: '温度', kind: 'number', unit: '°C' },
        { id: 'light', label: '光照', kind: 'number', unit: '0-1023' },
        { id: 'motion', label: '有人移动', kind: 'bool' },
        { id: 'door_status', label: '门', kind: 'enum', choices: ['open', 'closed'],
          choice_labels: { open: '开', closed: '关' } },
        { id: 'g:有人在家', label: '状态·有人在家', kind: 'bool' },
        { id: 'g:全屋模式', label: '状态·全屋模式', kind: 'enum',
          choices: ['auto', 'manual'], choice_labels: { auto: '自动', manual: '手动' } },
    ],
    events: [{ id: 'touch_on', label: '触摸按下' }],
    comparators: [{ id: '>', label: '大于' }, { id: '<', label: '小于' },
                  { id: '==', label: '等于' }],
    state_vars: [
        { id: 'g:有人在家', label: '有人在家', type: 'bool' },
        { id: 'g:全屋模式', label: '全屋模式', type: 'enum', choices: ['auto', 'manual'],
          choice_labels: { auto: '自动', manual: '手动' } },
    ],
};

function load() {
    const context = vm.createContext({
        console, Date, Math, Set,
        window: { addEventListener() {} },
        document: { addEventListener() {}, getElementById: () => null },
        setInterval: () => 1,
        setTimeout: () => 1,
        fetch: async () => ({ ok: true, json: async () => ({}) }),
    });
    vm.runInContext(src, context);
    vm.runInContext(`CAPS = ${JSON.stringify(CAPS)};`, context);
    return context;
}

test('工具箱只有一层分类，积木不再藏在折叠文件夹里', () => {
    const xml = vm.runInContext('buildToolbox()', load());
    let depth = 0, maxDepth = 0;
    for (const m of xml.matchAll(/<\/?category\b/g)) {
        if (m[0].startsWith('</')) depth -= 1;
        else { depth += 1; maxDepth = Math.max(maxDepth, depth); }
    }
    assert.equal(depth, 0, 'category 标签没有配对');
    assert.equal(maxDepth, 1, '工具箱里仍有多层折叠分类');
});

test('每个已注册积木都能在工具箱直接看到，toolbox 也没有悬空类型', () => {
    const context = load();
    const xml = vm.runInContext('buildToolbox()', context);
    const defined = [...src.matchAll(/Blockly\.Blocks\['([a-z0-9_]+)'\]/g)]
        .map(m => m[1])
        .filter(t => /^(trig_|cond_|act_)/.test(t) || t === 'rule_block');
    const inToolbox = new Set(
        [...xml.matchAll(/<block type="([a-z0-9_]+)"/g)].map(m => m[1]));
    assert.ok(defined.length > 20, `积木定义没抓到（${defined.length} 个）`);
    for (const t of defined) assert.ok(inToolbox.has(t), `${t} 不在工具箱里`);
    for (const t of inToolbox) {
        assert.ok(defined.includes(t) || t === 'state_def', `工具箱引用了未定义的 ${t}`);
    }
});

test('规则卡片摊开显示全部条件与动作，不再折叠成「等 N 项」', () => {
    const context = load();
    const rule = {
        name: '门口有人时开门',
        id: 'r1',
        cooldown: 3,
        match: 'all',
        trigger: { kind: 'sensor', sensor: 'temperature', op: '>', value: 30 },
        conditions: [
            { sensor: 'g:有人在家', op: '==', value: true },
            { sensor: 'light', op: '<', value: 200 },
        ],
        actions: [
            { device: 'door', status: 'open' },
            { device: 'delay', seconds: 10 },
            { device: 'fan', op: 'set', speed: 60 },
        ],
        else_actions: [{ device: 'buzzer', mode: 'off' }],
    };
    const html = vm.runInContext(
        `ruleCardHtml(${JSON.stringify(rule)}, 0)`, context);
    assert.match(html, /class="rc-flow"/);
    for (const text of ['开门', '等待 10s', '风扇 60%']) {
        assert.ok(html.includes(text), `动作「${text}」没显示出来`);
    }
    for (const text of ['有人在家', '光照', '否则', '蜂鸣器 停']) {
        assert.ok(html.includes(text), `条件/否则分支「${text}」没显示出来`);
    }
    assert.ok(!/等 \d+ 项/.test(html), '仍被压成「等 N 项」');
    assert.ok(html.includes('4 动作'), '动作计数应含 else 分支');
    // 条件与动作一条一格，而不是拼成一整串（拼串会被 nowrap 撑出横向滚动）
    const count = (re) => (html.match(re) || []).length;
    assert.equal(count(/class="chip cond"/g), 2, '每条条件应各自成格');
    assert.equal(count(/class="chip act"/g), 4, '每条动作（含否则分支）应各自成格');
    assert.equal(count(/class="chip label"/g), 2, '「如果」「否则」标签应各出现一次');
});

test('卡片条件/动作文本走 esc，规则名带标签也不会注入', () => {
    const context = load();
    const rule = {
        name: '<img src=x>',
        id: 'r2',
        trigger: { kind: 'sensor', sensor: 'temperature', op: '>', value: 1 },
        conditions: [],
        actions: [{ device: 'oled', text: '<script>bad()</script>' }],
    };
    const html = vm.runInContext(`ruleCardHtml(${JSON.stringify(rule)}, 0)`, context);
    assert.ok(!html.includes('<img src=x>'), '规则名未转义');
    assert.ok(!html.includes('<script>bad()'), '动作文本未转义');
});

test('列表页样式给摊开的条目留了换行与滚动，而不是单行截断', () => {
    const html = fs.readFileSync(path.join(web, 'templates/automation.html'), 'utf8');
    const flow = html.match(/\.rc-flow\s*\{[^}]*\}/);
    assert.ok(flow, '缺少 .rc-flow 样式');
    assert.match(flow[0], /flex-wrap:\s*wrap/);
    assert.match(flow[0], /overflow-y:\s*auto/);
});

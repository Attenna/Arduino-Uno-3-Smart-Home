const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function sandbox() {
    const elements = new Map();
    const listeners = new Map();
    const timers = [];
    const posted = [];
    let now = 1000;
    let reply = null;
    const element = id => {
        if (!elements.has(id)) {
            const classes = new Set();
            elements.set(id, {
                value: '', dataset: {}, attrs: {}, textContent: '', disabled: false,
                style: {setProperty() {}},
                classList: {toggle(name, on) { on ? classes.add(name) : classes.delete(name); }, contains: name => classes.has(name)},
                setAttribute(name, value) { this.attrs[name] = value; },
                addEventListener(name, fn) { this[name] = fn; },
                querySelector() { return this.detail || null; },
                replaceChildren() {}, append() {},
            });
        }
        return elements.get(id);
    };
    const controls = ['light', 'fan', 'door', 'window', 'buzzer'].map(device => {
        const button = element(device); button.dataset.wcDevice = device;
        button.detail = element(device + '-detail'); return button;
    });
    const context = vm.createContext({
        console, Date: {now: () => now}, Set, Number, String, Array, JSON, Object, Math,
        document: {getElementById: element, querySelectorAll: () => controls,
            addEventListener: (name, fn) => listeners.set(name, fn),
            createElement: () => element('created'), activeElement: null},
        setInterval: fn => timers.push(fn),
        localStorage: {getItem: () => null, setItem() {}},
        apiGet: async () => [],
        apiPost: async (url, body) => { posted.push({url, body}); return reply; },
        loadStatus: async () => {}, lightStyleFromStatus: () => ({mode: 'white'}),
        showNotification() {}, getMessage: value => value.message,
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/static/js/watercolor-home.js'), 'utf8'), context);
    return {
        element, controls, posted,
        status: detail => listeners.get('status:update')({detail}),
        expire: () => { now += 13000; timers[0](); },
        reply: value => { reply = value; },
        flush: () => new Promise(resolve => setImmediate(resolve)),
    };
}
const online = {output_online: true, sensor_online: true,
    hardware_bridge: {enabled: true, online: true},
    door_status: 'closed', window_status: 'closed', light_status: 'off',
    light_brightness: 0, fan_speed: 0, temperature: 0, humidity: 0};

test('a rejected command cannot animate a closed door open', async () => {
    const ui = sandbox(); ui.status(online);
    ui.element('door').click();
    assert.equal(ui.element('door').disabled, true);
    await ui.flush();
    assert.equal(ui.posted[0].url, '/api/door');
    assert.equal(ui.element('watercolorRoom').classList.contains('door-open'), false);
    assert.equal(ui.element('door').disabled, false);
});
test('only confirmed status drives all scene devices', () => {
    const ui = sandbox(); ui.status({...online, door_status: 'open', window_status: 'open', light_status: 'on', light_brightness: 60, fan_speed: 30});
    for (const name of ['door-open', 'window-open', 'light-on', 'fan-on']) {
        assert.equal(ui.element('watercolorRoom').classList.contains(name), true);
    }
});
test('offline and expired status disable controls and clear stale animation', () => {
    const ui = sandbox(); ui.status({...online, door_status: 'open'}); ui.expire();
    assert.equal(ui.element('door').disabled, true);
    assert.equal(ui.element('watercolorRoom').classList.contains('door-open'), false);
    assert.equal(ui.element('wcTemperature').textContent, '—');
});
test('a live bridge allows confirmation after an output ACK expires', async () => {
    const ui = sandbox(); ui.status({...online, output_online: false});
    assert.equal(ui.element('fan').disabled, false);
    ui.element('fan').click(); await ui.flush();
    assert.equal(ui.posted.length, 1);
});
test('zero sensor readings remain visible', () => {
    const ui = sandbox(); ui.status(online);
    assert.equal(ui.element('wcTemperature').textContent, '0.0');
    assert.equal(ui.element('wcHumidity').textContent, '0');
});
test('light reading shows the engine dark/bright state next to the raw ADC', () => {
    const ui = sandbox();
    ui.status({...online, light_raw: 812, light_dark: true});
    assert.equal(ui.element('wcLightRaw').textContent, '812 · 暗');
    ui.status({...online, light_raw: 640, light_dark: false});
    assert.equal(ui.element('wcLightRaw').textContent, '640 · 亮');
    ui.status({...online, light_raw: 700, light_dark: null});
    assert.equal(ui.element('wcLightRaw').textContent, '700');
});
test('PIR idle and retained occupancy are shown independently', () => {
    const ui = sandbox();
    ui.status({...online, motion: false, occupancy: {value: true}});
    assert.equal(ui.element('wcPirRaw').textContent, '未检测到活动');
    assert.equal(ui.element('wcOccupancy').textContent, '保持有人');
    ui.expire();
    assert.equal(ui.element('wcOccupancy').textContent, '状态未知');
});
test('rapid repeat clicks issue only one command per device', async () => {
    const ui = sandbox(); ui.status(online);
    ui.element('door').click(); ui.element('door').click(); await ui.flush();
    assert.equal(ui.posted.length, 1);
});

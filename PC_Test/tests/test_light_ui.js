const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const web = path.join(__dirname, '../web');

test('dashboard IDs are unique', () => {
    const html = fs.readFileSync(path.join(web, 'templates/dashboard.html'), 'utf8');
    const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(m => m[1]);
    assert.equal(new Set(ids).size, ids.length);
});

test('brightness changes preserve night, temperature and RGB selection', async () => {
    const elements = new Map();
    const callbacks = new Map();
    const posted = [];
    let timer;
    const context = vm.createContext({
        console, Date, Math, Set,
        window: {addEventListener() {}},
        localStorage: {getItem: () => 'zh'},
        document: {
            addEventListener() {}, activeElement: null,
            getElementById(id) {
                if (!elements.has(id)) elements.set(id, {id, value: '#ff8000', addEventListener() {}});
                return elements.get(id);
            },
        },
        setTimeout: fn => { timer = fn; return 1; }, clearTimeout() {},
        capture: (el, label, format, cb) => callbacks.set(el.id, cb),
        record: async (url, body) => { posted.push(body); return {}; },
    });
    vm.runInContext(fs.readFileSync(path.join(web, 'static/js/main.js'), 'utf8'), context);
    vm.runInContext(`bindActuatorSlider = capture; apiPost = record;
        loadStatus = () => {}; showNotification = () => {};
        initControlSliders();`, context);
    for (const [select, expected] of [
        ["setLight('on', 25, 'night')", {mode: 'night'}],
        ['applyLightTemp(3000)', {temp: 3000}],
        ['applyLightColor()', {rgb: [255, 128, 0]}],
    ]) {
        vm.runInContext(select, context);
        await timer();
        callbacks.get('brightnessSlider')('40');
        await timer();
        assert.deepEqual(JSON.parse(JSON.stringify(posted.at(-1))),
            {status: 'on', brightness: 40, ...expected});
    }
});

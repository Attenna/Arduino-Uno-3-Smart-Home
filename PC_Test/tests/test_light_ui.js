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

// 灯光控件的可执行沙箱：main.js 直接跑在 vm 里，fetch/定时器/元素都打桩
function lightSandbox() {
    const elements = new Map();
    const callbacks = new Map();
    const posted = [];
    let timer;
    const element = id => {
        if (!elements.has(id)) {
            elements.set(id, {id, value: '', textContent: '', style: {},
                              classList: {toggle() {}}, addEventListener() {}, setAttribute() {}});
        }
        return elements.get(id);
    };
    element('lightColor').value = '#ff8000';
    element('tempSlider').value = '4000';
    const context = vm.createContext({
        console, Date, Math, Set, Number, String, Array, JSON, Object,
        window: {addEventListener() {}},
        localStorage: {getItem: () => 'zh'},
        document: {addEventListener() {}, activeElement: null, getElementById: element},
        setTimeout: fn => { timer = fn; return 1; },
        clearTimeout() {},
        capture: (el, label, format, cb) => callbacks.set(el.id, cb),
        record: async (url, body) => { posted.push(body); return {}; },
    });
    vm.runInContext(fs.readFileSync(path.join(web, 'static/js/main.js'), 'utf8'), context);
    vm.runInContext(`bindActuatorSlider = capture; apiPost = record;
        loadStatus = () => {}; showNotification = () => {}; t = key => key;
        initControlSliders();`, context);
    return {
        context, posted, elements,
        run: code => vm.runInContext(code, context),
        // vm 里造的对象带着沙箱自己的原型，跨上下文断言一律先 JSON 化
        json: code => JSON.parse(vm.runInContext(`JSON.stringify(${code})`, context)),
        flush: () => timer(),
        commit: (id, value) => {
            const el = vm.runInContext(`document.getElementById(${JSON.stringify(id)})`, context);
            el.value = value;
            return callbacks.get(id)(value);
        },
        last: () => JSON.parse(JSON.stringify(posted.at(-1))),
    };
}

test('levels preserve RGB and brightness and survive brightness changes', async () => {
    const ui = lightSandbox();
    ui.run("syncLightControls({light_status:'on',light_brightness:40,light_mode:'rgb',light_rgb:[255,128,0],light_count:8})");
    for (const count of [2,4,6,8]) {
        ui.run(`setLightCount(${count})`);
        await ui.flush();
        assert.deepEqual(ui.last(), {status:'on',brightness:40,rgb:[255,128,0],count});
    }
    ui.run('setLightCount(4)'); await ui.flush();
    ui.commit('brightnessSlider','60'); await ui.flush();
    assert.deepEqual(ui.last(), {status:'on',brightness:60,rgb:[255,128,0],count:4});
});
test('power restores brightness, color and count in the current page', async () => {
    const ui = lightSandbox();
    ui.run("syncLightControls({light_status:'on',light_brightness:35,light_mode:'rgb',light_rgb:[10,20,30],light_count:6})");
    ui.run('toggleLightPower()'); await ui.flush();
    assert.deepEqual(ui.last(), {status:'off',brightness:0});
    ui.run("syncLightControls({light_status:'off',light_brightness:0,light_mode:'rgb',light_rgb:[10,20,30],light_count:6})");
    ui.run('toggleLightPower()'); await ui.flush();
    assert.deepEqual(ui.last(), {status:'on',brightness:35,rgb:[10,20,30],count:6});
});
test('color presets and picker preserve level', async () => {
    const ui = lightSandbox();
    ui.run("syncLightControls({light_status:'on',light_brightness:45,light_mode:'rgb',light_rgb:[10,20,30],light_count:2})");
    ui.run("setLightColor('#ffffff')"); await ui.flush();
    assert.deepEqual(ui.last(), {status:'on',brightness:45,rgb:[255,255,255],count:2});
    assert.equal(ui.elements.get('lightColor').value,'#ffffff');
});
test('dashboard exposes four count levels and no temperature control', () => {
    const html = fs.readFileSync(path.join(web, 'templates/dashboard.html'),'utf8');
    assert.equal(html.includes('tempSlider'),false);
    assert.equal(html.includes('setLightNight'),false);
    for (const n of [2,4,6,8]) assert.ok(html.includes(`setLightCount(${n})`));
    assert.ok(html.includes('toggleLightPower()'));
});

test('dashboard no longer renders or binds the AC control card', () => {
    const html = fs.readFileSync(path.join(web, 'templates/dashboard.html'), 'utf8');
    const js = fs.readFileSync(path.join(web, 'static/js/main.js'), 'utf8');
    const css = fs.readFileSync(path.join(web, 'static/css/style.css'), 'utf8');
    for (const marker of ['card-ac', 'acTempSlider', 'acModeButtons', 'acFanButtons',
                          'acSwingUdBtn', 'acSwingLrBtn', 'acPowerBtn']) {
        assert.equal(html.includes(marker), false, `${marker} 仍出现在仪表盘`);
        assert.equal(js.includes(marker), false, `${marker} 仍被 main.js 绑定`);
    }
    assert.equal(css.includes('.ac-indicator'), false);
    assert.match(html, /remoteControl\('ac_on'\)/,
        '远程控制区不属于被删除的独立空调卡片');
});

// JS 内部调用同样要能解析：远程面板的开/关灯走 remoteControl()，模板里搜不到。
// 改名漏改内部调用只在点击时抛 ReferenceError，页面其它部分照常工作，最难发现。
test('every light entry point called in main.js is defined', () => {
    const js = fs.readFileSync(path.join(web, 'static/js/main.js'), 'utf8');
    const called = new Set([...js.matchAll(/\b(setLight[A-Za-z]*|turnLightOff)\s*\(/g)]
        .map(m => m[1]));
    assert.ok(called.size >= 4);
    for (const name of called) {
        assert.match(js, new RegExp(`function ${name}\\(`), `${name} 被调用但没有定义`);
    }
});

test('remote control preserves RGB and level', async () => {
    const ui = lightSandbox();
    ui.run("syncLightControls({light_status:'on',light_brightness:40,light_mode:'rgb',light_rgb:[10,20,30],light_count:4})");
    ui.run("remoteControl('light_on')"); await ui.flush();
    assert.deepEqual(ui.last(), {status:'on',brightness:100,rgb:[10,20,30],count:4});
    ui.run("remoteControl('light_off')"); await ui.flush();
    assert.deepEqual(ui.last(), {status:'off',brightness:0});
});

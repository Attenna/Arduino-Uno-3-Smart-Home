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
                              classList: {toggle() {}}, addEventListener() {}});
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
        loadStatus = () => {}; showNotification = () => {};
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

test('brightness changes preserve night, temperature and RGB selection', async () => {
    const ui = lightSandbox();
    for (const [select, expected] of [
        ['setLightNight()', {mode: 'night'}],
        ['applyLightTemp(3000)', {temp: 3000}],
        ["document.getElementById('lightColor').value = '#ff8000'; applyLightColor()", {rgb: [255, 128, 0]}],
    ]) {
        ui.run(select);
        await ui.flush();
        await ui.commit('brightnessSlider', '40');
        await ui.flush();
        assert.deepEqual(ui.last(), {status: 'on', brightness: 40, ...expected});
    }
});

// #27 的核心：全亮/半亮只是亮度快捷键，绝不能再把色温或颜色清成白光
test('brightness shortcuts keep the persisted style', async () => {
    const ui = lightSandbox();
    ui.run("syncLightControls({light_status: 'on', light_brightness: 80,"
        + " light_mode: 'temp', light_temp: 4000})");
    ui.run('setLightBrightness(100)');
    await ui.flush();
    assert.deepEqual(ui.last(), {status: 'on', brightness: 100, temp: 4000});

    ui.run("syncLightControls({light_status: 'on', light_brightness: 100,"
        + " light_mode: 'rgb', light_rgb: [10, 20, 30]})");
    ui.run('setLightBrightness(50)');
    await ui.flush();
    assert.deepEqual(ui.last(), {status: 'on', brightness: 50, rgb: [10, 20, 30]});

    // 关灯不带亮法：由服务端沿用库里当前值
    ui.run('turnLightOff()');
    await ui.flush();
    assert.deepEqual(ui.last(), {status: 'off', brightness: 0});

    // 白光是显式按钮给的，不是副作用；刚关过灯，所以从 100% 起步
    ui.run('setLightWhite()');
    await ui.flush();
    assert.deepEqual(ui.last(), {status: 'on', brightness: 100, mode: 'white'});
});

test('status report restores the style into the controls', async () => {
    const ui = lightSandbox();
    ui.run("syncLightControls({light_status: 'on', light_brightness: 40,"
        + " light_mode: 'temp', light_temp: 3000})");
    assert.deepEqual(ui.json('lightStyle'), {temp: 3000});
    assert.equal(ui.elements.get('tempSlider').value, 3000);
    assert.equal(ui.elements.get('lightTempValue').textContent, '3000K');
    assert.equal(ui.json('lightStyleFromStatus({light_mode: "night"})').mode, 'night');
    assert.equal(ui.json('lightStyleFromStatus({})').mode, 'white');

    ui.run("syncLightControls({light_status: 'on', light_brightness: 40,"
        + " light_mode: 'rgb', light_rgb: [255, 0, 128]})");
    assert.deepEqual(ui.json('lightStyle'), {rgb: [255, 0, 128]});
    assert.equal(ui.elements.get('lightColor').value, '#ff0080');
    assert.equal(ui.elements.get('bulb').style.background, 'rgb(255,0,128)');
    // 白光/夜灯不染色，沿用主题的暖黄
    ui.run("syncLightControls({light_status: 'on', light_brightness: 40, light_mode: 'white'})");
    assert.equal(ui.elements.get('bulb').style.background, '');
});

// 页面按钮与 JS 函数必须同名：改了函数名忘了改模板会静默失效
test('dashboard light buttons are wired to defined functions', () => {
    const html = fs.readFileSync(path.join(web, 'templates/dashboard.html'), 'utf8');
    const js = fs.readFileSync(path.join(web, 'static/js/main.js'), 'utf8');
    const calls = [...html.matchAll(/onclick="(setLight[A-Za-z]*|turnLightOff)\(([^)]*)\)/g)]
        .map(m => `${m[1]}(${m[2]})`);
    assert.deepEqual(calls, ['setLightBrightness(100)', 'setLightBrightness(50)',
                             'setLightWhite()', 'setLightNight()', 'turnLightOff()']);
    for (const name of ['setLightBrightness', 'setLightWhite', 'setLightNight',
                        'turnLightOff', 'applyLightTemp', 'applyLightColor']) {
        assert.match(js, new RegExp(`function ${name}\\(`), `${name} 已不存在`);
    }
    assert.equal(/function setLight\(/.test(js), false, 'setLight 应已被显式入口取代');
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

test('remote control light buttons still drive the light and keep the style', async () => {
    const ui = lightSandbox();
    ui.run("syncLightControls({light_status: 'on', light_brightness: 40,"
        + " light_mode: 'temp', light_temp: 3000})");
    ui.run("remoteControl('light_on')");
    await ui.flush();
    assert.deepEqual(ui.last(), {status: 'on', brightness: 100, temp: 3000});

    ui.run("remoteControl('light_off')");
    await ui.flush();
    assert.deepEqual(ui.last(), {status: 'off', brightness: 0});
});

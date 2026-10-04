const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const web = path.join(__dirname, '../web');

// #29：DOM 桩必须照着 history.html 上真实存在的 id 来搭。
// 旧桩对任意 id 都返回一个只有 value/textContent 的对象，于是两个后果：
//   * applyStatView 写 .style.display / .setAttribute 时直接 TypeError；
//   * 源码里 `if (grid)`、`if (label)` 这些守卫永远走「元素在」的分支，
//     「页面上没这个元素」这条路径其实一次都没被跑过。
// 现在页面上没有的 id 一律返回 null（和浏览器行为一致），并把被问到过、
// 但模板里不存在的 id 记下来交给最后的漂移用例断言——否则守卫会把漂移吞掉。
function historySandbox() {
    const pageIds = new Set(
        [...fs.readFileSync(path.join(web, 'templates/history.html'), 'utf8')
            .matchAll(/\bid="([^"]+)"/g)].map(m => m[1]));
    const elements = new Map();
    const missing = new Set();
    let rows = [];
    const element = id => {
        if (!pageIds.has(id)) {
            missing.add(id);
            return null;
        }
        if (!elements.has(id)) {
            elements.set(id, {
                value: id === 'dataType' ? 'temperature' : '24',
                textContent: '',
                innerHTML: '',
                style: {},
                attributes: {},
                setAttribute(name, value) { this.attributes[name] = value; },
            });
        }
        return elements.get(id);
    };
    const context = vm.createContext({
        console, Date, Math, Number, String, Array, Object, JSON, isNaN,
        document: {addEventListener() {}, getElementById: element},
        t: key => key,
        readRows: async () => rows,
    });
    vm.runInContext(fs.readFileSync(path.join(web, 'static/js/history.js'), 'utf8'), context);
    vm.runInContext('apiGet = readRows; updateTable = () => {};', context);
    return {
        elements, missing,
        run: async (type, list) => {
            rows = list;
            element('dataType').value = type;
            await vm.runInContext('loadHistory()', context);
        },
    };
}

test('NULL and empty history clear previous summary values', async () => {
    const ui = historySandbox();
    for (const type of ['temperature', 'humidity']) {
        await ui.run(type, [{temperature: 23, humidity: 50}]);
        assert.notEqual(ui.elements.get('statAvg').textContent, '--');
        for (const empty of [[{temperature: null, humidity: null}], []]) {
            await ui.run(type, empty);
            for (const id of ['statMax', 'statMin', 'statAvg']) {
                assert.equal(ui.elements.get(id).textContent, '--');
            }
            assert.equal(Number(ui.elements.get('statCount').textContent), empty.length);
        }
    }
});

// 统计区在门窗/灯光下是整块隐藏的（这两个数据类型没有「最高/最低/平均」可言）
test('stat grid is hidden for the data types without aggregates', async () => {
    const ui = historySandbox();
    for (const type of ['door_window', 'light']) {
        await ui.run(type, [{status: 'open', brightness: 60}]);
        assert.equal(ui.elements.get('statGrid').style.display, 'none');
        assert.equal(ui.elements.get('statMax').textContent, '--');
    }
    for (const type of ['temperature', 'humidity']) {
        await ui.run(type, [{temperature: 23, humidity: 50}]);
        assert.equal(ui.elements.get('statGrid').style.display, '');
    }
});

// 湿度数据类型的统计文案与单位要跟着换，且 data-i18n 键得重写（否则切语言还显示温度文案）
test('humidity switches the stat labels and their i18n keys', async () => {
    const ui = historySandbox();
    await ui.run('temperature', [{temperature: 23, humidity: 50}]);
    assert.deepEqual(ui.elements.get('statMaxLabel').attributes, {'data-i18n': 'history.stat_max'});
    assert.equal(ui.elements.get('statMaxLabel').textContent, 'history.stat_max');
    assert.equal(ui.elements.get('statMinUnit').textContent, '°C');

    await ui.run('humidity', [{temperature: 23, humidity: 50}]);
    assert.deepEqual(ui.elements.get('statAvgLabel').attributes, {'data-i18n': 'history.stat_avg_humidity'});
    assert.equal(ui.elements.get('statAvgUnit').textContent, '%');
});

// 源码要找的 id 必须真在模板里：少了元素守卫会静默跳过，页面就少一块统计
test('history.js only looks up ids that exist on the page', async () => {
    const ui = historySandbox();
    for (const type of ['temperature', 'humidity', 'door_window', 'light']) {
        await ui.run(type, [{temperature: 23, humidity: 50}]);
    }
    assert.deepEqual([...ui.missing], []);
});

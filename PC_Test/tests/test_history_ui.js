const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const HTML_PATH = path.join(__dirname, '../web/templates/history.html');
const SCRIPT_PATH = path.join(__dirname, '../web/static/js/history.js');

// 桩按 history.html 里真实存在的 id 搭建：页面上没有的 id 必须返回 null，
// 否则源码里的 `if (el)` 守卫分支在测试里永远是死的（issue #29）。
function pageIds() {
    const html = fs.readFileSync(HTML_PATH, 'utf8');
    return new Set([...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]));
}

function makeContext(rows) {
    const elements = new Map();
    const ids = pageIds();
    const context = vm.createContext({
        console,
        document: {
            addEventListener() {},
            getElementById(id) {
                if (!ids.has(id)) return null;
                if (!elements.has(id)) elements.set(id, {
                    value: id === 'dataType' ? 'temperature' : '24',
                    textContent: '', style: {}, setAttribute() {},
                });
                return elements.get(id);
            },
        },
        t: key => key,
        serverDate: value => new Date(value),
        I18N: {currentLang: 'zh'},
        // rows 传入的是取值函数，用例可在两次 loadHistory 之间替换数据
        readRows: async () => rows(),
    });
    vm.runInContext(fs.readFileSync(SCRIPT_PATH, 'utf8'), context);
    vm.runInContext('apiGet = readRows; updateTable = () => {};', context);
    return {context, elements};
}

test('NULL and empty history clear previous summary values', async () => {
    let rows = [];
    const {context, elements} = makeContext(() => rows);
    for (const type of ['temperature', 'humidity', 'light_level']) {
        context.document.getElementById('dataType').value = type;
        rows = [{temperature: 23, humidity: 50, light_raw: 456}];
        await vm.runInContext('loadHistory()', context);
        assert.notEqual(elements.get('statAvg').textContent, '--');
        for (const empty of [[{temperature: null, humidity: null, light_raw: null}], []]) {
            rows = empty;
            await vm.runInContext('loadHistory()', context);
            for (const id of ['statMax', 'statMin', 'statAvg']) {
                assert.equal(elements.get(id).textContent, '--');
            }
            assert.equal(Number(elements.get('statCount').textContent), rows.length);
        }
    }
});

test('unknown ids resolve to null so source guards are exercised', () => {
    const {context} = makeContext(() => []);
    assert.equal(context.document.getElementById('notOnThePage'), null);
    // 真实存在的 id 仍要返回可写对象
    const grid = context.document.getElementById('statGrid');
    assert.ok(grid);
    grid.style.display = 'none';
    assert.equal(grid.style.display, 'none');
});

test('statGrid is hidden for door/window and light, visible for temperature', async () => {
    const rows = [];
    const {context} = makeContext(() => rows);
    const grid = context.document.getElementById('statGrid');
    const dataType = context.document.getElementById('dataType');

    dataType.value = 'door_window';
    await vm.runInContext('loadHistory()', context);
    assert.equal(grid.style.display, 'none');

    dataType.value = 'light';
    await vm.runInContext('loadHistory()', context);
    assert.equal(grid.style.display, 'none');

    dataType.value = 'temperature';
    await vm.runInContext('loadHistory()', context);
    assert.equal(grid.style.display, '');
});

test('history page exposes light level separately from lamp status', () => {
    const html = fs.readFileSync(HTML_PATH, 'utf8');
    const script = fs.readFileSync(SCRIPT_PATH, 'utf8');
    const lang = fs.readFileSync(path.join(__dirname, '../web/static/js/lang.js'), 'utf8');
    assert.match(html, /value="light_level"[^>]*data-i18n="history\.type_light_level"/);
    assert.match(html, /value="light"[^>]*data-i18n="history\.type_light"/);
    assert.match(script, /\/api\/light-level\/history\?hours=/);
    assert.match(script, /d\.light_raw/);
    assert.match(lang, /'history\.type_light_level': '光照强度'/);
    assert.match(lang, /'history\.type_light_level': 'Light Level'/);
});

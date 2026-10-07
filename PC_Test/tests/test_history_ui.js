const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('NULL and empty history clear previous summary values', async () => {
    const elements = new Map();
    let rows = [];
    const context = vm.createContext({
        console,
        document: {
            addEventListener() {},
            getElementById(id) {
                if (!elements.has(id)) elements.set(id, {
                    value: id === 'dataType' ? 'temperature' : '24',
                    textContent: '', style: {}, setAttribute() {},
                });
                return elements.get(id);
            },
        },
        t: key => key,
        readRows: async () => rows,
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/static/js/history.js'), 'utf8'), context);
    vm.runInContext('apiGet = readRows; updateTable = () => {};', context);
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

test('history page exposes light level separately from lamp status', () => {
    const html = fs.readFileSync(path.join(__dirname, '../web/templates/history.html'), 'utf8');
    const script = fs.readFileSync(path.join(__dirname, '../web/static/js/history.js'), 'utf8');
    const lang = fs.readFileSync(path.join(__dirname, '../web/static/js/lang.js'), 'utf8');
    assert.match(html, /value="light_level"[^>]*data-i18n="history\.type_light_level"/);
    assert.match(html, /value="light"[^>]*data-i18n="history\.type_light"/);
    assert.match(script, /\/api\/light-level\/history\?hours=/);
    assert.match(script, /d\.light_raw/);
    assert.match(lang, /'history\.type_light_level': '光照强度'/);
    assert.match(lang, /'history\.type_light_level': 'Light Level'/);
});

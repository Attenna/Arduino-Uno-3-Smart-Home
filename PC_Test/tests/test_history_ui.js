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
                if (!elements.has(id)) elements.set(id, {value: id === 'dataType' ? 'temperature' : '24', textContent: ''});
                return elements.get(id);
            },
        },
        t: key => key,
        readRows: async () => rows,
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/static/js/history.js'), 'utf8'), context);
    vm.runInContext('apiGet = readRows; updateTable = () => {};', context);
    for (const type of ['temperature', 'humidity']) {
        context.document.getElementById('dataType').value = type;
        rows = [{temperature: 23, humidity: 50}];
        await vm.runInContext('loadHistory()', context);
        assert.notEqual(elements.get('statAvg').textContent, '--');
        for (const empty of [[{temperature: null, humidity: null}], []]) {
            rows = empty;
            await vm.runInContext('loadHistory()', context);
            for (const id of ['statMax', 'statMin', 'statAvg']) {
                assert.equal(elements.get(id).textContent, '--');
            }
            assert.equal(Number(elements.get('statCount').textContent), rows.length);
        }
    }
});

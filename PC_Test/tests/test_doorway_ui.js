const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname, '../web/static/js/doorway.js'), 'utf8');

async function render(data, ok = true) {
    const label = {};
    let watchdog;
    const context = {
        document: { getElementById: () => label },
        fetch: async () => ({ ok, json: async () => data }),
        AbortSignal: { timeout: () => null },
        setInterval: fn => { watchdog = fn; }, setTimeout: () => {},
        Date, Number,
    };
    vm.runInNewContext(script, context);
    await new Promise(resolve => setImmediate(resolve));
    return { label, watchdog, context };
}

test('distance renders a valid decimal in centimetres', async () => {
    const { label } = await render({ valid: true, distance_cm: 49.25 });
    assert.equal(label.textContent, '49.3 cm');
});
test('invalid echo never renders zero distance', async () => {
    const { label } = await render({ valid: false, distance_cm: null });
    assert.match(label.textContent, /暂无有效距离/);
});
test('failed requests and old cache visibly invalidate distance', async () => {
    const failed = await render({}, false);
    assert.match(failed.label.textContent, /连接中断/);
    const result = await render({ valid: true, distance_cm: 20 });
    result.context.Date = { now: () => Date.now() + 4000 };
    result.watchdog();
    assert.match(result.label.textContent, /数据过期/);
});

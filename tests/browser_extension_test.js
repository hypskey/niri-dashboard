// Runs the real background script against browser API doubles; no browser required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const event = () => ({listeners: [], addListener(fn) { this.listeners.push(fn); },
    fire(...args) { for (const fn of this.listeners) fn(...args); }});
let windows = [
    {id: 1, tabs: [{active: true, url: 'https://chatgpt.com/c/123', title: 'Nautilus Transparency Setup'}]},
    {id: 2, tabs: [{active: true, url: 'https://www.youtube.com/watch?v=1'}]},
    {id: 3, incognito: true, tabs: [{active: true, url: 'https://mail.google.com/'}]}
];
const messages = [], updates = [], connections = [], timers = new Map();
let timerId = 0;
const browser = {
    tabs: Object.fromEntries(['onActivated', 'onUpdated', 'onRemoved', 'onAttached', 'onDetached'].map(k => [k, event()])),
    windows: {
        onCreated: event(), onRemoved: event(),
        async getAll() { return structuredClone(windows); },
        async update(id, change) { updates.push({id, change}); }
    }
};
class WebSocket {
    static OPEN = 1;
    constructor(url) {
        assert.equal(url, 'ws://127.0.0.1:47831');
        this.readyState = 0;
        connections.push(this);
    }
    open() { this.readyState = 1; this.onopen(); }
    send(text) { assert.equal(this.readyState, 1); messages.push(JSON.parse(text)); }
    close() { this.readyState = 3; this.onclose(); }
}
const context = vm.createContext({browser, WebSocket, URL, Uint8Array, Map, console,
    crypto: require('node:crypto').webcrypto,
    setTimeout(fn, delay) { const id = ++timerId; timers.set(id, {fn, delay}); return id; },
    clearTimeout(id) { timers.delete(id); }, setInterval() {}});
vm.runInContext(fs.readFileSync('browser-extension/background.js', 'utf8'), context);
async function tick(maxDelay=30) {
    for (const [id, timer] of [...timers]) {
        if (timer.delay <= maxDelay) { timers.delete(id); await timer.fn(); }
    }
    await new Promise(resolve => setImmediate(resolve));
}
(async () => {
    await tick();
    assert.equal(messages.length, 0);
    connections[0].open();
    await tick();
    let snapshot = messages.at(-1);
    const keys = Object.keys(snapshot);
    assert.equal(keys.length, 2);
    const first = keys.find(key => key.endsWith(':1'));
    const second = keys.find(key => key.endsWith(':2'));
    assert.match(first, /^[a-f0-9]{32}:1$/);
    assert.equal(snapshot[first], 'chatgpt.com');
    assert.equal(snapshot[second], 'www.youtube.com');
    assert.equal(updates[0].change.titlePreface, `[ND:${first}] `);
    assert.ok(updates.every(({change}) => Object.keys(change).join() === 'titlePreface'));
    // Same title, new active URL: no dependency on title change or restart.
    windows[0].tabs[0].url = 'https://random.example/ChatGPT';
    browser.tabs.onActivated.fire({windowId: 1});
    await tick();
    assert.equal(messages.at(-1)[first], 'random.example');
    windows[0].tabs[0].url = 'https://youtube.com/watch?v=2';
    browser.tabs.onUpdated.fire(1, {url: windows[0].tabs[0].url});
    await tick();
    assert.equal(messages.at(-1)[first], 'youtube.com');
    windows[0].tabs[0].url = 'about:blank';
    browser.tabs.onUpdated.fire(1, {url: 'about:blank'});
    await tick();
    assert.equal(messages.at(-1)[first], '');
    windows = windows.filter(window => window.id !== 2);
    browser.windows.onRemoved.fire(2);
    await tick();
    assert.ok(!(second in messages.at(-1)));
    connections[0].close();
    await tick();
    assert.equal(updates.at(-1).change.titlePreface, '');
    await tick(1000);
    await tick();
    assert.equal(connections.length, 2);
    connections[1].open();
    await tick();
    assert.equal(updates.at(-1).change.titlePreface, `[ND:${first}] `);
    console.log('Browser extension: hostname changes, multiwindow, privacy, removal, reconnect passed');
})().catch(error => { console.error(error); process.exitCode = 1; });

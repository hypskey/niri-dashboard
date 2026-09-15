/* Only active hostnames leave the browser, via a loopback WebSocket. */
const session = Array.from(crypto.getRandomValues(new Uint8Array(16)),
    value => value.toString(16).padStart(2, "0")).join("");
const ENDPOINT = "ws://127.0.0.1:47831";
let port = null;
let running = false;
let dirty = false;
let scheduled = null;
let retry = 1000;
const prefixes = new Map();

function hostname(url) {
    try {
        const parsed = new URL(url);
        return ["http:", "https:"].includes(parsed.protocol) ? parsed.hostname.replace(/^\[|\]$/g, "") : "";
    } catch (_) { return ""; }
}

async function publish() {
    dirty = true;
    if (running) return;
    running = true;
    try {
        while (dirty) {
            dirty = false;
            const connection = port && port.readyState === WebSocket.OPEN ? port : null;
            const windows = await browser.windows.getAll({populate: true, windowTypes: ["normal"]});
            const snapshot = {};
            for (const window of windows) {
                if (window.incognito) continue;
                const token = `${session}:${window.id}`;
                const prefix = `[ND:${token}] `;
                if (!connection) {
                    if (prefixes.has(window.id)) {
                        await browser.windows.update(window.id, {titlePreface: prefixes.get(window.id)});
                        prefixes.delete(window.id);
                    }
                    continue;
                }
                const active = (window.tabs || []).find(tab => tab.active);
                if (!active) continue;
                try {
                    if (!prefixes.has(window.id)) {
                        await browser.windows.update(window.id, {titlePreface: prefix});
                        prefixes.set(window.id, window.titlePreface || "");
                    }
                    snapshot[token] = hostname(active.url);
                } catch (_) { /* A window can close during enumeration. */ }
            }
            if (connection && port === connection && connection.readyState === WebSocket.OPEN) {
                connection.send(JSON.stringify(snapshot));
            }
        }
    } catch (error) {
        console.warn("NiriDashboard active-tab bridge:", error);
    } finally { running = false; }
}

function schedule() {
    clearTimeout(scheduled);
    scheduled = setTimeout(publish, 30);
}

function connect() {
    try {
        const connection = new WebSocket(ENDPOINT);
        port = connection;
        // Do not map titles or send until the handshake has completed.
        const opening = setTimeout(() => connection.close(), 5000);
        connection.onopen = () => {
            clearTimeout(opening);
            retry = 1000;
            schedule(); // Full snapshot restores all windows after dashboard restart.
        };
        connection.onclose = () => {
            clearTimeout(opening);
            if (port !== connection) return;
            port = null;
            schedule();
            setTimeout(connect, retry);
            retry = Math.min(retry * 2, 10000);
        };
        connection.onerror = () => connection.close();
    } catch (error) {
        console.warn("NiriDashboard localhost bridge unavailable", error);
        setTimeout(connect, retry);
        retry = Math.min(retry * 2, 10000);
    }
}

browser.tabs.onActivated.addListener(schedule);
browser.tabs.onUpdated.addListener((_id, change) => {
    if ("url" in change || "status" in change) schedule();
});
browser.tabs.onRemoved.addListener(schedule);
browser.tabs.onAttached.addListener(schedule);
browser.tabs.onDetached.addListener(schedule);
browser.windows.onCreated.addListener(schedule);
browser.windows.onRemoved.addListener(id => { prefixes.delete(id); schedule(); });
setInterval(schedule, 30000); // Heartbeat only; tab changes are event-driven.
connect();

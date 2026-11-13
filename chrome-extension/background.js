const WS_URL = "ws://127.0.0.1:8000/browser/ws";
const RECONNECT_ALARM = "jarvis-reconnect";

let socket = null;
let reconnectTimer = null;
let heartbeatTimer = null;

// The Jarvis UI lives in a Chrome tab (http://127.0.0.1:8000). Anything that
// "opens" a URL must never reuse that tab, or Jarvis's own interface gets
// navigated away and appears to close itself.
function isJarvisTab(tab) {
  return /^https?:\/\/(127\.0\.0\.1|localhost):8000\b/.test(tab?.url || "");
}

async function execute(command) {
  const { action, payload = {} } = command;
  if (action === "open_url") {
    // Reuse a blank new-tab page if one exists — never a real page, and
    // never the Jarvis tab (which would navigate Jarvis's own UI away).
    const tabs = await chrome.tabs.query({});
    const blank = tabs.find((tab) => !isJarvisTab(tab) && (tab.url === "chrome://newtab/" || tab.url === "about:blank" || !tab.url));
    let tab;
    if (blank) {
      tab = await chrome.tabs.update(blank.id, { url: payload.url, active: true });
    } else {
      tab = await chrome.tabs.create({ url: payload.url });
    }
    return { message: `Chrome-Tab geöffnet: ${payload.url}`, data: { tabId: tab.id, url: payload.url } };
  }
  if (action === "list_tabs") {
    const tabs = (await chrome.tabs.query({})).map((tab) => ({ id: tab.id, title: tab.title, url: tab.url, active: tab.active }));
    return { message: `${tabs.length} Chrome-Tabs gefunden.`, data: { tabs } };
  }
  throw new Error(`Unbekannte Browser-Aktion: ${action}`);
}

function stopHeartbeat() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, 1500);
}

function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
  // Every handler works on its own `ws`, not on the shared `socket`: an old
  // socket closing late used to null the reference of the NEW connection,
  // which then got a second, parallel connection on top (commands ran twice).
  const ws = new WebSocket(WS_URL);
  socket = ws;
  const reply = (payload) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
  };
  ws.onopen = () => {
    stopHeartbeat();
    const heartbeat = () => reply({ type: "heartbeat" });
    heartbeat();
    heartbeatTimer = setInterval(heartbeat, 10_000);
  };
  ws.onmessage = async ({ data }) => {
    let command;
    try { command = JSON.parse(data); } catch (error) { return; }
    if (!command || typeof command !== "object") return;
    try {
      const outcome = await execute(command);
      reply({ id: command.id, ok: true, message: outcome.message, data: outcome.data });
    } catch (error) {
      reply({ id: command.id, ok: false, error: error.message || String(error) });
    }
  };
  ws.onclose = () => {
    if (socket !== ws) return;
    stopHeartbeat();
    socket = null;
    scheduleReconnect();
  };
  ws.onerror = () => ws.close();
}

// Manifest-V3 service workers may sleep after Chrome or Jarvis restarts. The
// alarm wakes the worker regularly so the local WebSocket is recreated.
chrome.alarms.create(RECONNECT_ALARM, { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === RECONNECT_ALARM) connect();
});
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
connect();

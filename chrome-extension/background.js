const API = "http://127.0.0.1:8000";
const WS_URL = "ws://127.0.0.1:8000/browser/ws";
const RECONNECT_ALARM = "jarvis-reconnect";

let socket = null;
let reconnectTimer = null;
let heartbeatTimer = null;

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab) throw new Error("Kein aktiver Chrome-Tab.");
  return tab;
}

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
  if (action === "activate_tab") {
    const tab = await chrome.tabs.update(payload.tabId, { active: true });
    return { message: `Tab aktiviert: ${tab.title || tab.url}`, data: { tabId: tab.id, url: tab.url } };
  }
  if (action === "go_back") {
    const tab = await activeTab();
    await chrome.tabs.goBack(tab.id);
    return { message: "Im Chrome-Tab zurück navigiert.", data: { tabId: tab.id } };
  }
  if (action === "page_state" || action === "find_and_click" || action === "type_text") {
    const tab = await activeTab();
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (kind, value) => {
        const visible = (element) => !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length);
        const text = (element) => (element.innerText || element.value || element.getAttribute("aria-label") || "").trim();
        if (kind === "page_state") {
          return { title: document.title, url: location.href, elements: [...document.querySelectorAll("a,button,input,textarea")].filter(visible).slice(0, 80).map((el) => ({ tag: el.tagName, text: text(el).slice(0, 120), href: el.href || "", aria: el.getAttribute("aria-label") || "" })) };
        }
        const needle = String(value || "").toLowerCase();
        const candidates = [...document.querySelectorAll("a,button,input,textarea,[role=button]")].filter(visible);
        const target = candidates.find((el) => `${text(el)} ${el.getAttribute("aria-label") || ""}`.toLowerCase().includes(needle));
        if (!target) throw new Error(`Element nicht gefunden: ${value}`);
        if (kind === "find_and_click") { target.click(); return { clicked: text(target), url: location.href }; }
        target.focus(); target.value = value; target.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value })); target.dispatchEvent(new Event("change", { bubbles: true })); return { typedInto: target.name || target.id || target.getAttribute("aria-label") || target.tagName };
      },
      args: [action, payload.text || payload.selector || ""],
    });
    return { message: action === "page_state" ? `Seite gelesen: ${result.title}` : "Browser-Aktion ausgeführt.", data: result };
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
  socket = new WebSocket(WS_URL);
  socket.onopen = () => {
    stopHeartbeat();
    const heartbeat = () => {
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "heartbeat" }));
    };
    heartbeat();
    heartbeatTimer = setInterval(heartbeat, 10_000);
  };
  socket.onmessage = async ({ data }) => {
    const command = JSON.parse(data);
    try {
      const outcome = await execute(command);
      socket.send(JSON.stringify({ id: command.id, ok: true, message: outcome.message, data: outcome.data }));
    } catch (error) {
      socket.send(JSON.stringify({ id: command.id, ok: false, error: error.message || String(error) }));
    }
  };
  socket.onclose = () => {
    stopHeartbeat();
    socket = null;
    scheduleReconnect();
  };
  socket.onerror = () => socket.close();
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

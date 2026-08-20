const API = "http://127.0.0.1:8000";

let socket = null;

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab) throw new Error("Kein aktiver Chrome-Tab.");
  return tab;
}

async function execute(command) {
  const { action, payload = {} } = command;
  if (action === "open_url") {
    const tab = await activeTab();
    await chrome.tabs.update(tab.id, { url: payload.url, active: true });
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

function connect() {
  socket = new WebSocket("ws://127.0.0.1:8000/browser/ws");
  socket.onmessage = async ({ data }) => {
    const command = JSON.parse(data);
    try {
      const outcome = await execute(command);
      socket.send(JSON.stringify({ id: command.id, ok: true, message: outcome.message, data: outcome.data }));
    } catch (error) {
      socket.send(JSON.stringify({ id: command.id, ok: false, error: error.message || String(error) }));
    }
  };
  socket.onclose = () => setTimeout(connect, 1500);
  socket.onerror = () => socket.close();
}

connect();

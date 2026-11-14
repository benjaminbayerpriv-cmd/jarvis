// JARVIS-Browser — Elementfinder. Wird vom Launcher per evaluate_js in jede
// Seite des Jarvis-Browsers eingespeist (siehe launcher/browser_window.py).
//
// Statt eines Screenshots bekommt das Modell eine nummerierte Liste der
// bedienbaren Elemente (Rolle, Name, Zustand) und wählt eine Nummer. Das
// Skript führt den Klick/die Eingabe selbst aus. Jede Funktion gibt einen
// JSON-String zurück (evaluate_js kann Objekte je nach Version unterschiedlich
// liefern, ein String ist eindeutig).
(() => {
  'use strict';
  if (window.__jb && window.__jb.v === 3) return;

  const MAX_ITEMS = 50;
  const MAX_NODES = 30000;
  const SELECTOR = [
    'a[href]', 'button', 'input:not([type=hidden])', 'select', 'textarea', 'summary',
    '[role=button]', '[role=link]', '[role=tab]', '[role=checkbox]', '[role=radio]', '[role=switch]',
    '[role=menuitem]', '[role=menuitemcheckbox]', '[role=menuitemradio]', '[role=option]',
    '[role=combobox]', '[role=searchbox]', '[role=textbox]', '[role=treeitem]',
    '[onclick]', '[contenteditable=""]', '[contenteditable="true"]',
  ].join(',');

  const state = { epoch: 0, items: [] };

  const clean = (s, n) => {
    s = String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
    return n && s.length > n ? s.slice(0, n - 1) + '…' : s;
  };

  // Alle Wurzeln durchlaufen: Dokument, offene Shadow-DOMs, gleich-originäre Iframes.
  function collect() {
    const found = [];
    let visited = 0;
    const walkRoot = (root, win) => {
      let list;
      try { list = root.querySelectorAll(SELECTOR); } catch (e) { return; }
      for (const el of list) found.push([el, win]);
      // Shadow-Hosts und Iframes finden (günstig: nur Elemente mit Shadow oder iframe).
      const all = root.querySelectorAll('*');
      for (const el of all) {
        if (++visited > MAX_NODES) return;
        if (el.shadowRoot) walkRoot(el.shadowRoot, win);
        else if (el.tagName === 'IFRAME') {
          try {
            const doc = el.contentDocument;
            if (doc && doc.documentElement) walkRoot(doc, el.contentWindow);
          } catch (e) { /* fremde Herkunft: nicht erreichbar */ }
        }
      }
    };
    walkRoot(document, window);
    return found;
  }

  function isVisible(el, win, relaxed) {
    let r;
    try { r = el.getBoundingClientRect(); } catch (e) { return false; }
    if (r.width < 2 || r.height < 2) return false;
    let cs;
    try { cs = win.getComputedStyle(el); } catch (e) { return false; }
    if (cs.visibility === 'hidden' || cs.display === 'none' || Number(cs.opacity) === 0) return false;
    if (r.bottom <= 0 || r.right <= 0 || r.top >= win.innerHeight || r.left >= win.innerWidth) return false;
    if (relaxed) return true;
    // Verdeckt (Overlay, Cookie-Banner davor)? Mittelpunkt prüfen.
    const x = Math.min(Math.max(r.left + r.width / 2, 1), win.innerWidth - 1);
    const y = Math.min(Math.max(r.top + r.height / 2, 1), win.innerHeight - 1);
    let top;
    try { top = el.getRootNode().elementFromPoint ? el.getRootNode().elementFromPoint(x, y) : win.document.elementFromPoint(x, y); } catch (e) { return true; }
    if (!top) return true;
    return top === el || el.contains(top) || top.contains(el) || (el.getRootNode().host && el.getRootNode().host.contains(top));
  }

  function textOfIds(ids, doc) {
    return ids.split(/\s+/).map((id) => { const n = doc.getElementById(id); return n ? n.textContent : ''; }).join(' ');
  }

  function nameOf(el) {
    const doc = el.ownerDocument;
    let n = el.getAttribute('aria-label');
    if (n && n.trim()) return clean(n, 80);
    const by = el.getAttribute('aria-labelledby');
    if (by) { n = clean(textOfIds(by, doc), 80); if (n) return n; }
    if (el.labels && el.labels.length) { n = clean(Array.from(el.labels).map((l) => l.textContent).join(' '), 80); if (n) return n; }
    const tag = el.tagName;
    if (tag === 'INPUT') {
      const t = (el.type || 'text').toLowerCase();
      if (['button', 'submit', 'reset'].includes(t)) return clean(el.value || t, 80);
      if (t === 'image') return clean(el.alt || el.value, 80);
      n = el.placeholder || el.title || el.name || el.getAttribute('autocomplete') || '';
      return clean(n, 80);
    }
    if (tag === 'TEXTAREA') return clean(el.placeholder || el.title || el.name, 80);
    n = clean(el.innerText || el.textContent, 80);
    if (n) return n;
    const img = el.querySelector('img[alt]');
    if (img && img.alt.trim()) return clean(img.alt, 80);
    const svgTitle = el.querySelector('svg title');
    if (svgTitle) return clean(svgTitle.textContent, 80);
    return clean(el.title || el.getAttribute('data-testid') || el.name || el.id || el.getAttribute('href') || '', 80);
  }

  function describe(el) {
    const tag = el.tagName;
    const role = (el.getAttribute('role') || '').toLowerCase();
    const info = { role: 'Element', value: null, checked: null, disabled: false, expanded: null };
    if (tag === 'A') info.role = 'Link';
    else if (tag === 'BUTTON' || tag === 'SUMMARY' || role === 'button') info.role = 'Button';
    else if (tag === 'SELECT' || role === 'combobox' || role === 'listbox') {
      info.role = 'Auswahlliste';
      if (tag === 'SELECT') {
        info.value = clean(Array.from(el.selectedOptions).map((o) => o.text).join(', '), 40);
        info.options = Array.from(el.options).slice(0, 12).map((o) => clean(o.text, 24));
      }
    } else if (tag === 'TEXTAREA' || role === 'textbox' || el.isContentEditable) {
      info.role = 'Textfeld';
      info.value = clean(el.value != null ? el.value : el.textContent, 40);
    } else if (tag === 'INPUT') {
      const t = (el.type || 'text').toLowerCase();
      const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
      if (t === 'password') info.role = 'Passwortfeld';
      else if (ac.startsWith('cc-')) info.role = 'Zahlungsfeld';
      else if (t === 'checkbox') { info.role = 'Checkbox'; info.checked = !!el.checked; }
      else if (t === 'radio') { info.role = 'Auswahlknopf'; info.checked = !!el.checked; }
      else if (['button', 'submit', 'reset', 'image'].includes(t)) info.role = 'Button';
      else if (t === 'search') { info.role = 'Suchfeld'; info.value = clean(el.value, 40); }
      else if (t === 'file') info.role = 'Dateiauswahl';
      else { info.role = 'Eingabefeld'; info.value = clean(el.value, 40); }
    } else if (role === 'link') info.role = 'Link';
    else if (role === 'tab') info.role = 'Tab';
    else if (role === 'checkbox' || role === 'switch' || role === 'menuitemcheckbox') { info.role = role === 'switch' ? 'Schalter' : 'Checkbox'; info.checked = el.getAttribute('aria-checked') === 'true'; }
    else if (role === 'radio' || role === 'menuitemradio') { info.role = 'Auswahlknopf'; info.checked = el.getAttribute('aria-checked') === 'true'; }
    else if (role === 'menuitem') info.role = 'Menüpunkt';
    else if (role === 'option' || role === 'treeitem') info.role = 'Eintrag';
    else if (role === 'searchbox') { info.role = 'Suchfeld'; info.value = clean(el.textContent, 40); }
    if (info.role === 'Passwortfeld' || info.role === 'Zahlungsfeld') info.value = null;  // nie Inhalte preisgeben
    info.disabled = !!el.disabled || el.getAttribute('aria-disabled') === 'true';
    const ex = el.getAttribute('aria-expanded');
    if (ex === 'true' || ex === 'false') info.expanded = ex === 'true';
    return info;
  }

  function look() {
    state.epoch += 1;
    let candidates = collect();
    let visible = candidates.filter(([el, win]) => isVisible(el, win, false));
    if (visible.length < 3) visible = candidates.filter(([el, win]) => isVisible(el, win, true));
    // Reihenfolge wie auf dem Bildschirm: von oben nach unten, zeilenweise von links nach rechts.
    const rows = visible.map(([el, win]) => { const r = el.getBoundingClientRect(); return { el, win, top: Math.round(r.top / 14), left: r.left }; });
    rows.sort((a, b) => a.top - b.top || a.left - b.left);
    const kept = [];
    const items = [];
    for (const { el } of rows) {
      const name = nameOf(el);
      const info = describe(el);
      // Reine Container (onclick auf einem großen Block ohne Namen) und Dubletten überspringen.
      if (!name && info.role === 'Element') continue;
      if (info.role === 'Element' && name.length > 70) continue;
      if (kept.some((k) => k.el.contains(el) && k.name === name && k.role !== 'Textfeld')) continue;
      if (kept.some((k) => k.el === el)) continue;
      kept.push({ el, name, role: info.role });
      items.push({ el, name, info });
      if (items.length > MAX_ITEMS) break;
    }
    const more = items.length > MAX_ITEMS;
    if (more) items.length = MAX_ITEMS;
    state.items = items.map((i) => i.el);
    const doc = document.documentElement;
    const scrollY = window.scrollY || doc.scrollTop || 0;
    return JSON.stringify({
      ok: true, epoch: state.epoch, title: clean(document.title, 120), url: location.href, more,
      below: (doc.scrollHeight - (scrollY + window.innerHeight)) > 60, above: scrollY > 60,
      elements: items.map((it, i) => Object.assign({ n: i + 1, name: it.name }, it.info)),
    });
  }

  function pick(nr, epoch) {
    if (Number(epoch) !== state.epoch) return { error: 'Die Seite wurde seit der letzten Elementliste neu gelesen oder hat sich geändert. Bitte erst browser_look aufrufen.' };
    const el = state.items[Number(nr) - 1];
    if (!el) return { error: `Es gibt kein Element mit der Nummer ${nr}. Bitte browser_look aufrufen.` };
    if (!el.isConnected) return { error: `Element ${nr} ist von der Seite verschwunden. Bitte browser_look aufrufen.` };
    return { el };
  }

  function bring(el) {
    try { el.scrollIntoView({ block: 'center', inline: 'center' }); } catch (e) { /* egal */ }
  }

  function click(nr, epoch) {
    const p = pick(nr, epoch);
    if (p.error) return JSON.stringify({ ok: false, error: p.error });
    const el = p.el;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') return JSON.stringify({ ok: false, error: `Element ${nr} ist deaktiviert.` });
    bring(el);
    // Neue Tabs/Fenster würden im Standardbrowser des Nutzers landen — im selben Fenster bleiben.
    const link = el.closest ? el.closest('a[target]') : null;
    if (link && link.target && link.target !== '_self') link.target = '_self';
    const win = el.ownerDocument.defaultView || window;
    try {
      ['pointerdown', 'mousedown', 'pointerup', 'mouseup'].forEach((t) => el.dispatchEvent(new win.MouseEvent(t, { bubbles: true, cancelable: true, view: win })));
      el.click();
    } catch (e) {
      return JSON.stringify({ ok: false, error: 'Klick fehlgeschlagen: ' + e.message });
    }
    return JSON.stringify({ ok: true });
  }

  function setValue(el, text) {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value');
    // Der native Setter umgeht React/Vue, die den Wert sonst auf den alten zurücksetzen.
    if (setter && setter.set) setter.set.call(el, text); else el.value = text;
  }

  function type(nr, epoch, text, enter) {
    const p = pick(nr, epoch);
    if (p.error) return JSON.stringify({ ok: false, error: p.error });
    const el = p.el;
    const info = describe(el);
    if (info.role === 'Passwortfeld' || info.role === 'Zahlungsfeld') return JSON.stringify({ ok: false, error: 'In Passwort- und Zahlungsfelder tippe ich nicht. Das musst du selbst eingeben.' });
    if (el.disabled || el.readOnly) return JSON.stringify({ ok: false, error: `Element ${nr} ist nicht beschreibbar.` });
    bring(el);
    try { el.focus(); } catch (e) { /* egal */ }
    text = String(text == null ? '' : text);
    if (el.isContentEditable) {
      el.textContent = text;
      el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
    } else if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      setValue(el, text);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      return JSON.stringify({ ok: false, error: `Element ${nr} ist kein Eingabefeld (${info.role}).` });
    }
    if (enter) {
      const opts = { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true };
      const down = new KeyboardEvent('keydown', opts);
      el.dispatchEvent(down);
      el.dispatchEvent(new KeyboardEvent('keypress', opts));
      el.dispatchEvent(new KeyboardEvent('keyup', opts));
      if (!down.defaultPrevented && el.form) {
        try { el.form.requestSubmit(); } catch (e) { try { el.form.submit(); } catch (e2) { /* egal */ } }
      }
    }
    return JSON.stringify({ ok: true });
  }

  function select(nr, epoch, wanted) {
    const p = pick(nr, epoch);
    if (p.error) return JSON.stringify({ ok: false, error: p.error });
    const el = p.el;
    if (el.tagName !== 'SELECT') return JSON.stringify({ ok: false, error: `Element ${nr} ist keine Auswahlliste.` });
    const w = clean(wanted).toLowerCase();
    const opt = Array.from(el.options).find((o) => clean(o.text).toLowerCase() === w || String(o.value).toLowerCase() === w)
      || Array.from(el.options).find((o) => clean(o.text).toLowerCase().includes(w));
    if (!opt) return JSON.stringify({ ok: false, error: `Die Option "${wanted}" gibt es nicht. Optionen: ` + Array.from(el.options).slice(0, 12).map((o) => clean(o.text, 24)).join(', ') });
    el.value = opt.value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return JSON.stringify({ ok: true });
  }

  function scroll(dir) {
    const h = window.innerHeight * 0.8;
    const d = String(dir || 'unten').toLowerCase();
    if (d.startsWith('unt') || d === 'down') window.scrollBy(0, h);
    else if (d.startsWith('ob') || d === 'up') window.scrollBy(0, -h);
    else if (d.startsWith('anf') || d === 'top') window.scrollTo(0, 0);
    else if (d.startsWith('end') || d === 'bottom') window.scrollTo(0, document.documentElement.scrollHeight);
    else return JSON.stringify({ ok: false, error: 'Richtung muss unten, oben, anfang oder ende sein.' });
    return JSON.stringify({ ok: true });
  }

  function read(maxChars) {
    const root = document.querySelector('article') || document.querySelector('main') || document.querySelector('[role=main]') || document.body;
    let text = (root && (root.innerText || root.textContent)) || '';
    text = text.replace(/\r/g, '').replace(/[ \t]+/g, ' ').replace(/\n[ \t]+/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
    const limit = Math.max(500, Math.min(Number(maxChars) || 5000, 12000));
    return JSON.stringify({ ok: true, title: clean(document.title, 120), url: location.href, length: text.length, text: text.slice(0, limit), truncated: text.length > limit });
  }

  window.__jb = { v: 3, look, click, type, select, scroll, read };
})();

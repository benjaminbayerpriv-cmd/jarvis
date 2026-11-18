/* =====================================================================
   Liquid Glass für Jarvis — nachgebaut nach Apples API, mit Werten, die an
   Apples eigener Implementierung gemessen wurden.

   API wie SwiftUI/AppKit:
     .glassEffect()                           glassEffect(el)
     .glassEffect(.regular, in: .capsule)     glassEffect(el, Glass.regular, 'capsule')
     .glassEffect(.clear.interactive(),       glassEffect(el, Glass.clear.interactive(),
                  in: .rect(cornerRadius:16))             { cornerRadius: 16 })
     .glassEffect(.regular.tint(.orange))     glassEffect(el, Glass.regular.tint('#d97757'))
     Glass.identity                           -> kein Glas
   Formen: 'capsule' (Apple-Standard), 'circle', { cornerRadius: n }, 'auto'.

   Herkunft der Werte (macOS 27.2, NSGlassEffectView, zur Laufzeit erzeugt):
   - Layer-Baum ausgelesen: CABackdropLayer mit Filter "glassBackground"
     (inputInnerRefractionAmount -60, inputInnerRefractionHeight 20), Form als
     SDF (CASDFLayer), kein Schlagschatten (inputShadowOpacity 0), Tönung als
     Farbmatrix, Druck-Ebene mit CASDFKeyFillHighlightEffect.
   - Farbantwort gemessen: Glas über 21 einfarbigen Flächen fotografiert.
     Apple bildet die Luminanz über eine Kennlinie ab (dunkles regular:
     Schwarz -> 0,082, Weiß -> 0,49) und gibt die Farbanteile mit festem
     Faktor wieder dazu - deshalb bleibt Farbe kräftig, Helles wird gedeckelt.
   - Rand gemessen: 1 px, zeigt den ungefilterten Hintergrund abgedunkelt
     (regular oben/unten ~50 %, seitlich ~36 %; clear 100 % / 43 %).

   Grenzen: WebKit (Jarvis' Mac-App) kennt keine SVG-Filter als
   backdrop-filter - dort Unschärfe und Farbe per CSS, Rand statisch, ohne
   Brechung. Nicht nachgebaut: GlassEffectContainer (Verschmelzen) und die
   Vibrancy der Inhalte.
   ===================================================================== */
(function () {
  'use strict';

  const SVG_NS = 'http://www.w3.org/2000/svg';
  // Nur Chromium wendet url(#filter) als backdrop-filter an.
  const CAN_LENS = /Chrome\//.test(navigator.userAgent) && !/Firefox\//.test(navigator.userAgent);

  // ------------------------------------------------------------- Glass
  class Glass {
    constructor(variant, tintColor = null, isInteractive = false) {
      this.variant = variant;          // 'regular' | 'clear' | 'identity'
      this.tintColor = tintColor;
      this.isInteractive = isInteractive;
    }
    tint(color) { return new Glass(this.variant, color, this.isInteractive); }
    interactive(on = true) { return new Glass(this.variant, this.tintColor, on); }
  }
  Glass.regular = new Glass('regular');
  Glass.clear = new Glass('clear');
  Glass.identity = new Glass('identity');

  // ------------------------------------------------------ gemessene Werte
  // luma: Kennlinie Hintergrund-Luminanz 0..1 -> Glas (17 Stützstellen).
  // chroma: Faktor, mit dem die Farbanteile (Farbe minus Luminanz) bleiben.
  // rimTop/rimSide: 1-px-Rand = ungefilterter Hintergrund * Faktor (oben/unten
  // bzw. an den Seiten).
  const CLEAR = {
    luma: '0.098 0.142 0.187 0.232 0.277 0.322 0.365 0.408 0.453 0.498 0.542 0.586 0.631 0.676 0.721 0.767 0.812',
    chroma: 1.12, rimTop: 1, rimSide: 0.43,
  };
  const GLASS = {
    dark: {
      regular: {
        luma: '0.082 0.124 0.163 0.199 0.236 0.268 0.298 0.326 0.352 0.378 0.399 0.419 0.437 0.453 0.468 0.479 0.490',
        chroma: 0.78, rimTop: 0.5, rimSide: 0.36,
      },
      clear: CLEAR,
    },
    light: {
      regular: {
        luma: '0.647 0.668 0.689 0.709 0.729 0.748 0.767 0.787 0.806 0.825 0.844 0.863 0.883 0.901 0.918 0.937 0.957',
        chroma: 0.7, rimTop: 0.5, rimSide: 0.36,
      },
      clear: CLEAR,
    },
  };
  // inputBlurRadius 5 bei backdrop .scale 0,25 (regular) bzw. 10 bei 0,5
  // (clear) = 20 px; an Apples Bild abgeglichen (Rest-Welligkeit eines
  // Streifenmusters) als Gauß-σ.
  const BLUR = 15.5;
  // inputInnerRefractionAmount / -Height (beide Varianten gleich).
  const REFRACTION = { amount: 60, height: 20 };
  // Druck-Ebene: Farbmatrix mit +0,147 (regular) / +0,2 (clear).
  const PRESS_LIFT = { regular: 0.1471, clear: 0.2 };

  function luminanceOf(color) {
    const probe = document.createElement('span');
    probe.style.color = color;
    probe.style.display = 'none';
    document.body.appendChild(probe);
    const rgb = getComputedStyle(probe).color.match(/[\d.]+/g) || ['0', '0', '0'];
    probe.remove();
    return rgb.slice(0, 3).map((v) => Number(v) / 255);
  }

  function appearance() {
    const bg = getComputedStyle(document.documentElement).getPropertyValue('--jsBg').trim() || '#151515';
    const [r, g, b] = luminanceOf(bg);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.5 ? 'light' : 'dark';
  }

  // --------------------------------------------------- Form als Distanzfeld
  // Abstand zum Rand (innen positiv) und Randnormale für einen Pixel.
  function sdf(x, y, w, h, r) {
    const hx = w / 2, hy = h / 2;
    const cx = x + 0.5 - hx, cy = y + 0.5 - hy;
    const qx = Math.abs(cx) - (hx - r), qy = Math.abs(cy) - (hy - r);
    if (qx > 0 && qy > 0) {
      const len = Math.hypot(qx, qy) || 1;
      return [r - len, qx / len * Math.sign(cx), qy / len * Math.sign(cy)];
    }
    if (qx > qy) return [r - qx, Math.sign(cx), 0];
    return [r - qy, 0, Math.sign(cy)];
  }

  // Brechungsprofil über die Randzone: gewölbte Kante (Squircle), senkrecht
  // einfallendes Licht, Brechungsindex 1,5; auf 0..1 normiert.
  const height = (t) => Math.pow(1 - Math.pow(1 - t, 4), 0.25);
  const PROFILE = (() => {
    const steps = 128, out = new Float32Array(steps + 1);
    let max = 0;
    for (let i = 0; i <= steps; i++) {
      const t = Math.min(Math.max(i / steps, 0.0005), 0.9995);
      const slope = (height(t + 0.0005) - height(t - 0.0005)) / 0.001;
      const a1 = Math.atan(slope), a2 = Math.asin(Math.sin(a1) / 1.5);
      out[i] = height(t) * Math.tan(a1 - a2);
      max = Math.max(max, out[i]);
    }
    return out.map((v) => v / (max || 1));
  })();
  const profileAt = (t) => PROFILE[Math.round(Math.min(Math.max(t, 0), 1) * (PROFILE.length - 1))];

  function paint(w, h, fn) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const ctx = c.getContext('2d'), img = ctx.createImageData(w, h);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) fn(x, y, img.data, (y * w + x) * 4);
    ctx.putImageData(img, 0, 0);
    return c.toDataURL();
  }

  // Verschiebungskarte: R = x, G = y (128 = keine). Apple bricht nach innen
  // (negativer Amount): Am Rand erscheint gestaucht, was weiter innen liegt.
  function refractionMap(w, h, r) {
    const band = Math.min(REFRACTION.height, Math.min(w, h) / 2 - 1);
    return paint(w, h, (x, y, px, i) => {
      const [d, nx, ny] = sdf(x, y, w, h, r);
      const m = d >= 0 && d < band ? profileAt(d / band) : 0;
      px[i] = 128 - nx * m * 127;
      px[i + 1] = 128 - ny * m * 127;
      px[i + 2] = 128;
      px[i + 3] = 255;
    });
  }

  // 1-px-Randring: Deckkraft = Abdeckung des Rings, Farbe = Faktor je
  // Richtung (oben/unten top, Seiten side).
  function rimMap(w, h, r, top, side) {
    return paint(w, h, (x, y, px, i) => {
      const [d, , ny] = sdf(x, y, w, h, r);
      if (d < 0 || d >= 1.5) return;
      const cover = d < 1 ? 1 : 1.5 - d;
      const f = side + (top - side) * Math.abs(ny);
      px[i] = px[i + 1] = px[i + 2] = Math.round(f * 255);
      px[i + 3] = Math.round(cover * 255);
    });
  }

  // Ohne SVG-Filter (WebKit): statischer Rand - oben/unten leicht hell,
  // seitlich dunkel, wie über dem dunklen Jarvis-Hintergrund gemessen.
  function staticRimMap(w, h, r) {
    return paint(w, h, (x, y, px, i) => {
      const [d, , ny] = sdf(x, y, w, h, r);
      if (d < 0 || d >= 1.5) return;
      const cover = d < 1 ? 1 : 1.5 - d;
      const top = Math.abs(ny);
      px[i] = px[i + 1] = px[i + 2] = top > 0.5 ? 255 : 0;
      px[i + 3] = Math.round(cover * (top > 0.5 ? 0.16 * top : 0.45 * (1 - top)) * 255);
    });
  }

  // ------------------------------------------------------- SVG-Filter
  let defs = null;
  function ensureDefs() {
    if (defs && defs.isConnected) return defs;
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('aria-hidden', 'true');
    svg.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden;pointer-events:none;';
    defs = document.createElementNS(SVG_NS, 'defs');
    svg.appendChild(defs);
    // In #jsApp: Alles andere direkt unter <body> blendet claude-app.js aus.
    (document.getElementById('jsApp') || document.body).appendChild(svg);
    return defs;
  }

  const LUMA_ROW = '0.2126 0.7152 0.0722 0 0';
  let filterSeq = 0;

  // glassBackground als Filterkette: Brechung -> Luminanz-Kennlinie +
  // Farbanteile (bzw. Tönung) pro Pixel -> Unschärfe -> 1-px-Rand aus dem
  // Hintergrund. Die Kennlinie kommt VOR der Unschärfe: nur so trifft der
  // Mittelwert über gemustertem Hintergrund Apples Messung.
  function buildFilter(state, w, h, r, p, tint) {
    const id = state.filterId || (state.filterId = 'lg-glass-' + (++filterSeq));
    let f = document.getElementById(id);
    if (!f) {
      f = document.createElementNS(SVG_NS, 'filter');
      f.id = id;
      ensureDefs().appendChild(f);
    }
    for (const [k, v] of Object.entries({ x: 0, y: 0, width: w, height: h, filterUnits: 'userSpaceOnUse',
      primitiveUnits: 'userSpaceOnUse', 'color-interpolation-filters': 'sRGB' })) f.setAttribute(k, String(v));
    // Tönung (gemessene Farbmatrix): Tönungsfarbe + (1 - Tönung) * 0,27 * Luminanz.
    const face = tint
      ? `<feColorMatrix in="sharp" type="matrix" values="
          ${tint.map((c) => `${(1 - c) * 0.27 * 0.2126} ${(1 - c) * 0.27 * 0.7152} ${(1 - c) * 0.27 * 0.0722} 0 ${c}`).join('\n')}
          0 0 0 0 1" result="face"/>`
      : `<feColorMatrix in="sharp" type="matrix" values="${LUMA_ROW} ${LUMA_ROW} ${LUMA_ROW} 0 0 0 0 1" result="lum"/>
         <feComponentTransfer in="lum" result="curve">
           <feFuncR type="table" tableValues="${p.luma}"/>
           <feFuncG type="table" tableValues="${p.luma}"/>
           <feFuncB type="table" tableValues="${p.luma}"/>
         </feComponentTransfer>
         <feComposite in="sharp" in2="lum" operator="arithmetic" k1="0" k2="1" k3="-1" k4="0.5" result="chroma"/>
         <feComposite in="curve" in2="chroma" operator="arithmetic" k1="0" k2="1" k3="${p.chroma}" k4="${-0.5 * p.chroma}" result="face"/>`;
    f.innerHTML = `
      <feImage href="${refractionMap(w, h, r)}" x="0" y="0" width="${w}" height="${h}" preserveAspectRatio="none" result="map"/>
      <feDisplacementMap in="SourceGraphic" in2="map" scale="${REFRACTION.amount * 2}" xChannelSelector="R" yChannelSelector="G" result="bent"/>
      <feColorMatrix in="bent" type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 0 1" result="sharp"/>
      ${face}
      <feGaussianBlur in="face" stdDeviation="${BLUR}" edgeMode="duplicate" result="soft"/>
      <feColorMatrix in="soft" type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 0 1" result="glass"/>
      <feImage href="${rimMap(w, h, r, p.rimTop, p.rimSide)}" x="0" y="0" width="${w}" height="${h}" preserveAspectRatio="none" result="ring"/>
      <feComposite in="SourceGraphic" in2="ring" operator="arithmetic" k1="1" k2="0" k3="0" k4="0" result="rim"/>
      <feComposite in="rim" in2="glass" operator="over"/>`;
    return id;
  }

  // ------------------------------------------------------- glassEffect
  const states = new WeakMap();

  function radiusFor(el, shape, w, h) {
    if (shape === 'capsule' || shape === 'circle') return Math.min(w, h) / 2;
    if (shape && typeof shape === 'object' && shape.cornerRadius != null) return Math.min(shape.cornerRadius, w / 2, h / 2);
    return Math.min(parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0, w / 2, h / 2);
  }
  function cssRadius(shape) {
    if (shape === 'capsule') return '9999px';
    if (shape === 'circle') return '50%';
    if (shape && typeof shape === 'object' && shape.cornerRadius != null) return shape.cornerRadius + 'px';
    return '';
  }

  function relayout(el, force = false) {
    const state = states.get(el);
    if (!state) return;
    const w = Math.round(el.offsetWidth), h = Math.round(el.offsetHeight);
    if (w < 2 || h < 2) return;  // ausgeblendet - der ResizeObserver meldet sich wieder
    const look = appearance();
    if (!force && state.w === w && state.h === h && state.look === look) return;
    Object.assign(state, { w, h, look });
    const p = GLASS[look][state.glass.variant];
    const r = radiusFor(el, state.shape, w, h);
    el.dataset.lgLook = look;
    if (CAN_LENS) {
      const tint = state.glass.tintColor ? luminanceOf(state.glass.tintColor) : null;
      el.style.setProperty('--lg-backdrop', `url(#${buildFilter(state, w, h, r, p, tint)})`);
    } else {
      el.style.setProperty('--lg-rim', `url(${staticRimMap(w, h, r)})`);
    }
  }

  const resizeObserver = typeof ResizeObserver === 'function'
    ? new ResizeObserver((entries) => entries.forEach((e) => relayout(e.target)))
    : null;

  function onPointerDown(e) { e.currentTarget.classList.add('lg-pressed'); }
  function onPointerUp(e) { e.currentTarget.classList.remove('lg-pressed'); }

  function removeGlassEffect(el) {
    const state = states.get(el);
    if (!state) return;
    el.classList.remove('lg', 'lg-regular', 'lg-clear', 'lg-interactive', 'lg-lens', 'lg-tinted', 'lg-pressed');
    ['--lg-backdrop', '--lg-tint', '--lg-radius', '--lg-rim', '--lg-lift'].forEach((k) => el.style.removeProperty(k));
    delete el.dataset.lgLook;
    if (state.addedRelative) el.style.position = '';
    if (state.origTransition != null) el.style.transition = state.origTransition;
    if (state.filterId) document.getElementById(state.filterId)?.remove();
    if (resizeObserver) resizeObserver.unobserve(el);
    el.removeEventListener('pointerdown', onPointerDown);
    ['pointerup', 'pointerleave', 'pointercancel'].forEach((t) => el.removeEventListener(t, onPointerUp));
    states.delete(el);
  }

  function glassEffect(el, glass = Glass.regular, shape = 'capsule') {
    if (!el) return el;
    removeGlassEffect(el);
    if (!glass || glass.variant === 'identity') return el;

    const state = { glass, shape };
    states.set(el, state);
    el.classList.add('lg', 'lg-' + glass.variant);
    if (CAN_LENS) el.classList.add('lg-lens');
    const radius = cssRadius(shape);
    if (radius) el.style.setProperty('--lg-radius', radius);
    if (glass.tintColor) {
      el.classList.add('lg-tinted');
      el.style.setProperty('--lg-tint', glass.tintColor);
    }
    if (getComputedStyle(el).position === 'static') {
      el.style.position = 'relative';
      state.addedRelative = true;
    }
    if (glass.isInteractive) {
      el.classList.add('lg-interactive');
      el.style.setProperty('--lg-lift', String(PRESS_LIFT[glass.variant]));
      // Vorhandene Inline-Transition (z.B. das Gleiten des Modus-Schiebers)
      // behalten und nur transform anhängen.
      state.origTransition = el.style.transition;
      const extra = 'transform .16s ease-out';
      el.style.transition = state.origTransition ? `${state.origTransition}, ${extra}` : extra;
      el.addEventListener('pointerdown', onPointerDown);
      ['pointerup', 'pointerleave', 'pointercancel'].forEach((t) => el.addEventListener(t, onPointerUp));
    }
    if (resizeObserver) resizeObserver.observe(el);
    relayout(el, true);
    return el;
  }

  window.JarvisGlass = { Glass, glassEffect, removeGlassEffect, supportsLensing: CAN_LENS, parameters: GLASS };

  // ------------------------------------------- Jarvis-Oberfläche verglasen
  // [Selektor, Glas, Form]. Bei jeder DOM-Änderung neu geprüft, weil
  // claude-app.js Menüs, Einstellungen und Sprachmodus erst später aufbaut.
  const RULES = [
    ['#jsApp .js-sidebar', Glass.regular, { cornerRadius: 22 }],
    ['#jsApp .js-composer > div > div:first-child', Glass.regular, { cornerRadius: 26 }],
    ['#jsApp .js-mode', Glass.regular, 'capsule'],
    ['#jsApp .js-mode-indicator', Glass.clear.interactive(), 'capsule'],
    ['#jsApp .js-send', Glass.regular.tint('var(--jsAccent, #d97757)').interactive(), 'circle'],
    ['#jsApp .js-chatitem-menu, #jsApp .js-projects-sort-menu, #jsApp .js-project-card-menu', Glass.regular, { cornerRadius: 16 }],
    ['#jsApp .js-project-card', Glass.regular, { cornerRadius: 18 }],
    ['#jsSettingsSheet > div', Glass.regular, { cornerRadius: 24 }],
    ['#jsSpeechbar > div', Glass.regular, 'capsule'],
    ['#jsSpeechbar > div > button', Glass.clear.interactive(), 'circle'],
    ['#jsSpeechCaption > div', Glass.regular, { cornerRadius: 22 }],
  ];

  function applyAll() {
    for (const [selector, glass, shape] of RULES) {
      document.querySelectorAll(selector).forEach((el) => {
        if (!states.has(el)) glassEffect(el, glass, shape);
      });
    }
  }

  let queued = false;
  function schedule() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; applyAll(); });
  }

  // Theme-Wechsel (hell/dunkel) ändert die Glaswerte.
  let lastLook = null;
  function refreshIfLookChanged() {
    const look = appearance();
    if (look === lastLook) return;
    lastLook = look;
    document.querySelectorAll('.lg').forEach((el) => relayout(el, true));
  }

  function start() {
    lastLook = appearance();
    applyAll();
    new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
    new MutationObserver(refreshIfLookChanged).observe(document.documentElement, { attributes: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();

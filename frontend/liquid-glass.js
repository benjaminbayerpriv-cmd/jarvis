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
  const CLEAR = {
    luma: '0.098 0.142 0.187 0.232 0.277 0.322 0.365 0.408 0.453 0.498 0.542 0.586 0.631 0.676 0.721 0.767 0.812',
    chroma: 1.12,
  };
  const GLASS = {
    dark: {
      regular: {
        luma: '0.082 0.124 0.163 0.199 0.236 0.268 0.298 0.326 0.352 0.378 0.399 0.419 0.437 0.453 0.468 0.479 0.490',
        chroma: 0.78,
      },
      clear: CLEAR,
    },
    light: {
      regular: {
        luma: '0.647 0.668 0.689 0.709 0.729 0.748 0.767 0.787 0.806 0.825 0.844 0.863 0.883 0.901 0.918 0.937 0.957',
        chroma: 0.7,
      },
      clear: CLEAR,
    },
  };
  // Unschärfe als Gauß-σ. Apples NSGlassEffectView liegt bei ~15,5 (an einem
  // Streifenmuster abgeglichen) - das wirkt wie normaler Hintergrund-Blur.
  // Gewünscht ist der klare Liquid-Glass-Look, bei dem Brechung und
  // Lichtkante den Eindruck tragen: deshalb bewusst viel weniger.
  // Einstellbar (Einstellungen -> Erscheinungsbild -> Liquid Glass), in
  // localStorage unter "jarvisGlass". clear nutzt 20 % der Unschärfe.
  const CONFIG_KEY = 'jarvisGlass';
  const DEFAULTS = { enabled: true, blur: 5, refraction: 60, rim: 1 };
  let config = loadConfig();
  function loadConfig() {
    try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(CONFIG_KEY) || '{}') }; } catch (e) { return { ...DEFAULTS }; }
  }
  const blurFor = (variant) => (variant === 'clear' ? config.blur * 0.2 : config.blur);
  // inputInnerRefractionHeight; die Stärke (Apple: 60) ist einstellbar.
  const REFRACTION = { height: 20 };
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

  // --------------------------------------------------------------- Form
  // Apple zeichnet Ecken "continuous" (cornerCurve .continuous, im Layer-Baum
  // als curve=continuous ausgelesen): Die Rundung setzt früher und weicher ein
  // als ein Kreisbogen. Nachgebaut als Superellipse mit Exponent 3,4 über das
  // 1,6-Fache des Radius - so liegt die Ecke bei 45° gleich weit innen wie ein
  // Kreisbogen mit demselben Radius, läuft aber krümmungsstetig in die Kante.
  // Kapseln und Kreise bleiben wie bei Apple echte Halbkreise.
  const CONTINUOUS_N = 3.4, CONTINUOUS_EXTENT = 1.6;
  function geometry(shape, r, w, h) {
    const half = Math.min(w, h) / 2;
    if (shape === 'capsule' || shape === 'circle' || r >= half) return { e: half, n: 2 };
    return { e: Math.min(r * CONTINUOUS_EXTENT, half), n: CONTINUOUS_N };
  }

  // Abstand zum Rand (innen positiv) und Randnormale für einen Pixel.
  function sdf(x, y, w, h, g) {
    const hx = w / 2, hy = h / 2;
    const cx = x + 0.5 - hx, cy = y + 0.5 - hy;
    const qx = Math.abs(cx) - (hx - g.e), qy = Math.abs(cy) - (hy - g.e);
    if (qx > 0 && qy > 0) {
      const rho = Math.pow(Math.pow(qx, g.n) + Math.pow(qy, g.n), 1 / g.n);
      let nx = Math.pow(qx, g.n - 1), ny = Math.pow(qy, g.n - 1);
      const len = Math.hypot(nx, ny) || 1;
      return [g.e - rho, nx / len * Math.sign(cx), ny / len * Math.sign(cy)];
    }
    if (qx > qy) return [g.e - qx, Math.sign(cx), 0];
    return [g.e - qy, 0, Math.sign(cy)];
  }

  // Umriss als clip-path, damit die Glasfläche genau diese Form hat.
  function shapePath(w, h, g) {
    const pts = [];
    const corner = (cx, cy, sx, sy, from) => {
      for (let i = 0; i <= 12; i++) {
        const t = (from + i / 12 * 0.5) * Math.PI;
        const c = Math.cos(t), sn = Math.sin(t);
        const px = Math.sign(c) * Math.pow(Math.abs(c), 2 / g.n) * g.e;
        const py = Math.sign(sn) * Math.pow(Math.abs(sn), 2 / g.n) * g.e;
        pts.push(`${(cx + px * sx).toFixed(2)} ${(cy + py * sy).toFixed(2)}`);
      }
    };
    corner(w - g.e, g.e, 1, -1, 0);      // oben rechts
    corner(g.e, g.e, 1, -1, 0.5);        // oben links
    corner(g.e, h - g.e, 1, -1, 1);      // unten links
    corner(w - g.e, h - g.e, 1, -1, 1.5); // unten rechts
    return `path('M ${pts.join(' L ')} Z')`;
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
  function refractionMap(w, h, g) {
    // Kleine Flächen (Knöpfe, die Schalter-Linse) brechen nur am Rand und
    // bleiben innen klar - sonst verschwimmt alles darunter.
    const band = Math.max(3, Math.min(REFRACTION.height, Math.min(w, h) * 0.3));
    return paint(w, h, (x, y, px, i) => {
      const [d, nx, ny] = sdf(x, y, w, h, g);
      const m = d >= 0 && d < band ? profileAt(d / band) : 0;
      px[i] = 128 - nx * m * 127;
      px[i + 1] = 128 - ny * m * 127;
      px[i + 2] = 128;
      px[i + 3] = 255;
    });
  }

  // Lichtkante: 1 px, nur heller als die Glasfläche, nie dunkler. Apple zeigt
  // an dieser Stelle den abgedunkelten Hintergrund (über dunklem Grund ein
  // fast schwarzer Rand, auch bei SwiftUIs .glassEffect gemessen) - das sah
  // in Jarvis wie ein schwarzer Rahmen aus, deshalb hier bewusst abweichend:
  // Licht von oben, oben am stärksten, unten schwächer, seitlich kaum.
  const RIM = { top: 0.26, bottom: 0.12, side: 0.05 };
  function lightRimMap(w, h, g) {
    return paint(w, h, (x, y, px, i) => {
      const [d, , ny] = sdf(x, y, w, h, g);
      if (d < 0 || d >= 1.5) return;
      const cover = d < 1 ? 1 : 1.5 - d;
      const v = ny < 0 ? RIM.side + (RIM.top - RIM.side) * -ny : RIM.side + (RIM.bottom - RIM.side) * ny;
      px[i] = px[i + 1] = px[i + 2] = 255;
      px[i + 3] = Math.round(Math.min(1, cover * v * config.rim) * 255);
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
  // Farbanteile (bzw. Tönung) pro Pixel -> Unschärfe. Die Kennlinie kommt VOR
  // der Unschärfe: nur so trifft der Mittelwert über gemustertem Hintergrund
  // Apples Messung. Die Lichtkante liegt als eigene Ebene darüber (::after).
  function buildFilter(state, w, h, g, p, tint) {
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
      <feImage href="${refractionMap(w, h, g)}" x="0" y="0" width="${w}" height="${h}" preserveAspectRatio="none" result="map"/>
      <feDisplacementMap in="SourceGraphic" in2="map" scale="${config.refraction * 2}" xChannelSelector="R" yChannelSelector="G" result="bent"/>
      <feColorMatrix in="bent" type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 0 1" result="sharp"/>
      ${face}
      <feGaussianBlur in="face" stdDeviation="${blurFor(state.glass.variant)}" edgeMode="duplicate" result="soft"/>
      <feColorMatrix in="soft" type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 0 1"/>`;
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
    const g = geometry(state.shape, radiusFor(el, state.shape, w, h), w, h);
    el.dataset.lgLook = look;
    el.style.setProperty('--lg-clip', shapePath(w, h, g));
    el.style.setProperty('--lg-rim', `url(${lightRimMap(w, h, g)})`);
    if (CAN_LENS) {
      const tint = state.glass.tintColor ? luminanceOf(state.glass.tintColor) : null;
      el.style.setProperty('--lg-backdrop', `url(#${buildFilter(state, w, h, g, p, tint)})`);
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
    ['--lg-backdrop', '--lg-tint', '--lg-radius', '--lg-rim', '--lg-clip', '--lg-lift'].forEach((k) => el.style.removeProperty(k));
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

  // Schwarz -> durchsichtig (Code-Tab, Sprachmodus-Terminal): Deckkraft aus
  // der Summe der Farbkanäle. Schwarze und fast schwarze Pixel verschwinden,
  // Text - auch dunkelblauer - bleibt deckend.
  function ensureBlackToAlpha() {
    if (document.getElementById('lg-black-transparent')) return;
    const f = document.createElementNS(SVG_NS, 'filter');
    f.id = 'lg-black-transparent';
    f.setAttribute('color-interpolation-filters', 'sRGB');
    f.innerHTML = '<feColorMatrix type="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  1.6 1.6 1.6 0 -0.35"/>';
    ensureDefs().appendChild(f);
  }

  // Einstellungen anwenden: Glas an/aus, Unschärfe, Brechung, Lichtkante.
  function applyConfig() {
    ensureBlackToAlpha();
    const root = document.documentElement;
    root.classList.toggle('lg-on', !!config.enabled);
    root.style.setProperty('--lg-blur-regular', blurFor('regular') + 'px');
    root.style.setProperty('--lg-blur-clear', blurFor('clear') + 'px');
    if (!config.enabled) {
      document.querySelectorAll('.lg').forEach(removeGlassEffect);
      return;
    }
    applyAll();
    document.querySelectorAll('.lg').forEach((el) => relayout(el, true));
  }
  function configure(next) {
    config = { ...config, ...next };
    try { localStorage.setItem(CONFIG_KEY, JSON.stringify(config)); } catch (e) {}
    applyConfig();
    return { ...config };
  }

  window.JarvisGlass = {
    Glass, glassEffect, removeGlassEffect, supportsLensing: CAN_LENS, parameters: GLASS,
    configure, config: () => ({ ...config }), defaults: { ...DEFAULTS },
  };

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
    ['#jsSpeechTerm', Glass.regular, { cornerRadius: 16 }],
    ['#jsApp .js-you .js-text', Glass.regular, { cornerRadius: 18 }],
  ];

  function applyAll() {
    document.querySelectorAll('#jsApp .js-mode').forEach(wireSegmented);
    if (!config.enabled) return;
    for (const [selector, glass, shape] of RULES) {
      document.querySelectorAll(selector).forEach((el) => {
        if (!states.has(el)) glassEffect(el, glass, shape);
      });
    }
  }

  // Startseite | Code wie ein SwiftUI-Schalter (macOS 27, mit echten
  // Mausereignissen an einem SwiftUI-Toggle beobachtet): In Ruhe ein heller
  // Knopf. Gedrückt wird er in ~50 ms zur klaren Glaslinse, rund 1,5-mal so
  // breit und 1,75-mal so hoch, größer als die Schiene, und bricht, was
  // darunter liegt. Beim Ziehen folgt die Linse dem Zeiger, beim Loslassen
  // schrumpft sie federnd zurück und rastet an der näheren Seite ein.
  const SPRING = 'cubic-bezier(.3,1.45,.45,1)';
  function wireSegmented(track) {
    const thumb = track.querySelector('.js-mode-indicator');
    if (!thumb || thumb.dataset.lgSegmented) return;
    thumb.dataset.lgSegmented = '1';
    let last = parseFloat(thumb.style.left) || 0;
    let drag = null;
    const springTransition = `left .5s ${SPRING}, width .5s ${SPRING}, transform .32s ${SPRING}`;
    const pills = () => [...track.querySelectorAll('.js-pill')];

    new MutationObserver(() => {
      // claude-app.js setzt beim Start kurz "none" und danach seine eigene
      // Transition zurück - die Feder wieder einsetzen, sobald es fertig ist.
      const t = thumb.style.transition;
      if (t !== 'none' && t !== springTransition) thumb.style.transition = springTransition;
      const now = parseFloat(thumb.style.left) || 0;
      if (Math.abs(now - last) < 1) return;
      const dir = now > last ? 1 : -1;
      last = now;
      if (t === 'none' || drag) return;  // Erstplatzierung oder Ziehen: keine Tropfen-Animation
      thumb.animate([
        { transform: 'scale(1, 1)' },
        { transform: `translateX(${dir * 3}px) scale(1.22, 0.88)`, offset: 0.35 },
        { transform: `translateX(${-dir * 1.5}px) scale(0.96, 1.05)`, offset: 0.7 },
        { transform: 'scale(1, 1)' },
      ], { duration: 520, easing: 'cubic-bezier(.25,.8,.35,1)', composite: 'add' });
    }).observe(thumb, { attributes: true, attributeFilter: ['style'] });

    track.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      drag = { x: e.clientX, left: parseFloat(thumb.style.left) || 0, moved: false, id: e.pointerId };
      thumb.classList.add('lg-lifted');
    });
    track.addEventListener('pointermove', (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      const dx = e.clientX - drag.x;
      if (!drag.moved) {
        if (Math.abs(dx) < 4) return;
        drag.moved = true;
        // Erst ab echter Bewegung einfangen - ein normaler Klick soll weiter
        // auf dem Knopf (Startseite/Code) landen.
        try { track.setPointerCapture(e.pointerId); } catch (err) {}
        thumb.style.transition = 'none';
      }
      const max = track.clientWidth - thumb.offsetWidth - 1;
      thumb.style.left = Math.min(max, Math.max(1, drag.left + dx)) + 'px';
    });
    const release = (e) => {
      if (!drag || (e && e.pointerId !== drag.id)) return;
      const wasDrag = drag.moved;
      drag = null;
      thumb.classList.remove('lg-lifted');
      if (!wasDrag) return;
      thumb.style.transition = springTransition;
      // An der näheren Seite einrasten.
      const center = thumb.offsetLeft + thumb.offsetWidth / 2;
      const target = pills().reduce((best, p) => {
        const d = Math.abs(p.offsetLeft + p.offsetWidth / 2 - center);
        return !best || d < best.d ? { p, d } : best;
      }, null);
      if (!target) return;
      if (target.p.classList.contains('active')) {
        thumb.style.left = target.p.offsetLeft + 'px';
        thumb.style.width = target.p.offsetWidth + 'px';
      } else {
        target.p.click();
      }
    };
    track.addEventListener('pointerup', release);
    track.addEventListener('pointercancel', release);
    track.addEventListener('lostpointercapture', release);
    track.addEventListener('pointerleave', (e) => { if (drag && !drag.moved) release(e); });
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
    applyConfig();
    new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
    new MutationObserver(refreshIfLookChanged).observe(document.documentElement, { attributes: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();

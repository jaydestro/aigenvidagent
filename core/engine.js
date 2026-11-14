/* Deterministic frame engine: every visual state is a pure function of t (seconds). */
(function () {
  const E = (window.E = {});
  const tracks = new Map(); // element -> [{t0,t1,from,to,ease}]
  const hooks = [];
  const scenes = [];
  const renderConfig = window.AIGENVIDAGENT_RENDER || {};
  E.W = renderConfig.width || 1920; E.H = renderConfig.height || 1080;
  E.DUR = renderConfig.duration ?? (window.META && window.META.duration) ?? 90;
  const stage = document.getElementById('stage');
  const scale = Math.min(E.W / 1920, E.H / 1080);
  document.documentElement.style.setProperty('--render-width', `${E.W}px`);
  document.documentElement.style.setProperty('--render-height', `${E.H}px`);
  if (stage) {
    stage.style.transformOrigin = '0 0';
    stage.style.transform = `translate(${(E.W - 1920 * scale) / 2}px,${(E.H - 1080 * scale) / 2}px) scale(${scale})`;
  }

  // ---------- easing ----------
  const EASE = {
    lin: (x) => x,
    io: (x) => x * x * (3 - 2 * x),
    out: (x) => 1 - Math.pow(1 - x, 3),
    expo: (x) => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)),
    inout: (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
    expoio: (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x < 0.5 ? Math.pow(2, 20 * x - 10) / 2 : (2 - Math.pow(2, -20 * x + 10)) / 2),
    in: (x) => x * x * x,
  };
  E.EASE = EASE;
  E.clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
  E.lerp = (a, b, k) => a + (b - a) * k;
  E.p = (t, a, b, ease = 'expo') => EASE[ease](E.clamp((t - a) / (b - a)));
  E.win = (t, a, b, fi = 0.5, fo = 0.5, ease = 'io') => Math.min(fi ? E.p(t, a, a + fi, ease) : +(t >= a), fo ? 1 - E.p(t, b - fo, b, ease) : +(t < b));

  // ---------- word cues ----------
  const norm = (s) => s.toLowerCase().replace(/[^0-9a-z]/g, '');
  E.cue = (word, n = 0) => {
    const hits = (window.WORDS || []).filter((w) => norm(w[0]) === norm(word));
    if (!hits[n]) throw new Error('cue not found: ' + word + ' #' + n);
    return hits[n][1];
  };
  // first occurrence of `word` starting at or after time `after` (robust to repeated words)
  E.cueAt = (word, after = 0) => {
    const h = (window.WORDS || []).find((w) => norm(w[0]) === norm(word) && w[1] >= after - 1e-3);
    if (!h) throw new Error('cue not found: ' + word + ' after ' + after);
    return h[1];
  };
  // end time of the word occurrence
  E.cueEnd = (word, after = 0) => {
    const h = (window.WORDS || []).find((w) => norm(w[0]) === norm(word) && w[1] >= after - 1e-3);
    if (!h) throw new Error('cue not found: ' + word + ' after ' + after);
    return h[2];
  };
  E.P = (window.META && window.META.para_start) || [];
  E.END = (window.META && window.META.narration_end) || 87;

  // ---------- tracks ----------
  const $ = (s) => (typeof s === 'string' ? document.querySelectorAll(s) : s instanceof Element ? [s] : s);
  E.$ = (s, root = document) => root.querySelector(s);
  E.at = (sel, t0, t1, from, to, ease = 'expo') => {
    $(sel).forEach((el) => {
      if (!tracks.has(el)) tracks.set(el, []);
      tracks.get(el).push({ t0, t1, from, to, ease });
    });
  };
  // convenience: enter (from state -> identity) and exit (identity -> state)
  E.in = (sel, t0, d, from, ease = 'expo') => E.at(sel, t0, t0 + d, from, Object.fromEntries(Object.keys(from).map((k) => [k, DEF[k] ?? 0])), ease);
  E.out = (sel, t0, d, to, ease = 'io') => E.at(sel, t0, t0 + d, Object.fromEntries(Object.keys(to).map((k) => [k, DEF[k] ?? 0])), to, ease);
  E.hook = (fn) => hooks.push(fn);
  E.scene = (sel, t0, t1) => scenes.push({ els: $(sel), t0, t1 });

  const DEF = { o: 1, x: 0, y: 0, z: 0, s: 1, sx: 1, sy: 1, r: 0, rx: 0, ry: 0, blur: 0, bright: 1, sat: 1, draw: 1, reveal: 100, revealY: 100, persp: 0 };
  E.DEF = DEF;

  function evalTracks(list, t) {
    const v = {};
    list.sort((a, b) => a.t0 - b.t0);
    for (const tr of list) {
      for (const k of Object.keys(tr.to)) {
        if (!(k in v)) v[k] = tr.from[k] ?? DEF[k] ?? 0;
        if (t >= tr.t0) {
          const k01 = tr.t1 > tr.t0 ? EASE[tr.ease](E.clamp((t - tr.t0) / (tr.t1 - tr.t0))) : 1;
          const f = tr.from[k] ?? v[k];
          v[k] = typeof tr.to[k] === 'number' ? f + (tr.to[k] - f) * k01 : k01 >= 1 ? tr.to[k] : f;
        }
      }
    }
    return v;
  }

  function apply(el, v) {
    const st = el.style;
    const has = (k) => k in v;
    if (has('o')) st.opacity = v.o;
    const tf = [];
    if (has('persp') && v.persp) tf.push(`perspective(${v.persp}px)`);
    if (has('x') || has('y') || has('z')) tf.push(`translate3d(${v.x ?? 0}px,${v.y ?? 0}px,${v.z ?? 0}px)`);
    if (has('rx')) tf.push(`rotateX(${v.rx}deg)`);
    if (has('ry')) tf.push(`rotateY(${v.ry}deg)`);
    if (has('r')) tf.push(`rotate(${v.r}deg)`);
    if (has('s')) tf.push(`scale(${v.s})`);
    if (has('sx') || has('sy')) tf.push(`scale(${v.sx ?? 1},${v.sy ?? 1})`);
    if (tf.length) st.transform = tf.join(' ');
    const fl = [];
    if (has('blur')) fl.push(`blur(${Math.max(0, v.blur)}px)`);
    if (has('bright')) fl.push(`brightness(${v.bright})`);
    if (has('sat')) fl.push(`saturate(${v.sat})`);
    if (fl.length) st.filter = fl.join(' ');
    if (has('draw')) {
      // SVG stroke drawing: element needs pathLength=1
      st.strokeDasharray = '1 1';
      st.strokeDashoffset = 1 - v.draw;
    }
    if (has('reveal')) st.clipPath = `inset(0 ${100 - v.reveal}% 0 0)`;
    if (has('revealY')) st.clipPath = `inset(${100 - v.revealY}% 0 0 0)`;
    for (const k of Object.keys(v)) if (k.startsWith('--')) st.setProperty(k, v[k]);
  }

  // ---------- typing ----------
  E.type = (sel, text, t0, t1, opts = {}) => {
    const el = E.$(sel);
    E.hook((t) => {
      const n = Math.round(text.length * E.clamp((t - t0) / (t1 - t0)));
      const s = text.slice(0, n);
      el.textContent = s.length ? s : opts.placeholder ?? '';
      el.classList.toggle('typing', t >= t0 && t < t1 + 0.4);
      el.classList.toggle('placeholder', !s.length && !!opts.placeholder);
    });
  };
  // streaming words (assistant response)
  E.stream = (sel, text, t0, t1) => {
    const el = E.$(sel);
    const words = text.split(' ');
    el.innerHTML = words.map((w) => `<span class="sw">${w} </span>`).join('');
    const spans = el.querySelectorAll('.sw');
    E.hook((t) => {
      const k = E.clamp((t - t0) / (t1 - t0));
      spans.forEach((s, i) => {
        const a = E.clamp(k * words.length - i, 0, 1);
        s.style.opacity = a;
        s.style.filter = `blur(${(1 - a) * 4}px)`;
      });
    });
  };

  // ---------- captions ----------
  E.captions = () => {
    const mode = renderConfig.captions || 'static';
    if (mode === 'none') return;
    const box = document.createElement('div');
    box.id = 'cap';
    const span = document.createElement('span');
    box.appendChild(span);
    document.getElementById('stage').appendChild(box);
    const captions = window.CAPTIONS || [];
    const words = window.WORDS || [];
    const phraseWords = new Map();
    if (mode === 'highlight') {
      let wordIndex = 0;
      for (const phrase of captions) {
        let cursor = 0;
        const segments = [];
        while (wordIndex < words.length && cursor < phrase.text.length) {
          const word = words[wordIndex];
          const offset = phrase.text.indexOf(word[0], cursor);
          if (offset < 0) throw new Error('caption word does not match phrase: ' + word[0]);
          segments.push({ prefix: phrase.text.slice(cursor, offset), word });
          cursor = offset + word[0].length;
          wordIndex += 1;
        }
        phraseWords.set(phrase, { segments, suffix: phrase.text.slice(cursor) });
      }
      if (wordIndex !== words.length) throw new Error('caption phrases do not cover every timed word');
    }
    let cur = null;
    let activeWords = [];
    E.hook((t0) => {
      const t = E.T != null ? E.T : t0; // captions always follow the real (audio) clock
      const c = captions.find((p) => t >= p.show && t < p.hide);
      if (c !== cur) {
        cur = c;
        span.textContent = '';
        activeWords = [];
        if (c && mode === 'highlight') {
          const phrase = phraseWords.get(c);
          for (const segment of phrase.segments) {
            span.appendChild(document.createTextNode(segment.prefix));
            const wordSpan = document.createElement('span');
            wordSpan.className = 'cap-word';
            wordSpan.textContent = segment.word[0];
            span.appendChild(wordSpan);
            activeWords.push({ element: wordSpan, word: segment.word });
          }
          span.appendChild(document.createTextNode(phrase.suffix));
        } else {
          span.textContent = c ? c.text : '';
        }
      }
      for (const entry of activeWords) entry.element.classList.toggle('spoken', t >= entry.word[1] && t < entry.word[2]);
      const a = c ? Math.min(1, (t - c.show) / 0.12, (c.hide - t) / 0.12) : 0;
      box.style.opacity = a;
    });
  };

  // ---------- image sequence (portal capture) ----------
  E.sequence = (sel, frames, t0, fps = 30, startIndex = 0) => {
    const host = E.$(sel);
    const imgs = frames.map((src) => {
      const im = new Image();
      im.src = src;
      im.decoding = 'sync';
      im.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;visibility:hidden';
      host.appendChild(im);
      return im;
    });
    let last = -1;
    E.hook((t) => {
      const i = Math.max(0, Math.min(imgs.length - 1, startIndex + Math.floor((t - t0) * fps)));
      if (i !== last) {
        if (last >= 0) imgs[last].style.visibility = 'hidden';
        imgs[i].style.visibility = 'visible';
        last = i;
      }
    });
    return Promise.all(imgs.map((im) => im.decode().catch(() => {})));
  };

  // ---------- render ----------
  // Continuous camera drift: every scene element without its own transform track slowly pushes in
  // and pans across its lifetime, so no frame reads as a static slide.
  const driftOpts = { on: false, amp: 0.045, pan: 14 };
  E.drift = (opts = {}) => Object.assign(driftOpts, { on: true }, opts);
  // Float: a gentle 3D tilt/bob for a panel, product capture or card over [t0, t1].
  E.float = (sel, t0, t1, { ry = 6, rx = 3, bob = 8, persp = 1600, phase = 0 } = {}) => {
    $(sel).forEach((el) => {
      E.hook((t) => {
        if (t < t0 - 0.5 || t > t1 + 0.5) return;
        const k = (t - t0) / Math.max(0.001, t1 - t0);
        const a = Math.sin((t + phase) * 0.9), b = Math.cos((t + phase) * 0.7);
        const tl = tracks.get(el);
        // keep any entrance transform the tracks just applied this frame, then add the float
        const base = tl && tl.some((tr) => ['x', 'y', 's', 'sx', 'sy', 'r', 'rx', 'ry', 'z'].some((key) => key in tr.to)) ? el.style.transform : '';
        el.style.transform = `perspective(${persp}px) ${base} translate3d(0,${(bob * a).toFixed(2)}px,0) rotateY(${(E.lerp(ry, -ry, k) + a * 1.2).toFixed(3)}deg) rotateX(${(rx * b).toFixed(3)}deg)`;
      });
    });
  };
  E.render = (t) => {
    for (const sc of scenes) {
      const vis = t >= sc.t0 && t < sc.t1;
      sc.els.forEach((el) => (el.style.visibility = vis ? 'visible' : 'hidden'));
    }
    for (const [el, list] of tracks) apply(el, evalTracks(list, t));
    if (driftOpts.on) {
      for (const sc of scenes) {
        if (t < sc.t0 || t >= sc.t1) continue;
        const k = (t - sc.t0) / Math.max(0.001, sc.t1 - sc.t0);
        sc.els.forEach((el, i) => {
          const tl = tracks.get(el);
          if (tl && tl.some((tr) => ['x', 'y', 's', 'sx', 'sy', 'r', 'rx', 'ry', 'z'].some((key) => key in tr.to))) return;
          if (el.dataset.nodrift) return;
          const s = 1 + driftOpts.amp * E.EASE.inout(k);
          const dir = (sc.t0 * 7.13 + i) % 2 < 1 ? 1 : -1;
          const px = dir * driftOpts.pan * (k - 0.5) * 2;
          el.style.transformOrigin = '50% 46%';
          el.style.transform = `translate3d(${px.toFixed(2)}px,0,0) scale(${s.toFixed(4)})`;
        });
      }
    }
    return Promise.all(hooks.map((fn) => fn(t)));
  };
  window.render = async (T) => {
    // Optional word-aligned time warp: visuals choreographed to one take play in sync with another.
    let t = T;
    const Wp = window.WARP;
    if (Wp && Wp.length > 1) {
      if (T >= Wp[Wp.length - 1][0]) t = Wp[Wp.length - 1][1] + (T - Wp[Wp.length - 1][0]);
      else {
        let lo = 0, hi = Wp.length - 1;
        while (hi - lo > 1) { const m = (lo + hi) >> 1; if (Wp[m][0] <= T) lo = m; else hi = m; }
        const [a0, b0] = Wp[lo], [a1, b1] = Wp[hi];
        t = b0 + (b1 - b0) * ((T - a0) / Math.max(1e-6, a1 - a0));
      }
    }
    E.T = T;
    await E.render(t);
    if (E.afterRender) await E.afterRender(t);
    return true;
  };
  E.ready = async (extra = []) => {
    await document.fonts.ready;
    const imgs = [...document.images].map((im) => im.decode().catch(() => {}));
    await Promise.all([...imgs, ...extra]);
    await window.render(Number(new URLSearchParams(location.search).get('t') || 0));
    window.READY = true;
  };

  // numbered image sequence helper: E.frames('../assets/clip/', 120) -> ['../assets/clip/0001.png', ...]
E.frames = (dir, n) => Array.from({ length: n }, (_, i) => `${dir}${String(i + 1).padStart(4, '0')}.png`);
})();

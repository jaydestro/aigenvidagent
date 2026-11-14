// aigenvidagent example: three beats keyed to the spoken words of takes/example.
import { svgEl, htmlEl, orthoGlobe } from '../core/geo.js';

const W = document.getElementById('world');
const P = E.P;            // paragraph start times from the take
const END = E.END;        // narration end
const C = (w, n = 0) => E.cue(w, n);
E.drift({ amp: 0.035, pan: 10 }); // continuous camera drift: nothing reads as a static slide

function scene(id, t0, t1) {
  const d = htmlEl('div', { class: 'scene', id }, W);
  E.scene(d, t0 - 0.01, t1 + 0.01);
  E.at(d, t0, t0 + 0.4, { o: 0 }, { o: 1 }, 'io');
  E.at(d, t1 - 0.4, t1, { o: 1 }, { o: 0 }, 'io');
  return d;
}
function text(p, cls, html, y, t0, size) {
  const n = htmlEl('div', { class: cls }, p, html);
  n.style.top = y + 'px';
  if (size) n.style.fontSize = size + 'px';
  E.in(n, t0, 0.8, { o: 0, y: 24, blur: 10 });
  return n;
}

// Beat 1: the promise, with a rotating globe for reach
{
  const s = scene('b1', 0, P[1]);
  const g = svgEl('svg', { class: 'fill', viewBox: '0 0 1920 1080' }, s);
  const globe = orthoGlobe(g, { cx: 960, cy: 600, r: 260 });
  E.hook((t) => { if (t < P[1] + 0.5) globe.update(-40 + t * 6, -15); });
  E.in(g, 0.1, 1.0, { o: 0, s: 0.9 });
  text(s, 'title', 'Every great launch starts with a story', 150, C('story') - 0.4, 84);
}

// Beat 2: the pipeline, revealed step by step on the spoken words
{
  const s = scene('b2', P[1], P[2]);
  text(s, 'title', 'Script to film, frame by frame', 150, P[1] + 0.1, 76);
  const steps = [['Script', 'script'], ['Narration', 'narrated'], ['Captions', 'captioned'], ['Film', 'film']];
  steps.forEach(([label, word], i) => {
    const x = 240 + i * 380;
    const el = text(s, 'step', label, 520, C(word) - 0.2);
    el.style.left = x + 'px';
    const ring = htmlEl('div', { class: 'abs' }, s);
    ring.style.cssText = `left:${x + 130}px;top:400px;width:100px;height:100px;border-radius:50%;border:3px solid #4fd8ff`;
    E.in(ring, C(word) - 0.3, 0.6, { o: 0, s: 0.6 });
  });
}

// Beat 3: the call to action, three chips on their words
{
  const s = scene('b3', P[2], END + 0.4);
  [['Lock the words', 'Lock', 300], ['Shape the visuals', 'shape', 480], ['Ship with confidence', 'ship', 660]].forEach(([label, word, y]) => {
    const c = text(s, 'chip', label, y, C(word) - 0.15);
    c.style.left = '50%'; c.style.marginLeft = '-300px'; c.style.width = '600px'; c.style.textAlign = 'center';
  });
}

// End card: silent hold after narration
{
  const s = scene('end', END + 0.3, 999);
  text(s, 'title', 'aigenvidagent', 440, END + 0.4, 140);
}

E.captions();
E.ready([]);

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor() {
    this.children = [];
    this.value = '';
    this.style = { setProperty(name, value) { this[name] = value; } };
    this.classes = new Set();
    this.classList = { toggle: (name, active) => active ? this.classes.add(name) : this.classes.delete(name) };
  }
  appendChild(child) { this.children.push(child); return child; }
  set textContent(value) { this.value = value; this.children = []; }
  get textContent() { return this.value + this.children.map(child => child.textContent).join(''); }
}

function engine(config = {}) {
  const stage = new Element();
  const document = {
    documentElement: new Element(),
    getElementById: () => stage,
    createElement: () => new Element(),
    createTextNode: text => ({ textContent: text }),
    fonts: { ready: Promise.resolve() },
    images: [],
  };
  const window = {
    AIGENVIDAGENT_RENDER: config,
    CAPTIONS: [{ text: 'Go, go again!', show: 0, hide: 4 }],
    WORDS: [['Go,', 0.1, 0.5], ['go', 1, 1.4], ['again!', 2, 2.5]],
  };
  const context = { window, document, Element, URLSearchParams, location: { search: '' } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../core/engine.js'), 'utf8'), context);
  return { window, document, stage, engine: window.E };
}

test('output dimensions and total duration fit the entire legacy stage into portrait', () => {
  const result = engine({ width: 1080, height: 1920, duration: 24 });
  assert.equal(result.engine.W, 1080);
  assert.equal(result.engine.H, 1920);
  assert.equal(result.engine.DUR, 24);
  assert.equal(result.stage.style.transform, 'translate(0px,656.25px) scale(0.5625)');
  assert.equal(result.document.documentElement.style['--render-height'], '1920px');
});

test('default render dimensions preserve the legacy composition', () => {
  const result = engine();
  assert.equal(result.stage.style.transform, 'translate(0px,0px) scale(1)');
  assert.equal(result.engine.DUR, 90);
});

test('none creates no caption element', () => {
  const result = engine({ captions: 'none' });
  result.engine.captions();
  assert.equal(result.stage.children.length, 0);
});

test('static preserves the exact phrase and clears it after a seek', async () => {
  const result = engine({ captions: 'static' });
  result.engine.captions();
  await result.window.render(1.1);
  assert.equal(result.stage.children[0].textContent, 'Go, go again!');
  await result.window.render(5);
  assert.equal(result.stage.children[0].textContent, '');
  await result.window.render(0.2);
  assert.equal(result.stage.children[0].textContent, 'Go, go again!');
});

test('highlight uses timed word indices including repeated words and backward seeks', async () => {
  const result = engine({ captions: 'highlight' });
  result.engine.captions();
  const active = () => result.stage.children[0].children[0].children
    .filter(child => child.classes && child.classes.has('spoken')).map(child => child.textContent);
  for (const [timestamp, expected] of [[1.1, ['go']], [0.2, ['Go,']], [1.6, []], [2.2, ['again!']], [0.2, ['Go,']]]) {
    await result.window.render(timestamp);
    assert.deepEqual(active(), expected);
    assert.equal(result.stage.children[0].textContent, 'Go, go again!');
  }
});

test('ready waits for asynchronous render hooks and afterRender', async () => {
  const result = engine();
  const events = [];
  result.engine.hook(async () => { await Promise.resolve(); events.push('hook'); });
  result.engine.afterRender = async () => { await Promise.resolve(); events.push('after'); };
  await result.engine.ready();
  assert.deepEqual(events, ['hook', 'after']);
  assert.equal(result.window.READY, true);
});
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { mkdtemp, mkdir, writeFile, readFile, rm } = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { test } = require('node:test');

const root = path.resolve(__dirname, '..');
const script = path.join(root, 'tools', 'build.mjs');
const loadBuilder = () => import(pathToFileURL(script).href);

test('builds a project with spaces via the CLI from another working directory', async () => {
  const temporary = await mkdtemp(path.join(os.tmpdir(), 'aigenvidagent build '));
  try {
    const project = path.join(temporary, 'film with spaces');
    await mkdir(project);
    await writeFile(path.join(project, 'main.js'), 'globalThis.aigenvidagentBuildTest = 42;\n');
    const result = spawnSync(process.execPath, [script, project], {
      cwd: temporary, encoding: 'utf8',
    });
    assert.equal(result.status, 0, result.stderr);
    const bundle = await readFile(path.join(project, 'bundle.js'), 'utf8');
    assert.match(bundle, /aigenvidagentBuildTest/);
    assert.match(bundle, /\(\(\) =>/);
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});

test('requires exactly one project argument', () => {
  for (const args of [[], ['example', 'unexpected']]) {
    const result = spawnSync(process.execPath, [script, ...args], { cwd: root, encoding: 'utf8' });
    assert.equal(result.status, 1);
    assert.match(result.stderr, /Usage:/);
  }
});

test('rejects missing main.js without creating a bundle', async () => {
  const { buildProject } = await loadBuilder();
  const temporary = await mkdtemp(path.join(os.tmpdir(), 'aigenvidagent empty '));
  try {
    await assert.rejects(buildProject(temporary), /must contain main.js/);
    await assert.rejects(readFile(path.join(temporary, 'bundle.js')), { code: 'ENOENT' });
    await assert.rejects(buildProject(), /Usage:/);
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});

test('bundles the real example without changing its tracked output', async () => {
  const { buildProject } = await loadBuilder();
  const result = await buildProject(path.join(root, 'example'), { write: false });
  assert.equal(result.outputFiles.length, 1);
  assert.ok(result.outputFiles[0].contents.length > 0);
});
import { stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

export async function buildProject(project, options = {}) {
  if (!project || typeof project !== 'string') {
    throw new Error('Usage: npm run build -- <project-directory>');
  }
  const projectRoot = path.resolve(project);
  const entryPoint = path.join(projectRoot, 'main.js');
  if (!(await stat(entryPoint).catch(() => null))?.isFile()) {
    throw new Error(`Project must contain main.js: ${projectRoot}`);
  }
  return build({
    entryPoints: [entryPoint],
    bundle: true,
    format: 'iife',
    outfile: path.join(projectRoot, 'bundle.js'),
    write: options.write ?? true,
    logLevel: 'silent',
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv.length !== 3) {
      throw new Error('Usage: npm run build -- <project-directory>');
    }
    await buildProject(process.argv[2]);
    console.log(`Built ${path.resolve(process.argv[2], 'bundle.js')}`);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
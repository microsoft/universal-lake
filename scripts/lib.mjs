// Shared helpers for the build scripts: paths, command-line arguments and config.json.
import { existsSync, readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const OUT = join(ROOT, 'out');
export const NOTEBOOKS_SRC = join(ROOT, 'notebooks');
export const MODELS_SRC = join(ROOT, 'models');

export function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

export function loadUserConfig() {
  const file = resolve(arg('config', join(ROOT, 'config.json')));
  if (!existsSync(file)) throw new Error(`No config at ${file}. Copy config.template.json to config.json and fill it in.`);
  const cfg = JSON.parse(readFileSync(file, 'utf8'));
  // The build's catalog calls the Copilot interactions source 'core'.
  if (cfg.dataSources && 'copilotInteractions' in cfg.dataSources) {
    cfg.dataSources.core = cfg.dataSources.copilotInteractions;
    delete cfg.dataSources.copilotInteractions;
  }
  return { file, cfg };
}

/** This repo's commit, so out/SOURCE.lock.json records what the notebooks were built from. */
export function gitHead() {
  try {
    return execFileSync('git', ['-C', ROOT, 'rev-parse', 'HEAD'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
  } catch {
    return 'unknown';
  }
}

export const PLACEHOLDER = (name) => `<${name}>`;
export const isSet = (v) => typeof v === 'string' && v.length > 0 && !v.startsWith('<');

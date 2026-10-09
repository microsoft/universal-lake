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

/** Removes // line comments outside strings, so config.json can carry guidance (URLs in strings are kept). */
export function stripJsonComments(text) {
  let out = '', inStr = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inStr) {
      out += c;
      if (c === '\\') out += text[++i] ?? '';
      else if (c === '"') inStr = false;
    } else if (c === '"') { inStr = true; out += c; }
    else if (c === '/' && text[i + 1] === '/') { while (i < text.length && text[i] !== '\n') i++; out += '\n'; }
    else out += c;
  }
  return out;
}

export function loadUserConfig() {
  const file = resolve(arg('config', join(ROOT, 'config.json')));
  if (!existsSync(file)) throw new Error(`No config at ${file}. Copy config.template.json to config.json and fill it in.`);
  let cfg;
  try { cfg = JSON.parse(stripJsonComments(readFileSync(file, 'utf8'))); }
  catch (e) { throw new Error(`${file} is not valid JSON (check quotes and commas): ${e.message}`); }
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

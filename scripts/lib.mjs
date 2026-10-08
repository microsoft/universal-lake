// Shared helpers: read config.json, locate the pinned source repo clone, import the installer's own modules.
import { existsSync, readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const OUT = join(ROOT, 'out');

export function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

export function loadUserConfig() {
  const file = resolve(arg('config', join(ROOT, 'config.json')));
  if (!existsSync(file)) throw new Error(`No config at ${file}. Copy config.template.json to config.json and fill it in.`);
  const cfg = JSON.parse(readFileSync(file, 'utf8'));
  cfg.sourceRepo = process.env.SOURCE_REPO || cfg.sourceRepo;
  if (!cfg.sourceRepo || !existsSync(join(cfg.sourceRepo, '1. Fabric', 'installer', 'src', 'catalog.js'))) {
    throw new Error(`sourceRepo (${cfg.sourceRepo}) is not a clone of the source repo. Set it in config.json or the SOURCE_REPO env var.`);
  }
  return { file, cfg };
}

/** HEAD of the clone, and whether it matches the pinned commit and is clean. */
export function sourceState(repo, pinned) {
  const git = (...a) => execFileSync('git', ['-C', repo, ...a], { encoding: 'utf8' }).trim();
  let head = 'unknown', dirty = [];
  try {
    head = git('rev-parse', 'HEAD');
    dirty = git('status', '--porcelain', '--', '1. Fabric').split('\n').filter(Boolean);
  } catch { /* not a git checkout */ }
  return { head, pinned, matchesPin: !pinned || head === pinned, dirty };
}

export const fabricDir = (repo) => join(repo, '1. Fabric');

/** Imports a module from the clone's installer, e.g. installer('catalog.js'). */
export const installer = (repo, rel) => import(pathToFileURL(join(fabricDir(repo), 'installer', 'src', rel)).href);

export const PLACEHOLDER = (name) => `<${name}>`;
export const isSet = (v) => typeof v === 'string' && v.length > 0 && !v.startsWith('<');

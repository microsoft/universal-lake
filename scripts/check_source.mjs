// Confirms the source repo clone is the pinned, unmodified commit before anything is generated from it.
import { loadUserConfig, sourceState } from './lib.mjs';

const { cfg } = loadUserConfig();
const s = sourceState(cfg.sourceRepo, cfg.pinnedCommit);
console.log(`Source clone    : ${cfg.sourceRepo}`);
console.log(`HEAD            : ${s.head}`);
console.log(`Pinned          : ${s.pinned ?? '(none)'}`);
if (!s.matchesPin) console.warn('WARNING: HEAD is not the pinned commit. Either check out the pin or update pinnedCommit deliberately.');
if (s.dirty.length) {
  console.warn(`WARNING: ${s.dirty.length} local change(s) under "1. Fabric" will be baked into the output:`);
  for (const l of s.dirty.slice(0, 20)) console.warn(`  ${l}`);
}
if (s.matchesPin && !s.dirty.length) console.log('OK: source matches the pin.');
process.exitCode = process.argv.includes('--strict') && (!s.matchesPin || s.dirty.length) ? 1 : 0;

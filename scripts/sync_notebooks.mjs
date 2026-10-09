// Fills this repo's notebooks (notebooks/) with the IDs from config.json, for manual import into Fabric.
// Only the notebooks for the data sources you chose are written.
//
//   node scripts/sync_notebooks.mjs [--config config.json]
//
// Output: out/notebooks/<DisplayName>.ipynb, out/notebooks/MANIFEST.json, out/SOURCE.lock.json
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join } from 'node:path';
import { NOTEBOOKS_SRC, OUT, PLACEHOLDER, gitHead, isSet, loadUserConfig } from './lib.mjs';
import { NOTEBOOKS_DIR, normaliseModules, notebooksFor, permissionsFor } from './build/catalog.js';
import { prepareNotebook, serialiseNotebook } from './build/notebook.js';
import { notebookOptions, notebookSettings } from './build/settings.js';
import { modulesFromSources, normaliseDataSources } from './build/uploads.js';

const { file, cfg } = loadUserConfig();

const warnings = [];
const need = (value, name) => {
  if (isSet(value)) return value;
  warnings.push(`${name} is not set: a placeholder was written. Fill config.json and re-run, or edit the notebook in Fabric.`);
  return PLACEHOLDER(name);
};

// The build's working settings, filled from config.json below.
const config = {
  modules: normaliseModules(undefined),
  dataSources: {},
  history: {},
  app: {},
  keyVault: {},
  fabric: { notebooks: {} },
  semanticModel: { name: 'Universal Lake Model' },
  consumption: {},
  agentEvaluator: { environments: [] },
};
config.dataSources = normaliseDataSources(cfg.dataSources, config.modules, { azureSubscriptionId: cfg.azure?.subscriptionId });
config.modules = modulesFromSources(config.dataSources);
config.history = { days: cfg.backfillDays ?? 30 };
config.app.appId = need(cfg.appId, 'appId');
// Key Vault is the default. Without a vault URI, a clientSecret in config.json is written into the notebooks instead
// ('notebook' mode). Not recommended: anyone who can open the notebooks can read it.
const filled = (v) => isSet(v) && !v.includes('<');
const inlineSecret = !filled(cfg.keyVault?.uri) && filled(cfg.clientSecret);
if (inlineSecret) {
  config.keyVault = { secretName: cfg.keyVault?.secretName || 'universal-lake-client-secret', mode: 'notebook' };
  warnings.push('No keyVault.uri: the client secret from config.json is written INTO the notebooks. Anyone who can open them can read it. Move it to Key Vault as soon as you can (see 02-permissions).');
} else {
  config.keyVault = { uri: need(cfg.keyVault?.uri, 'keyVault.uri'), secretName: cfg.keyVault?.secretName || 'universal-lake-client-secret', mode: 'keyvault' };
  if (isSet(cfg.clientSecret)) warnings.push('Both keyVault.uri and clientSecret are set: Key Vault is used. Delete clientSecret from config.json.');
}
config.fabric = {
  notebooks: {},
  workspaceId: need(cfg.workspace?.id, 'workspace.id'),
  lakehouseId: need(cfg.lakehouse?.id, 'lakehouse.id'),
  lakehouseName: cfg.lakehouse?.name || 'UniversalLake_LH',
};
// The refresh notebook ships with the model id it refreshes; the orchestrator passes it again at run time.
config.semanticModel = { ...config.semanticModel, enabled: true, bound: true, id: cfg.semanticModels?.universal?.id || PLACEHOLDER('semanticModels.universal.id') };
const subscription = cfg.azure?.subscriptionId || '';
config.consumption = {
  ...config.consumption,
  azureSubscriptionId: subscription,
  azureAccess: !!subscription,
  paygSubscriptions: (cfg.azure?.paygSubscriptions ?? []).map((p) => (typeof p === 'string' ? { subscriptionId: p, access: true } : { access: true, ...p })),
};
const envs = (cfg.dataverseEnvironments ?? []).filter((e) => isSet(e.url) && !e.url.includes('<'));
config.agentEvaluator = { ...config.agentEvaluator, environments: envs.map((e) => ({ url: e.url.replace(/\/$/, ''), name: e.name ?? '', access: true })) };
if (config.dataSources.azureAi === 'api' && !subscription) warnings.push('dataSources.azureAi is "api" but azure.subscriptionId is empty: the Azure AI notebook is left out.');
if (config.dataSources.agentEvaluator === 'api' && !envs.length) warnings.push('dataSources.agentEvaluator is "api" but no dataverseEnvironments are set: the transcript parser is left out.');

const ctx = { config, user: { tenantId: need(cfg.tenantId, 'tenantId') }, pendingSecret: inlineSecret ? cfg.clientSecret : undefined };
const selected = notebooksFor(config.modules, notebookOptions(config));

const dir = join(OUT, 'notebooks');
rmSync(dir, { recursive: true, force: true });
mkdirSync(dir, { recursive: true });

const manifest = [];
for (const nb of selected) {
  const rel = [nb.dir ?? NOTEBOOKS_DIR, nb.file].filter((p) => p && p !== '.').join('/');
  const src = join(NOTEBOOKS_SRC, rel);
  const raw = readFileSync(src, 'utf8');
  const prepared = serialiseNotebook(prepareNotebook(JSON.parse(raw), notebookSettings(ctx, nb)));
  const outName = `${nb.displayName}.ipynb`;
  writeFileSync(join(dir, outName), prepared);
  manifest.push({
    key: nb.key,
    displayName: nb.displayName,
    module: nb.module,
    file: outName,
    source: `notebooks/${rel}`,
    sourceSha256: createHash('sha256').update(raw).digest('hex'),
    outputSha256: createHash('sha256').update(prepared).digest('hex'),
  });
}

const head = gitHead();
const lock = {
  generatedUtc: new Date().toISOString(),
  config: file,
  head,
  modules: config.modules,
  dataSources: config.dataSources,
  secretMode: inlineSecret ? 'notebook' : 'keyvault',
  graphPermissions: permissionsFor(config.modules, config.dataSources),
  notebooks: manifest,
};
const lockFile = join(OUT, 'SOURCE.lock.json');
const previous = existsSync(lockFile) ? JSON.parse(readFileSync(lockFile, 'utf8')) : null;
writeFileSync(join(dir, 'MANIFEST.json'), JSON.stringify(manifest, null, 2));
writeFileSync(lockFile, JSON.stringify(lock, null, 2));

console.log(`Wrote ${manifest.length} notebooks to ${dir}`);
for (const m of manifest) console.log(`  ${m.module.padEnd(15)} ${m.displayName}`);
console.log(`\nGraph application permissions needed: ${lock.graphPermissions.join(', ')}`);

if (previous?.notebooks) {
  const before = new Map(previous.notebooks.map((n) => [n.displayName, n.outputSha256]));
  const after = new Map(manifest.map((n) => [n.displayName, n.outputSha256]));
  const added = [...after.keys()].filter((k) => !before.has(k));
  const removed = [...before.keys()].filter((k) => !after.has(k));
  const changed = [...after.keys()].filter((k) => before.has(k) && before.get(k) !== after.get(k));
  console.log(`\nSince the previous sync (${previous.head?.slice(0, 7) ?? '?'} -> ${head.slice(0, 7)}):`);
  if (!added.length && !removed.length && !changed.length) console.log('  no notebook changed; nothing to re-import');
  for (const k of changed) console.log(`  changed  ${k}   <- re-import`);
  for (const k of added) console.log(`  new      ${k}   <- import`);
  for (const k of removed) console.log(`  removed  ${k}   <- delete from the workspace if no longer used`);
}
for (const w of [...new Set(warnings)]) console.warn(`WARNING: ${w}`);

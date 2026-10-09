// Builds the semantic model definitions from models/*.bim for the data sources you chose, then points
// them at the Lakehouse's gold schema instead of dbo. Nothing is deployed: Lake_Deploy_Models.ipynb (or the UI) does that.
//
//   node scripts/build_models.mjs [--config config.json] [--schema gold]
//
// Output, per model: out/models/<Name>/model.bim, definition.pbism, definition.json (REST payload)
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { MODELS_SRC, OUT, PLACEHOLDER, arg, isSet, loadUserConfig } from './lib.mjs';
import * as m from './build/model.js';
import { normaliseModules } from './build/catalog.js';
import { modulesFromSources, normaliseDataSources } from './build/uploads.js';

const { cfg } = loadUserConfig();
const schema = arg('schema', cfg.modelSchema || 'gold');

const server = isSet(cfg.lakehouse?.sqlEndpoint) ? cfg.lakehouse.sqlEndpoint : PLACEHOLDER('lakehouse.sqlEndpoint');
const database = cfg.lakehouse?.name || 'UniversalLake_LH';
const modules = modulesFromSources(normaliseDataSources(cfg.dataSources, normaliseModules(undefined), { azureSubscriptionId: cfg.azure?.subscriptionId }));

const MODELS = [
  { key: 'universal', name: cfg.semanticModels?.universal?.name || 'Universal Lake Model', template: 'universal.bim', build: (t) => m.buildModel(t, { server, database, modules }), on: true },
  { key: 'consumption', name: cfg.semanticModels?.consumption?.name || 'Universal Lake Consumption Model', template: 'consumption.bim', build: (t) => m.buildConsumptionModel(t, { server, database }), on: modules.consumption },
  { key: 'agentEvaluator', name: cfg.semanticModels?.agentEvaluator?.name || 'Universal Lake Agent Evaluator Model', template: 'agentEvaluator.bim', build: (t) => m.buildAgentEvaluatorModel(t, { server, database }), on: modules.agentEvaluator },
];

// Every place a model picks the Lakehouse schema: `each [Schema] = "dbo"` in its table-reader helper.
// Error messages that mention "dbo tables" are reworded too, so a failure names the schema actually read.
const SCHEMA_RE = /(\[Schema\]\s*=\s*)"dbo"/g;
const swap = (text) => {
  let n = 0;
  const out = text
    .replace(SCHEMA_RE, (_, pre) => { n++; return `${pre}"${schema}"`; })
    .replace(/\b(no|other) dbo (tables|objects)\b/g, `$1 ${schema} $2`);
  return { out, n };
};
function retarget(bim) {
  let count = 0;
  const fix = (holder, key) => {
    const v = holder[key];
    const text = Array.isArray(v) ? v.join('\n') : v;
    if (typeof text !== 'string') return;
    const { out, n } = swap(text);
    if (n) { count += n; holder[key] = Array.isArray(v) ? out.split('\n') : out; }
  };
  for (const e of bim.model.expressions ?? []) fix(e, 'expression');
  for (const t of bim.model.tables ?? []) for (const p of t.partitions ?? []) if (p.source) fix(p.source, 'expression');
  return count;
}

// Lakehouse tables a model reads: its partitions call a reader helper such as FabricTable("x") or GetTable("x").
function lakehouseTables(bim) {
  const names = new Set();
  const scan = (e) => {
    const text = Array.isArray(e) ? e.join('\n') : e || '';
    for (const [, name] of text.matchAll(/\b(?:FabricTable|GetTable|TryTable|OptionalTable)\(\s*"([A-Za-z][A-Za-z0-9_]*)"/g)) names.add(name.toLowerCase());
  };
  for (const x of bim.model.expressions ?? []) scan(x.expression);
  for (const t of bim.model.tables ?? []) for (const p of t.partitions ?? []) scan(p.source?.expression);
  return [...names].sort();
}

const requiredTables = {};
const dir = join(OUT, 'models');
rmSync(dir, { recursive: true, force: true });
const summary = [];
for (const model of MODELS) {
  if (!model.on) { summary.push({ key: model.key, name: model.name, skipped: 'module not enabled' }); continue; }
  const templatePath = join(MODELS_SRC, model.template);
  if (!existsSync(templatePath)) throw new Error(`Template not found: ${templatePath}`);
  const bim = model.build(m.loadTemplateModel(templatePath));
  const replaced = schema === 'dbo' ? 0 : retarget(bim);
  if (schema !== 'dbo' && replaced === 0) throw new Error(`${model.name}: found no "dbo" schema reference to replace. models/${model.template} changed; review before deploying.`);
  const leftover = JSON.stringify(bim).match(/\[Schema\]\s*=\s*\\"dbo\\"/g)?.length ?? 0;
  const out = join(dir, model.key);
  mkdirSync(out, { recursive: true });
  writeFileSync(join(out, 'model.bim'), JSON.stringify(bim, null, 2));
  writeFileSync(join(out, 'definition.pbism'), JSON.stringify(m.PBISM, null, 2));
  writeFileSync(join(out, 'definition.json'), JSON.stringify({ displayName: model.name, definition: m.semanticModelDefinition(bim, m.PBISM) }));
  const relationships = (bim.model.relationships ?? []).map((r) => `${r.fromTable}[${r.fromColumn}] -> ${r.toTable}[${r.toColumn}]${r.isActive === false ? ' (inactive)' : ''}`);
  writeFileSync(join(out, 'relationships.txt'), relationships.join('\n') + '\n');
  const reads = lakehouseTables(bim);
  writeFileSync(join(out, 'lakehouse_tables.txt'), reads.join('\n') + '\n');
  requiredTables[model.key] = reads;
  summary.push({ key: model.key, name: model.name, tables: bim.model.tables.length, relationships: relationships.length, lakehouseTables: reads.length, replaced, leftover });
}
writeFileSync(join(dir, 'SUMMARY.json'), JSON.stringify({ server, database, schema, modules, models: summary }, null, 2));
// Uploaded with the rest of out/models to Files/universal_lake/models/; Lake_Promote_Medallion uses it to
// promote exactly these tables to gold and report any a model needs but the ingest did not produce.
writeFileSync(join(dir, 'gold_tables.json'), JSON.stringify(requiredTables, null, 2));

console.log(`Server: ${server}   Lakehouse: ${database}   Schema: ${schema}\n`);
for (const s of summary) {
  if (s.skipped) console.log(`  -  ${s.name}: skipped (${s.skipped})`);
  else console.log(`  OK ${s.name}: ${s.tables} tables, ${s.relationships} relationships, ${s.replaced} "dbo" -> "${schema}"${s.leftover ? `, ${s.leftover} dbo left!` : ''}`);
}
if (!isSet(cfg.lakehouse?.sqlEndpoint)) console.warn('\nWARNING: lakehouse.sqlEndpoint is not set; the models carry a placeholder server.');

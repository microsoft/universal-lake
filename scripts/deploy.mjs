// Deploys everything to Fabric from config.json, so nothing is imported or uploaded by hand.
//
//   npm run deploy                     sign in, then do steps 1-6 below
//   npm run deploy -- --dry-run        check config.json and your exports folder only (no sign-in, nothing sent)
//   npm run deploy -- --run first_load also start Lake_Orchestrator's first load when setup passes
//   npm run deploy -- --device-code    sign in with a code instead of a browser window
//   npm run deploy -- --reupload-csv   upload CSVs again even if this Lakehouse already has them
//   npm run deploy -- --overwrite      replace same-named notebooks this PC didn't deploy (e.g. from a manual import)
//   npm run deploy -- --config <file>  use another config file
//
// What it does:
//   1. Finds the workspace (workspace.id or workspace.name) and finds or creates the Lakehouse (schemas on).
//   2. Writes the workspace ID, Lakehouse ID and SQL endpoint back into config.json (comments are kept).
//   3. Runs the build (npm run all), so the notebooks are bound to that Lakehouse.
//   4. Creates or updates every notebook in out/notebooks (same name = updated in place).
//   5. Uploads out/models to Files/universal_lake/models and the CSVs in exportsFolder to Files/analytics_hub_uploads.
//   6. Runs Lake_Setup (Lakehouse setup + permission checks) and shows the result.
//
// Needs: Node 20.12+, Python, Contributor (or higher) on the workspace, and the Fabric REST APIs allowed for
// users in your tenant (on by default). Sign-in uses the public Microsoft Azure CLI client; nothing is stored.
import { createHash, randomBytes } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { basename, extname, isAbsolute, join, relative, resolve } from 'node:path';
import { OUT, ROOT, arg, isSet, stripJsonComments } from './lib.mjs';
import { DATA_SOURCES, UPLOAD_DIR, UPLOAD_KINDS, normHeader } from './build/uploads.js';

const FLAGS = new Set(process.argv.slice(2));
const DRY_RUN = FLAGS.has('--dry-run');
const RUN = arg('run', '');
const CLIENT_ID = '04b07795-8ddb-461a-bbee-02f9e1bf7b46';
const FABRIC = 'https://api.fabric.microsoft.com/v1';
const ONELAKE = 'https://onelake.dfs.fabric.microsoft.com';
const MODELS_DIR = 'Files/universal_lake/models';
const STATE_FILE = join(OUT, 'DEPLOY_STATE.json');

const configFile = resolve(arg('config', join(ROOT, 'config.json')));
if (!existsSync(configFile)) fail(`No config at ${configFile}. Copy config.template.json to config.json and fill it in (step 3).`);
let configText = readFileSync(configFile, 'utf8');
const cfg = parseConfig(configText);

function fail(msg) {
  console.error(`\nERROR: ${msg}`);
  process.exit(1);
}
function parseConfig(text) {
  try { return JSON.parse(stripJsonComments(text)); }
  catch (e) { fail(`${configFile} is not valid JSON (check quotes and commas): ${e.message}`); }
}
const sha = (buf) => createHash('sha256').update(buf).digest('hex');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const filled = (v) => isSet(v) && !String(v).includes('<');

// ---------- CSV exports: which file feeds which source ----------

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)]));
}

/** Same rules as the upload router notebook: one header from every group; most groups wins; a tie is ambiguous. */
function recognise(file) {
  const head = readFileSync(file).subarray(0, 65536).toString('utf8').split(/\r?\n/)[0] ?? '';
  const delim = [',', ';', '\t'].map((d) => [d, head.split(d).length]).sort((a, b) => b[1] - a[1])[0][0];
  const cols = new Set(head.split(delim).map((c) => normHeader(c.replace(/^"|"$/g, ''))));
  const hits = UPLOAD_KINDS.filter((k) => k.groups.every((g) => g.some((h) => cols.has(h))));
  if (!hits.length) return { status: 'unrecognised' };
  const best = Math.max(...hits.map((k) => k.groups.length));
  const top = hits.filter((k) => k.groups.length === best);
  if (top.length > 1) return { status: 'ambiguous', detail: top.map((k) => k.kind).join(' or ') };
  return { status: 'ok', kind: top[0] };
}

function scanExports() {
  const ds = cfg.dataSources ?? {};
  const mode = (src) => ds[src] ?? DATA_SOURCES.find((s) => s.id === src)?.defaultMode ?? 'skip';
  const csvSources = [...new Set(UPLOAD_KINDS.map((k) => k.source))].filter((s) => mode(s) === 'csv');
  const folder = cfg.exportsFolder;
  const report = { folder: '', upload: [], other: [], missing: [] };
  if (!filled(folder)) {
    if (csvSources.length) report.missing = csvSources;
    return report;
  }
  report.folder = isAbsolute(folder) ? folder : resolve(ROOT, folder);
  if (!existsSync(report.folder) || !statSync(report.folder).isDirectory()) fail(`exportsFolder "${folder}" is not a folder on this PC. Fix it in config.json.`);
  const seen = new Set();
  for (const file of walk(report.folder)) {
    const name = relative(report.folder, file);
    if (extname(file).toLowerCase() !== '.csv') { report.other.push([name, 'not a .csv: ignored']); continue; }
    const r = recognise(file);
    if (r.status !== 'ok') { report.other.push([name, r.status === 'ambiguous' ? `matches ${r.detail}: rename columns or remove it` : 'not a known export: ignored']); continue; }
    if (mode(r.kind.source) === 'skip') { report.other.push([name, `${r.kind.kind}, but dataSources.${r.kind.source} is "skip": ignored`]); continue; }
    seen.add(r.kind.source);
    report.upload.push({ file, name, kind: r.kind.kind, source: r.kind.source });
  }
  report.missing = csvSources.filter((s) => !seen.has(s));
  return report;
}

function printExports(report) {
  console.log(`\nCSV exports${report.folder ? ` in ${report.folder}` : ''}:`);
  if (!report.folder) console.log('  exportsFolder is not set in config.json: no CSVs will be uploaded.');
  for (const u of report.upload) console.log(`  upload   ${u.name}  ->  ${u.kind} (${u.source})`);
  for (const [n, why] of report.other) console.log(`  skip     ${n}  (${why})`);
  for (const s of report.missing) console.log(`  WARNING: dataSources.${s} is "csv" but no file for it was found. Its tables stay empty until you add the export and deploy again.`);
}

// ---------- Build ----------

function build() {
  const passConfig = arg('config') ? ['--config', configFile] : [];
  const steps = [
    [process.execPath, ['scripts/sync_notebooks.mjs', ...passConfig]],
    [process.execPath, ['scripts/build_models.mjs', ...passConfig]],
    [process.platform === 'win32' ? 'python' : 'python3', ['scripts/build_ipynb.py', ...passConfig]],
  ];
  for (const [cmd, args] of steps) {
    const r = spawnSync(cmd, args, { cwd: ROOT, stdio: 'inherit' });
    if (r.error) fail(`Could not run ${cmd}: ${r.error.message}. Is it installed and on PATH?`);
    if (r.status !== 0) fail(`Build step "${args[0]}" failed (see above).`);
  }
}

// ---------- Sign-in (browser with PKCE, or device code) ----------

// You sign in to the tenant that holds the Fabric workspace. That is the app's tenant unless fabricTenantId says otherwise.
const tenant = filled(cfg.fabricTenantId) ? cfg.fabricTenantId : cfg.tenantId;
const tokenUrl = () => `https://login.microsoftonline.com/${tenant}/oauth2/v2.0/token`;
const SCOPE_FABRIC = 'https://api.fabric.microsoft.com/.default offline_access';
const SCOPE_STORAGE = 'https://storage.azure.com/.default offline_access';

async function tokenRequest(params) {
  const res = await fetch(tokenUrl(), { method: 'POST', body: new URLSearchParams({ client_id: CLIENT_ID, ...params }) });
  const body = await res.json();
  if (!res.ok) throw Object.assign(new Error(body.error_description?.split('\r\n')[0] ?? res.statusText), { code: body.error });
  return body;
}

function openBrowser(url) {
  const [cmd, args] = process.platform === 'win32' ? ['rundll32', ['url.dll,FileProtocolHandler', url]]
    : process.platform === 'darwin' ? ['open', [url]] : ['xdg-open', [url]];
  try { spawn(cmd, args, { stdio: 'ignore', detached: true }).unref(); } catch { /* the URL is printed too */ }
}

async function signInBrowser() {
  const verifier = randomBytes(32).toString('base64url');
  const challenge = createHash('sha256').update(verifier).digest('base64url');
  const state = randomBytes(16).toString('hex');
  let redirect;
  const code = await new Promise((done, reject) => {
    const server = createServer((req, res) => {
      const u = new URL(req.url, 'http://localhost');
      if (u.pathname !== '/') { res.writeHead(404).end(); return; }
      const ok = u.searchParams.get('state') === state && u.searchParams.get('code');
      res.writeHead(200, { 'Content-Type': 'text/html' }).end(ok ? '<p>Signed in. You can close this tab and go back to the terminal.</p>'
        : `<p>Sign-in failed: ${String(u.searchParams.get('error_description') ?? 'no code').replace(/[<>&]/g, '')}</p>`);
      server.close();
      ok ? done(ok) : reject(new Error(u.searchParams.get('error_description') ?? 'Sign-in failed'));
    });
    server.listen(0, '127.0.0.1', () => {
      redirect = `http://localhost:${server.address().port}`;
      const url = `https://login.microsoftonline.com/${tenant}/oauth2/v2.0/authorize?` + new URLSearchParams({
        client_id: CLIENT_ID, response_type: 'code', redirect_uri: redirect, scope: SCOPE_FABRIC, state,
        code_challenge: challenge, code_challenge_method: 'S256', prompt: 'select_account' });
      console.log('\nSign in to Fabric in the browser window that just opened. If none opened, open this link:\n' + url);
      openBrowser(url);
    });
    setTimeout(() => { server.close(); reject(new Error('Timed out waiting for sign-in. Try --device-code.')); }, 5 * 60_000).unref();
  });
  return tokenRequest({ grant_type: 'authorization_code', code, redirect_uri: redirect, code_verifier: verifier, scope: SCOPE_FABRIC });
}

async function signInDeviceCode() {
  const res = await fetch(`https://login.microsoftonline.com/${tenant}/oauth2/v2.0/devicecode`, {
    method: 'POST', body: new URLSearchParams({ client_id: CLIENT_ID, scope: SCOPE_FABRIC }) });
  const dc = await res.json();
  if (!res.ok) fail(`Device-code sign-in failed: ${dc.error_description ?? res.statusText}`);
  console.log(`\n${dc.message}`);
  for (;;) {
    await sleep((dc.interval ?? 5) * 1000);
    try { return await tokenRequest({ grant_type: 'urn:ietf:params:oauth:grant-type:device_code', device_code: dc.device_code }); }
    catch (e) { if (e.code !== 'authorization_pending' && e.code !== 'slow_down') throw e; }
  }
}

let fabricToken, storageToken;
async function signIn() {
  if (!filled(tenant)) fail('tenantId is not set in config.json (step 2).');
  const t = FLAGS.has('--device-code') ? await signInDeviceCode() : await signInBrowser();
  fabricToken = t.access_token;
  storageToken = (await tokenRequest({ grant_type: 'refresh_token', refresh_token: t.refresh_token, scope: SCOPE_STORAGE })).access_token;
  console.log('Signed in.');
}

// ---------- Fabric REST ----------

async function call(method, url, { body, token = fabricToken, headers = {}, raw = false } = {}) {
  for (let attempt = 0; ; attempt++) {
    const res = await fetch(url.startsWith('http') ? url : FABRIC + url, {
      method,
      headers: { Authorization: `Bearer ${token}`, ...(body && !raw ? { 'Content-Type': 'application/json' } : {}), ...headers },
      body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
    });
    if ((res.status === 429 || res.status >= 500) && attempt < 5) {
      await sleep(Number(res.headers.get('retry-after') ?? 10) * 1000);
      continue;
    }
    if (!res.ok) {
      const text = await res.text();
      let msg = text;
      try { const j = JSON.parse(text); msg = j.message ?? j.error?.message ?? text; } catch { /* plain text */ }
      const hint = res.status === 401 || res.status === 403
        ? ' Check you are a Contributor (or higher) on the workspace and that your tenant allows the Fabric REST APIs.' : '';
      throw new Error(`${method} ${url.split('?')[0]} failed: HTTP ${res.status} ${msg.slice(0, 400)}${hint}`);
    }
    return res;
  }
}

/** Waits for a long-running operation (HTTP 202) and returns its result, if any. */
async function settle(res) {
  if (res.status !== 202) return res.status === 204 ? null : res.json().catch(() => null);
  const location = res.headers.get('location');
  if (!location) return null;
  for (;;) {
    await sleep(Number(res.headers.get('retry-after') ?? 3) * 1000);
    const op = await (await call('GET', location)).json();
    if (op.status === 'Succeeded') {
      const r = await fetch(`${location}/result`, { headers: { Authorization: `Bearer ${fabricToken}` } });
      return r.ok ? r.json().catch(() => null) : null;
    }
    if (op.status === 'Failed') throw new Error(`Fabric operation failed: ${op.error?.message ?? JSON.stringify(op.error)}`);
  }
}

async function list(path) {
  const out = [];
  let url = path;
  while (url) {
    const page = await (await call('GET', url)).json();
    out.push(...(page.value ?? []));
    url = page.continuationUri ?? (page.continuationToken ? `${path}${path.includes('?') ? '&' : '?'}continuationToken=${encodeURIComponent(page.continuationToken)}` : null);
  }
  return out;
}

async function findWorkspace() {
  const want = cfg.workspace ?? {};
  const all = await list('/workspaces');
  const ws = filled(want.id) ? all.find((w) => w.id === want.id) : all.filter((w) => w.displayName === want.name)[0];
  if (!ws) fail(filled(want.id) ? `No workspace with id ${want.id} that you can see.`
    : filled(want.name) ? `No workspace named "${want.name}" that you can see. Create it first (step 1) or check workspace.name.`
      : 'Set workspace.name in config.json (step 1).');
  if (!filled(want.id) && all.filter((w) => w.displayName === want.name).length > 1) fail(`More than one workspace is named "${want.name}". Set workspace.id instead.`);
  if (!ws.capacityId) console.warn(`WARNING: workspace "${ws.displayName}" has no Fabric capacity. Notebooks can't run until you assign one (step 1).`);
  return ws;
}

async function findOrCreateLakehouse(ws) {
  const name = cfg.lakehouse?.name || 'UniversalLake_LH';
  let lh = (await list(`/workspaces/${ws.id}/lakehouses`)).find((l) => (filled(cfg.lakehouse?.id) ? l.id === cfg.lakehouse.id : l.displayName === name));
  if (!lh) {
    console.log(`Creating Lakehouse ${name} (with schemas) ...`);
    lh = await settle(await call('POST', `/workspaces/${ws.id}/lakehouses`, { body: { displayName: name, creationPayload: { enableSchemas: true } } }));
    if (!lh?.id) lh = (await list(`/workspaces/${ws.id}/lakehouses`)).find((l) => l.displayName === name);
  } else console.log(`Lakehouse ${lh.displayName} found.`);
  for (let i = 0; i < 40; i++) {
    const full = await (await call('GET', `/workspaces/${ws.id}/lakehouses/${lh.id}`)).json();
    const props = full.properties ?? {};
    if (!props.defaultSchema) fail(`Lakehouse ${full.displayName} is not schema-enabled. Delete it, or set a new lakehouse.name and deploy again; the new one is created with schemas.`);
    const sql = props.sqlEndpointProperties ?? {};
    if (sql.connectionString && sql.provisioningStatus !== 'InProgress') return { ...full, sqlEndpoint: sql.connectionString.replace(/^.*?:\/\//, '').replace(/[,;].*$/, '') };
    if (i === 0) console.log('Waiting for the SQL analytics endpoint ...');
    await sleep(6000);
  }
  fail('The Lakehouse SQL analytics endpoint is still being created. Wait a minute and run npm run deploy again.');
}

/** Puts the IDs into config.json by editing the text, so your comments stay. */
function writeBack(ws, lh) {
  const set = (block, key, value) => {
    const re = new RegExp(`("${block}"\\s*:\\s*\\{[^}]*?"${key}"\\s*:\\s*)"[^"]*"`);
    if (!re.test(configText)) return false;
    configText = configText.replace(re, `$1${JSON.stringify(value)}`);
    return true;
  };
  const before = configText;
  const ok = [set('workspace', 'id', ws.id), set('workspace', 'name', ws.displayName), set('lakehouse', 'id', lh.id),
    set('lakehouse', 'name', lh.displayName), set('lakehouse', 'sqlEndpoint', lh.sqlEndpoint)].every(Boolean);
  if (!ok) fail(`Could not update config.json automatically. Set these by hand, then deploy again:\n  workspace.id = ${ws.id}\n  lakehouse.id = ${lh.id}\n  lakehouse.sqlEndpoint = ${lh.sqlEndpoint}`);
  if (configText !== before) {
    writeFileSync(configFile, configText);
    console.log('Updated config.json with the workspace ID, Lakehouse ID and SQL endpoint.');
  }
}

// ---------- Notebooks, files, jobs ----------

const state = existsSync(STATE_FILE) ? JSON.parse(readFileSync(STATE_FILE, 'utf8')) : {};
const saveState = () => { mkdirSync(OUT, { recursive: true }); writeFileSync(STATE_FILE, JSON.stringify(state, null, 2)); };

async function deployNotebooks(ws, lh) {
  const dir = join(OUT, 'notebooks');
  const files = readdirSync(dir).filter((f) => f.endsWith('.ipynb')).sort((a, b) => (a === 'lake_ops.ipynb' ? -1 : b === 'lake_ops.ipynb' ? 1 : a.localeCompare(b)));
  const existing = new Map((await list(`/workspaces/${ws.id}/notebooks`)).map((n) => [n.displayName, n.id]));
  const done = (state[lh.id] ??= { notebooks: {}, csv: {} });
  const foreign = files.map((f) => basename(f, '.ipynb')).filter((n) => existing.has(n) && !done.notebooks[n]);
  if (foreign.length && !FLAGS.has('--overwrite')) {
    fail(`The workspace already has notebooks with these names, not deployed from this PC to this Lakehouse:\n  ${foreign.join(', ')}\n`
      + 'If they are from an earlier run of this guide, run npm run deploy -- --overwrite to replace them (your data is safe; it lives in the Lakehouse).\n'
      + 'If they belong to another solution, don\'t overwrite them: use a new workspace (TROUBLESHOOTING.md, "Notebooks with the same names").');
  }
  const ids = {};
  const retired = ['Lake_Init', 'Lake_Validate_Credentials'].filter((n) => existing.has(n));
  if (retired.length) console.log(`  Note: ${retired.join(' and ')} ${retired.length > 1 ? 'are' : 'is'} no longer used (Lake_Setup replaces them). You can delete ${retired.length > 1 ? 'them' : 'it'} from the workspace.`);
  console.log(`\nNotebooks (${files.length}):`);
  for (const f of files) {
    const name = basename(f, '.ipynb');
    const buf = readFileSync(join(dir, f));
    const definition = { format: 'ipynb', parts: [{ path: 'notebook-content.ipynb', payload: buf.toString('base64'), payloadType: 'InlineBase64' }] };
    let id = existing.get(name);
    if (id && done.notebooks[name] === sha(buf)) { console.log(`  unchanged ${name}`); ids[name] = id; continue; }
    if (id) {
      await settle(await call('POST', `/workspaces/${ws.id}/notebooks/${id}/updateDefinition`, { body: { definition } }));
      console.log(`  updated   ${name}`);
    } else {
      const item = await settle(await call('POST', `/workspaces/${ws.id}/notebooks`, { body: { displayName: name, definition } }));
      id = item?.id ?? (await list(`/workspaces/${ws.id}/notebooks`)).find((n) => n.displayName === name)?.id;
      console.log(`  created   ${name}`);
    }
    ids[name] = id;
    done.notebooks[name] = sha(buf);
    saveState();
  }
  return ids;
}

async function putFile(ws, lh, path, buf) {
  const url = `${ONELAKE}/${ws.id}/${lh.id}/${path.split('/').map(encodeURIComponent).join('/')}`;
  const opt = { token: storageToken, headers: { 'x-ms-version': '2023-11-03' } };
  await call('PUT', `${url}?resource=file`, opt);
  const CHUNK = 8 * 1024 * 1024;
  for (let pos = 0; pos < buf.length; pos += CHUNK) {
    await call('PATCH', `${url}?action=append&position=${pos}`, { ...opt, body: buf.subarray(pos, pos + CHUNK), raw: true });
  }
  await call('PATCH', `${url}?action=flush&position=${buf.length}`, opt);
}

async function uploadModels(ws, lh) {
  const dir = join(OUT, 'models');
  const files = walk(dir);
  for (const file of files) await putFile(ws, lh, `${MODELS_DIR}/${relative(dir, file).split('\\').join('/')}`, readFileSync(file));
  console.log(`\nUploaded ${files.length} model files to ${MODELS_DIR}.`);
}

async function uploadCsvs(ws, lh, report) {
  if (!report.upload.length) return;
  const done = state[lh.id].csv;
  console.log('\nCSV uploads:');
  for (const u of report.upload) {
    const buf = readFileSync(u.file);
    const key = sha(buf);
    if (done[key] && !FLAGS.has('--reupload-csv')) { console.log(`  already uploaded  ${u.name}`); continue; }
    await putFile(ws, lh, `${UPLOAD_DIR}/${basename(u.file)}`, buf);
    done[key] = { name: u.name, kind: u.kind, uploadedUtc: new Date().toISOString() };
    saveState();
    console.log(`  uploaded          ${u.name}  ->  ${UPLOAD_DIR}`);
  }
  console.log('  The orchestrator\'s upload_router step sorts them into their source folders.');
}

const notebookLink = (ws, id) => `https://app.fabric.microsoft.com/groups/${ws.id}/synapsenotebooks/${id}`;

async function runNotebook(ws, id, parameters, { wait }) {
  const body = parameters ? { executionData: { parameters } } : undefined;
  const res = await call('POST', `/workspaces/${ws.id}/items/${id}/jobs/instances?jobType=RunNotebook`, { body });
  const location = res.headers.get('location');
  if (!wait || !location) return null;
  const started = Date.now();
  let last = '';
  for (;;) {
    await sleep(15000);
    const job = await (await call('GET', location)).json();
    if (job.status !== last) { console.log(`  ${job.status} (${Math.round((Date.now() - started) / 1000)}s)`); last = job.status; }
    if (['Completed', 'Failed', 'Cancelled', 'Deduped'].includes(job.status)) return job;
    if (Date.now() - started > 45 * 60_000) return { status: 'StillRunning' };
  }
}

// ---------- Main ----------

const report = scanExports();
if (DRY_RUN) {
  const ws = cfg.workspace ?? {};
  console.log('Dry run: nothing is sent to Fabric.\n');
  console.log(`Workspace: ${filled(ws.id) ? ws.id : filled(ws.name) ? `"${ws.name}" (found by name)` : 'NOT SET: set workspace.name'}`);
  console.log(`Lakehouse: ${cfg.lakehouse?.name || 'UniversalLake_LH'}${filled(cfg.lakehouse?.id) ? ` (${cfg.lakehouse.id})` : ' (created if it does not exist)'}`);
  console.log(`Sign-in:   tenant ${filled(tenant) ? tenant : 'NOT SET: set tenantId'}${filled(cfg.fabricTenantId) ? ' (fabricTenantId; the app and data stay in ' + cfg.tenantId + ')' : ''}`);
  printExports(report);
  console.log('\nRun npm run deploy (without --dry-run) to deploy.');
  process.exit(0);
}

printExports(report);
await signIn();
const ws = await findWorkspace();
console.log(`Workspace ${ws.displayName} found.`);
const lh = await findOrCreateLakehouse(ws);
writeBack(ws, lh);

console.log('\nBuilding the notebooks and model files for this Lakehouse (npm run all) ...');
build();

const ids = await deployNotebooks(ws, lh);
await uploadModels(ws, lh);
await uploadCsvs(ws, lh, report);

if (FLAGS.has('--skip-setup')) process.exit(0);
const setupId = ids.Lake_Setup;
if (!setupId) fail('Lake_Setup was not found in out/notebooks. Check the build output above.');
console.log('\nRunning Lake_Setup (sets up the Lakehouse and checks the app). The first run waits for Spark to start, a few minutes ...');
const job = await runNotebook(ws, setupId, null, { wait: true });
if (job?.status !== 'Completed') {
  console.error(`\nLake_Setup did not succeed: ${job?.status}${job?.failureReason?.message ? `: ${job.failureReason.message}` : ''}`);
  console.error(`Open it to see which check failed: ${notebookLink(ws, setupId)}`);
  console.error('Fix the cause (TROUBLESHOOTING.md lists the usual ones), then run Lake_Setup again in Fabric or run npm run deploy again.');
  process.exit(1);
}
console.log('Lake_Setup passed: the Lakehouse is ready and the app has the permissions it needs.');

if (RUN === 'first_load') {
  const orch = ids.Lake_Orchestrator;
  await runNotebook(ws, orch, { RUN_MODE: { value: 'first_load', type: 'string' } }, { wait: false });
  console.log(`\nStarted Lake_Orchestrator with RUN_MODE = 'first_load'. It can take hours; follow it here:\n  ${notebookLink(ws, orch)}`);
} else {
  console.log(`\nNext (step 5): open Lake_Orchestrator, set RUN_MODE = 'first_load' and Run all, or run npm run deploy -- --run first_load.\n  ${notebookLink(ws, ids.Lake_Orchestrator)}`);
}

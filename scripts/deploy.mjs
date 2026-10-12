// Deploys everything to Fabric from config.json, so nothing is imported or uploaded by hand.
//
//   npm run deploy                     sign in to Fabric, then do steps 1-7 below
//   npm run deploy -- --dry-run        check config.json and your exports folder only (no sign-in, nothing sent)
//   npm run deploy -- --run first_load also start Lake_Orchestrator's first load when setup passes, and say when it ends
//   npm run deploy -- --rerun-failed   deploy, then re-run only the steps of the last run that did not succeed, and say
//                                      when it ends (--run-id <run_id> picks an older run)
//   npm run deploy -- --watch          only follow the latest Lake_Orchestrator run and say when it ends (deploys nothing)
//   npm run deploy -- --device-code    sign in with a code instead of a browser window
//   npm run deploy -- --reupload-csv   upload CSVs again even if this Lakehouse already has them
//   npm run deploy -- --overwrite      replace same-named notebooks this PC didn't deploy (e.g. from a manual import)
//   npm run deploy -- --capacity-retries <n>  when no Spark capacity is free, try again up to n times (default 6) ...
//   npm run deploy -- --retry-wait <minutes>  ... waiting this long between tries (default 5)
//   npm run deploy -- --config <file>  use another config file
//
// What it does:
//   1. Finds the workspace (workspace.id or workspace.name) and finds or creates the Lakehouse (schemas on).
//   2. Writes the workspace ID, Lakehouse ID and SQL endpoint back into config.json (comments are kept).
//   3. Runs the build (npm run all), so the notebooks are bound to that Lakehouse.
//   4. Creates or updates every notebook in out/notebooks (same name = updated in place).
//   5. Uploads out/models to Files/universal_lake/models and the CSVs in exportsFolder to Files/analytics_hub_uploads.
//   6. Runs Lake_Setup (Lakehouse setup + permission checks) and shows the result.
//   7. Connects the semantic models to the Lakehouse with the workspace identity (created if missing), so model
//      refreshes need no manual sign-in. Needs workspace Admin and a paid Fabric capacity; skipped with a warning otherwise.
//
// Needs: Node 20.12+, Python, Contributor (or higher) on the workspace, and the Fabric REST APIs allowed for
// users in your tenant (on by default). Sign-in uses the public Microsoft Azure CLI client; nothing is stored.
import { createHash, randomBytes } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { createInterface } from 'node:readline';
import { basename, extname, isAbsolute, join, relative, resolve } from 'node:path';
import { OUT, ROOT, arg, isSet, stripJsonComments } from './lib.mjs';
import { DATA_SOURCES, UPLOAD_DIR, UPLOAD_KINDS, normHeader } from './build/uploads.js';

const FLAGS = new Set(process.argv.slice(2));
const DRY_RUN = FLAGS.has('--dry-run');
const RUN = arg('run', '');
const RERUN_FAILED = FLAGS.has('--rerun-failed');
const CAPACITY_RETRIES = Math.max(0, Number(arg('capacity-retries', '6')) || 0);
const CAPACITY_WAIT_MIN = Math.max(1, Number(arg('retry-wait', '5')) || 5);
// What Fabric says when no Spark capacity is free right now. It clears by itself, so these are retried.
const CAPACITY_BUSY = /HTTP 430|TooManyRequestsForCapacity|CapacityLimitExceeded|SparkJobQueue|Spark compute or API rate limit|capacity (is )?(full|busy|throttl)|no (available )?(spark )?capacity|not enough (spark )?(capacity|cores)|queue (is )?full/i;
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

// You sign in to the tenant that holds the Fabric workspace. confirmFabricTenant() asks once and saves it as fabricTenantId.
let tenant = filled(cfg.fabricTenantId) ? cfg.fabricTenantId : cfg.tenantId;
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

// Says plainly which sign-in this is: the Fabric tenant, not the app's Microsoft Graph access (that uses the app's secret).
const fabricSignInNote = () => `=== Sign in to MICROSOFT FABRIC (tenant ${tenant}) ===\n` +
  'Use the account that has the Fabric workspace. This is NOT the Microsoft Graph sign-in: the app reads Graph with its own secret.\n' +
  'Deploy uses this sign-in to upload the notebooks and to connect the semantic models to the Lakehouse.';
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
      console.log(`\n${fabricSignInNote()}\nSign in in the browser window that just opened. If none opened, open this link:\n` + url);
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
  console.log(`\n${fabricSignInNote()}\n${dc.message}`);
  for (;;) {
    await sleep((dc.interval ?? 5) * 1000);
    try { return await tokenRequest({ grant_type: 'urn:ietf:params:oauth:grant-type:device_code', device_code: dc.device_code }); }
    catch (e) { if (e.code !== 'authorization_pending' && e.code !== 'slow_down') throw e; }
  }
}

/** Asks once whether Fabric is in the app's tenant, and saves the answer as fabricTenantId so it isn't asked again. */
async function confirmFabricTenant() {
  if (filled(cfg.fabricTenantId) || !filled(cfg.tenantId)) return;
  if (!process.stdin.isTTY) {
    console.log(`Signing in to tenant ${cfg.tenantId} (the app's). If Fabric is in another tenant, set fabricTenantId in config.json.`);
    return;
  }
  const rl = createInterface({ input: process.stdin });
  const lines = rl[Symbol.asyncIterator]();
  const ask = async (q) => { process.stdout.write(q); const r = await lines.next(); return r.done ? null : r.value.trim(); };
  console.log(`\nYour app registration (and the data it reads) is in tenant ${cfg.tenantId}.`);
  const same = await ask('Is your Fabric workspace in this same tenant? [Y/n] ');
  let value = cfg.tenantId;
  if (same?.toLowerCase().startsWith('n')) {
    console.log('Enter the Fabric tenant: its ID, or a domain you sign in with, e.g. contoso.com.');
    console.log('(Fabric portal > ? > About shows the tenant.)');
    do { value = await ask('Fabric tenant: '); } while (value === '');
  }
  rl.close();
  if (!value) fail('No Fabric tenant entered. Set fabricTenantId in config.json, or run deploy again.');
  tenant = value;
  const re = /("fabricTenantId"\s*:\s*)"[^"]*"/;
  const appLine = /("appId"\s*:\s*"[^"]*",[^\r\n]*)(\r?\n)/;
  if (re.test(configText)) configText = configText.replace(re, `$1${JSON.stringify(value)}`);
  else if (appLine.test(configText)) configText = configText.replace(appLine, `$1$2  "fabricTenantId": ${JSON.stringify(value)},$2`);
  else { console.log(`Could not save this in config.json. Add "fabricTenantId": ${JSON.stringify(value)} to skip this question.`); return; }
  writeFileSync(configFile, configText);
  console.log(`Saved fabricTenantId = ${value} in config.json; you won't be asked again.`);
}

let fabricToken, storageToken, refreshToken, fabricExpires = 0;
async function signIn() {
  if (!filled(tenant)) fail('tenantId is not set in config.json (step 2).');
  await confirmFabricTenant();
  const t = FLAGS.has('--device-code') ? await signInDeviceCode() : await signInBrowser();
  fabricToken = t.access_token;
  refreshToken = t.refresh_token;
  fabricExpires = Date.now() + (t.expires_in ?? 3600) * 1000;
  storageToken = (await tokenRequest({ grant_type: 'refresh_token', refresh_token: t.refresh_token, scope: SCOPE_STORAGE })).access_token;
  console.log('Signed in.');
}

// A run can outlast the sign-in tokens (about an hour), so the watch loop renews them.
async function renewTokens() {
  if (Date.now() < fabricExpires - 5 * 60_000) return;
  const t = await tokenRequest({ grant_type: 'refresh_token', refresh_token: refreshToken, scope: SCOPE_FABRIC });
  fabricToken = t.access_token;
  if (t.refresh_token) refreshToken = t.refresh_token;
  fabricExpires = Date.now() + (t.expires_in ?? 3600) * 1000;
  storageToken = (await tokenRequest({ grant_type: 'refresh_token', refresh_token: refreshToken, scope: SCOPE_STORAGE })).access_token;
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

// ---------- Model connection (workspace identity) ----------

/**
 * Lets the semantic models read the Lakehouse with no sign-in to keep alive: the workspace identity (a Fabric-managed
 * identity of this workspace, in the Fabric tenant) reads the SQL endpoint through one shareable connection.
 * Needs workspace Admin and a paid Fabric capacity. Lake_Deploy_Models attaches later models to the same connection.
 */
async function connectModels(ws, lh) {
  console.log('\nConnecting the semantic models to the Lakehouse with the workspace identity ...');
  let identity = (await (await call('GET', `/workspaces/${ws.id}`)).json()).workspaceIdentity;
  if (!identity?.servicePrincipalId) {
    console.log('  Creating the workspace identity (a minute or two) ...');
    identity = await settle(await call('POST', `/workspaces/${ws.id}/provisionIdentity`));
    if (!identity?.servicePrincipalId) identity = (await (await call('GET', `/workspaces/${ws.id}`)).json()).workspaceIdentity;
    if (!identity?.servicePrincipalId) throw new Error('the workspace identity was not created');
  }
  const roles = await list(`/workspaces/${ws.id}/roleAssignments`);
  if (!roles.some((r) => r.principal?.id === identity.servicePrincipalId)) {
    await call('POST', `/workspaces/${ws.id}/roleAssignments`,
      { body: { principal: { id: identity.servicePrincipalId, type: 'ServicePrincipal' }, role: 'Viewer' } });
    console.log('  Gave the workspace identity the Viewer role, so it can read the Lakehouse.');
  }
  const server = lh.sqlEndpoint, database = lh.displayName;
  const path = `${server};${database}`;
  let conn = (await list('/connections')).find((c) => String(c.connectionDetails?.type).toUpperCase() === 'SQL'
    && String(c.connectionDetails?.path).toLowerCase() === path.toLowerCase()
    && c.credentialDetails?.credentialType === 'WorkspaceIdentity');
  if (!conn) {
    conn = await (await call('POST', '/connections', { body: {
      connectivityType: 'ShareableCloud', displayName: `Universal Lake ${database} (workspace identity, ${ws.displayName})`.slice(0, 200),
      privacyLevel: 'Organizational',
      connectionDetails: { type: 'SQL', creationMethod: 'Sql', parameters: [
        { dataType: 'Text', name: 'server', value: server }, { dataType: 'Text', name: 'database', value: database }] },
      credentialDetails: { singleSignOnType: 'None', connectionEncryption: 'NotEncrypted', skipTestConnection: false,
        credentials: { credentialType: 'WorkspaceIdentity' } },
    } })).json();
    console.log(`  Created the connection "${conn.displayName}".`);
  } else console.log(`  Using the connection "${conn.displayName}".`);
  const summaryFile = join(OUT, 'models', 'SUMMARY.json');
  const names = existsSync(summaryFile) ? JSON.parse(readFileSync(summaryFile, 'utf8')).models.filter((m) => !m.skipped).map((m) => m.name) : [];
  const models = (await list(`/workspaces/${ws.id}/semanticModels`)).filter((m) => names.includes(m.displayName));
  for (const m of models) {
    await call('POST', `/workspaces/${ws.id}/semanticModels/${m.id}/bindConnection`, { body: { connectionBinding: {
      id: conn.id, connectivityType: 'ShareableCloud', connectionDetails: { type: 'SQL', path } } } });
    console.log(`  ${m.displayName}: connected.`);
  }
  if (!models.length) console.log('  No models yet; Lake_Deploy_Models connects them when it creates them.');
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

async function waitForCapacity(name, budget, reason) {
  budget.used++;
  console.log(`  ${clock()} No Spark capacity is free right now for ${name} (${reason.replace(/\s+/g, ' ').slice(0, 200)}).`);
  console.log(`  Trying again in ${CAPACITY_WAIT_MIN} min (retry ${budget.used} of ${CAPACITY_RETRIES}). Ctrl+C stops waiting.`);
  await sleep(CAPACITY_WAIT_MIN * 60_000);
  await renewTokens();
}

async function startNotebook(ws, id, parameters, name, budget) {
  const body = parameters ? { executionData: { parameters } } : undefined;
  for (;;) {
    try {
      const res = await call('POST', `/workspaces/${ws.id}/items/${id}/jobs/instances?jobType=RunNotebook`, { body });
      return res.headers.get('location');
    } catch (e) {
      if (!CAPACITY_BUSY.test(e.message) || budget.used >= CAPACITY_RETRIES) throw e;
      await waitForCapacity(name, budget, e.message);
    }
  }
}

async function runNotebook(ws, id, parameters, { wait, name = 'the notebook', budget = { used: 0 } }) {
  for (;;) {
    const location = await startNotebook(ws, id, parameters, name, budget);
    if (!wait || !location) return location;
    const started = Date.now();
    let last = '', job;
    for (;;) {
      await sleep(15000);
      job = await (await call('GET', location)).json();
      if (job.status !== last) { console.log(`  ${job.status} (${Math.round((Date.now() - started) / 1000)}s)`); last = job.status; }
      if (['Completed', 'Failed', 'Cancelled', 'Deduped'].includes(job.status)) break;
      if (Date.now() - started > 45 * 60_000) return { status: 'StillRunning' };
    }
    const reason = job.failureReason?.message ?? '';
    if (job.status === 'Failed' && CAPACITY_BUSY.test(reason) && budget.used < CAPACITY_RETRIES) {
      await waitForCapacity(name, budget, reason);
      continue;
    }
    return job;
  }
}

const DONE = ['Completed', 'Failed', 'Cancelled', 'Deduped'];
const duration = (job, fallbackStart) => {
  const start = Date.parse(job.startTimeUtc ?? '') || fallbackStart;
  const end = Date.parse(job.endTimeUtc ?? '') || Date.now();
  const m = Math.max(0, Math.round((end - start) / 60_000));
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`;
};
const clock = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

// Lake_Orchestrator writes this file when it starts and when it ends, with each failed step's error.
const RUN_STATUS = 'Files/universal_lake/runs/latest.json';
async function readRunStatus(ws, lhId, job) {
  const st = await readLatestStatus(ws, lhId);
  const jobStart = Date.parse(job.startTimeUtc ?? '');
  return st && jobStart && Date.parse(st.started) < jobStart - 10 * 60_000 ? null : st; // from an earlier run
}

function printNextSteps(mode) {
  if (mode === 'incremental') {
    console.log('Nothing else to do. If the daily run is not scheduled yet: Lake_Orchestrator > Run > Schedule (step 7).');
    return;
  }
  console.log('\nNext:');
  console.log('  1. Check the data and the models: step 6 (06-models/README.md).');
  console.log("  2. Set up the daily run: open Lake_Orchestrator, set RUN_MODE = 'incremental' (RUN_ID blank, RERUN_FAILED = False),");
  console.log('     Save, then Run > Schedule > once a day. Step 7 (07-orchestrate/README.md).');
}

async function readLatestStatus(ws, lhId) {
  try {
    await renewTokens();
    const res = await fetch(`${ONELAKE}/${ws.id}/${lhId}/${RUN_STATUS}`, { headers: { Authorization: `Bearer ${storageToken}`, 'x-ms-version': '2023-11-03' } });
    return res.ok ? await res.json() : null;
  } catch { return null; }
}

// Polls the orchestrator run until it ends, then says how it ended and what to do next.
async function watchOrchestrator(ws, lhId, id, location, restart) {
  console.log('\nWatching the run; this window says when it ends. You can close it or press Ctrl+C at any time: the run keeps');
  console.log('going in Fabric, and npm run deploy -- --watch picks it up again.');
  const started = Date.now();
  const budget = { used: 0 };
  let job, last = '', lastNote = 0;
  for (;;) {
    try {
      await renewTokens();
      job = await (await call('GET', location)).json();
    } catch (e) {
      console.log(`  ${clock()} could not check the run (${e.message.slice(0, 160)}); trying again in a minute`);
      await sleep(60_000);
      continue;
    }
    if (job.status !== last || Date.now() - lastNote >= 15 * 60_000) {
      console.log(`  ${clock()} ${job.status === 'InProgress' ? 'running' : job.status} (${duration(job, started)})`);
      last = job.status; lastNote = Date.now();
    }
    const reason = job.failureReason?.message ?? '';
    if (job.status === 'Failed' && restart && CAPACITY_BUSY.test(reason) && budget.used < CAPACITY_RETRIES) {
      await waitForCapacity('Lake_Orchestrator', budget, reason);
      location = await restart(budget);
      last = '';
      continue;
    }
    if (DONE.includes(job.status)) break;
    await sleep(60_000);
  }
  const total = duration(job, started);
  process.stdout.write('\x07');
  if (job.status === 'Completed') {
    const st = await readRunStatus(ws, lhId, job);
    console.log(`\nLake_Orchestrator finished after ${total}: every step succeeded and the semantic models are refreshed.`);
    for (const w of st?.warnings ?? []) console.log(`WARNING: ${w}`);
    printNextSteps(st?.run_mode);
  } else {
    const st = await readRunStatus(ws, lhId, job);
    console.log(`\nLake_Orchestrator ${job.status === 'Failed' ? 'failed' : `ended as ${job.status}`} after ${total}.`);
    if (st?.failed?.length) {
      console.log(`${st.failed.length} step(s) did not succeed (run_id ${st.run_id}):`);
      for (const f of st.failed) console.log(`  ${f.step}: ${f.status}${f.error ? `: ${f.error.replace(/\s+/g, ' ').slice(0, 400)}` : ''}`);
      console.log('To re-run only those, fix the cause, then run npm run deploy -- --rerun-failed');
      console.log(`(or open Lake_Orchestrator, set ${st.rerun} in the first cell and Run all).`);
    } else {
      if (job.failureReason?.message) console.log(`Fabric says: ${job.failureReason.message.slice(0, 600)}`);
      if (CAPACITY_BUSY.test(job.failureReason?.message ?? '')) {
        console.log('No Spark capacity was free. Run the same command again later, or wait longer with');
        console.log(`--capacity-retries <n> (now ${CAPACITY_RETRIES}, every ${CAPACITY_WAIT_MIN} min; --retry-wait <minutes> changes the gap).`);
      }
      if (st?.status === 'running') console.log('It stopped before or between steps (in one of its own cells), not in an ingest step.');
    }
    for (const w of st?.warnings ?? []) console.log(`WARNING: ${w}`);
    console.log('The full output is in Fabric: open the notebook, then the Run tab > Recent runs > this run:');
    console.log(`  ${notebookLink(ws, id)}`);
    console.log("More on retrying: step 5, 'Retry only what failed' (05-ingest/README.md).");
  }
  return job;
}

// ---------- Main ----------

const report = scanExports();
if (DRY_RUN) {
  const ws = cfg.workspace ?? {};
  console.log('Dry run: nothing is sent to Fabric.\n');
  console.log(`Workspace: ${filled(ws.id) ? ws.id : filled(ws.name) ? `"${ws.name}" (found by name)` : 'NOT SET: set workspace.name'}`);
  console.log(`Lakehouse: ${cfg.lakehouse?.name || 'UniversalLake_LH'}${filled(cfg.lakehouse?.id) ? ` (${cfg.lakehouse.id})` : ' (created if it does not exist)'}`);
  console.log(`Sign-in:   tenant ${filled(tenant) ? tenant : 'NOT SET: set tenantId'}${!filled(cfg.fabricTenantId) ? " (deploy asks you to confirm it's also the Fabric tenant)" : cfg.fabricTenantId !== cfg.tenantId ? ' (fabricTenantId; the app and data stay in ' + cfg.tenantId + ')' : ''}`);
  printExports(report);
  console.log('\nRun npm run deploy (without --dry-run) to deploy.');
  process.exit(0);
}

if (FLAGS.has('--watch')) {
  if (!filled(cfg.lakehouse?.id)) fail('lakehouse.id is not set in config.json. Run npm run deploy first.');
  await signIn();
  const ws = await findWorkspace();
  const orch = (await list(`/workspaces/${ws.id}/notebooks`)).find((n) => n.displayName === 'Lake_Orchestrator');
  if (!orch) fail(`No Lake_Orchestrator notebook in workspace ${ws.displayName}. Run npm run deploy first.`);
  const runs = await list(`/workspaces/${ws.id}/items/${orch.id}/jobs/instances`);
  const latest = runs.sort((a, b) => Date.parse(b.startTimeUtc ?? 0) - Date.parse(a.startTimeUtc ?? 0))[0];
  if (!latest) fail('Lake_Orchestrator has not been run yet. Start it with npm run deploy -- --run first_load, or Run all in Fabric.');
  console.log(`Latest Lake_Orchestrator run started ${new Date(latest.startTimeUtc).toLocaleString()}.`);
  const job = await watchOrchestrator(ws, cfg.lakehouse.id, orch.id, `/workspaces/${ws.id}/items/${orch.id}/jobs/instances/${latest.id}`);
  process.exit(job.status === 'Completed' ? 0 : 1);
}

printExports(report);
await signIn();
const ws = await findWorkspace();
console.log(`Workspace ${ws.displayName} found.`);
const lh = await findOrCreateLakehouse(ws);
writeBack(ws, lh);

let rerun = null;
if (RERUN_FAILED) {
  const st = await readLatestStatus(ws, lh.id);
  const runId = arg('run-id', '') || st?.run_id;
  if (!runId) fail('No Lake_Orchestrator run to retry yet. Start one with npm run deploy -- --run first_load.');
  if (!arg('run-id', '') && st?.status === 'running') {
    fail(`Run ${runId} has not finished its summary: it is still running (follow it with npm run deploy -- --watch), or it stopped in one of\n` +
      `its own cells. To retry it anyway: npm run deploy -- --rerun-failed --run-id ${runId}`);
  }
  if (!arg('run-id', '') && !st?.failed?.length) {
    console.log(`\nThe last run (${runId}) has no failed steps: nothing to retry.`);
    process.exit(0);
  }
  rerun = { runId, mode: (st?.run_id === runId && st.run_mode) || runId.split('-')[0] };
  if (st?.run_id === runId) console.log(`\nWill retry ${st.failed.map((f) => f.step).join(', ')} from run ${runId} after deploying.`);
}

console.log('\nBuilding the notebooks and model files for this Lakehouse (npm run all) ...');
build();

const ids = await deployNotebooks(ws, lh);
await uploadModels(ws, lh);
await uploadCsvs(ws, lh, report);

if (FLAGS.has('--skip-setup')) process.exit(0);
const setupId = ids.Lake_Setup;
if (!setupId) fail('Lake_Setup was not found in out/notebooks. Check the build output above.');
console.log('\nRunning Lake_Setup (sets up the Lakehouse and checks the app). The first run waits for Spark to start, a few minutes ...');
const job = await runNotebook(ws, setupId, null, { wait: true, name: 'Lake_Setup' });
if (job?.status !== 'Completed') {
  console.error(`\nLake_Setup did not succeed: ${job?.status}${job?.failureReason?.message ? `: ${job.failureReason.message}` : ''}`);
  console.error(`Open it to see which check failed: ${notebookLink(ws, setupId)}`);
  console.error('Fix the cause (TROUBLESHOOTING.md lists the usual ones), then run Lake_Setup again in Fabric or run npm run deploy again.');
  process.exit(1);
}
console.log('Lake_Setup passed: the Lakehouse is ready and the app has the permissions it needs.');
try { await connectModels(ws, lh); }
catch (e) {
  console.warn(`  Could not connect the models with the workspace identity: ${e.message}`);
  console.warn('  This needs workspace Admin and a paid Fabric capacity (F SKU). Until it works, model refreshes fail with');
  console.warn('  Premium_ASWL_Error. Fix the cause and run npm run deploy again, or see 06-models/README.md for the manual sign-in.');
}

if (rerun) {
  const orch = ids.Lake_Orchestrator;
  const params = {
    RUN_MODE: { value: rerun.mode, type: 'string' },
    RUN_ID: { value: rerun.runId, type: 'string' },
    RERUN_FAILED: { value: true, type: 'bool' },
  };
  const start = (budget) => runNotebook(ws, orch, params, { wait: false, name: 'Lake_Orchestrator', budget });
  const location = await start({ used: 0 });
  console.log(`\nStarted Lake_Orchestrator for run ${rerun.runId}, only the steps that did not succeed. Open the notebook:\n  ${notebookLink(ws, orch)}`);
  console.log('The notebook\'s saved settings (and its schedule) are not changed.');
  if (location) {
    const run = await watchOrchestrator(ws, lh.id, orch, location, start);
    process.exit(run.status === 'Completed' ? 0 : 1);
  }
} else if (RUN === 'first_load') {
  const orch = ids.Lake_Orchestrator;
  const start = (budget) => runNotebook(ws, orch, { RUN_MODE: { value: 'first_load', type: 'string' } },
    { wait: false, name: 'Lake_Orchestrator', budget });
  const location = await start({ used: 0 });
  console.log(`\nStarted Lake_Orchestrator with RUN_MODE = 'first_load'. It can take hours. Open the notebook:\n  ${notebookLink(ws, orch)}`);
  console.log("This link opens the notebook, not the run. To see each step, open the Run tab at the top of the notebook (not the Run all menu), choose Recent runs and open the newest one:");
  console.log("each cell shows whether it has run and its output so far. The Monitor hub (left bar in Fabric) lists the run too.");
  if (location) {
    const run = await watchOrchestrator(ws, lh.id, orch, location, start);
    process.exit(run.status === 'Completed' ? 0 : 1);
  }
} else {
  console.log(`\nNext (step 5): open Lake_Orchestrator, set RUN_MODE = 'first_load' and Run all, or run npm run deploy -- --run first_load.\n  ${notebookLink(ws, ids.Lake_Orchestrator)}`);
}

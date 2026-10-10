# %% [markdown]
# # Set up the Lakehouse and check the app
#
# `npm run deploy` runs this notebook for you, with the parameters filled in from `config.json`. You only open it
# yourself to see why it failed, or to run it again after fixing a permission. It is safe to run again: nothing is
# ever dropped.
#
# **Part 1: the Lakehouse**
#
# 1. Checks the Lakehouse is **schema-enabled** (the ingesters write to `dbo`; the promote step needs other schemas).
# 2. Creates the schemas **bronze**, **silver**, **gold** and **ops**, and the ops tables
#    (`ops.config`, `ops.run_log`, `ops.backfill_ledger`, `ops.table_layers`).
# 3. Creates the `Files/` folders for the sources you turned on.
# 4. Saves your settings to `ops.config`, which every later notebook reads.
#
# **Part 2: the app's permissions**, one check at a time, so a missing permission fails here with a clear message
# instead of an hour into a backfill.
#
# | Check | Proves | Fix if it fails |
# |---|---|---|
# | Key Vault | You can read the client secret (skipped, with a warning, if you use `CLIENT_SECRET`) | Give yourself *Key Vault Secrets User* on the vault |
# | Graph token | Tenant, app ID and secret are right | Check the IDs; make a new secret if it expired |
# | Graph roles | Admin consent covers every enabled source | Grant the missing permission, then *Grant admin consent* |
# | Graph probes | Each API answers (audit query, reports, users, Copilot packages) | See the message: licence, consent delay, or report privacy |
# | Report privacy | Usage reports show real names, so they join to org data | M365 admin center > Settings > Org settings > Reports: turn off concealment |
# | Azure | The app can read the subscription(s) for Azure AI spend | Give the app Reader, Cost Management Reader and Monitoring Reader |
# | Dataverse | The app can read conversation transcripts | Add the app as an application user with the Bot Transcript Viewer role |
#
# More fixes: `TROUBLESHOOTING.md` in the repo.

# %% [parameters]
TENANT_ID = ''
CLIENT_ID = ''
KEY_VAULT_URI = ''                   # recommended; leave blank only if you use the CLIENT_SECRET bypass
SECRET_NAME = 'universal-lake-client-secret'
CLIENT_SECRET = ''                   # NOT recommended: only when you have no Key Vault
SECRET_IN_NOTEBOOKS = False          # True when config.json has clientSecret and no Key Vault
SQL_ENDPOINT = ''                    # Lakehouse > SQL analytics endpoint > Settings > SQL connection string
SCALE = 'standard'                   # 'standard' or 'large' (more than ~20k Copilot users, or busy audit logs)
BACKFILL_DAYS = 30                   # audit history the first load fetches (max 180)
MODULES = 'copilotInteractions,orgData,m365Activity,agent365,productFeedback,consumption,agentEvaluator'
CSV_SOURCES = 'productFeedback,studioCredits,coworkCredits'  # sources set to 'csv'; Lake_Orchestrator checks their folders
AGENT365_SOURCE = 'api'              # 'api' needs Graph permissions; 'csv' does not
AZURE_SUBSCRIPTION_IDS = ''          # comma-separated; empty skips the Azure checks
DATAVERSE_URLS = ''                  # comma-separated, e.g. https://contoso.crm.dynamics.com
MODEL_ID_UNIVERSAL = ''              # filled in by Lake_Deploy_Models; set here only to reuse an existing model
MODEL_ID_CONSUMPTION = ''
MODEL_ID_AGENT_EVALUATOR = ''
STRICT = True                        # fail the run if any required check failed

# %%
%run lake_ops

# %%
import os

ctx = notebookutils.runtime.context
workspace_id = ctx.get('currentWorkspaceId')
workspace_name = ctx.get('currentWorkspaceName')
lakehouse_id = ctx.get('defaultLakehouseId')
lakehouse_name = ctx.get('defaultLakehouseName')
if not lakehouse_id:
    raise RuntimeError('No default Lakehouse. In the notebook explorer, add the Lakehouse and pin it as default.')
print(f'Workspace: {workspace_name} ({workspace_id})')
print(f'Lakehouse: {lakehouse_name} ({lakehouse_id})')

def _schema_name(s):
    return str(s).strip('`').split('.')[-1].strip('`').lower()

schemas = {_schema_name(r[0]) for r in spark.sql('SHOW SCHEMAS').collect()}
if 'dbo' not in schemas and not os.path.isdir('/lakehouse/default/Tables/dbo'):
    print('Schemas Spark sees:', ', '.join(sorted(schemas)) or '(none)')
    raise RuntimeError('This Lakehouse is not schema-enabled (it has no dbo schema). Check the Lakehouse explorer: a '
                       'schema-enabled Lakehouse shows Tables > dbo. If it does, make sure THIS Lakehouse is pinned as '
                       'the notebook default. If it does not, create a new Lakehouse with "Lakehouse schemas" ticked; '
                       'schemas cannot be turned on for an existing one.')

# %%
ensure_ops()
print('Schemas now:', ', '.join(sorted(r[0] for r in spark.sql('SHOW SCHEMAS').collect())))
for name in OPS_TABLES:
    print(f'  ops.{name}: {row_count(f"ops.{name}")} rows')

# %% [markdown]
# ## Files folders
#
# Only the folders for the sources you turned on are created (`analytics_hub_uploads` and `universal_lake/models` always).
#
# | Folder | Read by | Put here |
# |---|---|---|
# | `Files/analytics_hub_uploads` | Upload Router | Any CSV export; the router recognises it and moves it to the right folder |
# | `Files/agent365` | Agent365 Lander | `agents.csv` from the Microsoft 365 admin centre (CSV mode, or API fallback) |
# | `Files/product_feedback` | Product Feedback ingester | Feedback exports |
# | `Files/landing/studio` | Consumption_Ingest_Studio | Copilot Studio credit exports |
# | `Files/landing/viva` | Consumption_Ingest_Viva | Cowork / Viva credit exports |
# | `Files/org_workday` | Workday lander | Workday org extract (only when org data comes from Workday) |
# | `Files/universal_lake/models` | Lake_Promote_Medallion, Lake_Deploy_Models | Upload the whole `out/models` folder from `npm run models` here (`gold_tables.json`, `<key>/definition.json`) |

# %%
_mods = {m.strip() for m in MODULES.split(',') if m.strip()}
_csv = {s.strip() for s in CSV_SOURCES.split(',') if s.strip()}
FOLDERS = ['analytics_hub_uploads', 'universal_lake/models']
if 'agent365' in _mods: FOLDERS.append('agent365')
if 'productFeedback' in _mods: FOLDERS.append('product_feedback')
if 'consumption' in _mods: FOLDERS += ['landing/studio', 'landing/viva']
if 'workday' in _csv: FOLDERS.append('org_workday')
print('Created only for the sources you turned on:')
for f in FOLDERS:
    os.makedirs(f'/lakehouse/default/Files/{f}', exist_ok=True)
    print(f'  Files/{f}')

# %%
cfg_set({
    'workspace_id': workspace_id, 'workspace_name': workspace_name,
    'lakehouse_id': lakehouse_id, 'lakehouse_name': lakehouse_name, 'sql_endpoint': SQL_ENDPOINT,
    'tenant_id': TENANT_ID, 'client_id': CLIENT_ID, 'key_vault_uri': KEY_VAULT_URI, 'secret_name': SECRET_NAME,
    'secret_mode': 'notebook' if (SECRET_IN_NOTEBOOKS or (CLIENT_SECRET and not KEY_VAULT_URI)) else 'keyvault',
    'scale': SCALE, 'backfill_days': BACKFILL_DAYS, 'modules': MODULES, 'csv_sources': CSV_SOURCES,
    'model_id.universal': MODEL_ID_UNIVERSAL, 'model_id.consumption': MODEL_ID_CONSUMPTION,
    'model_id.agentEvaluator': MODEL_ID_AGENT_EVALUATOR,
})
display(spark.table('ops.config').orderBy('key'))
missing = [k for k in ('tenant_id', 'client_id', 'sql_endpoint') if not cfg(k)]
if not SECRET_IN_NOTEBOOKS and not cfg('key_vault_uri'):
    missing.append('key_vault_uri (or use the clientSecret bypass)')
if SECRET_IN_NOTEBOOKS:
    print('WARNING: no Key Vault. The client secret is inside the notebooks; move it to Key Vault when you can.')
if missing:
    print('Still to set (fix config.json and run npm run deploy again):', ', '.join(missing))

# %% [markdown]
# ## Part 2: the app's permissions

# %%
import base64
import json
import requests

modules = {'copilotInteractions' if m.strip() == 'core' else m.strip() for m in MODULES.split(',') if m.strip()}
results = []


def check(name, ok, detail='', required=True):
    results.append({'check': name, 'ok': bool(ok), 'required': required, 'detail': detail})
    mark = 'OK  ' if ok else ('FAIL' if required else 'WARN')
    print(f'{mark} {name}' + (f': {detail}' if detail else ''))
    return ok


for name, value in {'TENANT_ID': TENANT_ID, 'CLIENT_ID': CLIENT_ID}.items():
    if not value:
        raise ValueError(f'{name} is empty. Fill in the parameters cell first.')
if not KEY_VAULT_URI and not CLIENT_SECRET:
    raise ValueError('Set KEY_VAULT_URI (recommended) or, if you have no Key Vault, CLIENT_SECRET.')

# %% [markdown]
# ## Client secret and app token

# %%
secret = None
if KEY_VAULT_URI:
    try:
        secret = notebookutils.credentials.getSecret(KEY_VAULT_URI, SECRET_NAME)
        check('Key Vault secret readable', bool(secret), f'{KEY_VAULT_URI} / {SECRET_NAME}')
    except Exception as e:
        check('Key Vault secret readable', False, str(e)[:300])
else:
    secret = CLIENT_SECRET
    check('Client secret from Key Vault', False, 'using CLIENT_SECRET from the notebook (not recommended); move it to Key Vault when you can', required=False)


def app_token(scope):
    r = requests.post(f'https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token', timeout=30, data={
        'client_id': CLIENT_ID, 'client_secret': secret, 'grant_type': 'client_credentials', 'scope': scope})
    if r.status_code != 200:
        raise RuntimeError(r.json().get('error_description', r.text)[:400])
    return r.json()['access_token']


def claims(token):
    part = token.split('.')[1]
    return json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))


graph = None
if secret:
    try:
        graph = app_token('https://graph.microsoft.com/.default')
        check('Graph token', True, f"app {claims(graph).get('app_displayname', CLIENT_ID)}")
    except Exception as e:
        check('Graph token', False, str(e))

# %% [markdown]
# ## Graph permissions (admin consent)
#
# The token's `roles` claim lists the application permissions that have admin consent. New consent can take a
# few minutes to appear in new tokens.

# %%
REQUIRED = {
    'copilotInteractions': ['AuditLogsQuery.Read.All', 'Reports.Read.All'],
    'orgData': ['User.Read.All'],
    'm365Activity': ['Reports.Read.All'],
    'agent365': ['CopilotPackages.Read.All', 'Application.Read.All', 'User.Read.All'] if AGENT365_SOURCE == 'api' else [],
}
if graph:
    roles = set(claims(graph).get('roles', []))
    print('Consented roles:', ', '.join(sorted(roles)) or '(none)')
    for module, needed in REQUIRED.items():
        if module in modules or module == 'copilotInteractions':
            missing = [p for p in needed if p not in roles]
            check(f'Graph permissions for {module}', not missing, 'missing ' + ', '.join(missing) if missing else ', '.join(needed))

# %% [markdown]
# ## Graph probes
#
# A role in the token is not proof the API works: the audit query API also needs auditing turned on, and the
# Copilot packages API needs the tenant to have Copilot. Each probe makes the smallest call the ingester makes.

# %%
def graph_get(url):
    return requests.get(url, headers={'Authorization': f'Bearer {graph}'}, timeout=60, allow_redirects=True)


if graph:
    r = graph_get('https://graph.microsoft.com/beta/security/auditLog/queries?$top=1')
    check('Audit log query API', r.status_code == 200, f'HTTP {r.status_code} {r.text[:200] if r.status_code != 200 else ""}')

    r = graph_get("https://graph.microsoft.com/v1.0/reports/getOffice365ActiveUserDetail(period='D7')")
    ok = r.status_code == 200
    check('Usage reports API (licensed users)', ok, f'HTTP {r.status_code}')
    if ok:
        rows = [l for l in r.text.splitlines()[1:] if l.strip()]
        upn = rows[0].split(',')[1] if rows and len(rows[0].split(',')) > 1 else ''
        check('Usage reports show real user names', '@' in upn or not rows,
              'names look concealed (hashed); turn off concealment in M365 admin centre > Org settings > Reports' if rows and '@' not in upn else f'{len(rows)} users',
              required=False)

    if 'orgData' in modules or (AGENT365_SOURCE == 'api' and 'agent365' in modules):
        r = graph_get('https://graph.microsoft.com/v1.0/users?$top=1&$select=id,userPrincipalName,department,manager')
        check('Users API (org data)', r.status_code == 200, f'HTTP {r.status_code}')

    if 'm365Activity' in modules:
        r = graph_get("https://graph.microsoft.com/v1.0/reports/getM365AppUserDetail(period='D7')?$format=text/csv")
        check('M365 app activity report', r.status_code == 200, f'HTTP {r.status_code}')

    if 'agent365' in modules and AGENT365_SOURCE == 'api':
        r = graph_get('https://graph.microsoft.com/v1.0/copilot/admin/catalog/packages?$top=1')
        if r.status_code == 404:
            r = graph_get('https://graph.microsoft.com/beta/copilot/admin/catalog/packages?$top=1')
        check('Copilot packages API (Agent 365)', r.status_code == 200, f'HTTP {r.status_code} {r.text[:200] if r.status_code != 200 else ""}')

# %% [markdown]
# ## Azure (Azure AI spend) and Dataverse (agent transcripts)

# %%
subs = [s.strip() for s in AZURE_SUBSCRIPTION_IDS.split(',') if s.strip()]
if secret and subs and 'consumption' in modules:
    try:
        arm = app_token('https://management.azure.com/.default')
        for sub in subs:
            h = {'Authorization': f'Bearer {arm}'}
            r = requests.get(f'https://management.azure.com/subscriptions/{sub}?api-version=2022-12-01', headers=h, timeout=60)
            check(f'Azure subscription {sub} readable (Reader)', r.status_code == 200, f'HTTP {r.status_code}')
            r = requests.post(f'https://management.azure.com/subscriptions/{sub}/providers/Microsoft.CostManagement/query?api-version=2023-03-01',
                              headers=h, timeout=60, json={'type': 'ActualCost', 'timeframe': 'MonthToDate',
                                                           'dataset': {'granularity': 'None', 'aggregation': {'c': {'name': 'Cost', 'function': 'Sum'}}}})
            check(f'Azure cost query on {sub} (Cost Management Reader)', r.status_code == 200, f'HTTP {r.status_code}')
    except Exception as e:
        check('Azure token', False, str(e))
elif 'consumption' in modules:
    print('SKIP Azure checks: no AZURE_SUBSCRIPTION_IDS')

envs = [u.strip().rstrip('/') for u in DATAVERSE_URLS.split(',') if u.strip()]
if secret and envs and 'agentEvaluator' in modules:
    for env in envs:
        try:
            dv = app_token(f'{env}/.default')
            h = {'Authorization': f'Bearer {dv}', 'Accept': 'application/json'}
            r = requests.get(f'{env}/api/data/v9.2/WhoAmI', headers=h, timeout=60)
            check(f'Dataverse {env}: application user exists', r.status_code == 200, f'HTTP {r.status_code}')
            r = requests.get(f'{env}/api/data/v9.2/conversationtranscripts?$top=1&$select=conversationtranscriptid', headers=h, timeout=60)
            check(f'Dataverse {env}: transcripts readable (Bot Transcript Viewer)', r.status_code == 200, f'HTTP {r.status_code}')
        except Exception as e:
            check(f'Dataverse {env}: token', False, str(e))
elif 'agentEvaluator' in modules:
    print('SKIP Dataverse checks: no DATAVERSE_URLS')

# %% [markdown]
# ## Result

# %%
failed = [r for r in results if r['required'] and not r['ok']]
warned = [r for r in results if not r['required'] and not r['ok']]
print(f"\n{len(results) - len(failed) - len(warned)} passed, {len(failed)} failed, {len(warned)} warnings")
for r in failed:
    print(f"  FAIL {r['check']}: {r['detail']}")
if failed and STRICT:
    raise RuntimeError(f'{len(failed)} credential check(s) failed. Fix them (see TROUBLESHOOTING.md), then run this notebook again.')
notebookutils.notebook.exit(json.dumps({'passed': not failed, 'failed': [r['check'] for r in failed]}))

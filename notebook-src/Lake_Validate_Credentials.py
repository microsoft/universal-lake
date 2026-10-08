# %% [markdown]
# # Validate credentials
#
# Run this **before** any ingester. It proves, one check at a time, that the app registration can do what the
# ingesters will ask of it, so a missing permission fails here with a clear message instead of an hour into a backfill.
#
# It needs no Lakehouse and writes nothing. Fill in the parameters cell from your `config.json`, then **Run all**.
#
# | Check | Proves | Fix if it fails |
# |---|---|---|
# | Key Vault | The notebook's user can read the client secret (skipped, with a warning, if you use `CLIENT_SECRET`) | Give yourself *Key Vault Secrets User* on the vault |
# | Graph token | Tenant, app ID and secret are right | Check the IDs; make a new secret if it expired |
# | Graph roles | Admin consent covers every enabled module | Grant the missing permission, then *Grant admin consent* |
# | Graph probes | Each API answers (audit query, reports, users, Copilot packages) | See the message: licence, consent delay, or report privacy |
# | Report privacy | Usage reports show real names, so they join to org data | M365 admin centre > Settings > Org settings > Reports: turn off concealment |
# | Azure | The app can read the subscription(s) for Azure AI spend | Give the app Reader, Cost Management Reader and Monitoring Reader |
# | Dataverse | The app can read conversation transcripts | Add the app as an application user with the Bot Transcript Viewer role |

# %% [parameters]
TENANT_ID = ''
CLIENT_ID = ''
KEY_VAULT_URI = ''              # https://<vault>.vault.azure.net/  (recommended)
SECRET_NAME = 'universal-lake-client-secret'
CLIENT_SECRET = ''              # NOT recommended: only when you have no Key Vault. Leave blank to use Key Vault.
MODULES = 'core,orgData,m365Activity,agent365,productFeedback,consumption,agentEvaluator'
AGENT365_SOURCE = 'api'         # 'api' needs Graph permissions; 'csv' does not
AZURE_SUBSCRIPTION_IDS = ''     # comma-separated; empty skips the Azure checks
DATAVERSE_URLS = ''             # comma-separated, e.g. https://contoso.crm.dynamics.com
STRICT = True                   # raise at the end if any required check failed

# %%
import base64
import json
import requests

modules = {m.strip() for m in MODULES.split(',') if m.strip()}
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
    'core': ['AuditLogsQuery.Read.All', 'Reports.Read.All'],
    'orgData': ['User.Read.All'],
    'm365Activity': ['Reports.Read.All'],
    'agent365': ['CopilotPackages.Read.All', 'Application.Read.All', 'User.Read.All'] if AGENT365_SOURCE == 'api' else [],
}
if graph:
    roles = set(claims(graph).get('roles', []))
    print('Consented roles:', ', '.join(sorted(roles)) or '(none)')
    for module, needed in REQUIRED.items():
        if module in modules or module == 'core':
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
    raise RuntimeError(f'{len(failed)} credential check(s) failed. Fix them before running the ingesters.')
notebookutils.notebook.exit(json.dumps({'passed': not failed, 'failed': [r['check'] for r in failed]}))

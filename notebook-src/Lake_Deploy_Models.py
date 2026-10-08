# %% [markdown]
# # Deploy the semantic models
#
# Deploys the models built on your PC by `npm run models`, which uses the installer's own model code and points it
# at the **gold** schema. Then it connects each model to the Lakehouse, refreshes it and checks it holds data.
#
# Before you run it:
#
# 1. Upload `out/models/<key>/definition.json` for each model to `Files/universal_lake/models/<key>/definition.json`.
#    `<key>` is `universal`, `consumption` or `agentEvaluator`.
# 2. Run Lake_Promote_Medallion so the gold tables exist. Otherwise the refresh fails on missing tables.
#
# For each model, in order:
#
# | Step | What happens | If it fails |
# |---|---|---|
# | Find | Looks the model up by the ID in `ops.config`, then by display name | n/a |
# | Create / update | Creates the model, or replaces its definition (`updateDefinition`). Updating clears its data until the refresh | Fix the reported error and run again. Nothing else has changed yet |
# | Connect | `CONNECTION_MODE`: `spn` creates or updates a SQL connection signed in as the app (secret from Key Vault, or `CLIENT_SECRET`); `existing` uses `CONNECTION_ID`; `skip` leaves it to you | Bind it yourself: model **Settings > Gateway and cloud connections** |
# | Refresh | Full refresh, then waits for it | `ops.run_log` holds the service's error; usually a missing gold table or the connection |
# | Probe | Counts rows in each model table through DAX | Zero rows means the gold table is empty: check the ingest for that source |
#
# Rerunning is safe: it updates the same models and the same connection.

# %% [parameters]
RUN_ID = ''
MODELS = 'universal,consumption,agentEvaluator'   # keys to deploy; missing definition files are skipped
DEFINITIONS_DIR = '/lakehouse/default/Files/universal_lake/models'
CONNECTION_MODE = 'spn'              # 'spn', 'existing' or 'skip'
CONNECTION_ID = ''                   # for CONNECTION_MODE = 'existing'
CONNECTION_NAME = ''                 # blank: 'Universal Lake SQL <workspace id prefix>'
DEPLOY = True                        # False: skip create/update and only connect, refresh and probe
REFRESH = True
REFRESH_TIMEOUT_MIN = 60
CLIENT_SECRET = ''                   # NOT recommended: only when you have no Key Vault (blank = read it from Key Vault)

# %%
%run lake_ops

# %%
import base64
import json
import os
import time

run_id = RUN_ID or new_run_id('deploy')
ws = cfg('workspace_id', required=True)
server = cfg('sql_endpoint', required=True)
database = cfg('lakehouse_name', required=True)
conn_name = CONNECTION_NAME or f'Universal Lake SQL {ws[:8]}'
keys = [k.strip() for k in MODELS.split(',') if k.strip()]


def load_definition(key):
    path = f'{DEFINITIONS_DIR}/{key}/definition.json'
    if not os.path.exists(path):
        return None
    return json.load(open(path))


def bim_of(definition):
    for p in definition['definition']['parts']:
        if p['path'] == 'model.bim':
            return json.loads(base64.b64decode(p['payload']))
    raise ValueError('definition has no model.bim part')


def find_model(key, name):
    known = cfg(f'model_id.{key}')
    models = rest_list(f'/workspaces/{ws}/semanticModels')
    for m in models:
        if known and m['id'] == known:
            return m
    for m in models:
        if m['displayName'] == name:
            return m
    return None


# %% [markdown]
# ## Connection
#
# The models load the Lakehouse SQL endpoint in **Import** mode, the same as the installer. The
# installer creates a new app secret for this connection; this notebook reuses the Key Vault secret instead, so
# rotating that one secret is all the upkeep there is (rerun this notebook after rotating it).

# %%
def ensure_connection():
    if CONNECTION_MODE == 'skip':
        return None
    if CONNECTION_MODE == 'existing':
        if not CONNECTION_ID:
            raise ValueError('CONNECTION_MODE is "existing" but CONNECTION_ID is blank')
        return CONNECTION_ID
    if CLIENT_SECRET:
        secret = CLIENT_SECRET
    elif cfg('key_vault_uri'):
        secret = notebookutils.credentials.getSecret(cfg('key_vault_uri'), cfg('secret_name', required=True))
    else:
        raise ValueError('No Key Vault in ops.config and CLIENT_SECRET is blank. Set one, or use CONNECTION_MODE = "skip".')
    credentials = {
        'singleSignOnType': 'None', 'connectionEncryption': 'Encrypted', 'skipTestConnection': False,
        'credentials': {'credentialType': 'ServicePrincipal', 'tenantId': cfg('tenant_id', required=True),
                        'servicePrincipalClientId': cfg('client_id', required=True), 'servicePrincipalSecret': secret},
    }
    existing = next((c for c in rest_list('/connections') if c.get('displayName') == conn_name), None)
    if existing:
        rest('PATCH', f"/connections/{existing['id']}", {'connectivityType': 'ShareableCloud', 'credentialDetails': credentials})
        print(f'Updated connection "{conn_name}" ({existing["id"]})')
        return existing['id']
    body = {
        'connectivityType': 'ShareableCloud', 'displayName': conn_name, 'privacyLevel': 'Organizational',
        'connectionDetails': {'type': 'SQL', 'creationMethod': 'Sql', 'parameters': [
            {'dataType': 'Text', 'name': 'server', 'value': server},
            {'dataType': 'Text', 'name': 'database', 'value': database}]},
        'credentialDetails': credentials,
    }
    created = rest('POST', '/connections', body).json()
    print(f'Created connection "{conn_name}" ({created["id"]})')
    return created['id']


def bind(model_id, connection_id):
    sources = rest('GET', f'{PBI_API}/groups/{ws}/datasets/{model_id}/datasources').json().get('value', [])
    sql = next((d.get('connectionDetails') for d in sources if str(d.get('datasourceType')).lower() == 'sql'), None) or {}
    path = f"{sql.get('server') or server};{sql.get('database') or database}"
    rest('POST', f'/workspaces/{ws}/semanticModels/{model_id}/bindConnection', {'connectionBinding': {
        'id': connection_id, 'connectivityType': 'ShareableCloud', 'connectionDetails': {'type': 'SQL', 'path': path}}})


def refresh(model_id):
    url = f'{PBI_API}/groups/{ws}/datasets/{model_id}/refreshes'
    r = rest('POST', url, {'type': 'full', 'commitMode': 'transactional', 'applyRefreshPolicy': True, 'retryCount': 1},
             ok=(200, 202, 409))
    if r.status_code == 409:
        print('  A refresh is already running; following it.')
        request_id = rest('GET', url + '?$top=1').json()['value'][0]['requestId']
    else:
        request_id = (r.headers.get('Location') or '').rstrip('/').split('/')[-1] or r.headers.get('RequestId')
    deadline = time.time() + REFRESH_TIMEOUT_MIN * 60
    while time.time() < deadline:
        time.sleep(15)
        detail = rest('GET', f'{url}/{request_id}').json()
        state = detail.get('extendedStatus') or detail.get('status')
        if state in ('Completed', 'Failed', 'Cancelled', 'Disabled'):
            return state, detail
    return 'TimedOut', {'requestId': request_id}


def probe(model_id, bim):
    tables = [t['name'] for t in bim['model']['tables']
              if not t.get('isHidden') and any(p.get('source', {}).get('type') == 'm' for p in t.get('partitions', []))]
    if not tables:
        return []
    rows = ', '.join(f"""ROW("table", "{t}", "rows", COUNTROWS('{t.replace("'", "''")}'))""" for t in tables)
    q = f'EVALUATE UNION({rows})' if len(tables) > 1 else f'EVALUATE {rows}'
    res = rest('POST', f'{PBI_API}/groups/{ws}/datasets/{model_id}/executeQueries',
               {'queries': [{'query': q}], 'serializerSettings': {'includeNulls': True}}).json()
    return [(r.get('[table]'), r.get('[rows]')) for r in res['results'][0]['tables'][0]['rows']]


# %%
connection_id = None
outcomes = {}
for i, key in enumerate(keys, 1):
    definition = load_definition(key)
    if definition is None:
        print(f'{key}: no {DEFINITIONS_DIR}/{key}/definition.json; skipped')
        outcomes[key] = 'skipped'
        continue
    name = definition['displayName']
    bim = bim_of(definition)
    step = log_start(run_id, f'deploy:{key}', 'Lake_Deploy_Models', 'deploy' if DEPLOY else 'refresh',
                     {'name': name, 'connection_mode': CONNECTION_MODE}, step_no=i)
    try:
        print(f'\n=== {name} ===')
        model = find_model(key, name)
        if DEPLOY:
            if model:
                rest_lro('POST', f"/workspaces/{ws}/semanticModels/{model['id']}/updateDefinition", {'definition': definition['definition']})
                print(f"Updated definition of {model['id']}")
            else:
                rest_lro('POST', f'/workspaces/{ws}/semanticModels',
                         {'displayName': name, 'description': 'Universal Data Lake semantic model, reads the gold schema', 'definition': definition['definition']})
                model = find_model(key, name)
                if not model:
                    raise RuntimeError('Create reported success but the model is not listed yet; rerun this notebook.')
                print(f"Created {model['id']}")
        elif not model:
            raise RuntimeError(f'{name} does not exist and DEPLOY is False')
        model_id = model['id']
        cfg_set({f'model_id.{key}': model_id})

        if CONNECTION_MODE != 'skip':
            connection_id = connection_id or ensure_connection()
            bind(model_id, connection_id)
            print(f'Bound to connection {connection_id}')
        else:
            print('CONNECTION_MODE is skip: bind it under model Settings > Gateway and cloud connections, then rerun with DEPLOY=False.')

        print('Relationships:')
        for r in bim['model'].get('relationships', []):
            print(f"  {r['fromTable']}[{r['fromColumn']}] -> {r['toTable']}[{r['toColumn']}]{'' if r.get('isActive', True) else ' (inactive)'}")

        state = 'not refreshed'
        if REFRESH:
            print('Refreshing...')
            state, detail = refresh(model_id)
            print(f'Refresh: {state}')
            if state != 'Completed':
                raise RuntimeError(f'Refresh {state}: {json.dumps(detail.get("serviceExceptionJson") or detail)[:3000]}')
            try:
                counts = probe(model_id, bim)
            except Exception as e:
                counts = []
                print(f'Row-count check skipped ({str(e)[:200]}). The tenant setting '
                      '"Semantic model Execute Queries REST API" may be off; the refresh itself succeeded.')
            for t, n in counts:
                print(f'  {t:40} {n if n is not None else 0:>12,}')
            empty = [t for t, n in counts if not n]
            if empty:
                print(f'Empty tables: {", ".join(empty)}. Check the ingest for those sources.')
        outcomes[key] = state
        log_end(step, 'succeeded', json.dumps({'model_id': model_id, 'refresh': state}))
    except Exception as e:
        outcomes[key] = f'failed: {str(e)[:300]}'
        log_end(step, 'failed', error=e)
        print(f'FAILED: {e}')

print('\n', json.dumps(outcomes, indent=2))
if any(str(v).startswith('failed') for v in outcomes.values()):
    raise RuntimeError(f'One or more models failed: {outcomes}')
notebookutils.notebook.exit(json.dumps(outcomes))

# %% [markdown]
# # Initialise the Lakehouse
#
# Attach the Lakehouse as this notebook's **default Lakehouse**, fill in the parameters, then **Run all**.
#
# What it does (all of it is safe to run again; nothing is ever dropped):
#
# 1. Checks the Lakehouse is **schema-enabled** (the ingesters write to `dbo`; the promote step needs other schemas).
# 2. Creates the schemas **bronze**, **silver**, **gold** and **ops**.
# 3. Creates the ops tables: `ops.config`, `ops.run_log`, `ops.backfill_ledger` and `ops.table_layers`.
# 4. Creates the `Files/` folders the ingesters and the upload router read.
# 5. Saves your settings to `ops.config`, which every later notebook reads, so you enter them once.
#
# | Schema | Holds | Written by |
# |---|---|---|
# | `dbo` | The ingesters' working tables, as they write them | Ingester and processor notebooks (unchanged) |
# | `bronze` | Raw extracts: parsed audit records, raw transcripts, upload and load logs | Lake_Promote_Medallion |
# | `silver` | Cleaned dimensions and module outputs the models do not read directly | Lake_Promote_Medallion |
# | `gold` | Exactly the tables the semantic models read | Lake_Promote_Medallion |
# | `ops` | Run log, backfill ledger, promote log and settings | Every `Lake_*` notebook |

# %% [parameters]
TENANT_ID = ''
CLIENT_ID = ''
KEY_VAULT_URI = ''                   # recommended; leave blank only if you use the CLIENT_SECRET bypass
SECRET_NAME = 'universal-lake-client-secret'
SECRET_IN_NOTEBOOKS = False          # True when config.json has clientSecret and no Key Vault (not recommended)
SQL_ENDPOINT = ''                    # Lakehouse > SQL analytics endpoint > Settings > SQL connection string
SCALE = 'standard'                   # 'standard' or 'large' (more than ~20k Copilot users, or busy audit logs)
BACKFILL_DAYS = 30                   # audit history the first load fetches (max 180)
MODULES = 'copilotInteractions,orgData,m365Activity,agent365,productFeedback,consumption,agentEvaluator'
CSV_SOURCES = 'productFeedback,studioCredits,coworkCredits'  # sources set to 'csv'; Lake_Orchestrator checks their folders
MODEL_ID_UNIVERSAL = ''              # filled in by Lake_Deploy_Models; set here only to reuse an existing model
MODEL_ID_CONSUMPTION = ''
MODEL_ID_AGENT_EVALUATOR = ''

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
    'secret_mode': 'notebook' if SECRET_IN_NOTEBOOKS else 'keyvault',
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
    print('Still to set (rerun this notebook with them filled in):', ', '.join(missing))

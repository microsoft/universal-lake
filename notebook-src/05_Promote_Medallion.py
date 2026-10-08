# %% [markdown]
# # 05 Promote to bronze, silver and gold
#
# The ingesters and the processor are the installer's own notebooks, unchanged, so they write to `dbo`. This notebook
# copies each `dbo` table into **exactly one** medallion layer, so the semantic models can read `gold` and nothing else.
#
# | Layer | Rule | Tables today |
# |---|---|---|
# | **gold** | Every table a semantic model reads (from `gold_tables.json`, made by `npm run models`) | `copilot_interactions_curated`, `copilot_licensed_users`, `copilot_org_data`, `agents_365`, `user_feedback`, `m365_activity_daily`, `azure_*`, `studio_*`, `viva_*`, `agent_*`, ... |
# | **bronze** | Raw extracts and operational logs (`BRONZE_PATTERNS`) | `copilot_interactions_parsed`, `*_raw`, `*_staging*`, `agents_365_detail_cache`, `analytics_hub_upload_log`, `load_log`, `attempt_errors` |
# | **silver** | Everything else | `agents_365_history`, `studio_agent_daily`, `is_returning_user`, Workday preview, ... |
#
# Every copy is a full **overwrite** of the target from the current `dbo` table, so a promote can always be rerun and
# always leaves the layer equal to `dbo`. With `SKIP_UNCHANGED`, a table whose `dbo` Delta version has not moved since
# its last successful promote is skipped. Every table's result is written to `ops.table_layers`.

# %% [parameters]
RUN_ID = ''                          # set by 07_Orchestrator; blank makes a new one
SOURCE_SCHEMA = 'dbo'
GOLD_TABLES_FILE = '/lakehouse/default/Files/universal_lake/models/gold_tables.json'
TABLES = ''                          # comma-separated subset; blank promotes every table in SOURCE_SCHEMA
SKIP_UNCHANGED = True                # skip tables whose source has not changed since the last promote
DRY_RUN = False                      # print the plan only
REQUIRED_GOLD = 'copilot_interactions_curated,copilot_licensed_users'   # fail if any of these is not in gold afterwards
LAYER_OVERRIDES_JSON = '{}'          # e.g. {"agents_365_history": "gold"}
DROP_STALE = False                   # drop copies of a table left in another layer after its layer changed

# %%
%run lake_ops

# %%
import fnmatch
import json
import os

BRONZE_PATTERNS = ['copilot_interactions_parsed', '*_raw', '*_staging*', 'staging_*', '*_detail_cache',
                   'analytics_hub_upload_log', 'load_log', 'attempt_errors']

run_id = RUN_ID or new_run_id('promote')
overrides = json.loads(LAYER_OVERRIDES_JSON or '{}')

if os.path.exists(GOLD_TABLES_FILE):
    by_model = json.load(open(GOLD_TABLES_FILE))
else:
    raise FileNotFoundError(f'{GOLD_TABLES_FILE} not found. Run `npm run models` on your PC and upload the '
                            'out/models folder into Files/universal_lake/ (giving Files/universal_lake/models/).')
gold_set = {t.lower() for tables in by_model.values() for t in tables}


def layer_for(table):
    t = table.lower()
    if t in overrides:
        return overrides[t]
    if t in gold_set:
        return 'gold'
    if any(fnmatch.fnmatch(t, p) for p in BRONZE_PATTERNS):
        return 'bronze'
    return 'silver'


def delta_version(full):
    try:
        return spark.sql(f'DESCRIBE HISTORY {full} LIMIT 1').collect()[0]['version']
    except Exception:
        return None


def last_promoted_version(table, layer):
    rows = spark.sql(f"""
        SELECT source_version FROM ops.table_layers
        WHERE table_name = '{table}' AND layer = '{layer}' AND status = 'promoted'
        ORDER BY promoted_at DESC LIMIT 1
    """).collect()
    return rows[0]['source_version'] if rows else None


source_tables = list_tables(SOURCE_SCHEMA)
wanted = {t.strip().lower() for t in TABLES.split(',') if t.strip()}
if wanted:
    unknown = wanted - {t.lower() for t in source_tables}
    if unknown:
        raise ValueError(f'Not in {SOURCE_SCHEMA}: {", ".join(sorted(unknown))}')
    source_tables = [t for t in source_tables if t.lower() in wanted]

plan = [(t, layer_for(t)) for t in source_tables]
print(f'Run {run_id}: {len(plan)} table(s) from {SOURCE_SCHEMA}\n')
for layer in ('bronze', 'silver', 'gold'):
    names = [t for t, l in plan if l == layer]
    print(f'{layer:7} {len(names):3}  {", ".join(names)}')

# %%
results = []
step = log_start(run_id, 'promote', '05_Promote_Medallion', 'dry_run' if DRY_RUN else 'promote',
                 {'tables': TABLES or '*', 'skip_unchanged': SKIP_UNCHANGED})
try:
    for table, layer in plan:
        src, dst = f'{SOURCE_SCHEMA}.{table}', f'{layer}.{table}'
        version = delta_version(src)
        if DRY_RUN:
            results.append((table, layer, 'planned', None, version, ''))
            continue
        if SKIP_UNCHANGED and version is not None and table_exists(dst) and last_promoted_version(table, layer) == version:
            results.append((table, layer, 'unchanged', row_count(dst), version, 'source version unchanged'))
            continue
        try:
            df = spark.table(src)
            df.write.format('delta').mode('overwrite').option('overwriteSchema', 'true').saveAsTable(dst)
            n = spark.table(dst).count()
            results.append((table, layer, 'promoted', n, version, ''))
        except Exception as e:
            results.append((table, layer, 'failed', None, version, str(e)[:2000]))

        for other in ('bronze', 'silver', 'gold'):
            if other != layer and table_exists(f'{other}.{table}'):
                if DROP_STALE:
                    spark.sql(f'DROP TABLE {other}.{table}')
                    print(f'Dropped stale {other}.{table}')
                else:
                    print(f'WARNING: {other}.{table} also exists (stale from an earlier layer rule). DROP_STALE=True removes it.')

    if not DRY_RUN:
        now = utcnow()
        _append('table_layers', OPS_TABLES['table_layers'],
                [(run_id, t, f'{SOURCE_SCHEMA}.{t}', l, f'{l}.{t}', n, v, s, now, note) for t, l, s, n, v, note in results])

    print(f"{'table':40} {'layer':7} {'status':10} {'rows':>12}")
    for t, l, s, n, v, note in results:
        print(f"{t:40} {l:7} {s:10} {'' if n is None else f'{n:,}':>12}  {note[:120]}")

    # Which tables each model needs that gold does not have.
    gold_now = {t.lower() for t in list_tables('gold')}
    print('\nGold coverage per model:')
    for model, tables in by_model.items():
        missing = [t for t in tables if t.lower() not in gold_now]
        print(f'  {model:15} {len(tables) - len(missing)}/{len(tables)}' + (f'  missing: {", ".join(missing)}' if missing else ''))
    required_missing = [t for t in REQUIRED_GOLD.split(',') if t.strip() and t.strip().lower() not in gold_now]
    failed = [t for t, l, s, *_ in results if s == 'failed']
    if failed or (required_missing and not DRY_RUN):
        raise RuntimeError(f'Promote incomplete. Failed: {failed or "none"}. Required but not in gold: {required_missing or "none"}')
    summary = {'promoted': sum(1 for r in results if r[2] == 'promoted'), 'unchanged': sum(1 for r in results if r[2] == 'unchanged')}
    log_end(step, 'succeeded', json.dumps(summary))
except Exception as e:
    log_end(step, 'failed', error=e)
    raise

notebookutils.notebook.exit(json.dumps(summary if not DRY_RUN else {'planned': len(plan)}))

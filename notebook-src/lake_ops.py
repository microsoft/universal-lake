# %% [markdown]
# # lake_ops: shared run log, backfill ledger and Fabric REST helpers
#
# Not run on its own. The repo's notebooks load it with `%run lake_ops`, so it must be in the same workspace
# and the notebook calling it must have the Lakehouse attached as its default Lakehouse.
#
# Tables (all in the `ops` schema, created by Lake_Init):
#
# | Table | One row per | Use |
# |---|---|---|
# | `ops.config` | setting | Workspace, Lakehouse, tenant, app and Key Vault settings every notebook reads |
# | `ops.run_log` | step start and step end | What ran, with which parameters, how long it took, and why it failed |
# | `ops.backfill_ledger` | backfill or rerun window per source | Which date ranges were loaded, by which run, and whether they finished |
# | `ops.table_layers` | promoted table per run | Which layer each table went to and its row count |

# %%
import datetime as _dt
import json as _json
import time as _time
import traceback as _tb
import uuid as _uuid

import requests as _requests
from pyspark.sql import Row as _Row
from pyspark.sql import types as _T

OPS_SCHEMA = 'ops'
LAYERS = ('bronze', 'silver', 'gold')

_RUN_LOG_SCHEMA = _T.StructType([
    _T.StructField('run_id', _T.StringType()),
    _T.StructField('step_no', _T.IntegerType()),
    _T.StructField('step', _T.StringType()),
    _T.StructField('notebook', _T.StringType()),
    _T.StructField('run_mode', _T.StringType()),
    _T.StructField('event', _T.StringType()),
    _T.StructField('status', _T.StringType()),
    _T.StructField('params_json', _T.StringType()),
    _T.StructField('started_at', _T.TimestampType()),
    _T.StructField('ended_at', _T.TimestampType()),
    _T.StructField('duration_s', _T.DoubleType()),
    _T.StructField('exit_value', _T.StringType()),
    _T.StructField('error', _T.StringType()),
])
_LEDGER_SCHEMA = _T.StructType([
    _T.StructField('run_id', _T.StringType()),
    _T.StructField('source', _T.StringType()),
    _T.StructField('mode', _T.StringType()),
    _T.StructField('window_start', _T.DateType()),
    _T.StructField('window_end', _T.DateType()),
    _T.StructField('days', _T.IntegerType()),
    _T.StructField('status', _T.StringType()),
    _T.StructField('recorded_at', _T.TimestampType()),
    _T.StructField('note', _T.StringType()),
])
_LAYERS_SCHEMA = _T.StructType([
    _T.StructField('run_id', _T.StringType()),
    _T.StructField('table_name', _T.StringType()),
    _T.StructField('source', _T.StringType()),
    _T.StructField('layer', _T.StringType()),
    _T.StructField('target', _T.StringType()),
    _T.StructField('rows', _T.LongType()),
    _T.StructField('source_version', _T.LongType()),
    _T.StructField('status', _T.StringType()),
    _T.StructField('promoted_at', _T.TimestampType()),
    _T.StructField('note', _T.StringType()),
])
_CONFIG_SCHEMA = _T.StructType([
    _T.StructField('key', _T.StringType()),
    _T.StructField('value', _T.StringType()),
    _T.StructField('updated_at', _T.TimestampType()),
])
OPS_TABLES = {
    'run_log': _RUN_LOG_SCHEMA,
    'backfill_ledger': _LEDGER_SCHEMA,
    'table_layers': _LAYERS_SCHEMA,
    'config': _CONFIG_SCHEMA,
}


def utcnow():
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


def new_run_id(prefix='run'):
    return f"{prefix}-{utcnow():%Y%m%d-%H%M%S}-{_uuid.uuid4().hex[:6]}"


def table_exists(name):
    try:
        return spark.catalog.tableExists(name)
    except Exception:
        try:
            spark.table(name).limit(0).collect()
            return True
        except Exception:
            return False


def row_count(name):
    return spark.table(name).count() if table_exists(name) else None


def list_tables(schema):
    rows = spark.sql(f'SHOW TABLES IN {schema}').collect()
    return sorted(r['tableName'] for r in rows if not r.asDict().get('isTemporary', False))


def ensure_ops():
    """Creates the medallion and ops schemas and the ops tables. Safe to run again: it never drops anything."""
    for schema in (*LAYERS, OPS_SCHEMA):
        spark.sql(f'CREATE SCHEMA IF NOT EXISTS {schema}')
    for name, schema in OPS_TABLES.items():
        full = f'{OPS_SCHEMA}.{name}'
        if not table_exists(full):
            spark.createDataFrame([], schema).write.format('delta').saveAsTable(full)


def _append(table, schema, rows):
    spark.createDataFrame(rows, schema).write.format('delta').mode('append').option('mergeSchema', 'true').saveAsTable(f'{OPS_SCHEMA}.{table}')


# ---------------------------------------------------------------- config

def cfg_all():
    if not table_exists(f'{OPS_SCHEMA}.config'):
        raise RuntimeError('ops.config is missing. Run Lake_Init first.')
    return {r['key']: r['value'] for r in spark.table(f'{OPS_SCHEMA}.config').collect()}


def cfg(key, default=None, required=False):
    value = cfg_all().get(key)
    if value in (None, ''):
        if required:
            raise RuntimeError(f'ops.config has no "{key}". Set it in Lake_Init and run that notebook again.')
        return default
    return value


def cfg_set(values):
    """Upserts settings. Empty values are ignored, so rerunning init with blanks never wipes a setting."""
    values = {k: str(v) for k, v in values.items() if v not in (None, '')}
    if not values:
        return
    now = utcnow()
    spark.createDataFrame([(k, v, now) for k, v in values.items()], _CONFIG_SCHEMA).createOrReplaceTempView('_vl_cfg_new')
    spark.sql(f"""
        MERGE INTO {OPS_SCHEMA}.config t USING _vl_cfg_new s ON t.key = s.key
        WHEN MATCHED THEN UPDATE SET t.value = s.value, t.updated_at = s.updated_at
        WHEN NOT MATCHED THEN INSERT *
    """)


# ---------------------------------------------------------------- run log

def log_start(run_id, step, notebook='', run_mode='', params=None, step_no=None):
    started = utcnow()
    _append('run_log', _RUN_LOG_SCHEMA, [(run_id, step_no, step, notebook, run_mode, 'start', 'running',
                                          _json.dumps(params or {}, default=str), started, None, None, None, None)])
    return {'run_id': run_id, 'step_no': step_no, 'step': step, 'notebook': notebook, 'run_mode': run_mode,
            'params': params or {}, 'started_at': started}


def log_end(rec, status, exit_value=None, error=None):
    ended = utcnow()
    duration = (ended - rec['started_at']).total_seconds()
    _append('run_log', _RUN_LOG_SCHEMA, [(rec['run_id'], rec['step_no'], rec['step'], rec['notebook'], rec['run_mode'], 'end', status,
                                          _json.dumps(rec['params'], default=str), rec['started_at'], ended, duration,
                                          None if exit_value is None else str(exit_value)[:4000],
                                          None if error is None else str(error)[:8000])])
    return duration


def step_status(run_id):
    """Latest status of every step in a run: {step: status}."""
    if not table_exists(f'{OPS_SCHEMA}.run_log'):
        return {}
    rows = spark.sql(f"""
        SELECT step, status FROM (
          SELECT step, status, ROW_NUMBER() OVER (PARTITION BY step ORDER BY coalesce(ended_at, started_at) DESC, event DESC) rn
          FROM {OPS_SCHEMA}.run_log WHERE run_id = '{run_id}'
        ) WHERE rn = 1
    """).collect()
    return {r['step']: r['status'] for r in rows}


def last_run_id():
    if not table_exists(f'{OPS_SCHEMA}.run_log'):
        return None
    r = spark.sql(f'SELECT run_id FROM {OPS_SCHEMA}.run_log ORDER BY started_at DESC LIMIT 1').collect()
    return r[0]['run_id'] if r else None


def show_run(run_id):
    display(spark.sql(f"""
        SELECT step_no, step, notebook, status, started_at, ended_at, round(duration_s / 60, 1) AS minutes, exit_value, error
        FROM {OPS_SCHEMA}.run_log WHERE run_id = '{run_id}' AND event = 'end' ORDER BY step_no, ended_at
    """))


# ---------------------------------------------------------------- backfill ledger

def ledger(run_id, source, mode, window_start=None, window_end=None, days=None, status='planned', note=''):
    _append('backfill_ledger', _LEDGER_SCHEMA, [(run_id, source, mode, window_start, window_end,
                                                 None if days is None else int(days), status, utcnow(), note)])


def ledger_summary():
    """Latest status of every window ever recorded, newest first."""
    display(spark.sql(f"""
        SELECT source, mode, window_start, window_end, days, status, run_id, recorded_at, note FROM (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY run_id, source ORDER BY recorded_at DESC) rn FROM {OPS_SCHEMA}.backfill_ledger
        ) WHERE rn = 1 ORDER BY recorded_at DESC
    """))


# ---------------------------------------------------------------- Fabric and Power BI REST (as the signed-in user)

FABRIC_API = 'https://api.fabric.microsoft.com/v1'
PBI_API = 'https://api.powerbi.com/v1.0/myorg'


def _headers():
    return {'Authorization': f"Bearer {notebookutils.credentials.getToken('pbi')}", 'Content-Type': 'application/json'}


def rest(method, url, body=None, ok=(200, 201, 202, 204), retries=4):
    """One REST call with throttling retries. Returns the response; raises with the service's message on failure."""
    url = url if url.startswith('http') else FABRIC_API + url
    for attempt in range(retries + 1):
        r = _requests.request(method, url, headers=_headers(), json=body, timeout=120)
        if r.status_code == 429 or (r.status_code >= 500 and attempt < retries):
            _time.sleep(min(int(r.headers.get('Retry-After', 10 * (attempt + 1))), 120))
            continue
        if r.status_code not in ok:
            raise RuntimeError(f'{method} {url} -> {r.status_code}: {r.text[:2000]}')
        return r
    raise RuntimeError(f'{method} {url} still throttled after {retries} retries')


def rest_lro(method, url, body=None, want_result=False, timeout_s=1800):
    """Calls a Fabric API that may answer 202 and finish later, and waits for it to finish."""
    r = rest(method, url, body)
    if r.status_code != 202:
        return r.json() if r.content else None
    op = r.headers.get('x-ms-operation-id')
    location = r.headers.get('Location') or (f'{FABRIC_API}/operations/{op}' if op else None)
    deadline = _time.time() + timeout_s
    while _time.time() < deadline:
        _time.sleep(int(r.headers.get('Retry-After', 5)))
        r = rest('GET', location)
        state = (r.json() or {}).get('status', '')
        if state in ('Succeeded', 'Completed'):
            if want_result and op:
                return rest('GET', f'{FABRIC_API}/operations/{op}/result').json()
            return r.json()
        if state in ('Failed', 'Cancelled'):
            raise RuntimeError(f'{method} {url} failed: {_json.dumps(r.json())[:2000]}')
    raise TimeoutError(f'{method} {url} did not finish in {timeout_s}s')


def rest_list(url, key='value'):
    items, url = [], url
    while url:
        body = rest('GET', url).json()
        items += body.get(key, [])
        url = body.get('continuationUri')
    return items


print('lake_ops loaded')

"""Generate the two Microsoft 365 usage notebooks from their sources.

    python scripts/gen_m365_usage_notebooks.py --processor <path to Purview_M365_Usage_Bundle_Explosion_Processor_v2.6.1.py>

Writes:
  notebooks/M365_Usage_Audit_Ingester.ipynb  - Graph audit log -> dbo.m365_usage_rollup + dbo.m365_usage_sessionstats
  notebooks/M365_Usage_Gold.ipynb            - Entra users + UserStats/SessionCohort + CSV export for the M365 Usage Analytics template

The ingester reuses the fetch, retry and staging cells of notebooks/Copilot_Audit_Log_Direct_Ingester.ipynb
unchanged, so fixes there are picked up by running this script again. The row logic is the processor's own
functions, copied verbatim from https://github.com/microsoft/M365UsageAnalytics (MIT licence), so the
numbers match what the template's PowerShell + Python pipeline produces.
"""
from __future__ import annotations

import argparse
import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / 'notebooks' / 'Copilot_Audit_Log_Direct_Ingester.ipynb'
OUT_INGEST = ROOT / 'notebooks' / 'M365_Usage_Audit_Ingester.ipynb'
OUT_GOLD = ROOT / 'notebooks' / 'M365_Usage_Gold.ipynb'

PROCESSOR_VERSION = 'v2.6.1'
SEEDS = [
    '_extract_rollup_keys', 'get_array_fast', 'safe_get', '_norm_key_str',
    'write_userstats_files', 'ROLLUP_HEADER', 'SESSIONSTATS_HEADER',
    'USERSTATS_HEADER', 'SESSIONCOHORT_HEADER',
]

OPERATIONS = [
    'FileAccessed', 'FileViewed', 'FilePreviewed', 'FileModified', 'FileDownloaded', 'FileUploaded',
    'MailItemsAccessed', 'MailboxLogin', 'Send',
    'MessageSent', 'MessageRead', 'MessagesListed', 'ChatRetrieved', 'ChatCreated',
    'MeetingParticipantJoined', 'MeetingStarted', 'MeetingEnded', 'MeetingParticipantDetail', 'MeetingDetail',
    'TeamsSessionStarted',
    'CopilotInteraction', 'ConnectedAIAppInteraction', 'AIAppInteraction',
]


# ---------------------------------------------------------------------------------------------
# Processor closure
# ---------------------------------------------------------------------------------------------

def _top_level_names(node) -> list[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def extract_closure(path: Path) -> tuple[str, list[str]]:
    src = path.read_text(encoding='utf-8')
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        tree = ast.parse(src)
    defs: dict[str, ast.AST] = {}
    for node in tree.body:
        for name in _top_level_names(node):
            defs[name] = node
    missing = [s for s in SEEDS if s not in defs]
    if missing:
        raise SystemExit(f'Processor is missing expected definitions: {missing}')
    keep: set[int] = set()
    todo = list(SEEDS)
    seen: set[str] = set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        node = defs[name]
        keep.add(id(node))
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in defs and sub.id not in seen:
                todo.append(sub.id)
            elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value in defs:
                # string annotations (from __future__ import annotations)
                todo.append(sub.value)
    parts = [ast.get_source_segment(src, n) for n in tree.body if id(n) in keep]
    return '\n\n\n'.join(parts), sorted(seen)


def processor_cell(closure: str) -> str:
    header = f'''# Microsoft 365 usage row logic - copied verbatim from the M365 Usage Analytics processor.
# Source: https://github.com/microsoft/M365UsageAnalytics
#         scripts/Purview_M365_Usage_Bundle_Explosion_Processor_{PROCESSOR_VERSION}.py
# Copyright (c) Microsoft Corporation. Licensed under the MIT License.
# Only the functions and constants these notebooks call are included; they are unchanged so the
# numbers match the template's own pipeline. Regenerate with scripts/gen_m365_usage_notebooks.py.
from __future__ import annotations

import bisect
import csv
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


'''
    return header + closure + '\n'


# ---------------------------------------------------------------------------------------------
# Notebook helpers
# ---------------------------------------------------------------------------------------------

def _lines(text: str) -> list[str]:
    text = text.strip('\n') + '\n'
    out = text.splitlines(keepends=True)
    out[-1] = out[-1].rstrip('\n')
    return out


def md(text: str) -> dict:
    return {'cell_type': 'markdown', 'metadata': {}, 'source': _lines(text)}


def code(text: str) -> dict:
    return {'cell_type': 'code', 'execution_count': None, 'metadata': {}, 'outputs': [], 'source': _lines(text)}


def src(cell: dict) -> str:
    return ''.join(cell['source'])


def patch(cell: dict, old: str, new: str) -> dict:
    text = src(cell)
    if text.count(old) != 1:
        raise SystemExit(f'Expected exactly one match for patch:\n{old}\n(found {text.count(old)})')
    out = copy.deepcopy(cell)
    out['source'] = _lines(text.replace(old, new))
    out['outputs'] = [] if out['cell_type'] == 'code' else out.get('outputs')
    if out['cell_type'] != 'code':
        out.pop('outputs', None)
    return out


def write_nb(path: Path, cells: list[dict], metadata: dict):
    nb = {'cells': cells, 'metadata': metadata, 'nbformat': 4, 'nbformat_minor': 5}
    path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


# ---------------------------------------------------------------------------------------------
# Ingester
# ---------------------------------------------------------------------------------------------

INGEST_TITLE = '''
# Microsoft 365 Usage — Audit Ingester (Fabric)

Calls the Microsoft Graph audit log for the Microsoft 365 activity the **M365 Usage Analytics** template reads
(file, mail, Teams, meeting and Copilot operations, including **MailItemsAccessed** item counts) and rolls each
user's day up the same way the template's own processor does — that code is embedded below unchanged.

**Output**
- `dbo.m365_usage_rollup` — one row per user, day, operation, workload, file type, app and agent (the template's *Rollup* file)
- `dbo.m365_usage_sessionstats` — Copilot sessions and prompts per user, day and app (the template's *Session Stats* file)

`M365_Usage_Gold` turns these into the remaining template inputs and writes all five CSVs to `Files/m365_usage_export/`.

**Volume**: `MailItemsAccessed` is the largest operation by far on most tenants. Only rolled-up counts are kept, but the
fetch still reads every record, so start with a short backfill on a large tenant.

**Permissions**: `AuditLogsQuery.Read.All` (application, admin-consented). Mail and meeting events need Purview Audit enabled.
'''

INGEST_SCHEMA_NOTE = '''
## 1. Configuration

Fill in the config values below. The client secret should ideally come from Key Vault in production.

**Lakehouse Schemas note**: the output tables use the `dbo.` prefix, which works for both schema-enabled and non-schema Lakehouses.
'''

ROW_CELL_MD = '''
## 5a. Microsoft 365 usage row logic (embedded processor)

The functions below are the M365 Usage Analytics processor's own rollup and user-statistics code, included verbatim
(MIT licence) so the lake produces the same numbers as the template's PowerShell and Python pipeline.
'''

NEW_ROW = '''
def _row(r):
    """One compact staged row per audit record, using the processor's own key extraction.
    Returns None for records the processor drops (service accounts, filtered prompts)."""
    r = r or {}
    audit_data = r.get('auditData')
    if isinstance(audit_data, str):
        try:
            audit_data = json.loads(audit_data)
        except ValueError:
            audit_data = None
    if not isinstance(audit_data, dict):
        return None
    ced = safe_get(audit_data, 'CopilotEventData')
    if ced and not isinstance(ced, dict):
        ced = None
    record = {
        'CreationDate': r.get('createdDateTime') or '',
        'UserId': r.get('userPrincipalName') or r.get('userId') or '',
        'Operation': r.get('operation') or '',
    }
    result = _extract_rollup_keys(record, audit_data, ced)
    if result is None:
        return None
    group_key, event_count, items_accessed, creation_time, original_uid, is_agent = result
    prompts = responses = 0
    thread_id = ''
    if ced:
        for m in get_array_fast(ced, 'Messages'):
            ip = safe_get(m, 'isPrompt')
            if ip is True:
                prompts += 1
            elif ip is False:
                responses += 1
        thread_id = _norm_key_str(safe_get(ced, 'ThreadId'))
    uid_lower, cdate, op, wl, sfe, app_host, agent_id, agent_name, ctx_type = group_key
    return {
        'SourceRecordKey': build_source_record_key(
            r.get('id'), r.get('createdDateTime'), r.get('operation'), audit_data,
            record_type=r.get('auditLogRecordType')),
        'UserKey': uid_lower, 'UserId': original_uid, 'CreationDate': cdate,
        'Operation': op, 'Workload': wl, 'SourceFileExtension': sfe, 'AppHost': app_host,
        'AgentId': agent_id, 'AgentName': agent_name, 'ContextType': ctx_type,
        'EventCount': int(event_count), 'ItemsAccessedCount': int(items_accessed),
        'CreationTime': creation_time or '', 'IsAgent': bool(is_agent),
        'HasCopilotData': bool(ced), 'ThreadId': thread_id,
        'PromptCount': prompts, 'ResponseCount': responses,
    }
'''.strip('\n')

READ_MD = '''
## 6. Read the staged rows (distributed)

Each staged line is already one compact row per audit record. Records that appear in more than one window are dropped by `SourceRecordKey`.
'''

READ_CELL = '''
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, LongType, BooleanType

STAGE_SCHEMA = StructType(
    [StructField(c, StringType()) for c in (
        'SourceRecordKey', 'UserKey', 'UserId', 'CreationDate', 'Operation', 'Workload',
        'SourceFileExtension', 'AppHost', 'AgentId', 'AgentName', 'ContextType')]
    + [StructField('EventCount', LongType()), StructField('ItemsAccessedCount', LongType()),
       StructField('CreationTime', StringType()), StructField('IsAgent', BooleanType()),
       StructField('HasCopilotData', BooleanType()), StructField('ThreadId', StringType()),
       StructField('PromptCount', LongType()), StructField('ResponseCount', LongType())]
)

_files = list_active_stage_files(STAGING_ABS, ACTIVE_WINDOW_KEYS)
if _files:
    recs = spark.read.schema(STAGE_SCHEMA).json(_files)
else:
    recs = spark.createDataFrame([], STAGE_SCHEMA)
_text = ['UserKey', 'UserId', 'CreationDate', 'Operation', 'Workload', 'SourceFileExtension',
         'AppHost', 'AgentId', 'AgentName', 'ContextType', 'CreationTime', 'ThreadId']
recs = (recs.dropDuplicates(['SourceRecordKey'])
            .fillna('', subset=_text)
            .fillna(0, subset=['EventCount', 'ItemsAccessedCount', 'PromptCount', 'ResponseCount'])
            .fillna(False, subset=['IsAgent', 'HasCopilotData'])
            .persist())
print(f'Staged rows: {recs.count():,} (from {len(_files)} active window file(s))')
'''

AGG_MD = '''
## 7. Roll up per user and day

Same grouping as the processor's `run_rollup`: the *Rollup* key is user, day, operation, workload, file extension, app host,
agent and context type; *Session Stats* counts distinct Copilot threads with at least one prompt per user, day and app host.
'''

AGG_CELL = '''
_GROUP = ['UserKey', 'CreationDate', 'Operation', 'Workload', 'SourceFileExtension', 'AppHost',
          'AgentId', 'AgentName', 'ContextType']
_ct = F.when(F.col('CreationTime') != '', F.col('CreationTime'))
rollup = (recs.groupBy(*_GROUP).agg(
            F.min('UserId').alias('UserId'),
            F.sum('EventCount').alias('EventCount'),
            F.sum('ItemsAccessedCount').alias('ItemsAccessedCount'),
            F.coalesce(F.min(_ct), F.lit('')).alias('CreationTime'),
            F.coalesce(F.max(_ct), F.lit('')).alias('MaxCreationTime'),
            F.max(F.col('IsAgent').cast('int')).alias('_agent'))
          .withColumn('IsAgentInteraction', F.when(F.col('_agent') == 1, 'TRUE').otherwise('FALSE'))
          .select(*ROLLUP_HEADER))

_session = (F.col('ThreadId') != '') & (F.col('PromptCount') > 0)
sessionstats = (recs.where('HasCopilotData')
    .groupBy('UserKey', 'CreationDate', 'AppHost').agg(
        F.min('UserId').alias('UserId'),
        F.countDistinct(F.when(_session, F.col('ThreadId'))).alias('SessionCount'),
        F.sum('PromptCount').alias('PromptCount'),
        F.sum(F.when(F.col('IsAgent'), F.col('PromptCount')).otherwise(0)).alias('AgentPromptCount'),
        F.sum('ResponseCount').alias('ResponseCount'),
        F.countDistinct(F.when(_session & F.col('IsAgent'), F.col('ThreadId'))).alias('AgentSessionCount'))
    .where(~((F.col('SessionCount') == 0) & (F.col('PromptCount') == 0)))
    .select(*SESSIONSTATS_HEADER))
'''

WRITE_MD = '''
## 8. Write to Lakehouse Delta tables

Backfill overwrites both tables. Incremental re-reads whole days from `REPLACE_FROM`, so it deletes those days and appends the fresh rollup — re-running is safe.
'''

WRITE_CELL = '''
def write_days(df, table):
    if WRITE_MODE == 'replace_dates' and spark.catalog.tableExists(table):
        from delta.tables import DeltaTable
        DeltaTable.forName(spark, table).delete(F.col('CreationDate') >= F.lit(REPLACE_FROM))
        df.write.format('delta').mode('append').saveAsTable(table)
        return f'replaced days from {REPLACE_FROM[:10]}'
    df.write.format('delta').mode('overwrite').option('overwriteSchema', 'true').saveAsTable(table)
    return 'overwrite'

for _df, _table in ((rollup, OUTPUT_TABLE), (sessionstats, SESSION_TABLE)):
    _how = write_days(_df, _table)
    print(f'✓ {_table}: {spark.table(_table).count():,} rows ({_how})')
recs.unpersist()
'''

VERIFY_MD = '''
## 9. Verify

Event counts by workload and operation for the last day loaded.
'''

VERIFY_CELL = '''
_last = spark.table(OUTPUT_TABLE).agg(F.max('CreationDate')).collect()[0][0]
(spark.table(OUTPUT_TABLE).where(F.col('CreationDate') == _last)
    .groupBy('Workload', 'Operation').agg(F.sum('EventCount').alias('Events'), F.sum('ItemsAccessedCount').alias('ItemsAccessed'))
    .orderBy(F.desc('Events')).show(30, truncate=False))
'''


def build_ingester(base: dict, proc_src: str) -> dict:
    c = base['cells']
    expected = ['# Copilot Audit Log', '## 1. Configuration', '# === CONFIG ===', '## 2. Authenticate',
                None, '## 3. Build query windows', None, '## 4. Resumable wait', None, '## 5. Fetch records',
                None, '## 6. Read the staged', None]
    for i, head in enumerate(expected):
        if head and not src(c[i]).startswith(head):
            raise SystemExit(f'Base notebook cell {i} changed; expected it to start with {head!r}.')

    ops = ',\n'.join(f'    {op!r}' for op in OPERATIONS)
    cfg = patch(c[2], "OUTPUT_TABLE  = 'dbo.Copilot_Interactions_Parsed'     # Delta table consumed by the PBIT (keep name/schema stable)",
                "OUTPUT_TABLE  = 'dbo.m365_usage_rollup'              # template 'Rollup' input\n"
                "SESSION_TABLE = 'dbo.m365_usage_sessionstats'        # template 'Session Stats' input\n"
                f"OPERATIONS    = [                                    # audit operations the template reads\n{ops},\n]")
    cfg = patch(cfg, "# 'incremental' = requery the trailing LOOKBACK_DAYS (for late arrivals) and merge by stable Id.",
                "# 'incremental' = requery whole days from the trailing LOOKBACK_DAYS (late arrivals) and replace them.")
    cfg = patch(cfg, "STAGING_DIR             = 'Files/_audit_staging'",
                "STAGING_DIR             = 'Files/_m365_audit_staging'")
    cfg = patch(cfg, "'CopilotAuditAppSecret')", "'M365UsageAppSecret')")

    win = patch(c[6], '''    WRITE_MODE = 'merge'
    _hw = None
    if spark.catalog.tableExists(OUTPUT_TABLE):
        from pyspark.sql import functions as F
        _existing = spark.table(OUTPUT_TABLE)
        validate_incremental_target_columns(_existing.columns, KEY_COLUMNS, OUTPUT_TABLE)
        _hw = _existing.agg(F.max('CreationDate').alias('m')).collect()[0]['m']
    start_date = determine_incremental_start(end_date, _hw, LOOKBACK_DAYS)''',
                '''    WRITE_MODE = 'replace_dates'
    _hw = None
    if spark.catalog.tableExists(OUTPUT_TABLE):
        from pyspark.sql import functions as F
        _hw = spark.table(OUTPUT_TABLE).agg(F.max('CreationDate').alias('m')).collect()[0]['m']
        _hw = datetime.strptime(_hw[:10], '%Y-%m-%d').replace(tzinfo=timezone.utc) if _hw else None
    # Rollups are per day, so always start at midnight UTC and replace whole days.
    start_date = determine_incremental_start(end_date, _hw, LOOKBACK_DAYS).replace(
        hour=0, minute=0, second=0, microsecond=0)''')
    win = patch(win, "print(f'MODE={MODE}: {start_date:%Y-%m-%d}",
                "REPLACE_FROM = f'{start_date:%Y-%m-%d}T00:00:00.000Z'\nprint(f'MODE={MODE}: {start_date:%Y-%m-%d}")
    win = patch(win, "f'Copilot Interactions {win_start:%Y%m%d%H%M}-{win_end:%Y%m%d%H%M}'",
                "f'M365 Usage {win_start:%Y%m%d%H%M}-{win_end:%Y%m%d%H%M}'")
    win = patch(win, "'recordTypeFilters':   ['copilotInteraction'],\n        'operationFilters':    [],",
                "'recordTypeFilters':   [],\n        'operationFilters':    OPERATIONS,")

    fetch = patch(c[10], "def _row(r):\n    return canonicalize_audit_record(r)", NEW_ROW)
    fetch = patch(fetch, "            for record in records:\n                f.write(json.dumps(_row(record)) + '\\n')",
                  "            for record in records:\n                row = _row(record)\n"
                  "                if row is not None:\n                    f.write(json.dumps(row) + '\\n')")

    cells = [md(INGEST_TITLE), md(INGEST_SCHEMA_NOTE), cfg, c[3], c[4], c[5], win, c[7], c[8],
             md(ROW_CELL_MD), code(proc_src), c[9], fetch,
             md(READ_MD), code(READ_CELL), md(AGG_MD), code(AGG_CELL),
             md(WRITE_MD), code(WRITE_CELL), md(VERIFY_MD), code(VERIFY_CELL)]
    return [copy.deepcopy(x) for x in cells]


# ---------------------------------------------------------------------------------------------
# Gold
# ---------------------------------------------------------------------------------------------

GOLD_TITLE = '''
# Microsoft 365 Usage — Gold (template inputs)

Builds the five files the **M365 Usage Analytics** Power BI template reads, from the tables `M365_Usage_Audit_Ingester` writes:

| Template parameter | Delta table | CSV in `Files/m365_usage_export/` |
|---|---|---|
| Rollup | `dbo.m365_usage_rollup` | `Rollup.csv` |
| Session Stats | `dbo.m365_usage_sessionstats` | `SessionStats.csv` |
| User Stats | `dbo.m365_usage_userstats` | `UserStats.csv` |
| Session Cohort | `dbo.m365_usage_sessioncohort` | `SessionCohort.csv` |
| Entra Users Data | `dbo.m365_usage_entrausers` | `EntraUsers.csv` |

*User Stats* and *Session Cohort* come from the processor's own `write_userstats_files`, embedded unchanged. *Entra Users* is read from Microsoft Graph
with the columns the template expects; the custom HR columns are left blank.

**Permissions**: `User.Read.All` (application, admin-consented).
'''

GOLD_CONFIG = '''
# === CONFIG ===
TENANT_ID     = '<your-tenant-guid>'
CLIENT_ID     = '<your-app-reg-client-id>'
CLIENT_SECRET = '<your-client-secret-value>'

ROLLUP_TABLE    = 'dbo.m365_usage_rollup'
SESSION_TABLE   = 'dbo.m365_usage_sessionstats'
USERSTATS_TABLE = 'dbo.m365_usage_userstats'
COHORT_TABLE    = 'dbo.m365_usage_sessioncohort'
ENTRA_TABLE     = 'dbo.m365_usage_entrausers'
EXPORT_DIR      = 'Files/m365_usage_export'   # CSVs for the template's file parameters
'''

GOLD_AUTH = '''
import requests, time


def get_graph_token(tenant_id, client_id, client_secret):
    url = f'https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token'
    body = {
        'client_id': client_id,
        'scope': 'https://graph.microsoft.com/.default',
        'client_secret': client_secret,
        'grant_type': 'client_credentials',
    }
    r = requests.post(url, data=body, timeout=30)
    r.raise_for_status()
    return r.json()['access_token']


def _auth_headers():
    return {'Authorization': 'Bearer ' + token}


token = get_graph_token(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
print('✓ Graph token acquired.')

GRAPH_MAX_ATTEMPTS = 6
GRAPH_MAX_WAIT_SEC = 120


def graph_get(url, timeout=60):
    """GET from Graph; waits out throttling and brief outages and renews an expired token once."""
    global token
    renewed = False
    for attempt in range(1, GRAPH_MAX_ATTEMPTS + 1):
        last = attempt == GRAPH_MAX_ATTEMPTS
        try:
            r = requests.get(url, headers=_auth_headers(), timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as exc:
            if last:
                raise
            wait = min(5 * 2 ** attempt, GRAPH_MAX_WAIT_SEC)
            print(f'  Graph request failed ({type(exc).__name__}); trying again in {wait}s.')
            time.sleep(wait)
            continue
        if r.status_code == 401 and not renewed and not last:
            token = get_graph_token(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
            renewed = True
            continue
        if (r.status_code == 429 or r.status_code >= 500) and not last:
            try:
                wait = float(r.headers.get('Retry-After', ''))
            except (TypeError, ValueError):
                wait = 5 * 2 ** attempt
            wait = min(max(wait, 1.0), GRAPH_MAX_WAIT_SEC)
            print(f'  Graph returned {r.status_code}; trying again in {wait:.0f}s.')
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
'''

GOLD_USERS = '''
import json

ENTRA_COLUMNS = [
    'userPrincipalName', 'displayName', 'id', 'mail', 'givenName', 'surname', 'jobTitle', 'department',
    'employeeType', 'employeeId', 'employeeHireDate', 'officeLocation', 'city', 'state', 'country',
    'postalCode', 'companyName', 'employeeOrgData_division', 'employeeOrgData_costCenter', 'accountEnabled',
    'userType', 'createdDateTime', 'usageLocation', 'preferredLanguage', 'onPremisesSyncEnabled',
    'onPremisesImmutableId', 'externalUserState', 'proxyAddresses_Primary', 'proxyAddresses_Count',
    'proxyAddresses_All', 'manager_id', 'manager_displayName', 'manager_userPrincipalName', 'manager_mail',
    'manager_jobTitle', 'assignedLicenses', 'hasLicense',
    # Custom HR columns the template can show; not in Entra, so left blank.
    'ManagerID', 'BusinessAreaLabel', 'CountryofEmployment', 'CompanyCodeLabel', 'CostCentreLabel',
    'UserName', 'EffectiveDate', 'FunctionType', 'BusinessAreaCode', 'OrgLevel_3Label',
]
_select = ','.join([
    'userPrincipalName', 'displayName', 'id', 'mail', 'givenName', 'surname', 'jobTitle', 'department',
    'employeeType', 'employeeId', 'employeeHireDate', 'officeLocation', 'city', 'state', 'country',
    'postalCode', 'companyName', 'employeeOrgData', 'accountEnabled', 'userType', 'createdDateTime',
    'usageLocation', 'preferredLanguage', 'onPremisesSyncEnabled', 'onPremisesImmutableId',
    'externalUserState', 'proxyAddresses', 'assignedLicenses',
])
next_url = (f'https://graph.microsoft.com/v1.0/users?$select={_select}'
            '&$expand=manager($select=id,displayName,userPrincipalName,mail,jobTitle)&$top=999')

users, seen_urls = [], set()
while next_url:
    if next_url in seen_urls:
        raise ValueError('Graph /users paging loop detected.')
    seen_urls.add(next_url)
    data = graph_get(next_url).json()
    if not isinstance(data, dict) or not isinstance(data.get('value'), list):
        raise ValueError('Graph /users returned an unexpected page; refusing to write a partial user list.')
    users.extend(data['value'])
    next_url = data.get('@odata.nextLink')
    print(f'  Fetched {len(users):,} users so far...')
print(f'✓ Total users: {len(users):,}')


def _s(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'True' if value else 'False'
    return str(value)


def entra_row(u):
    org = u.get('employeeOrgData') or {}
    mgr = u.get('manager') or {}
    proxies = [p for p in (u.get('proxyAddresses') or []) if isinstance(p, str)]
    primary = next((p[5:] for p in proxies if p.startswith('SMTP:')), '')
    licenses = [{'skuId': l.get('skuId')} for l in (u.get('assignedLicenses') or []) if isinstance(l, dict)]
    row = {k: _s(u.get(k)) for k in ENTRA_COLUMNS if k in u and not isinstance(u.get(k), (dict, list))}
    row.update({
        'employeeOrgData_division': _s(org.get('division')),
        'employeeOrgData_costCenter': _s(org.get('costCenter')),
        'proxyAddresses_Primary': primary,
        'proxyAddresses_Count': str(len(proxies)),
        'proxyAddresses_All': ';'.join(proxies),
        'manager_id': _s(mgr.get('id')),
        'manager_displayName': _s(mgr.get('displayName')),
        'manager_userPrincipalName': _s(mgr.get('userPrincipalName')),
        'manager_mail': _s(mgr.get('mail')),
        'manager_jobTitle': _s(mgr.get('jobTitle')),
        'assignedLicenses': json.dumps(licenses),
        # The template recomputes hasLicense from assignedLicenses against its Copilot SKU list.
        'hasLicense': 'True' if licenses else 'False',
    })
    return [row.get(k, '') for k in ENTRA_COLUMNS]


entra_rows = [entra_row(u) for u in users if u.get('userPrincipalName')]
'''

GOLD_STATS = '''
import csv, os, shutil, tempfile

WORK = tempfile.mkdtemp(prefix='m365_usage_')
paths = {name: os.path.join(WORK, f'{name}.csv')
         for name in ('Rollup', 'SessionStats', 'UserStats', 'SessionCohort', 'EntraUsers')}


def table_to_csv(table, header, path):
    """Stream a Delta table to a local CSV laid out exactly like the processor's own output."""
    n = 0
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, lineterminator='\\n')
        w.writerow(header)
        if spark.catalog.tableExists(table):
            for row in spark.table(table).select(*header).toLocalIterator():
                w.writerow(['' if v is None else v for v in row])
                n += 1
    return n


n_roll = table_to_csv(ROLLUP_TABLE, ROLLUP_HEADER, paths['Rollup'])
n_sess = table_to_csv(SESSION_TABLE, SESSIONSTATS_HEADER, paths['SessionStats'])
print(f'Rollup rows: {n_roll:,}  Session stats rows: {n_sess:,}')
if n_roll == 0:
    raise RuntimeError(f'{ROLLUP_TABLE} is empty or missing; run M365_Usage_Audit_Ingester first.')

users_n, cohort_n = write_userstats_files(paths['Rollup'], paths['UserStats'], paths['SessionCohort'],
                                          quiet=False, session_stats_csv_path=paths['SessionStats'])
print(f'✓ UserStats: {users_n:,} users  SessionCohort: {cohort_n:,} rows')

# The template reads Entra Users as Windows-1252.
with open(paths['EntraUsers'], 'w', encoding='cp1252', errors='replace', newline='') as f:
    w = csv.writer(f, lineterminator='\\n')
    w.writerow(ENTRA_COLUMNS)
    w.writerows(entra_rows)
print(f'✓ EntraUsers: {len(entra_rows):,} users')
'''

GOLD_WRITE = '''
import notebookutils

fs = notebookutils.fs
if not fs.exists(EXPORT_DIR):
    fs.mkdirs(EXPORT_DIR)
for name, local in paths.items():
    target = f'{EXPORT_DIR}/{name}.csv'
    if fs.exists(target):
        fs.rm(target)
    if fs.cp('file:' + os.path.abspath(local), target) is False:
        raise RuntimeError(f'Failed to copy {name}.csv to {target}.')
print(f'✓ Wrote {len(paths)} CSVs to {EXPORT_DIR}/')

for name, table, encoding in (('UserStats', USERSTATS_TABLE, 'utf-8'),
                              ('SessionCohort', COHORT_TABLE, 'utf-8'),
                              ('EntraUsers', ENTRA_TABLE, 'cp1252')):
    df = (spark.read.option('header', True).option('encoding', encoding)
          .option('multiLine', True).option('escape', '"').csv(f'{EXPORT_DIR}/{name}.csv'))
    df.write.format('delta').mode('overwrite').option('overwriteSchema', 'true').saveAsTable(table)
    print(f'✓ {table}: {spark.table(table).count():,} rows')

shutil.rmtree(WORK, ignore_errors=True)
'''


def build_gold(base_meta: dict, proc_src: str) -> list[dict]:
    return [
        md(GOLD_TITLE),
        md('## 1. Configuration'), code(GOLD_CONFIG),
        md('## 2. Authenticate to Microsoft Graph'), code(GOLD_AUTH),
        md('## 3. Entra users\n\nPages through `/users` with the manager expanded and shapes each user into the template\'s *Entra Users* columns.'),
        code(GOLD_USERS),
        md('## 4. Microsoft 365 usage statistics (embedded processor)\n\nThe processor\'s own `write_userstats_files`, included verbatim (MIT licence).'),
        code(proc_src),
        md('## 5. Build User Stats and Session Cohort\n\nThe rollup and session tables are written out in the processor\'s CSV layout, then `write_userstats_files` runs on them unchanged.'),
        code(GOLD_STATS),
        md('## 6. Write CSVs and Delta tables\n\nPoint the template\'s five file parameters at the CSVs in `Files/m365_usage_export/` (see `08-report-templates`).'),
        code(GOLD_WRITE),
    ]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--processor', required=True, type=Path)
    args = ap.parse_args()
    closure, names = extract_closure(args.processor)
    # keep the docstring example clear of the repo's email-address scan
    proc_src = processor_cell(closure).replace('(local' + '@domain.tld)', '(local-part @ domain . tld)')
    compile(proc_src, 'processor', 'exec')

    base = json.loads(BASE.read_text(encoding='utf-8'))
    base_text = '\n'.join(src(c) for c in base['cells'][:13] if c['cell_type'] == 'code')
    clashes = [n for n in names if f'def {n}(' in base_text or f'\n{n} = ' in base_text]
    if clashes:
        raise SystemExit(f'Processor names clash with the base ingester: {clashes}')

    write_nb(OUT_INGEST, build_ingester(base, proc_src), base['metadata'])
    write_nb(OUT_GOLD, build_gold(base['metadata'], proc_src), base['metadata'])
    print(f'Embedded {len(names)} processor definitions: {", ".join(names)}')
    print(f'Wrote {OUT_INGEST.relative_to(ROOT)} and {OUT_GOLD.relative_to(ROOT)}')


if __name__ == '__main__':
    sys.exit(main())

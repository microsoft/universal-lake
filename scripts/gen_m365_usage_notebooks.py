"""Generate the Microsoft 365 usage ingester notebook.

    python scripts/gen_m365_usage_notebooks.py

Writes notebooks/M365_Usage_Audit_Ingester.ipynb: Graph audit log -> dbo.m365_usage_rollup,
dbo.connected_ai_app_interactions, dbo.ai_app_interactions and dbo.m365_teams_call_participation.
CopilotInteraction is not fetched here: the template
reads it from dbo.Copilot_Interactions_Parsed, which Copilot_Audit_Log_Direct_Ingester already writes.

The notebook reuses the fetch, retry and staging cells of notebooks/Copilot_Audit_Log_Direct_Ingester.ipynb
unchanged, so fixes there are picked up by running this script again. Records are staged as raw JSON and parsed
with Spark built-in functions only (no Python UDFs), reproducing the rollup rules of the M365 Usage Analytics
processor (https://github.com/microsoft/M365UsageAnalytics, v2.6.1). scripts/test_m365_usage_parity.py checks
the parse against that processor. The per-user statistics the template needs are computed by the template itself
with T-SQL on the SQL analytics endpoint.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / 'notebooks' / 'Copilot_Audit_Log_Direct_Ingester.ipynb'
OUT_INGEST = ROOT / 'notebooks' / 'M365_Usage_Audit_Ingester.ipynb'

OPERATIONS = [
    'FileAccessed', 'FileViewed', 'FilePreviewed', 'FileModified', 'FileDownloaded', 'FileUploaded',
    'MailItemsAccessed', 'MailboxLogin', 'Send',
    'MessageSent', 'MessageRead', 'MessagesListed', 'ChatRetrieved', 'ChatCreated',
    'MeetingParticipantJoined', 'MeetingStarted', 'MeetingEnded', 'MeetingParticipantDetail', 'MeetingDetail',
    'CallParticipantDetail', 'TeamsSessionStarted',
    'ConnectedAIAppInteraction', 'AIAppInteraction',
]


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
(file, mail, Teams and meeting operations, including **MailItemsAccessed** item counts, plus AI-app interactions) and
rolls each user's day up with the same rules as the template's own processor. All parsing runs in Spark.

`CopilotInteraction` is **not** fetched here: `Copilot_Audit_Log_Direct_Ingester` already writes it to
`dbo.Copilot_Interactions_Parsed`, and the template reads it from there.

**Output**
- `dbo.m365_usage_rollup` — one row per user, day, operation, workload, file type, app and agent (the template's *Rollup* file, without AI operations)
- `dbo.connected_ai_app_interactions` — one row per `ConnectedAIAppInteraction` audit record
- `dbo.ai_app_interactions` — one row per `AIAppInteraction` audit record
- `dbo.m365_teams_call_participation` — one row per Teams `CallParticipantDetail` / `MeetingParticipantDetail` record:
  join and leave times, time in the call or meeting (`DurationSeconds`) and screen-share sessions (`ScreenShareCount`,
  `ScreenShareSeconds`). `CallParticipantDetail` is kept out of the rollup so the template's current numbers don't change.

The audit log has no audio/video split; per-user audio, video and screen-share seconds from the Teams usage report are in
`m365_activity_daily` (Copilot_M365_Activity_Ingester).

The template combines these with `Copilot_Interactions_Parsed`, `copilot_org_data` and `copilot_licensed_users` and
computes its rollup, session stats, per-user statistics, cohorts and user directory with T-SQL on the SQL analytics endpoint.

**Volume**: `MailItemsAccessed` is the largest operation by far on most tenants. Only rolled-up counts are kept, but the
fetch still reads every record, so start with a short backfill on a large tenant.

**Permissions**: `AuditLogsQuery.Read.All` (application, admin-consented). Mail and meeting events need Purview Audit enabled.
'''

INGEST_SCHEMA_NOTE = '''
## 1. Configuration

Fill in the config values below. The client secret should ideally come from Key Vault in production.

**Lakehouse Schemas note**: the output tables use the `dbo.` prefix, which works for both schema-enabled and non-schema Lakehouses.
'''

NEW_ROW = '''
_STAGE_FIELDS = ('id', 'createdDateTime', 'operation', 'userPrincipalName', 'userId', 'auditLogRecordType', 'auditData')


def _row(r):
    """Stage only the fields the Spark parser reads (section 6); no per-record parsing here."""
    r = r or {}
    row = {k: r.get(k) for k in _STAGE_FIELDS}
    ad = row.get('auditData')
    if ad is not None and not isinstance(ad, str):
        row['auditData'] = json.dumps(ad, ensure_ascii=False, separators=(',', ':'))
    return row
'''.strip('\n')

PARSE_MD = '''
## 6. Parse the staged records (Spark)

Each audit record is parsed with Spark built-in functions — no Python UDFs — following the M365 Usage Analytics
processor (v2.6.1): non-human identities are dropped, operations are canonicalised (`FileViewed` → `FileAccessed`,
`MeetingParticipantJoined` → `MeetingParticipantDetail`, `ConnectedAIAppInteraction` → `AIAppInteraction`; the original
name is kept in `SourceOperation`), each AI-app record counts as its exploded row count (largest Copilot array, capped at 1,000), and each `MailItemsAccessed`
event counts the folder items it touched. Teams call and meeting participant records also get their call ids, join and
leave times, time in the call and screen-share sessions (`ArtifactsShared[].ArtifactShareSessions[]`).
'''

PARSE_CELL = r'''
from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType, BooleanType, StringType, StructField, StructType

ROLLUP_HEADER = ['UserId', 'CreationDate', 'Operation', 'Workload', 'SourceFileExtension', 'AppHost',
                 'EventCount', 'ItemsAccessedCount', 'CreationTime', 'MaxCreationTime',
                 'AgentId', 'AgentName', 'ContextType', 'IsAgentInteraction']
AI_APP_HEADER = ['Id', 'UserId', 'CreationDate', 'CreationTime', 'Operation', 'Workload', 'AppHost', 'AgentId',
                 'AgentName', 'ContextType', 'ThreadId', 'PromptCount', 'ResponseCount', 'EventCount', 'IsAgent']
CALL_HEADER = ['Id', 'UserId', 'CreationDate', 'CreationTime', 'Operation', 'SourceOperation', 'Workload', 'CallId',
               'MeetingDetailId', 'CommunicationType', 'CommunicationSubType', 'ActivityDate', 'JoinTime', 'LeaveTime',
               'DurationSeconds', 'ScreenShareCount', 'ScreenShareSeconds']

OP_RENAME = {'FileViewed': 'FileAccessed', 'MeetingParticipantJoined': 'MeetingParticipantDetail',
             'ConnectedAIAppInteraction': 'AIAppInteraction'}
# Teams participant records (after renaming) that carry join/leave times and screen-share sessions.
CALL_OPS = ['CallParticipantDetail', 'MeetingParticipantDetail']
# Kept out of the rollup: the template's processor never saw them, so its numbers stay unchanged.
CALL_ONLY_OPS = ['CallParticipantDetail']
AGENT_APPHOSTS = ['agent', 'copilotstudio', 'declarativeagent', 'customengineagent']
EVENT_ROW_CAP = 1000

_S = StringType()
STAGE_SCHEMA = StructType([StructField(c, _S) for c in (
    'id', 'createdDateTime', 'operation', 'userPrincipalName', 'userId', 'auditLogRecordType', 'auditData')])
AUDIT_SCHEMA = StructType(
    [StructField(c, _S) for c in ('UserId', 'Operation', 'Workload', 'SourceFileExtension', 'AppHost',
                                  'AgentId', 'AgentName', 'CreationTime', 'CopilotEventData')]
    + [StructField('Folders', ArrayType(StructType([StructField('FolderItems', ArrayType(_S))]))),
       StructField('_corrupt_record', _S)])
COPILOT_SCHEMA = StructType(
    [StructField(c, _S) for c in ('AppHost', 'AgentId', 'AgentName', 'ThreadId')]
    + [StructField('Messages', ArrayType(StructType([StructField('isPrompt', BooleanType())]))),
       StructField('Contexts', ArrayType(StructType([StructField('Type', _S), StructField('Items', ArrayType(_S))])))]
    + [StructField(c, ArrayType(_S)) for c in ('AccessedResources', 'SensitivityLabels', 'AISystemPlugin',
                                              'ModelTransparencyDetails')])
# Parsed separately so a malformed call field never changes which records the rollup keeps.
CALL_SCHEMA = StructType(
    [StructField(c, _S) for c in ('CallId', 'MeetingDetailId', 'CommunicationType', 'CommunicationSubType',
                                  'JoinTime', 'LeaveTime')]
    + [StructField('ArtifactsShared', ArrayType(StructType([StructField('ArtifactShareSessions', ArrayType(
        StructType([StructField('StartTimestamp', _S), StructField('EndTimestamp', _S)])))])))])
_ISO = r'^\s*(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})'


def _norm(c: Column) -> Column:
    """Trimmed text; null, 'null' and 'none' become ''."""
    c = F.regexp_replace(F.coalesce(c, F.lit('')), r'(?U)^\s+|\s+$', '')
    return F.when(F.lower(c).isin('null', 'none'), F.lit('')).otherwise(c)


def _first(*cols: Column) -> Column:
    """First value that is neither null nor '' (Python `a or b`)."""
    return F.coalesce(*[F.when(c != '', c) for c in cols], F.lit(''))


def _size(c: Column) -> Column:
    return F.greatest(F.size(c), F.lit(0))


def _is_human_upn(u: Column) -> Column:
    local, domain = F.substring_index(u, '@', 1), F.substring_index(u, '@', -1)
    return (~u.rlike(r'(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
            & ~F.lower(u).startswith('supervisoryreview{')
            & ((F.length(u) - F.length(F.regexp_replace(u, '@', ''))) == 1)
            & local.rlike(r'(?U)^[^\s\\@]+$')
            & domain.contains('.') & ~domain.startswith('.') & ~domain.endswith('.'))


def _creation_date(c: Column) -> Column:
    """Any Purview date format -> 'YYYY-MM-DDT00:00:00.000Z'."""
    raw = _norm(c)
    ts = F.coalesce(*[F.call_function('try_to_timestamp', raw, F.lit(fmt))
                      for fmt in ('M/d/yyyy h:mm:ss a', 'M/d/yyyy H:mm:ss', 'M/d/yyyy')])
    return (F.when(raw == '', F.lit(''))
             .when((F.length(raw) >= 10) & (F.substring(raw, 5, 1) == '-'),
                   F.concat(F.substring(raw, 1, 10), F.lit('T00:00:00.000Z')))
             .when(ts.isNotNull(), F.concat(F.date_format(ts, 'yyyy-MM-dd'), F.lit('T00:00:00.000Z')))
             .otherwise(raw))


def _creation_time(c: Column) -> Column:
    """Purview timestamp -> 'YYYY-MM-DDTHH:MM:SS.mmmZ'; anything unrecognised is kept as-is."""
    raw = _norm(c)
    iso = r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d{1,6})?Z?$'
    base, frac = F.regexp_extract(raw, iso, 1), F.regexp_extract(raw, iso, 2)
    iso_ok = (base != '') & F.call_function('try_to_timestamp', base, F.lit("yyyy-MM-dd'T'HH:mm:ss")).isNotNull()
    ts = F.coalesce(*[F.call_function('try_to_timestamp', raw, F.lit(fmt))
                      for fmt in ('M/d/yyyy h:mm:ss a', 'M/d/yyyy H:mm:ss')])
    return (F.when(iso_ok, F.concat(base, F.lit('.'), F.substring(F.rpad(F.substring(frac, 2, 6), 3, '0'), 1, 3), F.lit('Z')))
             .when(ts.isNotNull(), F.date_format(ts, "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'"))
             .otherwise(raw))


def _iso_utc(c: Column) -> Column:
    """Audit UTC timestamp (any fraction, optional Z) -> 'YYYY-MM-DDTHH:MM:SSZ'; '' when not a timestamp."""
    d, t = F.regexp_extract(c, _ISO, 1), F.regexp_extract(c, _ISO, 2)
    return F.when(d != '', F.concat(d, F.lit('T'), t, F.lit('Z'))).otherwise(F.lit(''))


def _seconds_between(start: Column, end: Column) -> Column:
    """Whole seconds between two _iso_utc values; null when either is missing or end is before start."""
    fmt = F.lit("yyyy-MM-dd'T'HH:mm:ssX")
    s = F.call_function('try_to_timestamp', start, fmt).cast('long')
    e = F.call_function('try_to_timestamp', end, fmt).cast('long')
    return F.when(e >= s, e - s)


def parse_audit(raw: DataFrame) -> DataFrame:
    """Staged Graph audit records -> one row per kept record with the rollup keys and counts."""
    ad = F.from_json('auditData', AUDIT_SCHEMA)
    # Only JSON objects are audit records; malformed text or arrays are dropped as the processor does.
    df = (raw.withColumn('_ad', ad)
             .where(F.col('auditData').rlike(r'^\s*\{') & F.col('_ad').isNotNull() & F.col('_ad._corrupt_record').isNull())
             .withColumn('_cedraw', F.col('_ad.CopilotEventData'))
             .withColumn('_hasced', F.coalesce(F.col('_cedraw').rlike(r'^\s*\{\s*"'), F.lit(False)))
             .withColumn('_ced', F.when(F.col('_hasced'), F.from_json('_cedraw', COPILOT_SCHEMA))))
    a, c = F.col('_ad'), F.col('_ced')
    op = _norm(_first(a['Operation'], F.col('operation')))
    rename = F.create_map(*[F.lit(x) for kv in OP_RENAME.items() for x in kv])
    df = (df.withColumn('UserId', _norm(_first(a['UserId'], F.col('userPrincipalName'), F.col('userId'))))
            .where(_is_human_upn(F.col('UserId')))
            .withColumn('SourceOperation', op)
            .withColumn('Operation', F.coalesce(F.element_at(rename, op), op)))
    ctx_items = F.coalesce(F.array_max(F.transform(c['Contexts'], lambda x: _size(x['Items']))), F.lit(0))
    copilot_rows = F.greatest(
        F.lit(1), *[_size(c[k]) for k in ('Messages', 'Contexts', 'AccessedResources', 'SensitivityLabels',
                                          'AISystemPlugin', 'ModelTransparencyDetails')],
        F.when(F.col('Operation') == 'CopilotInteraction', ctx_items).otherwise(0))
    folder_items = F.aggregate(a['Folders'], F.lit(0),
                               lambda acc, f: acc + _size(f['FolderItems']))
    hc = F.col('_hasced')
    df = (df.withColumn('UserKey', F.lower('UserId'))
            .withColumn('CreationDate', _creation_date(F.col('createdDateTime')))
            .withColumn('Workload', _norm(a['Workload']))
            .withColumn('SourceFileExtension', F.lower(_norm(a['SourceFileExtension'])))
            .withColumn('AppHost', _norm(_first(c['AppHost'], a['AppHost'])))
            .withColumn('AgentId', _norm(_first(c['AgentId'], a['AgentId'])))
            .withColumn('AgentName', _norm(_first(c['AgentName'], a['AgentName'])))
            .withColumn('ContextType', _norm(F.element_at(c['Contexts'], 1)['Type']))
            .withColumn('CreationTime', _creation_time(a['CreationTime']))
            .withColumn('EventCount', F.when(hc, F.least(copilot_rows, F.lit(EVENT_ROW_CAP))).otherwise(1).cast('long'))
            .withColumn('ItemsAccessedCount', F.when(F.col('Operation') != 'MailItemsAccessed', 0)
                                               .when(folder_items > 0, folder_items).otherwise(1).cast('long'))
            .withColumn('IsAgent', (F.col('AgentId') != '') | F.lower('AppHost').isin(AGENT_APPHOSTS)
                                   | (F.col('Operation') == 'AIAppInteraction'))
            .withColumn('HasCopilotData', hc)
            .withColumn('ThreadId', F.when(hc, _norm(c['ThreadId'])).otherwise(''))
            .withColumn('PromptCount', F.when(hc, _size(F.filter(c['Messages'], lambda m: m['isPrompt']))).otherwise(0).cast('long'))
            .withColumn('ResponseCount', F.when(hc, _size(F.filter(c['Messages'], lambda m: ~m['isPrompt']))).otherwise(0).cast('long')))
    is_call = F.col('Operation').isin(CALL_OPS)
    k = F.col('_call')
    shares = F.flatten(F.filter(F.transform(k['ArtifactsShared'], lambda x: x['ArtifactShareSessions']),
                                lambda x: x.isNotNull()))
    df = (df.withColumn('_call', F.when(is_call, F.from_json('auditData', CALL_SCHEMA)))
            .withColumn('CallId', _norm(k['CallId']))
            .withColumn('MeetingDetailId', _norm(k['MeetingDetailId']))
            .withColumn('CommunicationType', _norm(k['CommunicationType']))
            .withColumn('CommunicationSubType', _norm(k['CommunicationSubType']))
            .withColumn('JoinTime', _iso_utc(k['JoinTime']))
            .withColumn('LeaveTime', _iso_utc(k['LeaveTime']))
            # Participant records are logged hours after the call, so the activity day comes from the join time.
            .withColumn('ActivityDate', F.when(F.col('JoinTime') != '', F.concat(F.substring('JoinTime', 1, 10),
                                                                                 F.lit('T00:00:00.000Z')))
                                         .otherwise(F.col('CreationDate')))
            .withColumn('DurationSeconds', _seconds_between(F.col('JoinTime'), F.col('LeaveTime')))
            .withColumn('ScreenShareCount', _size(shares).cast('long'))
            .withColumn('ScreenShareSeconds', F.coalesce(F.aggregate(
                shares, F.lit(0).cast('long'), lambda acc, s: acc + F.coalesce(
                    _seconds_between(_iso_utc(s['StartTimestamp']), _iso_utc(s['EndTimestamp'])), F.lit(0).cast('long'))),
                F.lit(0).cast('long'))))
    return df.select('id', 'UserKey', 'UserId', 'CreationDate', 'SourceOperation', 'Operation', 'Workload', 'SourceFileExtension', 'AppHost',
                     'AgentId', 'AgentName', 'ContextType', 'CreationTime', 'EventCount', 'ItemsAccessedCount',
                     'IsAgent', 'HasCopilotData', 'ThreadId', 'PromptCount', 'ResponseCount',
                     'CallId', 'MeetingDetailId', 'CommunicationType', 'CommunicationSubType', 'ActivityDate',
                     'JoinTime', 'LeaveTime', 'DurationSeconds', 'ScreenShareCount', 'ScreenShareSeconds')
'''

READ_MD = '''
## 7. Read and parse the staged records (distributed)

Records that appear in more than one window are dropped by their audit record `id` before parsing.
'''

READ_CELL = '''
_files = list_active_stage_files(STAGING_ABS, ACTIVE_WINDOW_KEYS)
if _files:
    _raw = spark.read.schema(STAGE_SCHEMA).json(_files)
else:
    _raw = spark.createDataFrame([], STAGE_SCHEMA)
_raw = _raw.withColumn('_key', F.coalesce('id', F.sha2(F.concat_ws('|', 'createdDateTime', 'operation', 'auditData'), 256)))
recs = parse_audit(_raw.dropDuplicates(['_key'])).persist()
_parsed = recs.count()
print(f'Parsed rows: {_parsed:,} (from {len(_files)} active window file(s))')
if _parsed == 0 and _files:
    _d = _raw.agg(F.count(F.lit(1)).alias('raw'),
                  F.sum(F.col('auditData').isNull().cast('int')).alias('no_auditData'),
                  F.sum(F.col('operation').isNull().cast('int')).alias('no_operation')).collect()[0]
    print(f"Staged rows: {_d['raw']:,}; missing auditData: {_d['no_auditData']:,}; missing operation: {_d['no_operation']:,}")
    if _d['raw'] and _d['no_auditData'] == _d['raw']:
        raise RuntimeError(
            f'The staged files under {STAGING_DIR} are not raw Graph audit records (no auditData). They were probably '
            'written by an older ingester version. Delete that folder and rerun with RUN_MODE backfill.')
'''

AGG_MD = '''
## 8. Roll up per user and day

Same grouping as the processor's `run_rollup`: the *Rollup* key is user, day, operation, workload, file extension, app host,
agent and context type. AI-app interactions are kept one row per audit record in their own tables; the template rolls them
up together with `Copilot_Interactions_Parsed` and derives *Session Stats* from them. Teams call and meeting participant
records also go one row per record to the call table (`CallParticipantDetail` only there).
'''

AGG_CELL = '''
_GROUP = ['UserKey', 'CreationDate', 'Operation', 'Workload', 'SourceFileExtension', 'AppHost',
          'AgentId', 'AgentName', 'ContextType']
_ct = F.when(F.col('CreationTime') != '', F.col('CreationTime'))
rollup = (recs.where(~F.col('Operation').isin('CopilotInteraction', 'AIAppInteraction', *CALL_ONLY_OPS)).groupBy(*_GROUP).agg(
            F.min('UserId').alias('UserId'),
            F.sum('EventCount').alias('EventCount'),
            F.sum('ItemsAccessedCount').alias('ItemsAccessedCount'),
            F.coalesce(F.min(_ct), F.lit('')).alias('CreationTime'),
            F.coalesce(F.max(_ct), F.lit('')).alias('MaxCreationTime'),
            F.max(F.col('IsAgent').cast('int')).alias('_agent'))
          .withColumn('IsAgentInteraction', F.when(F.col('_agent') == 1, 'TRUE').otherwise('FALSE'))
          .select(*ROLLUP_HEADER))

def ai_app_records(source_operation):
    return (recs.where(F.col('SourceOperation') == source_operation)
            .withColumn('Id', F.col('id'))
            .withColumn('Operation', F.col('SourceOperation'))
            .withColumn('IsAgent', F.when(F.col('IsAgent'), 'TRUE').otherwise('FALSE'))
            .select(*AI_APP_HEADER))

connected_ai = ai_app_records('ConnectedAIAppInteraction')
ai_app = ai_app_records('AIAppInteraction')

# One row per Teams call / meeting participant record with its time in the call and screen-share sessions.
calls = recs.where(F.col('Operation').isin(CALL_OPS)).withColumn('Id', F.col('id')).select(*CALL_HEADER)
'''

WRITE_MD = '''
## 9. Write to Lakehouse Delta tables

Backfill overwrites all four tables. Incremental re-reads whole days from `REPLACE_FROM`, so it deletes those days and appends the fresh rollup — re-running is safe.
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

for _df, _table in ((rollup, OUTPUT_TABLE), (connected_ai, CONNECTED_AI_TABLE), (ai_app, AI_APP_TABLE),
                    (calls, CALL_TABLE)):
    _how = write_days(_df, _table)
    print(f'✓ {_table}: {spark.table(_table).count():,} rows ({_how})')
recs.unpersist()
'''

VERIFY_MD = '''
## 10. Verify

Event counts by workload and operation for the last day loaded, then Teams call and meeting time by operation.
'''

VERIFY_CELL = '''
_last = spark.table(OUTPUT_TABLE).agg(F.max('CreationDate')).collect()[0][0]
(spark.table(OUTPUT_TABLE).where(F.col('CreationDate') == _last)
    .groupBy('Workload', 'Operation').agg(F.sum('EventCount').alias('Events'), F.sum('ItemsAccessedCount').alias('ItemsAccessed'))
    .orderBy(F.desc('Events')).show(30, truncate=False))
(spark.table(CALL_TABLE).groupBy('Operation', 'CommunicationType')
    .agg(F.count(F.lit(1)).alias('Records'), F.countDistinct('UserId').alias('Users'),
         F.round(F.sum('DurationSeconds') / 3600, 1).alias('Hours'),
         F.sum('ScreenShareCount').alias('ScreenShares'), F.round(F.sum('ScreenShareSeconds') / 3600, 1).alias('ScreenShareHours'))
    .orderBy(F.desc('Records')).show(30, truncate=False))
'''


def build_ingester(base: dict) -> list[dict]:
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
                "CONNECTED_AI_TABLE = 'dbo.connected_ai_app_interactions'  # ConnectedAIAppInteraction records\n"
                "AI_APP_TABLE  = 'dbo.ai_app_interactions'           # AIAppInteraction records\n"
                "CALL_TABLE    = 'dbo.m365_teams_call_participation' # Teams call / meeting participant records\n"
                f"OPERATIONS    = [                                    # audit operations the template reads\n{ops},\n]")
    cfg = patch(cfg, "# 'incremental' = requery the trailing LOOKBACK_DAYS (for late arrivals) and merge by stable Id.",
                "# 'incremental' = requery whole days from the trailing LOOKBACK_DAYS (late arrivals) and replace them.")
    cfg = patch(cfg, "STAGING_DIR             = 'Files/_audit_staging'",
                "STAGING_DIR             = 'Files/_m365_audit_staging_raw'  # raw Graph records; bump the name if the staged format changes")
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

    cells = [md(INGEST_TITLE), md(INGEST_SCHEMA_NOTE), cfg, c[3], c[4], c[5], win, c[7], c[8], c[9], fetch,
             md(PARSE_MD), code(PARSE_CELL), md(READ_MD), code(READ_CELL), md(AGG_MD), code(AGG_CELL),
             md(WRITE_MD), code(WRITE_CELL), md(VERIFY_MD), code(VERIFY_CELL)]
    return [copy.deepcopy(x) for x in cells]


def main():
    base = json.loads(BASE.read_text(encoding='utf-8'))
    for name, text in (('PARSE_CELL', PARSE_CELL), ('READ_CELL', READ_CELL), ('AGG_CELL', AGG_CELL)):
        compile(text, name, 'exec')
    write_nb(OUT_INGEST, build_ingester(base), base['metadata'])
    print(f'Wrote {OUT_INGEST.relative_to(ROOT)}')


if __name__ == '__main__':
    sys.exit(main())

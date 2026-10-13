"""Check the M365 usage ingester's Spark parse against the M365 Usage Analytics processor.

    python scripts/test_m365_usage_parity.py --processor path/to/Purview_M365_Usage_Bundle_Explosion_Processor_v2.6.1.py

Needs pyspark 3.5+ and Java. Builds synthetic Graph audit records covering the edge cases the processor handles
(string or object auditData, service identities, date formats, folder items, Copilot arrays, prompt flags),
runs each through the processor's own key extraction and through the notebook's `parse_audit`, and compares
every output field. Exits non-zero on any mismatch.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import gen_m365_usage_notebooks as gen  # noqa: E402

FIELDS = ['UserKey', 'UserId', 'CreationDate', 'Operation', 'Workload', 'SourceFileExtension', 'AppHost',
          'AgentId', 'AgentName', 'ContextType', 'CreationTime', 'EventCount', 'ItemsAccessedCount',
          'IsAgent', 'HasCopilotData', 'ThreadId', 'PromptCount', 'ResponseCount']


def load_processor(path: Path):
    spec = importlib.util.spec_from_file_location('m365_processor', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def reference_row(p, r: dict):
    """The previous (processor-based) ingester's per-record logic."""
    audit_data = r.get('auditData')
    if isinstance(audit_data, str):
        try:
            audit_data = json.loads(audit_data)
        except ValueError:
            audit_data = None
    if not isinstance(audit_data, dict):
        return None
    ced = p.safe_get(audit_data, 'CopilotEventData')
    if ced and not isinstance(ced, dict):
        ced = None
    record = {'CreationDate': r.get('createdDateTime') or '',
              'UserId': r.get('userPrincipalName') or r.get('userId') or '',
              'Operation': r.get('operation') or ''}
    result = p._extract_rollup_keys(record, audit_data, ced)
    if result is None:
        return None
    group_key, event_count, items_accessed, creation_time, original_uid, is_agent = result
    prompts = responses = 0
    thread_id = ''
    if ced:
        for m in p.get_array_fast(ced, 'Messages'):
            ip = p.safe_get(m, 'isPrompt')
            if ip is True:
                prompts += 1
            elif ip is False:
                responses += 1
        thread_id = p._norm_key_str(p.safe_get(ced, 'ThreadId'))
    uid_lower, cdate, op, wl, sfe, app_host, agent_id, agent_name, ctx_type = group_key
    return {'UserKey': uid_lower, 'UserId': original_uid, 'CreationDate': cdate, 'Operation': op,
            'Workload': wl, 'SourceFileExtension': sfe, 'AppHost': app_host, 'AgentId': agent_id,
            'AgentName': agent_name, 'ContextType': ctx_type, 'CreationTime': creation_time or '',
            'EventCount': int(event_count), 'ItemsAccessedCount': int(items_accessed), 'IsAgent': bool(is_agent),
            'HasCopilotData': bool(ced), 'ThreadId': thread_id, 'PromptCount': prompts, 'ResponseCount': responses}


USERS = ['Alice@Contoso.com', 'bob@contoso.com', ' carol@contoso.com ', '11111111-1111-1111-1111-111111111111',
         'SupervisoryReview{abc}@contoso.com', 'app@sp', 'no-at-sign', 'two@@contoso.com', 'dave@.',
         'None', '', None, 'erin@contoso-uk.com']
DATES = ['2025-03-04T10:11:12Z', '2025-03-04T10:11:12.1234567Z', '2025-03-04T10:11:12.5Z', '2025-03-04T10:11:12',
         '3/4/2025 10:11:12 AM', '3/4/2025 1:02:03 PM', '03/04/2025 13:02:03', '2025-03-04', '3/4/2025',
         'garbage', '', None]
OPS = gen.OPERATIONS + ['CopilotInteraction', '', 'None', 'SomethingElse']
WORKLOADS = ['SharePoint', 'OneDrive', 'Exchange', 'MicrosoftTeams', 'Copilot', ' Copilot ', 'null', None]
EXTS = ['DOCX', 'xlsx', 'pptx', 'pdf', '', None, ' Docx ']
APPHOSTS = ['Word', 'Teams', 'Agent', 'copilotstudio', 'DeclarativeAgent', 'BizChat', '', None]


def _maybe(rng, v):
    return v if rng.random() < 0.8 else rng.choice([None, '', 'None', 'null'])


def make_ced(rng):
    kind = rng.random()
    if kind < 0.08:
        return {}
    if kind < 0.12:
        return 'not-an-object'
    if kind < 0.15:
        return None
    ced = {}
    if rng.random() < 0.7:
        ced['AppHost'] = rng.choice(APPHOSTS)
    if rng.random() < 0.3:
        ced['AgentId'] = rng.choice(['agent-1', 'T_abc.declarative', '', None])
        ced['AgentName'] = rng.choice(['HR Bot', 'Sales Helper', '', None])
    if rng.random() < 0.8:
        ced['ThreadId'] = rng.choice(['19:thread-a', '19:thread-b', ' 19:thread-c ', '', None])
    if rng.random() < 0.85:
        ced['Messages'] = [{'Id': str(i), 'isPrompt': rng.choice([True, False, None])} for i in range(rng.randint(0, 6))]
    if rng.random() < 0.6:
        ced['Contexts'] = [{'Type': rng.choice(['File', 'Email', 'TeamsMeeting', '', None]),
                            'Id': 'x', 'Items': ['i'] * rng.randint(0, 9)} for _ in range(rng.randint(0, 3))]
    for k in ('AccessedResources', 'SensitivityLabels', 'AISystemPlugin', 'ModelTransparencyDetails'):
        if rng.random() < 0.3:
            ced[k] = [str(i) for i in range(rng.randint(0, 5))]
    if rng.random() < 0.01:
        ced['Messages'] = [{'isPrompt': True}] * 1200
    return ced


def make_record(rng, i: int) -> dict:
    op = rng.choice(OPS)
    ad = {}
    if rng.random() < 0.6:
        ad['UserId'] = rng.choice(USERS)
    if rng.random() < 0.9:
        ad['Operation'] = rng.choice([op, op, rng.choice(OPS)])
    ad['Workload'] = rng.choice(WORKLOADS)
    if rng.random() < 0.6:
        ad['SourceFileExtension'] = rng.choice(EXTS)
    if rng.random() < 0.3:
        ad['AppHost'] = rng.choice(APPHOSTS)
    if rng.random() < 0.15:
        ad['AgentId'] = rng.choice(['agent-9', '', None])
        ad['AgentName'] = rng.choice(['Top Agent', None])
    ad['CreationTime'] = rng.choice(DATES)
    if op in ('MailItemsAccessed',) or rng.random() < 0.1:
        ad['Folders'] = [{'Path': '\\Inbox', 'FolderItems': [{'Id': str(k)} for k in range(rng.randint(0, 4))]}
                         for _ in range(rng.randint(0, 3))]
    if op in ('CopilotInteraction', 'AIAppInteraction', 'ConnectedAIAppInteraction') or rng.random() < 0.05:
        ced = make_ced(rng)
        if ced is not None:
            ad['CopilotEventData'] = ced
    shape = rng.random()
    audit = json.dumps(ad) if shape < 0.5 else ad
    if shape > 0.97:
        audit = rng.choice(['not json', '[1,2]', None, ''])
    return {'id': f'id-{i}' if rng.random() < 0.95 else None,
            'createdDateTime': rng.choice(DATES), 'operation': _maybe(rng, op),
            'userPrincipalName': _maybe(rng, rng.choice(USERS)), 'userId': rng.choice(USERS),
            'auditLogRecordType': 'x', 'auditData': audit, '_i': i}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--processor', required=True, type=Path)
    ap.add_argument('--records', type=int, default=4000)
    ap.add_argument('--seed', type=int, default=7)
    args = ap.parse_args()

    p = load_processor(args.processor)
    rng = random.Random(args.seed)
    records = [make_record(rng, i) for i in range(args.records)]
    expected = {r['_i']: reference_row(p, r) for r in records}

    from pyspark.sql import SparkSession
    spark = (SparkSession.builder.master('local[2]').appName('m365-parity')
             .config('spark.ui.enabled', 'false').config('spark.sql.shuffle.partitions', '4').getOrCreate())
    spark.sparkContext.setLogLevel('ERROR')
    ns = {'spark': spark}
    exec(gen.PARSE_CELL, ns)

    import tempfile
    tmp = Path(tempfile.mkdtemp()) / 'staged.jsonl'
    tmp.write_text('\n'.join(json.dumps({**{k: r[k] for k in ns['STAGE_SCHEMA'].fieldNames()}, 'id': str(r['_i'])})
                             for r in records), encoding='utf-8')
    raw = spark.read.schema(ns['STAGE_SCHEMA']).json(str(tmp))
    got = {int(row['id']): row.asDict() for row in ns['parse_audit'](raw).select('id', *FIELDS).collect()}
    spark.stop()

    mismatches = []
    for i, exp in expected.items():
        act = got.get(i)
        if act is not None:
            act = {k: act[k] for k in FIELDS}
        if exp != act:
            diff = ({k: (exp[k], act[k]) for k in FIELDS if exp[k] != act[k]} if exp and act
                    else {'expected': exp, 'actual': act})
            mismatches.append((i, diff))
    kept = sum(1 for v in expected.values() if v)
    print(f'{len(records)} records, {kept} kept by the processor, {len(mismatches)} mismatches')
    for i, diff in mismatches[:25]:
        rec = {k: records[i][k] for k in ('createdDateTime', 'operation', 'userPrincipalName', 'userId', 'auditData')}
        print(f'\n#{i}: {diff}\n   input: {json.dumps(rec)[:600]}')
    sys.exit(1 if mismatches else 0)


if __name__ == '__main__':
    main()

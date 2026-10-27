"""Check that the M365 usage ingester pulls Teams call and meeting signals through to its lake tables.

    python scripts/test_m365_teams_calls.py

Needs pyspark 3.5+ and Java. Checks notebooks/M365_Usage_Audit_Ingester.ipynb matches scripts/gen_m365_usage_notebooks.py,
then runs fixture CallParticipantDetail / MeetingParticipantDetail audit records through the notebook's parse and
rollup cells and checks dbo.m365_teams_call_participation (join/leave, time in call, screen share) and that
CallParticipantDetail stays out of dbo.m365_usage_rollup. Exits non-zero on any failure.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import gen_m365_usage_notebooks as gen  # noqa: E402

ALICE, BOB = 'alice@contoso.com', 'Bob@Contoso.com'


def _rec(rid, op, user, created, audit, as_text=False):
    audit = {'UserId': user, 'Operation': op, 'Workload': 'MicrosoftTeams', 'CreationTime': created, **audit}
    return {'id': rid, 'createdDateTime': created, 'operation': op, 'userPrincipalName': user, 'userId': user,
            'auditLogRecordType': 'x', 'auditData': json.dumps(audit) if as_text else audit}


RECORDS = [
    # 1:1 call, 30m15s, two screen shares (300s + 60s; fractional seconds are truncated).
    _rec('call-1', 'CallParticipantDetail', ALICE, '2025-03-04T14:00:00Z', {
        'CallId': 'c-1', 'CommunicationType': 'OneOnOne', 'CommunicationSubType': 'Call',
        'JoinTime': '2025-03-04T10:00:00Z', 'LeaveTime': '2025-03-04T10:30:15.1234567Z',
        'Attendees': [{'UPN': ALICE, 'Role': 'Attendee'}],
        'ArtifactsShared': [{'ArtifactSharedName': 'videoTransmitted', 'ArtifactShareSessions': [
            {'ScreenShareId': 's1', 'StartTimestamp': '2025-03-04T10:05:00Z', 'EndTimestamp': '2025-03-04T10:10:00Z'},
            {'ScreenShareId': 's2', 'StartTimestamp': '2025-03-04T10:20:00.5Z', 'EndTimestamp': '2025-03-04T10:21:00Z'}]}]}),
    # Meeting across midnight, logged the next day; auditData as text.
    _rec('mtg-1', 'MeetingParticipantDetail', BOB, '2025-03-05T03:00:00Z', {
        'MeetingDetailId': 'md-1', 'CommunicationType': 'GroupCall',
        'JoinTime': '2025-03-04T23:30:00Z', 'LeaveTime': '2025-03-05T00:15:00Z'}, as_text=True),
    # Older operation name, no leave time.
    _rec('mtg-2', 'MeetingParticipantJoined', ALICE, '2025-03-04T16:00:00Z', {
        'MeetingDetailId': 'md-2', 'JoinTime': '2025-03-04T15:00:00Z'}),
    # Leave before join; one open screen share session and an artifact without sessions.
    _rec('call-2', 'CallParticipantDetail', BOB, '2025-03-06T09:00:00Z', {
        'CallId': 'c-2', 'JoinTime': '2025-03-06T08:00:00Z', 'LeaveTime': '2025-03-06T07:59:00Z',
        'ArtifactsShared': [{'ArtifactSharedName': 'x'},
                            {'ArtifactShareSessions': [{'StartTimestamp': '2025-03-06T08:01:00Z'}]}]}),
    # Malformed call fields don't drop the record.
    _rec('call-3', 'CallParticipantDetail', ALICE, '2025-03-07T09:00:00Z', {
        'CallId': 'c-3', 'JoinTime': 'garbage', 'ArtifactsShared': 'not-an-array'}),
    # Non-human identity: dropped.
    _rec('call-4', 'CallParticipantDetail', '11111111-1111-1111-1111-111111111111', '2025-03-04T14:00:00Z', {
        'CallId': 'c-4', 'JoinTime': '2025-03-04T10:00:00Z', 'LeaveTime': '2025-03-04T11:00:00Z'}),
    # Control record: rollup only.
    {**_rec('file-1', 'FileAccessed', ALICE, '2025-03-04T12:00:00Z', {'SourceFileExtension': 'docx'}),
     'auditData': json.dumps({'UserId': ALICE, 'Operation': 'FileAccessed', 'Workload': 'SharePoint',
                              'SourceFileExtension': 'docx', 'CreationTime': '2025-03-04T12:00:00Z'})},
]

EXPECTED = {
    'call-1': {'UserId': ALICE, 'Operation': 'CallParticipantDetail', 'SourceOperation': 'CallParticipantDetail',
               'CallId': 'c-1', 'MeetingDetailId': '', 'CommunicationType': 'OneOnOne', 'CommunicationSubType': 'Call',
               'CreationDate': '2025-03-04T00:00:00.000Z', 'ActivityDate': '2025-03-04T00:00:00.000Z',
               'JoinTime': '2025-03-04T10:00:00Z', 'LeaveTime': '2025-03-04T10:30:15Z',
               'DurationSeconds': 1815, 'ScreenShareCount': 2, 'ScreenShareSeconds': 360},
    'mtg-1': {'UserId': BOB, 'Operation': 'MeetingParticipantDetail', 'SourceOperation': 'MeetingParticipantDetail',
              'CallId': '', 'MeetingDetailId': 'md-1', 'CommunicationType': 'GroupCall',
              'CreationDate': '2025-03-05T00:00:00.000Z', 'ActivityDate': '2025-03-04T00:00:00.000Z',
              'DurationSeconds': 2700, 'ScreenShareCount': 0, 'ScreenShareSeconds': 0},
    'mtg-2': {'Operation': 'MeetingParticipantDetail', 'SourceOperation': 'MeetingParticipantJoined',
              'ActivityDate': '2025-03-04T00:00:00.000Z', 'LeaveTime': '', 'DurationSeconds': None,
              'ScreenShareCount': 0, 'ScreenShareSeconds': 0},
    'call-2': {'ActivityDate': '2025-03-06T00:00:00.000Z', 'DurationSeconds': None,
               'ScreenShareCount': 1, 'ScreenShareSeconds': 0},
    'call-3': {'CallId': 'c-3', 'JoinTime': '', 'ActivityDate': '2025-03-07T00:00:00.000Z', 'DurationSeconds': None,
               'ScreenShareCount': 0, 'ScreenShareSeconds': 0},
}


def check_notebook_in_sync() -> list[str]:
    nb_path = gen.OUT_INGEST
    base = json.loads(gen.BASE.read_text(encoding='utf-8'))
    expected = {'cells': gen.build_ingester(base), 'metadata': base['metadata'], 'nbformat': 4, 'nbformat_minor': 5}
    actual = json.loads(nb_path.read_text(encoding='utf-8'))
    errors = []
    if actual != expected:
        errors.append(f'{nb_path.relative_to(ROOT)} is out of date: run python scripts/gen_m365_usage_notebooks.py')
    if 'CallParticipantDetail' not in gen.OPERATIONS:
        errors.append('CallParticipantDetail missing from OPERATIONS')
    return errors


def check_spark() -> list[str]:
    from pyspark.sql import SparkSession
    # A non-UTC session time zone proves durations and activity days don't depend on it.
    spark = (SparkSession.builder.master('local[1]').appName('m365-teams-calls')
             .config('spark.ui.enabled', 'false').config('spark.sql.shuffle.partitions', '2')
             .config('spark.sql.session.timeZone', 'America/Los_Angeles').getOrCreate())
    spark.sparkContext.setLogLevel('ERROR')
    ns = {'spark': spark}
    exec(gen.PARSE_CELL, ns)
    errors = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'staged.jsonl'
            staged = []
            for r in RECORDS:
                row = {k: r[k] for k in ns['STAGE_SCHEMA'].fieldNames()}
                if not isinstance(row['auditData'], str):
                    row['auditData'] = json.dumps(row['auditData'])
                staged.append(json.dumps(row))
            path.write_text('\n'.join(staged), encoding='utf-8')
            raw = spark.read.schema(ns['STAGE_SCHEMA']).json(str(path))
            ns['recs'] = ns['parse_audit'](raw).persist()
            exec(gen.AGG_CELL, ns)
            calls = {r['Id']: r.asDict() for r in ns['calls'].collect()}
            rollup = ns['rollup'].collect()
            if list(ns['calls'].columns) != ns['CALL_HEADER']:
                errors.append(f"call table columns {ns['calls'].columns} != CALL_HEADER")
    finally:
        spark.stop()

    if set(calls) != set(EXPECTED):
        errors.append(f'call table ids {sorted(calls)} != {sorted(EXPECTED)}')
    for rid, exp in EXPECTED.items():
        got = calls.get(rid, {})
        for col, val in exp.items():
            if got.get(col) != val:
                errors.append(f'{rid}.{col}: expected {val!r}, got {got.get(col)!r}')
    ops = sorted({r['Operation'] for r in rollup})
    if ops != ['FileAccessed', 'MeetingParticipantDetail']:
        errors.append(f'rollup operations {ops}: CallParticipantDetail must stay out, meetings and files stay in')
    mtg = sum(r['EventCount'] for r in rollup if r['Operation'] == 'MeetingParticipantDetail')
    if mtg != 2:
        errors.append(f'rollup MeetingParticipantDetail EventCount {mtg} != 2')
    print(f'{len(calls)} call/meeting rows, {len(rollup)} rollup rows')
    return errors


def main():
    errors = check_notebook_in_sync()
    errors += check_spark()
    for e in errors:
        print('FAIL:', e)
    print('PASS' if not errors else f'FAIL ({len(errors)} errors)')
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()

"""Check the template's T-SQL (08-report-templates/m365-usage-sql) against the M365 Usage Analytics processor.

    python scripts/test_m365_usage_sql.py --processor path/to/Purview_M365_Usage_Bundle_Explosion_Processor_v2.6.1.py

Needs pyspark 3.5+ and Java. Builds synthetic lake tables (non-AI rollup, Copilot_Interactions_Parsed and the two
AI-app record tables), runs the template SQL in Spark (after a few mechanical T-SQL -> Spark rewrites), checks the
derived Rollup and Session Stats against a Python reference built from the same records, then runs the processor's
write_userstats_files on those two files and compares every UserStats and SessionCohort cell. Exits non-zero on
any mismatch.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import random
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import gen_m365_usage_sql as gen  # noqa: E402

ROLLUP = ['UserId', 'CreationDate', 'Operation', 'Workload', 'SourceFileExtension', 'AppHost', 'EventCount',
          'ItemsAccessedCount', 'CreationTime', 'MaxCreationTime', 'AgentId', 'AgentName', 'ContextType',
          'IsAgentInteraction']
SESSION = ['UserId', 'CreationDate', 'AppHost', 'SessionCount', 'PromptCount', 'AgentPromptCount',
           'ResponseCount', 'AgentSessionCount']


def load_processor(path: Path):
    spec = importlib.util.spec_from_file_location('m365_processor', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def to_spark(sql: str) -> str:
    sql = re.sub(r'^\s*--.*$', '', sql, flags=re.M)
    sql = re.sub(r'DATEADD\(day, (-?\d+), (CAST\(\w+ AS DATE\))\)', r'date_add(\2, \1)', sql)
    sql = re.sub(r'DATEDIFF\(day, (CAST\(\w+ AS DATE\)), (CAST\(\w+ AS DATE\))\)', r'datediff(\2, \1)', sql)
    sql = re.sub(r'CONVERT\(VARCHAR\(23\), (.+?), 126\)',
                 lambda m: f'date_format({m.group(1)}, "yyyy-MM-dd\'T\'HH:mm:ss.SSS")', sql)
    sql = sql.replace('AS FLOAT)', 'AS DOUBLE)').replace('AS VARCHAR(10))', 'AS STRING)')
    return sql.replace('dbo.', '')


AI_COLS = ['UserId', 'CreationDate', 'CreationTime', 'Operation', 'Workload', 'AppHost', 'AgentId', 'AgentName',
           'ContextType', 'ThreadId', 'PromptCount', 'ResponseCount', 'EventCount', 'IsAgent']
PARSED_COLS = ['Source_RecordKey', 'Audit_UserId', 'InteractionDate', 'CreationDate', 'Workload', 'AppHost', 'AgentId',
               'AgentName', 'Context_Type', 'ThreadId', 'Message_Id', 'Message_isPrompt', 'Resource_Count']


def synth(seed: int, n_users: int, days: int):
    """Returns (non-AI rollup rows, parsed Copilot rows, connected rows, ai-app rows, reference AI interactions)."""
    rnd = random.Random(seed)
    users = [f'User{i}@Contoso.com' if i % 3 else f'user{i}@contoso.com' for i in range(n_users)] + ['', 'Zed@Example.com']
    base = date(2025, 1, 1)
    ops = gen.FILE_OPS + ['FilePreviewed'] + gen.OUTLOOK_OPS + gen.TEAMS_OPS + gen.DAX_TEAMS_OPS + ['SomethingElse']
    wls = ['SharePoint', 'OneDrive', 'Exchange', 'MicrosoftTeams', 'Copilot']
    exts = gen.WORD_EXTS + gen.EXCEL_EXTS + gen.PPT_EXTS + ['DOCX', 'Xlsx', 'pdf', '']
    hosts = ['Excel', 'excel', 'Word', 'Teams', '', 'Agent']
    rows, seen = [], set()
    for u in users:
        heavy = rnd.random()
        for _ in range(rnd.randint(0, int(5 + heavy * 120))):
            d = base + timedelta(days=rnd.randint(0, days - 1))
            dk = '' if rnd.random() < 0.01 else d.isoformat() + 'T00:00:00.000Z'
            key = (u.lower(), dk, rnd.choice(ops), rnd.choice(wls), rnd.choice(exts), rnd.choice(hosts))
            if key in seen:
                continue
            seen.add(key)
            ec = rnd.choice([1, 1, 2, 3, 7, 25, 0])
            rows.append([u, dk, key[2], key[3], key[4], key[5], ec, 0, '', '', '', '', '', 'FALSE'])
    # Stale Copilot rows from an older ingester version must be ignored.
    rows.append(['Stale@contoso.com', base.isoformat() + 'T00:00:00.000Z', 'CopilotInteraction', 'Copilot', '', 'Word',
                 99, 0, '', '', '', '', '', 'FALSE'])

    parsed, conn, aiapp, ref = [], [], [], []
    humans = [u for u in users if u]
    for n in range(rnd.randint(30, 300)):
        u = rnd.choice(humans)
        d = base + timedelta(days=rnd.randint(0, days - 1))
        t = f'{d.isoformat()}T{rnd.randint(0, 23):02d}:{rnd.randint(0, 59):02d}:{rnd.randint(0, 59):02d}.{rnd.randint(0, 999):03d}'
        host = rnd.choice(['Word', 'Excel', 'Teams', 'BizChat', 'Agent', 'copilotstudio', ''])
        agid, agname = rnd.choice([('', ''), ('', ''), ('agent-1', 'HR Bot'), ('T_x.declarative', 'Sales Helper')])
        ctx = rnd.choice(['', 'File', 'Email'])
        thread = rnd.choice(['', '19:t1', '19:t2', f'19:t{n}'])
        kind = rnd.choice(['copilot', 'copilot', 'copilot', 'connected', 'aiapp'])
        pc = rnd.choice([0, 1, 1, 2, 3, 5])
        if kind == 'copilot':
            rc = 1200 if rnd.random() < 0.01 else rnd.choice([0, 0, 1, 2, 4, 7])
            for m in (range(pc) if pc else [None]):
                for r_i in range(max(rc, 1)):
                    parsed.append([f'rec{n}', u, d.isoformat(), t, 'Copilot', host, agid, agname, ctx, thread,
                                   f'msg{m}' if m is not None else 'message:none', 'true' if m is not None else 'false',
                                   rc])
            ec = min(gen.EVENT_ROW_CAP, max(1, pc, rc))
            ag = agid != '' or host.lower() in gen.AGENT_APPHOSTS
            rec = [u, d.isoformat() + 'T00:00:00.000Z', t + 'Z', 'CopilotInteraction', 'Copilot', host, agid, agname,
                   ctx, thread, pc, pc, ec, ag]
        else:
            resp = rnd.choice([0, 1, 2])
            ec = rnd.choice([1, 2, 6])
            rec = [u, d.isoformat() + 'T00:00:00.000Z', t + 'Z', 'AIAppInteraction', 'Copilot', host, agid, agname,
                   ctx, thread, pc, resp, ec, True]
            (conn if kind == 'connected' else aiapp).append(
                [u, rec[1], rec[2], 'ConnectedAIAppInteraction' if kind == 'connected' else 'AIAppInteraction',
                 'Copilot', host, agid, agname, ctx, thread, pc, resp, ec, 'TRUE'])
        ref.append(rec)
    # Non-human identities in the parsed table are dropped by the SQL.
    parsed.append(['recX', 'app@sp', base.isoformat(), base.isoformat() + 'T01:00:00.000', 'Copilot', 'Word', '', '',
                   '', '19:x', 'msg0', 'true', 0])
    return rows, parsed, conn, aiapp, ref


def ref_rollup(ref):
    g = {}
    for u, dk, tm, op, wl, host, agid, agname, ctx, thread, pc, resp, ec, ag in ref:
        k = (u.lower(), dk, op, wl, host, agid, agname, ctx)
        x = g.setdefault(k, {'UserId': u, 'EventCount': 0, 'CreationTime': tm, 'MaxCreationTime': tm, 'ag': False})
        x['UserId'] = min(x['UserId'], u)
        x['EventCount'] += ec
        x['CreationTime'] = min(x['CreationTime'], tm)
        x['MaxCreationTime'] = max(x['MaxCreationTime'], tm)
        x['ag'] = x['ag'] or ag
    return {k: {**v, 'IsAgentInteraction': 'TRUE' if v.pop('ag') else 'FALSE'} for k, v in g.items()}


def ref_sessions(ref):
    g = {}
    for u, dk, tm, op, wl, host, agid, agname, ctx, thread, pc, resp, ec, ag in ref:
        x = g.setdefault((u.lower(), dk, host), {'UserId': u, 's': set(), 'as': set(), 'PromptCount': 0,
                                                 'AgentPromptCount': 0, 'ResponseCount': 0})
        x['UserId'] = min(x['UserId'], u)
        if thread and pc > 0:
            x['s'].add(thread)
            if ag:
                x['as'].add(thread)
        x['PromptCount'] += pc
        x['AgentPromptCount'] += pc if ag else 0
        x['ResponseCount'] += resp
    out = {}
    for k, x in g.items():
        if not x['s'] and x['PromptCount'] == 0:
            continue
        out[k] = {'UserId': x['UserId'], 'SessionCount': len(x['s']), 'PromptCount': x['PromptCount'],
                  'AgentPromptCount': x['AgentPromptCount'], 'ResponseCount': x['ResponseCount'],
                  'AgentSessionCount': len(x['as'])}
    return out


def check(name, exp, got, cols):
    errors = 0
    if set(exp) != set(got):
        print(f'[{name}] key mismatch: only reference={sorted(set(exp) - set(got))[:5]} '
              f'only sql={sorted(set(got) - set(exp))[:5]}')
        errors += 1
    for k in sorted(set(exp) & set(got)):
        for c in cols:
            if norm(exp[k][c]) != norm(got[k][c]):
                errors += 1
                if errors <= 20:
                    print(f'[{name}] {k} {c}: reference={exp[k][c]!r} sql={got[k][c]!r}')
    print(f'[{name}] {len(exp)} rows compared, {errors} mismatches')
    return errors


def write_csv(path: Path, header, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(header)
        w.writerows(rows)


def read_csv(path: Path):
    with open(path, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def norm(v) -> str:
    if v is None:
        return ''
    s = str(v)
    try:
        x = float(s)
        if x == int(x) and 'e' not in s.lower():
            return str(int(x))
        return f'{x:.6f}'
    except ValueError:
        return s


def compare(name, ref_rows, sql_rows, key_cols, cols):
    errors = 0
    ref = {tuple(r[k] for k in key_cols): r for r in ref_rows}
    got = {tuple(str(r[k] or '') for k in key_cols): r for r in sql_rows}
    if set(ref) != set(got):
        print(f'[{name}] key mismatch: only processor={sorted(set(ref) - set(got))[:5]} '
              f'only sql={sorted(set(got) - set(ref))[:5]}')
        errors += 1
    for k in sorted(set(ref) & set(got)):
        for c in cols:
            a, b = norm(ref[k][c]), norm(got[k][c])
            if a != b:
                if c.endswith('RankColumn') and abs(float(a) - float(b)) <= 1.1e-6:
                    continue
                errors += 1
                if errors <= 20:
                    print(f'[{name}] {k} {c}: processor={a!r} sql={b!r}')
    print(f'[{name}] {len(ref)} rows compared, {errors} mismatches')
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--processor', required=True, type=Path)
    args = ap.parse_args()
    p = load_processor(args.processor)

    from pyspark.sql import SparkSession
    spark = (SparkSession.builder.master('local[2]').appName('m365-sql-parity')
             .config('spark.ui.enabled', 'false').config('spark.sql.shuffle.partitions', '4')
             .config('spark.sql.session.timeZone', 'UTC').getOrCreate())
    spark.sparkContext.setLogLevel('ERROR')

    total = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for seed, n_users, days in [(1, 40, 90), (2, 15, 20), (3, 120, 75)]:
            rows, parsed, conn, aiapp, ref = synth(seed, n_users, days)
            write_csv(tmp / 'lake.csv', ROLLUP, rows)
            (spark.read.csv(str(tmp / 'lake.csv'), header=True, inferSchema=False)
             .selectExpr(*[f'CAST({c} AS BIGINT) AS {c}' if c in ('EventCount', 'ItemsAccessedCount')
                           else f'COALESCE({c}, \'\') AS {c}' for c in ROLLUP])
             .createOrReplaceTempView('m365_usage_rollup'))
            num = ('Resource_Count', 'PromptCount', 'ResponseCount', 'EventCount')
            for view, cols, data in [('copilot_interactions_parsed', PARSED_COLS, parsed),
                                     ('connected_ai_app_interactions', AI_COLS, conn),
                                     ('ai_app_interactions', AI_COLS, aiapp)]:
                write_csv(tmp / f'{view}.csv', cols, data)
                (spark.read.csv(str(tmp / f'{view}.csv'), header=True, inferSchema=False)
                 .selectExpr(*[f'CAST({c} AS DATE) AS {c}' if c == 'InteractionDate'
                               else f'CAST({c} AS TIMESTAMP) AS {c}' if view.startswith('copilot') and c == 'CreationDate'
                               else f'CAST({c} AS BIGINT) AS {c}' if c in num
                               else f'COALESCE({c}, \'\') AS {c}' for c in cols])
                 .createOrReplaceTempView(view))

            ru = [r.asDict() for r in spark.sql(to_spark(gen.rollup())).collect()]
            ss = [r.asDict() for r in spark.sql(to_spark(gen.sessionstats())).collect()]
            ai_ru = {(r['UserId'].lower(), r['CreationDate'], r['Operation'], r['Workload'], r['AppHost'], r['AgentId'],
                      r['AgentName'], r['ContextType']): r for r in ru if r['Operation'] in gen.AI_OPS}
            total += check('rollup-ai', ref_rollup(ref), ai_ru,
                           ['UserId', 'EventCount', 'CreationTime', 'MaxCreationTime', 'IsAgentInteraction'])
            n_lake = sum(1 for r in ru if r['Operation'] not in gen.AI_OPS)
            if n_lake != len(rows) - 1:
                print(f'[rollup-lake] expected {len(rows) - 1} non-AI rows, got {n_lake}')
                total += 1
            total += check('sessionstats', ref_sessions(ref),
                           {(r['UserId'].lower(), r['CreationDate'], r['AppHost']): r for r in ss}, SESSION[3:] + ['UserId'])

            write_csv(tmp / 'rollup.csv', ROLLUP, [[r[c] for c in ROLLUP] for r in ru])
            write_csv(tmp / 'sess.csv', SESSION, [[r[c] for c in SESSION] for r in ss])
            p.write_userstats_files(tmp / 'rollup.csv', tmp / 'us.csv', tmp / 'sc.csv', True, tmp / 'sess.csv')
            sess = ss

            us = [r.asDict() for r in spark.sql(to_spark(gen.userstats())).collect()]
            sc = [r.asDict() for r in spark.sql(to_spark(gen.sessioncohort())).collect()]
            print(f'seed {seed}: {len(rows)} rollup rows, {len(sess)} session rows')
            if us and list(us[0].keys()) != p.USERSTATS_HEADER:
                print('[userstats] column order differs from USERSTATS_HEADER')
                total += 1
            total += compare('userstats', read_csv(tmp / 'us.csv'), us, ['UserId'], p.USERSTATS_HEADER[1:])
            total += compare('sessioncohort', read_csv(tmp / 'sc.csv'), sc, ['UserId', 'AppColumn'],
                             ['SessionCohort'])
    spark.stop()
    print('PASS' if total == 0 else f'FAIL ({total} mismatches)')
    sys.exit(1 if total else 0)


if __name__ == '__main__':
    main()

"""Check the template's T-SQL (08-report-templates/m365-usage-sql) against the M365 Usage Analytics processor.

    python scripts/test_m365_usage_sql.py --processor path/to/Purview_M365_Usage_Bundle_Explosion_Processor_v2.6.1.py

Needs pyspark 3.5+ and Java. Writes a synthetic rollup and session-stats table to CSV, runs the processor's
write_userstats_files on them, runs the same SQL in Spark (after a few mechanical T-SQL -> Spark rewrites),
and compares every UserStats and SessionCohort cell. Exits non-zero on any mismatch.
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
    sql = sql.replace('AS FLOAT)', 'AS DOUBLE)').replace('AS VARCHAR(10))', 'AS STRING)')
    return sql.replace('dbo.', '')


def synth(seed: int, n_users: int, days: int):
    rnd = random.Random(seed)
    users = [f'User{i}@Contoso.com' if i % 3 else f'user{i}@contoso.com' for i in range(n_users)] + ['', 'Zed@Example.com']
    base = date(2025, 1, 1)
    ops = (gen.FILE_OPS + ['FilePreviewed'] + gen.OUTLOOK_OPS + gen.TEAMS_OPS + gen.DAX_TEAMS_OPS
           + gen.COPILOT_OPS + ['SomethingElse'])
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
    sess = []
    for u in users:
        for _ in range(rnd.randint(0, 6)):
            d = base + timedelta(days=rnd.randint(0, days - 1))
            uu = rnd.choice([u, u.upper(), ' ' + u + ' '])
            sess.append([uu, d.isoformat() + 'T00:00:00.000Z', rnd.choice(hosts), 1, rnd.choice([0, 1, 3, 9]), 0, 0, 0])
    sess.append(['Ghost@example.org', base.isoformat() + 'T00:00:00.000Z', 'Word', 1, 5, 0, 0, 0])
    return rows, sess


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
             .config('spark.ui.enabled', 'false').config('spark.sql.shuffle.partitions', '4').getOrCreate())
    spark.sparkContext.setLogLevel('ERROR')

    total = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for seed, n_users, days in [(1, 40, 90), (2, 15, 20), (3, 120, 75)]:
            rows, sess = synth(seed, n_users, days)
            write_csv(tmp / 'rollup.csv', ROLLUP, rows)
            write_csv(tmp / 'sess.csv', SESSION, sess)
            p.write_userstats_files(tmp / 'rollup.csv', tmp / 'us.csv', tmp / 'sc.csv', True, tmp / 'sess.csv')

            (spark.read.csv(str(tmp / 'rollup.csv'), header=True, inferSchema=False)
             .selectExpr(*[f'CAST({c} AS BIGINT) AS {c}' if c in ('EventCount', 'ItemsAccessedCount')
                           else f'COALESCE({c}, \'\') AS {c}' for c in ROLLUP])
             .createOrReplaceTempView('m365_usage_rollup'))
            (spark.read.csv(str(tmp / 'sess.csv'), header=True, inferSchema=False, ignoreLeadingWhiteSpace=False,
                            ignoreTrailingWhiteSpace=False)
             .selectExpr(*[f'CAST({c} AS BIGINT) AS {c}' if c not in ('UserId', 'CreationDate', 'AppHost')
                           else c for c in SESSION])
             .createOrReplaceTempView('m365_usage_sessionstats'))

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

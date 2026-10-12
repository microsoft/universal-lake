# %% [markdown]
# # Orchestrator
#
# Runs every ingest and processing step in order, one at a time from a notebook, so every step is visible,
# logged and individually re-runnable.
#
# * Every step writes a `start` and an `end` row to `ops.run_log` (status, duration, exit value, full error).
# * Every source that reads history writes the window it asked for to `ops.backfill_ledger` **before** it runs
#   (`planned`) and again after (`done` / `failed`), so you can always see what period was fetched by which run.
# * Nothing runs that you did not ask for: the plan is printed first, and `DRY_RUN = True` stops there.
#
# | `RUN_MODE` | Audit log | Processor | Transcripts | Model refresh | Use it for |
# |---|---|---|---|---|---|
# | `first_load` | backfill `BACKFILL_DAYS` | overwrite | last `BACKFILL_DAYS` | overwrite | the very first run |
# | `backfill` | backfill `BACKFILL_DAYS` | overwrite | last `BACKFILL_DAYS` | overwrite | widening history or repairing gaps |
# | `incremental` | since last load + `LOOKBACK_DAYS` | merge | last 14 days | merge | the daily run |
#
# Re-running: see `07-orchestrate/RERUNS.md`. In short: `RERUN_FAILED = True` re-runs only the steps of `RUN_ID`
# that did not succeed.

# %% [parameters]
RUN_MODE = 'incremental'       # 'first_load' (first run), 'backfill' (more history / fix a gap) or 'incremental' (daily)
RUN_ID = ''                    # to retry a run: its run_id ...
RERUN_FAILED = False           # ... and True: runs only the steps of RUN_ID that did not succeed
STEPS = ''                     # blank = everything; or e.g. 'org_data' to run just that step
DRY_RUN = False                # True = print the plan and stop

# Advanced: leave as is unless you have a reason
BACKFILL_DAYS = 0              # 0 = backfillDays from config.json; max 180
SCALE = ''                     # blank = scale from config.json
MODULES = ''                   # blank = modules from config.json
SKIP_STEPS = ''                # comma-separated step names to leave out
START_FROM = ''                # skip every step before this one
CONTINUE_ON_ERROR = True       # non-critical failures are logged and the run continues
AUTO_RESUME = 8                # extra automatic passes for an audit backfill that hits its time budget
CAPACITY_RETRIES = 6           # a step that fails because no Spark capacity is free is tried again this many times ...
CAPACITY_RETRY_MINUTES = 5     # ... waiting this many minutes between tries

# %%
%run lake_ops

# %%
import json
from datetime import timedelta

ensure_ops()

RUN_MODE = RUN_MODE.strip().lower()
assert RUN_MODE in ('first_load', 'backfill', 'incremental'), f'unknown RUN_MODE {RUN_MODE!r}'
IS_BACKFILL = RUN_MODE in ('first_load', 'backfill')

BACKFILL_DAYS = int(BACKFILL_DAYS or cfg('backfill_days', 30))
assert 1 <= BACKFILL_DAYS <= 180, 'BACKFILL_DAYS must be 1..180 (the audit log keeps 180 days)'
SCALE = (SCALE or cfg('scale', 'standard')).strip().lower()
assert SCALE in ('standard', 'large'), f'unknown SCALE {SCALE!r}'
MODULES = {'copilotInteractions' if m.strip() == 'core' else m.strip()
           for m in (MODULES or cfg('modules', 'copilotInteractions')).split(',') if m.strip()} | {'copilotInteractions'}
WORKSPACE_ID = cfg('workspace_id', required=True)

if RERUN_FAILED:
    assert RUN_ID, 'RERUN_FAILED needs RUN_ID (find it with: SELECT DISTINCT run_id FROM ops.run_log ORDER BY 1 DESC)'
RUN_ID = RUN_ID or new_run_id(RUN_MODE)
print(f'run_id={RUN_ID}  mode={RUN_MODE}  scale={SCALE}  backfill_days={BACKFILL_DAYS}')
print(f'modules={sorted(MODULES)}')

import os
from datetime import datetime, timezone
RUN_STATUS_FILE = '/lakehouse/default/Files/universal_lake/runs/latest.json'
RUN_STARTED = datetime.now(timezone.utc).isoformat()


def write_run_status(status, **fields):
    """npm run deploy -- --watch reads this file to say in the terminal which steps failed and why."""
    try:
        os.makedirs(os.path.dirname(RUN_STATUS_FILE), exist_ok=True)
        with open(RUN_STATUS_FILE, 'w') as f:
            json.dump({'run_id': RUN_ID, 'run_mode': RUN_MODE, 'status': status, 'started': RUN_STARTED,
                       'updated': datetime.now(timezone.utc).isoformat(), **fields}, f, indent=2, default=str)
    except Exception as e:
        print(f'(could not write {RUN_STATUS_FILE}: {e})')


write_run_status('running')

# %% [markdown]
# ## Steps
#
# Each step's arguments, bindings, scale settings and timeout. Only the notebooks that have a **parameters cell**
# accept arguments; the others always run with the values baked into them by `npm run sync`.

# %%
LARGE = SCALE == 'large'
H = 3600

def audit_args():
    a = {'MODE': 'backfill' if IS_BACKFILL else 'incremental', 'BACKFILL_DAYS': BACKFILL_DAYS}
    if LARGE:
        a.update({'CHUNK_HOURS': 2, 'WINDOW_RETRIES': 1, 'LOOKBACK_DAYS': 3, 'TIME_BUDGET_MIN': 300})
    else:
        a.update({'CHUNK_HOURS': 24, 'TIME_BUDGET_MIN': 90})
    return a

def model_args(key, write_mode):
    return {'WORKSPACE_ID': WORKSPACE_ID, 'SEMANTIC_MODEL_ID': cfg(f'model_id.{key}', ''),
            'WRITE_MODE': write_mode, 'TIMEOUT_MINUTES': 290 if LARGE else 170}

# Model key -> the module it belongs to. The models step creates any model that is missing and (re)connects all of
# them as the app, so the refreshes after it run unattended. Existing model definitions are left as they are.
MODEL_MODULE = {'universal': 'copilotInteractions', 'consumption': 'consumption', 'agentEvaluator': 'agentEvaluator'}

def models_args():
    return {'RUN_ID': RUN_ID, 'MODELS': ','.join(k for k, m in MODEL_MODULE.items() if m in MODULES),
            'DEPLOY': 'missing', 'REFRESH': False}

TRANSCRIPT_DAYS = BACKFILL_DAYS if IS_BACKFILL else 14

# name, notebook, module, critical, timeout_s, args (callable), ledger (source, days) or None
STEPS_ALL = [
    ('audit',            'Copilot_Audit_Log_Direct_Ingester',      'copilotInteractions',            True,  (6 if LARGE else 2) * H, audit_args,
        ('audit_log', BACKFILL_DAYS if IS_BACKFILL else None)),
    ('licensed_users',   'Copilot_Licensed_Users_Direct_Ingester', 'copilotInteractions',            True,  (30 if LARGE else 15) * 60, dict, ('licensed_users', 7)),
    ('agent365',         'Copilot_Agent365_Registry_Ingester',     'agent365',        False, 15 * 60, dict, ('agent365_registry', None)),
    ('processor',        'Copilot_Audit_Log_Processor',            'copilotInteractions',            True,  (3 if LARGE else 2) * H,
        lambda: {'WRITE_MODE': 'overwrite' if IS_BACKFILL else 'merge'}, None),
    ('upload_router',    'AnalyticsHub_Upload_Router',             'copilotInteractions',            False, 30 * 60, dict, None),
    ('org_data',         'Copilot_Org_Data_Direct_Ingester',       'orgData',         False, (1 if LARGE else 0.5) * H, dict, ('org_data', None)),
    ('m365_activity',    'Copilot_M365_Activity_Ingester',         'm365Activity',    False, (2 if LARGE else 1) * H, dict, ('m365_activity', None)),
    ('product_feedback', 'Copilot_ProductFeedback_Ingester',       'productFeedback', False, 30 * 60, dict, ('product_feedback', None)),
    ('transcripts',      'AgentEval_Transcript_Parser',            'agentEvaluator',  False, 2 * H,
        lambda: {'LOOKBACK_DAYS': TRANSCRIPT_DAYS}, ('agent_transcripts', TRANSCRIPT_DAYS)),
    ('m365_usage',       'M365_Usage_Audit_Ingester',              'm365Usage',       False, (6 if LARGE else 2) * H, audit_args,
        ('m365_usage_audit', BACKFILL_DAYS if IS_BACKFILL else None)),
    ('azure_ai',         'Consumption_Ingest_Azure_AI',            'consumption',     False, 1 * H, dict, ('azure_ai_consumption', 90)),
    ('studio',           'Consumption_Ingest_Studio',              'consumption',     False, 30 * 60, dict, ('studio_consumption', None)),
    ('viva',             'Consumption_Ingest_Viva',                'consumption',     False, 30 * 60, dict, ('viva_consumption', None)),
    ('promote',          'Lake_Promote_Medallion',                   'copilotInteractions',            True,  1 * H, lambda: {'RUN_ID': RUN_ID}, None),
    ('models',           'Lake_Deploy_Models',                     'copilotInteractions',            False, 1 * H, models_args, None),
    ('refresh_universal','AnalyticsHub_Refresh_Model',             'copilotInteractions',            False, (5 if LARGE else 3) * H,
        lambda: model_args('universal', 'overwrite' if IS_BACKFILL else 'merge'), None),
    ('refresh_consumption', 'AnalyticsHub_Refresh_Model',          'consumption',     False, (5 if LARGE else 3) * H,
        lambda: model_args('consumption', 'merge'), None),
    ('refresh_agent_evaluator', 'AnalyticsHub_Refresh_Model',      'agentEvaluator',  False, (5 if LARGE else 3) * H,
        lambda: model_args('agentEvaluator', 'merge'), None),
    ('data_check',       'AnalyticsHub_Data_Check',                'copilotInteractions',            False, 30 * 60, dict, None),
]
NAMES = [s[0] for s in STEPS_ALL]

# The Agent365 CSV lander is the registry's fallback, as in the pipeline: it runs only if the registry fails.
FALLBACKS = {'agent365': ('agent365_lander', 'Copilot_Agent365_Lander', 15 * 60)}

# Steps that must have succeeded (in this run or, with RERUN_FAILED, earlier in RUN_ID) before a step may start.
DEPENDS = {'processor': ['audit', 'licensed_users'], 'promote': ['processor'], 'models': ['promote']}
for r in ('refresh_universal', 'refresh_consumption', 'refresh_agent_evaluator'):
    DEPENDS[r] = ['promote']

# %% [markdown]
# ## Plan

# %%
def _csv(v):
    return [x.strip() for x in v.split(',') if x.strip()]

for n in _csv(STEPS) + _csv(SKIP_STEPS) + _csv(START_FROM):
    assert n in NAMES, f'unknown step {n!r}; steps are: {NAMES}'

previous = step_status(RUN_ID) if RERUN_FAILED else {}
only, skip = set(_csv(STEPS)), set(_csv(SKIP_STEPS))
start_idx = NAMES.index(START_FROM.strip()) if START_FROM.strip() else 0

# npm run deploy leaves out the notebooks of sources set to 'skip' (or not configured, e.g. Azure AI without a
# subscription), so a step whose notebook isn't in the workspace is skipped instead of failing.
try:
    DEPLOYED = {n.displayName for n in notebookutils.notebook.list(WORKSPACE_ID, 1000)}
    if not any(s[1] in DEPLOYED for s in STEPS_ALL if s[3]):
        DEPLOYED = None  # the list looks wrong (none of the core notebooks): don't skip on it
except Exception as e:
    print(f'Could not list the workspace notebooks ({e}); running every selected step.')
    DEPLOYED = None

plan = []
for i, (name, nb, module, critical, timeout, args, led) in enumerate(STEPS_ALL):
    reason = ''
    if module not in MODULES:
        reason = f'module {module} not selected'
    elif DEPLOYED is not None and nb not in DEPLOYED:
        reason = f'{nb} is not in this workspace (its source is set to skip or not configured)'
    elif only and name not in only:
        reason = 'not in STEPS'
    elif name in skip:
        reason = 'in SKIP_STEPS'
    elif i < start_idx:
        reason = f'before START_FROM={START_FROM}'
    elif RERUN_FAILED and previous.get(name) == 'succeeded':
        reason = f'already succeeded in {RUN_ID}'
    plan.append((name, nb, module, critical, timeout, args, led, reason))

# A refresh needs its model id. The models step saves it, so a missing id only skips the refresh when that step
# is not part of this run; otherwise it is checked again just before the refresh runs.
MODEL_KEY = {'refresh_universal': 'universal', 'refresh_consumption': 'consumption',
             'refresh_agent_evaluator': 'agentEvaluator'}
models_running = any(n == 'models' and not r for (n, *_rest, r) in plan)
plan = [(n, nb, m, c, t, a, l, r or ('' if n not in MODEL_KEY or models_running or cfg(f'model_id.{MODEL_KEY[n]}', '')
                                       else f"no model_id.{MODEL_KEY[n]} in ops.config; add 'models' to STEPS"))
        for (n, nb, m, c, t, a, l, r) in plan]

# Sources set to 'csv' need their export uploaded first. A missing file doesn't stop the run: the step still runs
# and leaves its table empty, so warn now and again in the summary.
import os
CSV_CHECKS = {  # config.json name: (step, folder, what to upload)
    'productFeedback': ('product_feedback', 'product_feedback', 'the product feedback export'),
    'studioCredits':   ('studio',           'landing/studio',   'the Copilot Studio credit exports'),
    'coworkCredits':   ('viva',             'landing/viva',     'the Copilot Consumption Dashboard exports'),
    'agent365':        ('agent365',         'agent365',         'agents.csv from Agents > All agents > Export'),
}

def _files(folder):
    path = f'/lakehouse/default/Files/{folder}'
    try:
        return [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
    except FileNotFoundError:
        return []

running = {n for (n, *_rest, r) in plan if not r}
csv_sources = [s for s in _csv(cfg('csv_sources', '') or '') if s in CSV_CHECKS]
pending_uploads = _files('analytics_hub_uploads') if 'upload_router' in running else []
csv_warnings = []
for src in csv_sources:
    step, folder, what = CSV_CHECKS[src]
    if step in running and not _files(folder) and not pending_uploads:
        csv_warnings.append(f"{src} is set to 'csv' but Files/{folder} is empty. Step {step} will still run, but its "
                            f"table stays empty. Put {what} in your exports folder and run npm run deploy, then rerun with STEPS='upload_router,{step}'.")
print('Upload check: ' + ('all CSV sources have files.' if csv_sources and not csv_warnings
                         else 'no sources set to csv.' if not csv_sources else ''))
for w in csv_warnings:
    print(f'  WARNING: {w}')
if pending_uploads:
    print(f'  {len(pending_uploads)} file(s) in Files/analytics_hub_uploads; the upload router sorts them first.')
print()

now = utcnow()
def window(days):
    return (now - timedelta(days=days), now) if days else (None, None)

print(f"{'#':>2}  {'step':<24} {'notebook':<40} {'timeout':>8}  plan")
for i, (name, nb, module, critical, timeout, args, led, reason) in enumerate(plan, 1):
    what = f'SKIP ({reason})' if reason else ('RUN' + (' [critical]' if critical else ''))
    print(f'{i:>2}  {name:<24} {nb:<40} {int(timeout // 60):>6}m  {what}')
    if not reason:
        print(f'{"":>4}args: {json.dumps(args(), default=str)}')
        if led:
            src, days = led
            ws, we = window(days)
            print(f'{"":>4}history: {src} ' + (f'{ws:%Y-%m-%d} -> {we:%Y-%m-%d} ({days} days)' if days
                                                  else 'snapshot / notebook-managed incremental window'))

print('\nBackfill summary:')
if IS_BACKFILL:
    print(f'  Audit log: BACKFILL of {BACKFILL_DAYS} days ({window(BACKFILL_DAYS)[0]:%Y-%m-%d} -> today). '
          'Already-fetched windows in Files/_audit_staging are reused, so re-running resumes rather than restarts.')
    print('  Processor: OVERWRITE of copilot_interactions_curated from the full parsed table.')
    print(f'  Transcripts: last {TRANSCRIPT_DAYS} days, merged on natural keys.')
else:
    print('  Audit log: INCREMENTAL from the newest loaded event, re-reading LOOKBACK_DAYS; refuses to run over an '
          'unrecovered gap (rerun with RUN_MODE=backfill to repair).')
    print('  Processor: MERGE on Id.  Transcripts: last 14 days, merged.')

if DRY_RUN:
    print('\nDRY_RUN: nothing was run.')
    notebookutils.notebook.exit(json.dumps({'run_id': RUN_ID, 'dry_run': True}))

# %% [markdown]
# ## Run

# %%
def ok_so_far(name, results):
    """A dependency blocks only if it ran (now or earlier in RUN_ID) and did not succeed.
    A dependency you left out with STEPS / SKIP_STEPS / START_FROM is your call: it is reported, not enforced."""
    for dep in DEPENDS.get(name, []):
        st = results.get(dep, previous.get(dep))
        if st is None:
            print(f'    note: {name} depends on {dep}, which is not part of this run; using the data already in dbo')
        elif st != 'succeeded':
            return False, dep
    return True, None


def run_one(step_no, name, nb, timeout, args, led, run_mode=RUN_MODE):
    a = args() if callable(args) else (args or {})
    ws, we = window(led[1]) if led else (None, None)
    if led:
        ledger(RUN_ID, led[0], 'backfill' if (IS_BACKFILL and led[1]) else ('incremental' if led[1] else 'snapshot'),
               ws, we, led[1], 'planned', nb)
    rec = log_start(RUN_ID, name, nb, run_mode, a, step_no)
    print(f'\n=== [{step_no}] {name}: {nb}  (timeout {int(timeout // 60)} min)')
    print(f'    args: {json.dumps(a, default=str)}')
    try:
        out = notebookutils.notebook.run(nb, int(timeout), a)
        dur = log_end(rec, 'succeeded', out)
        if led:
            ledger(RUN_ID, led[0], 'backfill' if (IS_BACKFILL and led[1]) else ('incremental' if led[1] else 'snapshot'),
                   ws, we, led[1], 'done', nb)
        print(f'    succeeded in {dur / 60:.1f} min' + (f'  exit: {str(out)[:300]}' if out else ''))
        return 'succeeded', None
    except Exception as e:
        err = str(e)
        status = 'paused' if 'time budget' in err.lower() else 'failed'
        dur = log_end(rec, status, None, err)
        if led:
            note = (f'{nb}: time budget reached; rerun the same RUN_MODE to resume from staged windows'
                    if status == 'paused' else f'{nb}: {err[:500]}')
            ledger(RUN_ID, led[0], 'backfill' if (IS_BACKFILL and led[1]) else ('incremental' if led[1] else 'snapshot'),
                   ws, we, led[1], status, note)
        print(f'    {status.upper()} after {dur / 60:.1f} min: {err[:1500]}')
        return status, err


import re
import time
# What Fabric says when no Spark capacity is free right now. It clears by itself, so the step is tried again.
CAPACITY_BUSY = re.compile(
    r'HTTP 430|TooManyRequestsForCapacity|CapacityLimitExceeded|SparkJobQueue|Spark compute or API rate limit'
    r'|capacity (is )?(full|busy|throttl)|no (available )?(spark )?capacity|not enough (spark )?(capacity|cores)'
    r'|queue (is )?full', re.I)


def run_retrying(step_no, name, nb, timeout, args, led):
    """run_one, plus: resume a backfill that hit its time budget (AUTO_RESUME) and wait out a busy capacity
    (CAPACITY_RETRIES every CAPACITY_RETRY_MINUTES). Every try is its own row in ops.run_log."""
    status, err = run_one(step_no, name, nb, timeout, args, led)
    passes = tries = 0
    while True:
        if status == 'paused' and passes < int(AUTO_RESUME):
            passes += 1
            print(f'    {name} paused (time budget); resuming automatically, pass {passes} of {AUTO_RESUME}. '
                  'Finished windows are reused from staging.')
        elif status == 'failed' and err and CAPACITY_BUSY.search(err) and tries < int(CAPACITY_RETRIES):
            tries += 1
            print(f'    No Spark capacity is free right now; trying {name} again in {CAPACITY_RETRY_MINUTES} min '
                  f'(retry {tries} of {CAPACITY_RETRIES}).')
            time.sleep(float(CAPACITY_RETRY_MINUTES) * 60)
        else:
            if status == 'failed' and err and CAPACITY_BUSY.search(err):
                print(f'    Still no Spark capacity after {tries} retries. Rerun later with RERUN_FAILED = True, or raise '
                      'CAPACITY_RETRIES / CAPACITY_RETRY_MINUTES.')
            return status, err
        status, err = run_one(step_no, name, nb, timeout, args, led)

results, failures = {}, []
stopped = None
for step_no, (name, nb, module, critical, timeout, args, led, reason) in enumerate(plan, 1):
    if reason:
        continue
    if stopped:
        rec = log_start(RUN_ID, name, nb, RUN_MODE, {}, step_no)
        log_end(rec, 'skipped', None, f'not run: critical step {stopped} failed')
        results[name] = 'skipped'
        continue
    if name in MODEL_KEY and not cfg(f'model_id.{MODEL_KEY[name]}', ''):
        rec = log_start(RUN_ID, name, nb, RUN_MODE, {}, step_no)
        log_end(rec, 'skipped', None, f'no model_id.{MODEL_KEY[name]}: the models step did not create it')
        results[name] = 'skipped'
        print(f'\n=== [{step_no}] {name}: SKIPPED, model {MODEL_KEY[name]} does not exist (see the models step)')
        continue
    ok, dep = ok_so_far(name, results)
    if not ok:
        rec = log_start(RUN_ID, name, nb, RUN_MODE, {}, step_no)
        log_end(rec, 'skipped', None, f'dependency {dep} did not succeed')
        results[name] = 'skipped'
        print(f'\n=== [{step_no}] {name}: SKIPPED, dependency {dep} did not succeed')
        if critical:
            stopped = name
        continue

    status, err = run_retrying(step_no, name, nb, timeout, args, led)
    results[name] = status

    if status != 'succeeded' and name in FALLBACKS:
        fname, fnb, ftimeout = FALLBACKS[name]
        fstatus, _ = run_retrying(step_no, fname, fnb, ftimeout, dict, (led[0] + '_csv', None) if led else None)
        results[fname] = fstatus
        if fstatus == 'succeeded':
            print(f'    {name} failed but its fallback {fname} succeeded')
            continue

    if status != 'succeeded' and name in MODEL_KEY and err and ('credential' in err.lower() or 'aswl' in err.lower()):
        mid = cfg(f'model_id.{MODEL_KEY[name]}', '')
        print('    The model has no working connection to the Lakehouse. Run npm run deploy: it connects the models with the '
              'workspace identity (needs workspace Admin and a paid Fabric capacity). Or sign in once by hand: '
              f'https://app.powerbi.com/groups/{WORKSPACE_ID}/settings/datasets/{mid} > Gateway and cloud connections > Maps to '
              f"> Create a connection > OAuth 2.0 > Edit credentials > Create > Apply. Then rerun with STEPS='{name}'.")

    if status != 'succeeded':
        failures.append((name, status, err))
        if critical:
            stopped = name
            print(f'    {name} is critical: the steps that depend on it will be skipped.')
        elif not CONTINUE_ON_ERROR:
            stopped = name

# %% [markdown]
# ## Summary

# %%
show_run(RUN_ID)
ledger_summary()

summary = {'run_id': RUN_ID, 'run_mode': RUN_MODE, 'results': results,
           'failed': [f[0] for f in failures]}
print(json.dumps(summary, indent=2))
for w in csv_warnings:
    print(f'WARNING: {w}')
write_run_status('failed' if failures else 'succeeded', results=results,
                 failed=[{'step': n, 'status': st, 'error': (e or '')[:1500]} for n, st, e in failures],
                 rerun=f"RUN_MODE='{RUN_MODE}', RUN_ID='{RUN_ID}', RERUN_FAILED=True" if failures else None,
                 warnings=csv_warnings)
if failures:
    print('\nTo re-run only what did not succeed:')
    print(f"  RUN_MODE='{RUN_MODE}', RUN_ID='{RUN_ID}', RERUN_FAILED=True")
    raise RuntimeError(f"{len(failures)} step(s) did not succeed: {', '.join(f[0] + '=' + f[1] for f in failures)}")
notebookutils.notebook.exit(json.dumps(summary))

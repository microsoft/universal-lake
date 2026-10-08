# %% [markdown]
# # Orchestrator
#
# Runs the same steps, in the same order, as the installer's `CopilotAdoptionPipeline`, but one at a time from a
# notebook, so every step is visible, logged and individually re-runnable.
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
# Re-running: see `08-orchestrate/RERUNS.md`. In short: `RERUN_FAILED = True` re-runs only the steps of `RUN_ID`
# that did not succeed; `START_FROM = '<step>'` skips everything before that step.

# %% [parameters]
RUN_MODE = 'incremental'       # 'first_load', 'backfill' or 'incremental'
BACKFILL_DAYS = 0              # 0 = use backfill_days from ops.config (set by Lake_Init); max 180
SCALE = ''                     # blank = ops.config scale; 'standard' or 'large'
MODULES = ''                   # blank = ops.config modules
STEPS = ''                     # comma-separated step names to run (blank = all applicable)
SKIP_STEPS = ''                # comma-separated step names to leave out
START_FROM = ''                # skip every step before this one
RUN_ID = ''                    # blank = new run; set it with RERUN_FAILED to resume that run
RERUN_FAILED = False           # with RUN_ID: run only the steps of RUN_ID whose last status is not 'succeeded'
CONTINUE_ON_ERROR = True       # non-critical step failures are logged and the run continues
DRY_RUN = False                # print the plan and stop

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

# %% [markdown]
# ## Steps
#
# Mirrors the installer: `pipeline.js` (`RUN_PARAMETERS`, `BINDINGS`, `SCALE_PROFILES`) and the template's activity
# timeouts. Only the installer notebooks that have a **parameters cell** accept arguments; the others always run with
# the values baked into them by `npm run sync`.

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
    ('azure_ai',         'Consumption_Ingest_Azure_AI',            'consumption',     False, 1 * H, dict, ('azure_ai_consumption', 90)),
    ('studio',           'Consumption_Ingest_Studio',              'consumption',     False, 30 * 60, dict, ('studio_consumption', None)),
    ('viva',             'Consumption_Ingest_Viva',                'consumption',     False, 30 * 60, dict, ('viva_consumption', None)),
    ('promote',          'Lake_Promote_Medallion',                   'copilotInteractions',            True,  1 * H, lambda: {'RUN_ID': RUN_ID}, None),
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
DEPENDS = {'processor': ['audit', 'licensed_users'], 'promote': ['processor']}
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

plan = []
for i, (name, nb, module, critical, timeout, args, led) in enumerate(STEPS_ALL):
    reason = ''
    if module not in MODULES:
        reason = f'module {module} not selected'
    elif only and name not in only:
        reason = 'not in STEPS'
    elif name in skip:
        reason = 'in SKIP_STEPS'
    elif i < start_idx:
        reason = f'before START_FROM={START_FROM}'
    elif RERUN_FAILED and previous.get(name) == 'succeeded':
        reason = f'already succeeded in {RUN_ID}'
    plan.append((name, nb, module, critical, timeout, args, led, reason))

# A refresh needs its model id, which Lake_Deploy_Models saves.
MODEL_KEY = {'refresh_universal': 'universal', 'refresh_consumption': 'consumption',
             'refresh_agent_evaluator': 'agentEvaluator'}
plan = [(n, nb, m, c, t, a, l, r or ('' if n not in MODEL_KEY or cfg(f'model_id.{MODEL_KEY[n]}', '')
                                       else f'no model_id.{MODEL_KEY[n]} in ops.config; run Lake_Deploy_Models'))
        for (n, nb, m, c, t, a, l, r) in plan]

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
    ok, dep = ok_so_far(name, results)
    if not ok:
        rec = log_start(RUN_ID, name, nb, RUN_MODE, {}, step_no)
        log_end(rec, 'skipped', None, f'dependency {dep} did not succeed')
        results[name] = 'skipped'
        print(f'\n=== [{step_no}] {name}: SKIPPED, dependency {dep} did not succeed')
        if critical:
            stopped = name
        continue

    status, err = run_one(step_no, name, nb, timeout, args, led)
    results[name] = status

    if status != 'succeeded' and name in FALLBACKS:
        fname, fnb, ftimeout = FALLBACKS[name]
        fstatus, _ = run_one(step_no, fname, fnb, ftimeout, dict, (led[0] + '_csv', None) if led else None)
        results[fname] = fstatus
        if fstatus == 'succeeded':
            print(f'    {name} failed but its fallback {fname} succeeded')
            continue

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
if failures:
    print('\nTo re-run only what did not succeed:')
    print(f"  RUN_MODE='{RUN_MODE}', RUN_ID='{RUN_ID}', RERUN_FAILED=True")
    raise RuntimeError(f"{len(failures)} step(s) did not succeed: {', '.join(f[0] + '=' + f[1] for f in failures)}")
notebookutils.notebook.exit(json.dumps(summary))

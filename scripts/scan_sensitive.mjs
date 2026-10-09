// Fails if any file that would be committed contains tenant/client IDs, secrets, tokens or personal details.
//
//   node scripts/scan_sensitive.mjs            scan tracked + untracked (non-ignored) files
//   node scripts/scan_sensitive.mjs --staged   scan only staged files (pre-commit hook)
//   node scripts/scan_sensitive.mjs --history  also check commit author/committer emails
//
// Extra terms to block (your alias, tenant name, customer names) go one per line in .scan-blocklist,
// which is git-ignored so the terms themselves are never committed. SCAN_BLOCKLIST (comma-separated) also works.
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';

const args = process.argv.slice(2);
const git = (...a) => execFileSync('git', a, { encoding: 'utf8' });

// Public, well-known IDs that are the same in every tenant.
const ALLOWED_GUIDS = new Set([
  '00000000-0000-0000-0000-000000000000',
  '00000003-0000-0000-c000-000000000000', // Microsoft Graph (resource app ID)
  '9a18296a-025f-4e37-9ffa-30bf8d1ce775', // Microsoft 365 Copilot SKU ID (public)
  '11111111-1111-1111-1111-111111111111', // placeholder
]);
// Model-internal IDs in .bim files (lineage tags, relationship names, PBI_Id) carry no tenant data.
const BIM_ID_LINE = /^\s*"(lineageTag|name|value)"\s*:\s*"[0-9a-f-]{36}",?\s*$/i;

const RULES = [
  ['GUID (tenant, client, workspace or object ID?)', /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi,
    (m) => !ALLOWED_GUIDS.has(m.toLowerCase())],
  ['Entra client secret', /[A-Za-z0-9_.-]{3}8Q~[A-Za-z0-9_.~-]{31,40}/g],
  ['Secret assigned a literal value', /(client_?secret|password|passwd|api_?key|access_?key|secret_?value)["']?\s*[:=]\s*["'][^"'<>{}\s$]{8,}["']/gi],
  ['Storage / SAS key', /(AccountKey=[^;"'\s]{20,}|[?&]sig=[A-Za-z0-9%+/=]{20,})/g],
  ['Private key', /-----BEGIN [A-Z ]*PRIVATE KEY-----/g],
  ['JWT / bearer token', /\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}/g],
  ['GitHub token', /\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b/g],
  ['Personal Windows profile path', /\b[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}(?!<|%|\$|USERNAME\b|Public\b|you\b|me\b)[^\\/\s"'`]+/gi],
  ['Personal home path', /(?<![\w.])\/(home|Users)\/(?!<|\$|runner\b|you\b)[A-Za-z0-9._-]+/g],
  ['Email address', /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g,
    (m) => !/@(users\.noreply\.github\.com|example\.(com|org)|contoso(-[a-z]+)?\.com|fabrikam\.com)$/i.test(m)],
  ['Personal OneDrive / SharePoint link', /https?:\/\/[A-Za-z0-9-]+-my\.sharepoint(-df)?\.com\S*/gi],
  ['Tenant domain', /\b(?!contoso|fabrikam|yourtenant|<)[A-Za-z0-9-]+\.onmicrosoft\.com\b/gi],
];

const block = [
  ...(existsSync('.scan-blocklist') ? readFileSync('.scan-blocklist', 'utf8').split(/\r?\n/) : []),
  ...(process.env.SCAN_BLOCKLIST || '').split(','),
].map((s) => s.trim()).filter((s) => s && !s.startsWith('#'));
if (block.length) {
  const esc = block.map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  RULES.push(['Blocked term (.scan-blocklist)', new RegExp(esc.join('|'), 'gi')]);
}

const files = (args.includes('--staged')
  ? git('diff', '--cached', '--name-only', '--diff-filter=ACMR')
  : git('ls-files', '--cached', '--others', '--exclude-standard')
).split(/\r?\n/).filter((f) => f && existsSync(f));

const SKIP = /\.(png|jpe?g|gif|ico|svg|pdf|pptx|docx|xlsx|zip|pbit|pbix)$/i;
const findings = [];
for (const f of files) {
  if (SKIP.test(f)) continue;
  if (block.length && new RegExp(RULES.at(-1)[1].source, 'i').test(f)) findings.push(`${f}: blocked term in the file path`);
  const text = readFileSync(f, 'utf8');
  if (f.endsWith('.ipynb')) {
    try {
      const nb = JSON.parse(text);
      if ((nb.cells || []).some((c) => (c.outputs || []).length)) findings.push(`${f}: notebook has saved outputs (clear them)`);
      if (nb.metadata?.dependencies?.lakehouse) findings.push(`${f}: notebook is bound to a Lakehouse (commit unbound copies)`);
    } catch { findings.push(`${f}: not valid JSON`); }
  }
  text.split(/\r?\n/).forEach((line, i) => {
    for (const [name, re, keep = () => true] of RULES) {
      if (name.startsWith('GUID') && f.endsWith('.bim') && BIM_ID_LINE.test(line)) continue;
      for (const m of line.matchAll(new RegExp(re.source, re.flags))) {
        if (keep(m[0])) findings.push(`${f}:${i + 1}: ${name}: ${m[0].slice(0, 12)}…`);
      }
    }
  });
}

if (args.includes('--history')) {
  const people = new Set(git('log', '--all', '--format=%an <%ae>%n%cn <%ce>').split(/\r?\n/).filter(Boolean));
  for (const p of people) {
    const email = p.match(/<(.*)>/)?.[1] || '';
    if (!/@users\.noreply\.github\.com$|^noreply@github\.com$/i.test(email)) findings.push(`commit history: author/committer email is not a GitHub noreply address: ${p}`);
  }
}

if (findings.length) {
  console.error(`Sensitive-content scan FAILED (${findings.length}):\n  ` + findings.join('\n  '));
  console.error('\nRemove the values (use placeholders like <tenant-id>), or allow a public ID in ALLOWED_GUIDS.');
  process.exit(1);
}
console.log(`Sensitive-content scan passed: ${files.length} files${args.includes('--history') ? ' + commit history' : ''}.`);

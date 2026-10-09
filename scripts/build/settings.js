// @ts-check
/**
 * What the build changes in each notebook: the IDs from config.json, how the client secret is read,
 * the upload router's signatures, the load-status labels and the per-notebook text patches.
 */
import { routedSources, routerSignaturesJson } from './uploads.js';
import { INLINE_SECRET_NOTE, MARKER, pyString } from './notebook.js';

/** Stands in for the client secret when there is no value to write. */
export const SECRET_PLACEHOLDER = '<client secret>';

/** The Azure AI notebook's Key Vault read, as it ships. */
export const AZURE_AI_SECRET_FIND = 'secret = notebookutils.credentials.getSecret(KEY_VAULT_URL, CLIENT_SECRET_NAME)';

/** The transcript parser's environment list, as it ships. */
export const ENVIRONMENTS_FIND = "DATAVERSE_URLS = [\n    # 'https://org1.crm.dynamics.com',\n    # 'https://org2.crm.dynamics.com',\n]";

/** The Azure AI notebook's extra pay-as-you-go subscriptions, as it ships. */
export const PAYG_FIND = 'PAYG_SUBSCRIPTION_IDS = []';

/** @param {any} c */
export const secretMode = (c) => c.keyVault?.mode ?? 'keyvault';
/** @param {any} c */
export const modelDeployed = (c) => !!(c.semanticModel?.enabled && c.semanticModel.id && c.semanticModel.bound);
/** @param {any} c */
export const azureAiOn = (c) => !!(c.modules.consumption && c.consumption?.azureSubscriptionId && c.consumption.azureAccess);
/** @param {any} c */
export const agentEvaluatorOn = (c) => !!(c.modules.agentEvaluator && c.agentEvaluator?.environments.some((/** @type {any} */ e) => e.access));

/** Plain names for each step of a run, as the load-status notebook records them. */
export const LOAD_LABELS = /** @type {Record<string, string>} */ ({
  Run_Audit_Log_Ingester: 'Copilot audit log',
  Run_Audit_Log_Processor: 'Copilot usage (audit log processing)',
  Refresh_Semantic_Model: 'Universal Lake model refresh',
  Run_Licensed_Users_Ingester: 'Licensed users',
  Run_Upload_Router: 'Uploaded CSV exports',
  Run_Agent365_Registry_Ingester: 'Agent 365 (API)',
  Run_Agent365_CSV_Fallback: 'Agent 365 (export)',
  Run_Agent365_Lander: 'Agent 365 (export)',
  Run_Org_Data_Ingester: 'Org data (Entra ID)',
  Run_Org_Data_Workday: 'Org data (Workday export)',
  Run_M365_Activity_Ingester: 'Microsoft 365 activity',
  Run_ProductFeedback_Ingester: 'Product feedback',
  Run_Consumption_Azure_AI: 'Azure AI spend',
  Run_Consumption_Studio: 'Copilot Studio credits',
  Refresh_Cowork_Credits: 'Cowork credits (Viva Insights)',
  Run_Consumption_Viva: 'Cowork credits (load)',
  Refresh_Consumption_Model: 'Consumption model refresh',
  Run_Agent_Evaluator_Transcripts: 'Agent transcripts',
  Refresh_Agent_Evaluator_Model: 'Agent Evaluator model refresh',
  Record_Load_Status: 'Load status record',
});

/**
 * Why a step failed, tested in order against "errorCode=<code> <message>". The patterns use only
 * syntax JavaScript and Python share, matched case-insensitively.
 */
export const REASONS = [
  { kind: 'capacity', pattern: 'TooManyRequestsForCapacity|(?:code|status)[\\s:\'"=-]{0,6}430\\b', text: 'Fabric\'s capacity was too busy to start it.' },
  { kind: 'notSynced', pattern: 'is not in (?:the )?database|SQL (?:analytics )?endpoint (?:to|has not|hasn.t) (?:sync|caught up)', text: 'The model refreshed before the Lakehouse\'s SQL endpoint had caught up with the new tables.' },
  { kind: 'signIn', pattern: 'AADSTS\\d+|\\b401\\b|\\b403\\b|Unauthori[sz]ed|Forbidden|invalid_client|consent|credential|sign.?in', text: 'It couldn\'t sign in, or wasn\'t allowed to read the data.' },
  { kind: 'timeout', pattern: 'timed? ?out|timeout|exceeded the (?:maximum|allowed)', text: 'It ran out of time.' },
  { kind: 'noData', pattern: 'PATH_NOT_FOUND|Path does not exist|FileNotFound|No such file', text: 'The file it reads wasn\'t there.' },
];

/** Labels and reasons as the load-status notebook has them. */
export const statusConfigJson = () => JSON.stringify({ labels: LOAD_LABELS, reasons: REASONS });

/**
 * What the upload router accepts: the sources that aren't skipped, and their header signatures.
 * @param {any} config
 */
export const routerValues = (config) => ({
  ENABLED_SOURCES: routedSources(config.dataSources).join(','),
  SIGNATURES_JSON: routerSignaturesJson(config.dataSources),
});

/**
 * Notebook options that follow the chosen sources.
 * @param {any} config
 */
export const notebookOptions = (config) => ({
  semanticModel: modelDeployed(config),
  azureAi: azureAiOn(config),
  dataverse: agentEvaluatorOn(config),
  dataSources: config.dataSources,
});

/**
 * The other subscriptions whose Copilot pay-as-you-go the app can read.
 * @param {any} config
 * @returns {{ subscriptionId: string, name?: string, access: boolean }[]}
 */
export const paygReadable = (config) => (config.consumption?.paygSubscriptions ?? []).filter((/** @type {any} */ p) => p.access);

/**
 * @param {{ subscriptionId: string, name?: string }[]} subs
 * @returns {import('./catalog.js').NotebookPatch}
 */
export function paygPatch(subs) {
  const lines = subs.map((s) => `    ${pyString(s.subscriptionId)},${s.name ? `  # ${s.name.replace(/[\r\n]+/g, ' ')}` : ''}`);
  return { find: PAYG_FIND, replace: ['PAYG_SUBSCRIPTION_IDS = [  # ' + MARKER, ...lines, ']'].join('\n') };
}

/**
 * Lists every chosen Dataverse environment.
 * @param {{ url: string, name?: string }[]} environments
 * @returns {import('./catalog.js').NotebookPatch}
 */
export function environmentsPatch(environments) {
  const lines = environments.map((e) => `    ${pyString(e.url)},${e.name ? `  # ${e.name.replace(/[\r\n]+/g, ' ')}` : ''}`);
  return { find: ENVIRONMENTS_FIND, replace: ['DATAVERSE_URLS = [  # ' + MARKER, ...lines, ']'].join('\n') };
}

/**
 * What the build changes in one notebook.
 * @param {{ config: any, user: { tenantId: string }, pendingSecret?: string }} ctx
 * @param {import('./catalog.js').NotebookInfo} nb
 * @returns {import('./notebook.js').NotebookSettings}
 */
export function notebookSettings(ctx, nb) {
  const { config, user } = ctx;
  const f = config.fabric;
  const inline = secretMode(config) === 'notebook';
  const value = ctx.pendingSecret ?? SECRET_PLACEHOLDER;
  /** @type {Record<string, string> | undefined} */
  let values = nb.values;
  if (nb.key === 'refreshModel') values = { WORKSPACE_ID: f.workspaceId, SEMANTIC_MODEL_ID: config.semanticModel.id };
  if (nb.key === 'azureAi') {
    values = {
      SUBSCRIPTION_ID: config.consumption.azureSubscriptionId,
      TENANT_ID: user.tenantId,
      CLIENT_ID: config.app.appId,
      KEY_VAULT_URL: inline ? '' : config.keyVault.uri,
      CLIENT_SECRET_NAME: inline ? '' : config.keyVault.secretName,
    };
  }
  // Merge upserts each run's window, so environments and days accumulate without duplicates.
  if (nb.key === 'agentTranscripts') values = { SOURCE_MODE: 'dataverse', WRITE_MODE: 'merge', RAW_TABLE: '' };
  if (nb.key === 'uploadRouter') values = routerValues(config);
  if (nb.key === 'loadStatus') values = { STATUS_JSON: statusConfigJson() };
  /** @type {import('./catalog.js').NotebookPatch[]} */
  const extra = [
    ...(nb.key === 'agentTranscripts' ? [environmentsPatch(config.agentEvaluator.environments)] : []),
    ...(nb.key === 'azureAi' && paygReadable(config).length ? [paygPatch(paygReadable(config))] : []),
    ...(nb.key === 'azureAi' && inline ? [{ find: AZURE_AI_SECRET_FIND, replace: `secret = ${pyString(value)}  # ${INLINE_SECRET_NOTE}` }] : []),
  ];
  return {
    ...(nb.credentials
      ? {
          tenantId: user.tenantId,
          clientId: config.app.appId,
          secret: inline ? { value } : { vaultUri: config.keyVault.uri, secretName: config.keyVault.secretName },
        }
      : {}),
    parameters: nb.parameters,
    ...(values ? { values } : {}),
    ...(nb.expressions ? { expressions: nb.expressions } : {}),
    patches: extra.length ? [...(nb.patches ?? []), ...extra] : nb.patches,
    lakehouse: { id: f.lakehouseId, name: f.lakehouseName, workspaceId: f.workspaceId },
  };
}

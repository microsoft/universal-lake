// @ts-check
/**
 * The data sources the lake reads, how each one arrives (an API, a CSV the admin exports, or
 * not at all), and the header signatures the upload router uses to recognise an uploaded CSV.
 */

/** The one drop folder for uploaded CSV exports. */
export const UPLOAD_DIR = 'Files/analytics_hub_uploads';
export const FEEDBACK_DIR = 'Files/product_feedback';
export const AGENT365_DIR = 'Files/agent365';
export const WORKDAY_DIR = 'Files/org_workday';

/** @typedef {'api' | 'csv' | 'skip'} SourceMode */
/** @typedef {'core' | 'orgData' | 'workday' | 'm365Activity' | 'agent365' | 'productFeedback' | 'studioCredits' | 'coworkCredits' | 'azureAi' | 'agentEvaluator'} DataSourceId */
/** @typedef {Record<DataSourceId, SourceMode>} DataSourceModes */

/**
 * @typedef {object} DataSourceInfo
 * @property {DataSourceId} id
 * @property {string} label
 * @property {string} description
 * @property {SourceMode[]} modes  In order of preference: the API first when there is one.
 * @property {SourceMode} defaultMode
 * @property {boolean} [locked]  The main semantic model is built on it, so it can't be skipped.
 * @property {{ where: string, url: string, files: string }} [export]  Where the admin downloads the CSV.
 * @property {string} [page]  The report page that stays empty when it is skipped.
 */

/** @type {DataSourceInfo[]} */
export const DATA_SOURCES = [
  {
    id: 'core',
    label: 'Copilot usage and licences',
    description: 'The Microsoft 365 audit log and your Copilot licences. The main semantic model is built on it.',
    modes: ['api'],
    defaultMode: 'api',
    locked: true,
  },
  {
    id: 'orgData',
    label: 'Org data (Microsoft Entra ID)',
    description: 'Department, job title, manager and location for each person.',
    modes: ['api'],
    defaultMode: 'api',
    locked: true,
  },
  {
    id: 'workday',
    label: 'Workday org data',
    description: 'Adds or overrides org fields from a Workday report, matched on Primary Work Email.',
    modes: ['csv', 'skip'],
    defaultMode: 'skip',
    export: {
      where: 'Workday: run a report of active workers that includes Primary Work Email and the fields you want (cost centre, level, location), then export it to CSV.',
      url: 'https://doc.workday.com/',
      files: 'One CSV. Each upload replaces the last.',
    },
  },
  {
    id: 'm365Activity',
    label: 'Microsoft 365 activity',
    description: 'Teams, Outlook, SharePoint, OneDrive, Viva Engage and Office app usage reports.',
    modes: ['api', 'skip'],
    defaultMode: 'api',
    page: 'M365 activity',
  },
  {
    id: 'agent365',
    label: 'Agent 365 registry',
    description: 'The agents in your tenant and who made them. The API needs an Agent 365 licence; the export doesn\'t.',
    modes: ['api', 'csv', 'skip'],
    defaultMode: 'skip',
    page: 'Agents',
    export: {
      where: 'Microsoft 365 admin center > Agents > All agents > Export.',
      url: 'https://admin.microsoft.com/',
      files: 'One CSV. Each upload replaces the last.',
    },
  },
  {
    id: 'productFeedback',
    label: 'Product feedback',
    description: 'What people say about Copilot. There is no API for it.',
    modes: ['csv', 'skip'],
    defaultMode: 'skip',
    page: 'User Feedback',
    export: {
      where: 'Microsoft 365 admin center > Health > Product feedback > Export.',
      url: 'https://admin.microsoft.com/',
      files: 'One CSV per export. Uploads add up; duplicates are removed by Feedback Id.',
    },
  },
  {
    id: 'studioCredits',
    label: 'Copilot Studio credits',
    description: 'Copilot Studio credits by environment, agent and user. A Power Automate flow can keep the environment and agent figures up to date.',
    modes: ['csv', 'skip'],
    defaultMode: 'skip',
    page: 'Consumption Central',
    export: {
      where: 'Power Platform admin center > Licensing > Products > Copilot Studio. Download the Summary, Environments and Agents exports (EntitlementConsumption*_MCSMessages*.csv).',
      url: 'https://admin.powerplatform.microsoft.com/',
      files: 'Up to three CSVs a month. A new file replaces the last one of the same kind.',
    },
  },
  {
    id: 'coworkCredits',
    label: 'Copilot Cowork credits',
    description: 'Cowork credits by person, from Viva Insights.',
    modes: ['api', 'csv', 'skip'],
    defaultMode: 'skip',
    page: 'Consumption Central',
    export: {
      where: 'Viva Insights > Copilot Consumption Dashboard > Export (PersonServiceCreditsMetrics and SpendingPolicyMetadata CSVs).',
      url: 'https://learn.microsoft.com/viva/insights/advanced/analyst/export-query-data-microsoft-fabric',
      files: 'Credits add up and are de-duplicated; a new policy file replaces the last.',
    },
  },
  {
    id: 'azureAi',
    label: 'Azure AI costs',
    description: 'Azure OpenAI and AI Foundry costs, and Copilot pay-as-you-go billed to Azure.',
    modes: ['api', 'skip'],
    defaultMode: 'skip',
    page: 'Consumption Central',
  },
  {
    id: 'agentEvaluator',
    label: 'Agent Evaluator',
    description: 'Copilot Studio conversation transcripts from Dataverse: how conversations end and where agents fall short.',
    modes: ['api', 'skip'],
    defaultMode: 'skip',
    page: 'Agent Evaluator',
  },
];

export const DATA_SOURCE_IDS = /** @type {DataSourceId[]} */ (DATA_SOURCES.map((s) => s.id));
/**
 * How a recognised file is stored for its ingester.
 *  - append: kept alongside earlier uploads (the ingester unions and de-duplicates them)
 *  - replace: overwrites the one file the ingester reads
 *  - replaceKind: earlier files of the same kind are moved to `_loaded/` first
 * @typedef {'append' | 'replace' | 'replaceKind'} UploadPolicy
 */

/**
 * @typedef {object} UploadKind
 * @property {string} kind
 * @property {DataSourceId} source
 * @property {string[][]} groups  Each group is a set of normalised header names; one from every group must be present.
 * @property {string} dir  Where the router puts it.
 * @property {string} name  File name. `{stamp}` becomes the upload time.
 * @property {UploadPolicy} policy
 */

/** @type {UploadKind[]} */
export const UPLOAD_KINDS = [
  {
    kind: 'productFeedback',
    source: 'productFeedback',
    groups: [['feedbackid'], ['datesubmittedutc'], ['feedbacktype']],
    dir: FEEDBACK_DIR,
    name: 'feedback_{stamp}.csv',
    policy: 'append',
  },
  {
    kind: 'agent365',
    source: 'agent365',
    groups: [
      ['agentname', 'name', 'displayname'],
      ['titleid', 'packageid', 'agentcreatorid', 'creatorid', 'agenttypea365', 'publishertype', 'supportedin', 'availability'],
    ],
    dir: AGENT365_DIR,
    name: 'agents.csv',
    policy: 'replace',
  },
  {
    kind: 'studioTenant',
    source: 'studioCredits',
    groups: [['billingplanid'], ['environmentid'], ['capacitytype'], ['prepaidconsumedquantity'], ['usagedate']],
    dir: 'Files/landing/studio',
    name: 'EntitlementConsumptionTenantDetailsReport_MCSMessages_{stamp}.csv',
    policy: 'replaceKind',
  },
  {
    kind: 'studioAgent',
    source: 'studioCredits',
    groups: [['agentid'], ['agentname'], ['billedcredit'], ['nonbilledcredit'], ['channel']],
    dir: 'Files/landing/studio',
    name: 'EntitlementConsumptionTenantPerAgentDetailsReport_MCSMessages_{stamp}.csv',
    policy: 'replaceKind',
  },
  {
    kind: 'studioUser',
    source: 'studioCredits',
    groups: [['userid'], ['useremail'], ['creditsused'], ['billablecreditused']],
    dir: 'Files/landing/studio',
    name: 'EntitlementConsumptionTenantPerUserDetailsReport_MCSMessages_{stamp}.csv',
    policy: 'replaceKind',
  },
  // Written each day by a Copilot Studio credits flow from the licensing API. Each
  // file restates the last ten days, so only the newest is kept; the notebook merges by day.
  {
    kind: 'studioAgentDaily',
    source: 'studioCredits',
    groups: [['usagedate'], ['agentid'], ['agentname'], ['billedcredit'], ['nonbilledcredit'], ['channel']],
    dir: 'Files/landing/studio',
    name: 'StudioApiAgentDaily_{stamp}.csv',
    policy: 'replaceKind',
  },
  {
    kind: 'studioEntitlement',
    source: 'studioCredits',
    groups: [['snapshotdate'], ['environmentid'], ['environmentallocated'], ['tenantprepaidconsumed'], ['tenantpaygconsumed']],
    dir: 'Files/landing/studio',
    name: 'StudioApiEntitlement_{stamp}.csv',
    policy: 'replaceKind',
  },
  {
    kind: 'vivaCredits',
    source: 'coworkCredits',
    groups: [['serviceid'], ['servicename'], ['spendingpolicyid'], ['metricdate'], ['totalcopilotcreditsused']],
    dir: 'Files/landing/viva',
    name: 'PersonServiceCreditsMetrics_{stamp}.csv',
    policy: 'append',
  },
  {
    kind: 'vivaPolicy',
    source: 'coworkCredits',
    groups: [['spendingpolicyid'], ['name'], ['planlimit'], ['userlimit'], ['includedservices']],
    dir: 'Files/landing/viva',
    name: 'SpendingPolicyMetadata_{stamp}.csv',
    policy: 'replaceKind',
  },
  {
    kind: 'workday',
    source: 'workday',
    groups: [['primaryworkemail']],
    dir: WORKDAY_DIR,
    name: 'workday.csv',
    policy: 'replace',
  },
];

/** Sources a CSV can be uploaded for. */
export const UPLOADABLE_SOURCES = /** @type {DataSourceId[]} */ ([...new Set(UPLOAD_KINDS.map((k) => k.source))]);

/**
 * Header name as the router compares it: lower case, letters and digits only.
 * @param {string} name
 */
export const normHeader = (name) => String(name).replace(/^\uFEFF/, '').toLowerCase().replace(/[^a-z0-9]/g, '');

/** @returns {DataSourceModes} */
export function defaultDataSources() {
  return /** @type {DataSourceModes} */ (Object.fromEntries(DATA_SOURCES.map((s) => [s.id, s.defaultMode])));
}

/**
 * Fills the gaps in config.json's dataSources. With none at all, the modules decide.
 * @param {Partial<Record<string, string>> | undefined} saved
 * @param {import('./catalog.js').ModuleChoice} modules
 * @param {{ azureSubscriptionId?: string }} [consumption]
 * @returns {DataSourceModes}
 */
export function normaliseDataSources(saved, modules, consumption = {}) {
  /** @type {Partial<DataSourceModes>} */
  const legacy = saved
    ? {}
    : {
        m365Activity: modules.m365Activity ? 'api' : 'skip',
        agent365: modules.agent365 ? 'api' : 'skip',
        productFeedback: modules.productFeedback ? 'csv' : 'skip',
        studioCredits: modules.consumption ? 'csv' : 'skip',
        coworkCredits: modules.consumption ? 'csv' : 'skip',
        azureAi: modules.consumption && consumption.azureSubscriptionId ? 'api' : 'skip',
        agentEvaluator: modules.agentEvaluator ? 'api' : 'skip',
      };
  const out = { ...defaultDataSources(), ...legacy };
  for (const s of DATA_SOURCES) {
    const v = /** @type {SourceMode | undefined} */ (saved?.[s.id]);
    if (v && s.modes.includes(v)) out[s.id] = v;
    if (s.locked) out[s.id] = s.modes[0];
  }
  return out;
}

/**
 * The modules the chosen sources switch on.
 * @param {DataSourceModes} ds
 * @returns {import('./catalog.js').ModuleChoice}
 */
export function modulesFromSources(ds) {
  const on = (/** @type {DataSourceId} */ id) => ds[id] !== 'skip';
  return {
    orgData: true,
    m365Activity: on('m365Activity'),
    agent365: on('agent365'),
    productFeedback: on('productFeedback'),
    consumption: on('studioCredits') || on('coworkCredits') || on('azureAi'),
    agentEvaluator: on('agentEvaluator'),
  };
}

/**
 * Sources the router accepts a CSV for: uploadable and not skipped. Agent 365 on the API still
 * accepts its export, which the CSV fallback reads when the registry can't be reached.
 * @param {DataSourceModes} ds
 * @returns {DataSourceId[]}
 */
export const routedSources = (ds) => UPLOADABLE_SOURCES.filter((id) => ds[id] !== 'skip');

/** The router is deployed when any source arrives as a CSV. */
export const routerWanted = (/** @type {DataSourceModes} */ ds) => routedSources(ds).length > 0;

/**
 * The signatures the router notebook reads, as one line of JSON.
 * @param {DataSourceModes} [ds]  When given, only the kinds of routed sources.
 */
export function routerSignaturesJson(ds) {
  const on = ds ? new Set(routedSources(ds)) : undefined;
  return JSON.stringify(
    UPLOAD_KINDS.filter((k) => !on || on.has(k.source)).map((k) => ({ kind: k.kind, source: k.source, groups: k.groups, dir: k.dir, name: k.name, policy: k.policy })),
  );
}

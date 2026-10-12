// @ts-check
/**
 * The notebooks this repo builds, the modules that switch them on,
 * and the Graph application permissions each module needs.
 */
import { routerWanted } from './uploads.js';

/** @typedef {'core' | 'orgData' | 'm365Activity' | 'agent365' | 'productFeedback' | 'consumption' | 'agentEvaluator' | 'm365Usage'} ModuleId */

/**
 * @typedef {object} ModuleInfo
 * @property {ModuleId} id
 * @property {string} label
 * @property {string} description
 * @property {boolean} required
 * @property {boolean} defaultOn
 * @property {string[]} permissions  Graph application permissions (by value).
 */

/** @type {Record<ModuleId, ModuleInfo>} */
export const MODULES = {
  core: {
    id: 'core',
    label: 'Copilot usage and licences',
    description: 'From the Microsoft 365 audit log and your Copilot licences. Shows who uses Copilot, in which apps and how often.',
    required: true,
    defaultOn: true,
    permissions: ['AuditLogsQuery.Read.All', 'Reports.Read.All'],
  },
  orgData: {
    id: 'orgData',
    label: 'Org data',
    description: 'From Microsoft Entra ID. Adds each person\'s department, job title, manager and location, so you can compare teams.',
    required: true,
    defaultOn: true,
    permissions: ['User.Read.All'],
  },
  m365Activity: {
    id: 'm365Activity',
    label: 'Microsoft 365 activity',
    description: 'From the Microsoft 365 usage reports. Shows how people work across Teams, Outlook, SharePoint, OneDrive, Viva Engage and the Office apps.',
    required: false,
    defaultOn: true,
    permissions: ['Reports.Read.All'],
  },
  agent365: {
    id: 'agent365',
    label: 'Agent 365 registry',
    description: 'From the Agent 365 registry, or its CSV export from the Microsoft 365 admin center. Lists the agents in your tenant and who made them. The registry needs an Agent 365 licence.',
    required: false,
    defaultOn: false,
    permissions: ['CopilotPackages.Read.All', 'Application.Read.All', 'User.Read.All'],
  },
  productFeedback: {
    id: 'productFeedback',
    label: 'Product feedback',
    description: 'From the product feedback export in the Microsoft 365 admin center, which you put in the Lakehouse. Shows what people say about Copilot.',
    required: false,
    defaultOn: false,
    permissions: [],
  },
  consumption: {
    id: 'consumption',
    label: 'Credit consumption',
    description: 'From Copilot Studio and Copilot Cowork credit exports you put in the Lakehouse, and your Azure costs. Shows credits used and what they cost across Copilot Studio, Cowork and Azure AI.',
    required: false,
    defaultOn: false,
    permissions: [],
  },
  agentEvaluator: {
    id: 'agentEvaluator',
    label: 'Agent Evaluator',
    description: 'From Copilot Studio conversation transcripts in Dataverse. Shows how well your agents work: how conversations end, what people thought and where agents fall short.',
    required: false,
    defaultOn: false,
    permissions: [],
  },
  m365Usage: {
    id: 'm365Usage',
    label: 'Microsoft 365 usage (audit)',
    description: 'From the Microsoft 365 audit log: Teams, Outlook, Word, Excel and PowerPoint activity, including mail items accessed, plus Copilot sessions. Produces the five inputs of the M365 Usage Analytics Power BI template.',
    required: false,
    defaultOn: false,
    permissions: ['AuditLogsQuery.Read.All', 'User.Read.All'],
  },
};

/** Modules that change the main semantic model. The others have their own model or none. */
export const MODEL_MODULES = /** @type {const} */ (['core', 'orgData', 'm365Activity', 'agent365', 'productFeedback']);

/** Always collected: the main semantic model is built on them. */
export const ESSENTIAL_MODULES = /** @type {const} */ (['core', 'orgData']);

/** Modules that can be switched on, in order. */
export const OPTIONAL_MODULES = /** @type {const} */ (['m365Activity', 'agent365', 'productFeedback', 'consumption', 'agentEvaluator', 'm365Usage']);

/** @typedef {'auditIngester' | 'licensedUsers' | 'processor' | 'dataCheck' | 'orgData' | 'm365Activity' | 'agent365Registry' | 'agent365Lander' | 'productFeedback' | 'refreshModel' | 'azureAi' | 'studioConsumption' | 'vivaConsumption' | 'agentTranscripts' | 'uploadRouter' | 'workdayLander' | 'loadStatus' | 'm365UsageIngester' | 'm365UsageGold'} NotebookKey */

/**
 * A text change the build makes to its copy of a notebook. `find` must occur exactly once.
 * @typedef {{ find: string, replace: string }} NotebookPatch
 */

/**
 * @typedef {object} NotebookInfo
 * @property {NotebookKey} key
 * @property {string} file  File name in `dir`.
 * @property {string} [dir]  Folder under `notebooks/`. Defaults to {@link NOTEBOOKS_DIR}.
 * @property {string} displayName  Item name in the Fabric workspace.
 * @property {ModuleId} module
 * @property {boolean} credentials  Has TENANT_ID / CLIENT_ID / CLIENT_SECRET to fill in.
 * @property {string[]} parameters  Assignments the orchestrator passes; the cell holding them is tagged `parameters`.
 * @property {boolean} [semanticModel]  Only deployed with the semantic model.
 * @property {boolean} [azure]  Only deployed when an Azure subscription is chosen for Azure AI.
 * @property {boolean} [dataverse]  Only deployed when at least one Dataverse environment is chosen.
 * @property {boolean} [uploads]  Only deployed when a source arrives as an uploaded CSV.
 * @property {boolean} [workday]  Only deployed when Workday org data is uploaded.
 * @property {boolean} [registry]  Left out when Agent 365 comes from its CSV export instead of the API.
 * @property {Record<string, string>} [values]  String settings the built copy always has.
 * @property {Record<string, string>} [expressions]  Python expressions the built copy always has, e.g. `True`.
 * @property {NotebookPatch[]} [patches]
 */

/** Notebook folders, relative to `notebooks/`. */
export const NOTEBOOKS_DIR = '.';
export const CONSUMPTION_NOTEBOOKS_DIR = 'credit-consumption';
export const AGENT_EVALUATOR_NOTEBOOKS_DIR = 'agent-evaluator';
export const WORKDAY_NOTEBOOKS_DIR = 'workday-org-data';
export const STUDIO_LANDING = 'Files/landing/studio';
export const VIVA_LANDING = 'Files/landing/viva';

/** @type {NotebookInfo[]} */
export const NOTEBOOKS = [
  {
    key: 'auditIngester',
    file: 'Copilot_Audit_Log_Direct_Ingester.ipynb',
    displayName: 'Copilot_Audit_Log_Direct_Ingester',
    module: 'core',
    credentials: true,
    parameters: ['MODE', 'BACKFILL_DAYS'],
  },
  {
    key: 'licensedUsers',
    file: 'Copilot_Licensed_Users_Direct_Ingester.ipynb',
    displayName: 'Copilot_Licensed_Users_Direct_Ingester',
    module: 'core',
    credentials: true,
    parameters: [],
  },
  {
    key: 'processor',
    file: 'Copilot_Audit_Log_Processor.ipynb',
    displayName: 'Copilot_Audit_Log_Processor',
    module: 'core',
    credentials: false,
    parameters: ['WRITE_MODE'],
  },
  {
    key: 'dataCheck',
    file: 'AnalyticsHub_Data_Check.ipynb',
    displayName: 'AnalyticsHub_Data_Check',
    module: 'core',
    credentials: false,
    parameters: [],
  },
  {
    key: 'orgData',
    file: 'Copilot_Org_Data_Direct_Ingester.ipynb',
    displayName: 'Copilot_Org_Data_Direct_Ingester',
    module: 'orgData',
    credentials: true,
    parameters: [],
  },
  {
    key: 'workdayLander',
    file: 'Copilot_Org_Data_Workday_Lander.ipynb',
    dir: WORKDAY_NOTEBOOKS_DIR,
    displayName: 'Copilot_Org_Data_Workday_Lander',
    module: 'orgData',
    credentials: false,
    parameters: [],
    workday: true,
    // Runs after the Graph org data load each time, so it enriches the published table itself.
    values: { OUTPUT_TABLE: 'dbo.copilot_org_data' },
    expressions: { ALLOW_BASE_OVERWRITE: 'True' },
  },
  {
    key: 'uploadRouter',
    file: 'AnalyticsHub_Upload_Router.ipynb',
    displayName: 'AnalyticsHub_Upload_Router',
    module: 'core',
    credentials: false,
    parameters: [],
    uploads: true,
  },
  {
    key: 'loadStatus',
    file: 'AnalyticsHub_Load_Status.ipynb',
    displayName: 'AnalyticsHub_Load_Status',
    module: 'core',
    credentials: false,
    parameters: ['PIPELINE_RUN_ID', 'PIPELINE_TRIGGER_TIME'],
  },
  {
    key: 'm365Activity',
    file: 'Copilot_M365_Activity_Ingester.ipynb',
    displayName: 'Copilot_M365_Activity_Ingester',
    module: 'm365Activity',
    credentials: true,
    parameters: [],
  },
  {
    key: 'agent365Registry',
    file: 'Copilot_Agent365_Registry_Ingester.ipynb',
    displayName: 'Copilot_Agent365_Registry_Ingester',
    module: 'agent365',
    credentials: true,
    parameters: [],
    registry: true,
  },
  {
    key: 'agent365Lander',
    file: 'Copilot_Agent365_Lander.ipynb',
    displayName: 'Copilot_Agent365_Lander',
    module: 'agent365',
    credentials: false,
    parameters: [],
    // Without an export, an empty table keeps the Agents page dormant instead of failing the model.
    patches: [
      {
        find: '          f"Preserving any existing {OUTPUT_TABLE} snapshot.")\n',
        replace: `          f"Preserving any existing {OUTPUT_TABLE} snapshot.")
    if not _table_exists(OUTPUT_TABLE):  # Set by the Universal Lake build: an empty table, not a missing one
        from pyspark.sql.types import StructField, StructType, StringType, TimestampType
        _empty_cols, _ = _build_alias_plan()
        (spark.createDataFrame([], StructType([StructField(c, StringType(), True) for c in _empty_cols]
                                              + [StructField('Snapshot As Of', TimestampType(), True)]))
            .write.mode('overwrite')
            .option('delta.columnMapping.mode', 'name')
            .option('delta.minReaderVersion', '2')
            .option('delta.minWriterVersion', '5')
            .format('delta').saveAsTable(OUTPUT_TABLE))
        print(f"Created an empty {OUTPUT_TABLE}; it fills on the first run after an export is uploaded.")
`,
      },
    ],
  },
  {
    key: 'productFeedback',
    file: 'Copilot_ProductFeedback_Ingester.ipynb',
    displayName: 'Copilot_ProductFeedback_Ingester',
    module: 'productFeedback',
    credentials: false,
    parameters: [],
    // Until the first export is uploaded, an empty table keeps the User Feedback page dormant.
    expressions: { ALLOW_EMPTY_FIRST_SNAPSHOT: 'True' },
  },
  {
    key: 'refreshModel',
    file: 'AnalyticsHub_Refresh_Model.ipynb',
    displayName: 'AnalyticsHub_Refresh_Model',
    module: 'core',
    credentials: false,
    parameters: ['WORKSPACE_ID', 'SEMANTIC_MODEL_ID', 'WRITE_MODE'],
    semanticModel: true,
  },
  {
    key: 'azureAi',
    file: 'Ingest_Azure_AI.ipynb',
    dir: CONSUMPTION_NOTEBOOKS_DIR,
    displayName: 'Consumption_Ingest_Azure_AI',
    module: 'consumption',
    credentials: false,
    parameters: [],
    azure: true,
  },
  {
    key: 'studioConsumption',
    file: 'Ingest_Studio.ipynb',
    dir: CONSUMPTION_NOTEBOOKS_DIR,
    displayName: 'Consumption_Ingest_Studio',
    module: 'consumption',
    credentials: false,
    parameters: [],
  },
  {
    key: 'vivaConsumption',
    file: 'Ingest_Viva_Consumption.ipynb',
    dir: CONSUMPTION_NOTEBOOKS_DIR,
    displayName: 'Consumption_Ingest_Viva',
    module: 'consumption',
    credentials: false,
    parameters: [],
  },
  {
    key: 'agentTranscripts',
    file: 'Copilot_Agent_Transcript_Parser.ipynb',
    dir: AGENT_EVALUATOR_NOTEBOOKS_DIR,
    displayName: 'AgentEval_Transcript_Parser',
    module: 'agentEvaluator',
    credentials: true,
    parameters: ['LOOKBACK_DAYS'],
    dataverse: true,
  },
  {
    key: 'm365UsageIngester',
    file: 'M365_Usage_Audit_Ingester.ipynb',
    displayName: 'M365_Usage_Audit_Ingester',
    module: 'm365Usage',
    credentials: true,
    parameters: ['MODE', 'BACKFILL_DAYS'],
  },
  {
    key: 'm365UsageGold',
    file: 'M365_Usage_Gold.ipynb',
    displayName: 'M365_Usage_Gold',
    module: 'm365Usage',
    credentials: true,
    parameters: [],
  },
];

/** @typedef {{ orgData: boolean, m365Activity: boolean, agent365: boolean, productFeedback: boolean, consumption: boolean, agentEvaluator: boolean, m365Usage: boolean }} ModuleChoice */

/** @returns {ModuleChoice} */
export function defaultModules() {
  return {
    orgData: MODULES.orgData.defaultOn,
    m365Activity: MODULES.m365Activity.defaultOn,
    agent365: MODULES.agent365.defaultOn,
    productFeedback: MODULES.productFeedback.defaultOn,
    consumption: MODULES.consumption.defaultOn,
    agentEvaluator: MODULES.agentEvaluator.defaultOn,
    m365Usage: MODULES.m365Usage.defaultOn,
  };
}

/**
 * Org data is always on, even in records saved when it could be switched off.
 * @param {Partial<ModuleChoice> | undefined} choice
 * @returns {ModuleChoice}
 */
export function normaliseModules(choice) {
  return { ...defaultModules(), ...(choice ?? {}), orgData: true };
}

/**
 * @param {ModuleChoice} modules
 * @returns {ModuleId[]}
 */
export function enabledModules(modules) {
  /** @type {ModuleId[]} */
  const out = ['core'];
  if (modules.orgData) out.push('orgData');
  if (modules.m365Activity) out.push('m365Activity');
  if (modules.agent365) out.push('agent365');
  if (modules.productFeedback) out.push('productFeedback');
  if (modules.consumption) out.push('consumption');
  if (modules.agentEvaluator) out.push('agentEvaluator');
  if (modules.m365Usage) out.push('m365Usage');
  return out;
}

/**
 * Notebooks to deploy for the chosen modules, in deployment order.
 * @param {ModuleChoice} modules
 * @param {{ semanticModel?: boolean, azureAi?: boolean, dataverse?: boolean, dataSources?: import('./uploads.js').DataSourceModes }} [opts]
 * @returns {NotebookInfo[]}
 */
export function notebooksFor(modules, opts = {}) {
  const on = new Set(enabledModules(modules));
  const ds = opts.dataSources;
  return NOTEBOOKS.filter(
    (nb) =>
      on.has(nb.module) &&
      (!nb.semanticModel || opts.semanticModel) &&
      (!nb.azure || opts.azureAi) &&
      (!nb.dataverse || opts.dataverse) &&
      (!nb.uploads || (!!ds && routerWanted(ds))) &&
      (!nb.workday || ds?.workday === 'csv') &&
      (!nb.registry || ds?.agent365 !== 'csv'),
  );
}

/**
 * Graph application permissions the app registration needs, de-duplicated and sorted.
 * Org data's User.Read.All is always included, because org data is always collected.
 * Agent 365 from its CSV export needs none of the registry's permissions.
 * @param {ModuleChoice} modules
 * @param {import('./uploads.js').DataSourceModes} [dataSources]
 * @returns {string[]}
 */
export function permissionsFor(modules, dataSources) {
  const set = new Set([...MODULES.core.permissions, ...MODULES.orgData.permissions]);
  for (const id of enabledModules(modules)) {
    if (id === 'agent365' && dataSources?.agent365 === 'csv') continue;
    for (const p of MODULES[id].permissions) set.add(p);
  }
  return [...set].sort();
}

# Troubleshooting

The fixes for things that can go wrong while setting up. For failed daily runs, see [07-orchestrate/RERUNS.md](07-orchestrate/RERUNS.md).

## Deploy can't sign in or is refused

`npm run deploy` signs in as **you** through the Azure CLI's public sign-in app (no app registration of yours is used for this).

| You see | Fix |
|---|---|
| No browser opens, or you're on a remote PC | `npm run deploy -- --device-code` and enter the code it prints at the link it gives. |
| Sign-in says the app is blocked or needs admin approval | Your tenant blocks the Azure CLI app. Ask an admin to allow it, or set up by hand ([below](#setting-up-by-hand)). |
| `401` or `403` from Fabric | You need **Contributor** or above on the workspace, and the workspace needs a Fabric capacity or trial ([step 1](01-fabric/README.md#12-create-the-workspace)). If you have it, a Fabric admin may have turned off *Users can create Fabric items* or API access for you in the tenant settings. |
| *No workspace named ...* | Check `workspace.name` (it must match exactly) and that you can see the workspace in the Fabric portal. |
| *More than one workspace is named ...* | Set `workspace.id` (the GUID after `/groups/` in the workspace URL). |
| *The Lakehouse SQL analytics endpoint is still being created* | Wait a minute, run deploy again. |
| *Could not update config.json automatically* | Paste the three values it prints into `config.json`, deploy again. |

## Lake_Setup checks

`Lake_Setup` runs at the end of every deploy. It sets up the Lakehouse, then checks the app. You can also open it in Fabric and **Run all**: it changes nothing that already exists. Each line it prints starts with `PASS`, `FAIL` or `WARN`.

| Check | If it fails |
|---|---|
| *This Lakehouse is not schema-enabled* | It was created without schemas, which can't be turned on later. Set a new `lakehouse.name`, clear `lakehouse.id` and `lakehouse.sqlEndpoint`, deploy again. |
| Key Vault secret readable | Give yourself *Key Vault Secrets User* on the vault. With the `config.json` bypass this is a **warning**, which is expected. |
| Graph token | Wrong `tenantId` or `appId`, or the secret expired or was mistyped. |
| Graph permissions for `<module>` | Add the permission and grant admin consent ([2.1](02-permissions/README.md#21-register-the-app-and-add-permissions)). Wait a few minutes, deploy again. |
| Audit log query API | Check Microsoft Purview > **Audit** is recording, and that `AuditLogsQuery.Read.All` is consented. |
| Usage reports show real user names | Turn off concealed names ([2.3](02-permissions/README.md#23-give-the-app-access)). |
| Copilot packages API (Agent 365) | No Agent 365 in the tenant: set `dataSources.agent365` to `csv` and add its export. |
| Azure subscription / cost query | Give the app the three reader roles on the subscription ([2.4](02-permissions/README.md#24-azure-ai-access-only-if-azureai-is-api)). |
| Dataverse / transcripts | Add the app as an application user with Bot Transcript Viewer ([2.3](02-permissions/README.md#23-give-the-app-access)). |

New consent or roles can take about 10 minutes to reach tokens. Deploy again after fixing; it skips what's already done.

## Notebooks with the same names

The notebooks call each other by name, so each name can exist only once in the workspace. Deploy stops if the workspace has notebooks with the same names that it didn't create.

| The existing notebooks are | Do this |
|---|---|
| **From an earlier run of this guide** (for example you imported them by hand) | `npm run deploy -- --overwrite`. Your data is safe: it lives in the Lakehouse, not in the notebooks. Delete any `... 1` copies too. |
| **From another solution** (for example a Copilot analytics app that uses the same notebook names) | **Don't overwrite them**: that solution would stop working. Use a new, empty workspace: change `workspace.name`, clear `workspace.id`, `lakehouse.id` and `lakehouse.sqlEndpoint`, deploy. |
| **Unsure** | Open one and check **Explorer > Lakehouses**. If it's attached to a different Lakehouse, treat it as another solution. |

`Lake_Init` and `Lake_Validate_Credentials`, from older versions of this guide, are no longer used: `Lake_Setup` replaces both. You can delete them.

## CSV files

| You see | Fix |
|---|---|
| Deploy says *skip ... (not a known export: ignored)* | The headers don't match any source. Check it's the right export, not renamed or re-saved in Excel with other columns. |
| Deploy says *skip ... (matches ...: rename columns or remove it)* | The headers fit more than one source. Use the unmodified export, or upload it by hand to `Files/analytics_hub_uploads` ([below](#setting-up-by-hand)). |
| *WARNING: dataSources.x is "csv" but no file for it was found* | Add the export to your exports folder and deploy again, or set the source to `skip`. |
| Orchestrator *WARNING* that a CSV folder is empty | Same: add the file, `npm run deploy`, then rerun with `STEPS = 'upload_router,<step>'`. |
| Two exports in different subfolders have the same file name | They're uploaded under that name, so one replaces the other. Give each a different file name. |

## Promote messages

| Message | Fix |
|---|---|
| `gold_tables.json not found` | Run `npm run deploy`; it uploads `out/models`. |
| `Required but not in gold: copilot_interactions_curated` | Run `audit`, `licensed_users` and `processor` first. |
| `WARNING: silver.x also exists` | A table changed layer. Rerun promote with `DROP_STALE = True`. |
| Table `unchanged` but you expected new rows | Its ingester didn't write; check `ops.run_log`. |

To run promote alone, open `Lake_Promote_Medallion`:

| Parameter | Use |
|---|---|
| `TABLES` | Only these tables, e.g. `'copilot_org_data,user_feedback'` |
| `SKIP_UNCHANGED = False` | Force a full copy |
| `DRY_RUN = True` | Show the layer for each table, change nothing |
| `LAYER_OVERRIDES_JSON` | Move a table, e.g. `{"agents_365_history": "gold"}` |
| `DROP_STALE = True` | Drop the old copy after a table changes layer |

To reclassify agents: add rows to `dbo.agent_type_overrides`, then run the orchestrator with `RUN_MODE = 'backfill'` and `STEPS = 'processor,promote'`. No re-fetch needed.

## Model refresh messages

| Message | Fix |
|---|---|
| `Premium_ASWL_Error` / *default data connection without explicit connection credentials* | The model isn't bound to a connection. Rerun the orchestrator with `STEPS='models,refresh_universal'` (or `Lake_Deploy_Models` with `DEPLOY = False`); it binds the model to a connection signed in as the app. If it reports the tenant setting, see [step 6](06-models/README.md#62-the-semantic-models). |
| *Could not connect the model as the app* | Turn on *Service principals can call Fabric public APIs* for the app (Admin portal > Tenant settings > Developer settings), check you're Admin or Member of the workspace and that the secret is current. |
| *Sign in once* | You're in `signin` mode. Sign in on the model's settings page as the message says, or switch to `spn` for unattended refreshes. |

## npm is blocked

`npm` is only a shortcut; nothing is downloaded. Run `node scripts/deploy.mjs` instead of `npm run deploy` (with the same options, without the `--`). On a Microsoft-managed PC you can also point npm at the internal feed once: `npm config set registry https://packagefeedproxy.microsoft.io/npm`.

## Setting up by hand

If deploy can't be used at all (for example your tenant blocks the sign-in), you can do what it does in the Fabric portal:

1. Create a Lakehouse **with _Lakehouse schemas_ ticked**. Copy into `config.json`: the GUID after `/groups/` in its URL (`workspace.id`), the GUID after `/lakehouses/` (`lakehouse.id`), and the host part of the SQL analytics endpoint's **SQL connection string** (`lakehouse.sqlEndpoint`, e.g. `xxxx.datawarehouse.fabric.microsoft.com`).
2. `npm run all`.
3. Workspace > **Import > Notebook > From this computer**: select every `.ipynb` in `out/notebooks/` (not the copies in this repo's folders). Don't rename them.
4. Open `Lake_Setup` > **Run all**. It creates the folders used below.
5. In the Lakehouse, **Files > universal_lake > … > Upload > Upload folder** > the `out/models` folder itself; tick **Overwrite if folder already exists**. You should then have `Files/universal_lake/models/gold_tables.json`.
6. Upload each CSV export to `Files/analytics_hub_uploads`; the orchestrator sorts them.

After changing `config.json`, repeat 2 and 3 for the notebooks it reports as changed (delete the old ones first: Fabric doesn't overwrite on import, it adds a copy named `... 1`).

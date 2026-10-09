# Step 4: Import into Fabric and set up the Lakehouse

Put the files from `out/` into the workspace, set up the Lakehouse, and check every credential. Nothing is ingested yet.

Order matters: `Lake_Init` (4.3) creates the Lakehouse folders that 4.5 and 4.6 upload into.

## 4.1 Import the notebooks

1. Open the workspace > **Import > Notebook > From this computer**.
2. Select **all `.ipynb` files in `out/notebooks/`** at once > **Open**.
   *Not* the copies in this repo's numbered folders: those have no Lakehouse attached and no values filled in.
3. Wait until they all show in the workspace (about 20, depending on your sources; `out/notebooks/MANIFEST.json` lists them).

> **Don't rename notebooks.** They call each other by name. When re-importing, **delete the old notebook first**: Fabric doesn't overwrite, it imports a copy named `lake_ops 1`, and the old one keeps being used.

## 4.2 Check the Lakehouse is attached

Open `Lake_Init`. In the **Explorer** pane on the left, `UniversalLake_LH` should be under *Lakehouses*, marked as default (pin icon).

If it isn't, `workspace.id` or `lakehouse.id` was wrong in `config.json`. Fix it, `npm run all`, delete the notebooks and import again. (Attaching by hand works too, **Add data items > Existing data source**, but you'd have to do it in every notebook.)

## 4.3 Run `Lake_Init`

Open `Lake_Init` and choose **Run all**. The first cell (parameters) is already filled in from `config.json`. The first run takes a minute or two while Spark starts.

It creates:

* schemas `bronze`, `silver`, `gold`, `ops` (next to `dbo`);
* `ops.config` with your settings, which the other notebooks read;
* the `Files/` folders for uploads, including `Files/universal_lake/`.

It ends by listing any setting that is still missing. It is safe to re-run; it never deletes anything.

| If it stops with | Fix |
|---|---|
| *This Lakehouse is not schema-enabled* | The *Lakehouse schemas* box wasn't ticked. Recreate the Lakehouse ([1.3](../01-fabric/README.md#13-create-the-lakehouse-with-schemas)), update `lakehouse.id`, rebuild and re-import. |
| *No default Lakehouse* | See 4.2. |

## 4.4 Run `Lake_Validate_Credentials`

Open it > **Run all**. It writes nothing; run it as often as you like, and again whenever an ingester fails with 401 or 403.

| Check | If it fails |
|---|---|
| Client secret from Key Vault | Give yourself *Key Vault Secrets User* on the vault. With the `config.json` bypass this shows as a **warning**, which is expected. |
| Graph token | Wrong tenant ID or app ID, or the secret expired or was mistyped. |
| Graph permissions for `<module>` | Add the permission and grant admin consent ([2.1](../02-permissions/README.md#21-register-the-app-and-add-permissions)). Wait a few minutes, re-run. |
| Audit log query API | Audit is on by default; check Microsoft Purview > **Audit** is recording, and that `AuditLogsQuery.Read.All` is consented. |
| Usage reports show real user names | Turn off concealed names ([2.3](../02-permissions/README.md#23-give-the-app-access)). |
| Copilot packages API | No Agent 365 in the tenant: set `dataSources.agent365` to `csv`, rebuild. |
| Azure subscription / cost query | Give the app the three reader roles on the subscription ([2.4](../02-permissions/README.md#24-azure-ai-access-only-if-azureai-is-api)). |
| Dataverse / transcripts | Add the app as an application user with Bot Transcript Viewer. |

**Don't continue until every required check passes.** It raises an error at the end if one fails.

## 4.5 Upload the model definitions

1. Open `UniversalLake_LH`. In the explorer, **Files > universal_lake** (created by 4.3).
2. Click **…** next to `universal_lake` > **Upload > Upload folder** > select the **`out/models`** folder itself.
3. If Fabric asks about existing files, choose to overwrite.
4. Check you now have `Files/universal_lake/models/gold_tables.json` and `Files/universal_lake/models/universal/definition.json`.

If you see `Files/universal_lake/universal/...` (no `models` level), you uploaded the folder's contents instead of the folder: delete it and upload again.

## 4.6 Upload CSV exports (only sources set to `csv`)

Upload each export to its folder under **Files** (created by 4.3). Not sure which? Use `Files/analytics_hub_uploads`; the upload router recognises the file and moves it. You can also do this later.

Before it runs anything, `Lake_Orchestrator` checks these folders. If a source is set to `csv` and its folder is empty, it prints a **WARNING** in the plan and again at the end, and carries on: the step still runs, but its table stays empty. Upload the file, then rerun just that step (for example `STEPS = 'product_feedback'`).

| Source | Folder | Export from |
|---|---|---|
| `agent365` | `Files/agent365` | Microsoft 365 admin center > **Agents > All agents > Export** |
| `productFeedback` | `Files/product_feedback` | Microsoft 365 admin center > **Health > Product feedback > Export** |
| `studioCredits` | `Files/landing/studio` | Power Platform admin center > **Licensing > Copilot Studio**: Summary, Environments and Agents exports |
| `coworkCredits` | `Files/landing/viva` | Viva Insights > **Copilot Consumption Dashboard > Export** (both CSVs) |
| `workday` | `Files/org_workday` | Workday report of active workers with Primary Work Email, as CSV |

## Re-building later

* **Changed `config.json`** (new source, new secret with the bypass, etc.): `npm run all`, then delete and re-import the notebooks it reports as changed.
* **Only the models changed**: `npm run models`, re-upload `out/models` (4.5), run `Lake_Deploy_Models` (step 7).
* **Newer source version**: see [Where the notebook code comes from](../README.md#where-the-notebook-code-comes-from).

Next: [Step 5: Ingest](../05-ingest/README.md)

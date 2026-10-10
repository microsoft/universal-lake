# Step 4: Deploy to Fabric

One command does the whole Fabric side, as **you** (your own sign-in, not the app):

1. finds the workspace from `workspace.name`;
2. creates the Lakehouse, with schemas (or uses the one named in `lakehouse.name`);
3. writes the workspace ID, Lakehouse ID and SQL endpoint back into `config.json`;
4. builds the notebooks and model files for your sources (`npm run all`);
5. imports the notebooks, attached to the Lakehouse;
6. uploads the model files, and every CSV in your `exportsFolder`;
7. runs `Lake_Setup`, which creates the schemas and folders and **checks every permission the app needs**.

Nothing is ingested yet. It is safe to run again: unchanged notebooks and already-uploaded CSVs are skipped.

## 4.1 Preview

```powershell
npm run deploy -- --dry-run
```

This signs in to nothing and changes nothing. Check two things:

* **Workspace and tenant** are right.
* **CSV exports**: each file you saved shows as `upload ... -> <source>`. A `WARNING` means a source set to `csv` has no file yet; that source's tables stay empty until you add it and deploy again.

## 4.2 Deploy

```powershell
npm run deploy
```

* A browser window opens: **sign in with your work account** (the one with access to the workspace). On a PC without a browser, add `-- --device-code` and follow the code prompt instead.
* The first run takes a few minutes: most of it is Spark starting for `Lake_Setup`.
* It ends with **`Lake_Setup passed`** and a link to `Lake_Orchestrator`.

If it stops, the message says what to fix. Fix it and run `npm run deploy` again; it carries on from where it stopped. The common cases are in [TROUBLESHOOTING.md](../TROUBLESHOOTING.md):

* **`Lake_Setup` reports a failed check** (a missing permission, consent or role): [Lake_Setup checks](../TROUBLESHOOTING.md#lake_setup-checks).
* **Notebooks with the same names already exist**: [Notebooks with the same names](../TROUBLESHOOTING.md#notebooks-with-the-same-names).
* **Sign-in or a 401/403 from Fabric**: [Deploy can't sign in or is refused](../TROUBLESHOOTING.md#deploy-cant-sign-in-or-is-refused).

## Checklist

- [ ] `npm run deploy` ended with *Lake_Setup passed*.
- [ ] `config.json` now has `workspace.id`, `lakehouse.id` and `lakehouse.sqlEndpoint` filled in.
- [ ] Every CSV you expected shows as uploaded.

## When to deploy again

Run `npm run deploy` again after any of these; it only sends what changed:

* you changed `config.json` (a new source, a new secret with the bypass, ...);
* you added or refreshed CSV exports in your exports folder (new files are uploaded; use `-- --reupload-csv` to send a file with the same content again);
* you took a newer version of this repo (`git pull`).

After a model change, also run `Lake_Deploy_Models` to update the existing models ([step 6](../06-models/README.md#run-lake_deploy_models-yourself-only-to)).

**Moving to a different workspace or Lakehouse:** change `workspace.name` or `lakehouse.name`, clear `workspace.id`, `lakehouse.id` and `lakehouse.sqlEndpoint` (set them to `""`), and deploy. Everything is set up fresh there.

Next: [Step 5: Ingest](../05-ingest/README.md) (or start it now with `npm run deploy -- --run first_load`).

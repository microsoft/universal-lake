# 8. Reports: the Power BI templates

Two ready-made reports read the Lakehouse once step 5 has loaded it. Use either, or both. A third, [M365 Usage Analytics](#m365-usage-analytics), works when the optional `m365Usage` source is on.

| Template | What it shows | Asks for |
|---|---|---|
| `ValueLens - Fabric.pbit` | The business value of Copilot and agents: ROI, cost, adoption, feedback | Fabric SQL Endpoint, Lakehouse Name |
| `AI-in-One Dashboard - Fabric.pbit` | Copilot and agent adoption and usage across the whole estate | Fabric SQL Endpoint, Lakehouse Database |

You need Power BI Desktop and read access to the workspace.

## Open one

1. Find the two values. When a `npm run deploy` run ends, the terminal prints both. Or in Fabric: open the Lakehouse, switch to **SQL analytics endpoint**, then **Settings > SQL endpoint** and copy the **SQL connection string**. The Lakehouse name is the item's name (by default `UniversalLake_LH`).
2. Double-click the `.pbit` file. Power BI Desktop opens it and asks for the values:
   * **Fabric SQL Endpoint**: the connection string, for example `xxxx.datawarehouse.fabric.microsoft.com`
   * **Lakehouse Name** (ValueLens) or **Lakehouse Database** (AI-in-One): the Lakehouse name
   * Leave the other settings at their defaults.
3. Select **Load**. When asked, sign in with **Microsoft account > Organizational account**, using an account that can read the workspace.
4. Wait for the data to load, then **File > Save as** a `.pbix`.

## M365 Usage Analytics

The [M365 Usage Analytics](https://github.com/microsoft/M365UsageAnalytics) template shows Teams, Outlook, Word, Excel and PowerPoint use per person, with activity tiers and Copilot licensing priorities. Turn on `m365Usage` in `config.json` (step 3) and its permissions (step 2). The `m365_usage` step writes two daily tables: `m365_usage_rollup` (one row per user, day, operation, app and file type) and `m365_usage_sessionstats` (Copilot sessions and prompts per user, day and app).

`M365 Usage Analytics - Fabric.pbit` asks for the same **Fabric SQL Endpoint** and **Lakehouse Name** as ValueLens. It reads the two tables, and builds its per-user stats (tiers, percentiles, ranks), session cohorts and Entra user list with SQL queries that run on the SQL endpoint at each refresh. The queries are in [`m365-usage-sql`](m365-usage-sql); the user list comes from `copilot_org_data` and `copilot_licensed_users`, so turn on `orgData` too.

On the first refresh Power BI asks you to approve each native database query. Select **Run** for all three.

To change a query, edit `scripts/gen_m365_usage_sql.py`, then run `python scripts/gen_m365_usage_sql.py` and `python scripts/patch_m365_pbit.py`. `scripts/test_m365_usage_sql.py` checks the queries against the original M365 Usage Analytics processor.

## Share it

**File > Publish**, pick the workspace, then in Fabric open the published semantic model > **Settings > Data source credentials > Edit credentials > OAuth2** and sign in, so the report can refresh. Set **Scheduled refresh** to run 1 to 2 hours after the daily `Lake_Orchestrator` run ([step 9](../09-autorefresh/README.md)).

## If it goes wrong

* **A page is empty or a table is missing**: that source wasn't loaded. Turn it on in `config.json` and run its ingester (step 5), or leave it; ValueLens skips sources it can't find.
* **Sign-in fails**: use the same tenant as the Fabric workspace, and check you can open the Lakehouse in Fabric.
* More: [TROUBLESHOOTING.md](../TROUBLESHOOTING.md).

Next: [step 9](../09-autorefresh/README.md), make the lake (and your reports) refresh by themselves.

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

The [M365 Usage Analytics](https://github.com/microsoft/M365UsageAnalytics) template shows Teams, Outlook, Word, Excel and PowerPoint use per person, with activity tiers and Copilot licensing priorities. Turn on `m365Usage` in `config.json` (step 3) and its permissions (step 2). The `m365_usage` and `m365_usage_gold` steps then write its five inputs to the Lakehouse folder `Files/m365_usage_export`:

| Template parameter | File in `Files/m365_usage_export` |
|---|---|
| Rollup | `Rollup.csv` |
| Session Stats | `SessionStats.csv` |
| User Stats | `UserStats.csv` |
| Session Cohort | `SessionCohort.csv` |
| Entra Users Data | `EntraUsers.csv` |

The same data is also in the tables `m365_usage_rollup`, `m365_usage_sessionstats`, `m365_usage_userstats`, `m365_usage_sessioncohort` and `m365_usage_entrausers`.

To open it, download the five CSVs (OneLake file explorer, or the Lakehouse **Files** view > **Download**), open the template and point each parameter at its file.

## Share it

**File > Publish**, pick the workspace, then in Fabric open the published semantic model > **Settings > Data source credentials > Edit credentials > OAuth2** and sign in, so the report can refresh. Set **Scheduled refresh** to run 1 to 2 hours after the daily `Lake_Orchestrator` run ([step 9](../09-autorefresh/README.md)).

## If it goes wrong

* **A page is empty or a table is missing**: that source wasn't loaded. Turn it on in `config.json` and run its ingester (step 5), or leave it; ValueLens skips sources it can't find.
* **Sign-in fails**: use the same tenant as the Fabric workspace, and check you can open the Lakehouse in Fabric.
* More: [TROUBLESHOOTING.md](../TROUBLESHOOTING.md).

Next: [step 9](../09-autorefresh/README.md), make the lake (and your reports) refresh by themselves.

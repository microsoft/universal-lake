# 8. Reports: the Power BI templates

Two ready-made reports read the Lakehouse once step 5 has loaded it. Use either, or both.

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

## Share it

**File > Publish**, pick the workspace, then in Fabric open the published semantic model > **Settings > Data source credentials > Edit credentials > OAuth2** and sign in, so the report can refresh. Set **Scheduled refresh** to run after the daily `Lake_Orchestrator` run (step 7).

## If it goes wrong

* **A page is empty or a table is missing**: that source wasn't loaded. Turn it on in `config.json` and run its ingester (step 5), or leave it; ValueLens skips sources it can't find.
* **Sign-in fails**: use the same tenant as the Fabric workspace, and check you can open the Lakehouse in Fabric.
* More: [TROUBLESHOOTING.md](../TROUBLESHOOTING.md).

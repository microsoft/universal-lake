# Step 1: Fabric capacity and workspace

Everything lives in **one Fabric workspace**: one Lakehouse, about 20 notebooks and up to three semantic models. You only create the workspace here. `npm run deploy` (step 4) creates the Lakehouse and everything in it.

## 1.1 Pick a capacity

Notebooks need a **Fabric capacity** (F SKU) or a Fabric trial. A Pro or PPU workspace alone won't do, and *My workspace* can't be used.

| Your situation | Use | Notes |
|---|---|---|
| Trying it out | **Fabric trial** (free, 60 days, F64-sized) | Fabric portal > your account picture > **Start trial**. Move to paid capacity before it ends. |
| Up to ~10,000 people with Copilot | **F2** or larger | A 30-day first load usually takes under an hour. |
| More than ~10–20k people | **F64** or larger | Also set `scale` to `large` in `config.json`. A first load can take several hours. |

Good to know:

* **Below F64**, everyone who opens a report on these models needs Power BI Pro or PPU.
* **The capacity must be running.** A paused capacity runs nothing, including schedules.
* **The capacity's region is where the data is stored.**

## 1.2 Create the workspace

1. Fabric portal > **Workspaces > New workspace**. Name it, e.g. `Universal Data Lake`.
2. **Advanced > License mode**: **Fabric capacity** (or **Trial**), pick the capacity, **Apply**.
3. Make sure you are **Admin**, **Member** or **Contributor** (*Manage access*). Deploy creates items as you, so it needs at least Contributor.
4. Put the workspace name in `config.json`: `"workspace": { "name": "Universal Data Lake", ... }`.

Use a workspace that **doesn't already hold another solution's notebooks** with the same names (for example another Copilot analytics lake). If you're unsure, a new, empty workspace is the safe choice.

> **Using a Lakehouse you already have?** Put its name in `lakehouse.name` and deploy uses it instead of creating one. It must be **schema-enabled** (it shows a `dbo` folder under *Tables*) and mustn't already hold `bronze`, `silver`, `gold` or `ops` tables from another solution.

## Checklist

- [ ] Workspace on a Fabric capacity or trial, and you are Contributor or above.
- [ ] `workspace.name` is set in `config.json`.

Next: [Step 2: Permissions](../02-permissions/README.md)

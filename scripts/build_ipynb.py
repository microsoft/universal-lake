"""Builds the repo's own Fabric notebooks from readable percent-format sources in notebook-src/.

    python scripts/build_ipynb.py

Cell markers:  "# %%" code, "# %% [parameters]" parameters cell (tagged for notebookutils.notebook.run
and pipelines), "# %% [markdown]" markdown (lines start with "# ").
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGETS = {
    "Lake_Setup.py": "04-deploy/Lake_Setup.ipynb",
    "Lake_Promote_Medallion.py": "06-models/Lake_Promote_Medallion.ipynb",
    "Lake_Deploy_Models.py": "06-models/Lake_Deploy_Models.ipynb",
    "Lake_Orchestrator.py": "07-orchestrate/Lake_Orchestrator.ipynb",
    "lake_ops.py": "07-orchestrate/lake_ops.ipynb",
}
METADATA = {
    "kernel_info": {"name": "synapse_pyspark"},
    "kernelspec": {"name": "synapse_pyspark", "display_name": "Synapse PySpark", "language": "Python"},
    "language_info": {"name": "python"},
    "microsoft": {"language": "python", "language_group": "synapse_pyspark"},
}
MARK = re.compile(r"^# %%(?: \[(markdown|parameters)\])?\s*$")


def strip_json_comments(text):
    """Removes // line comments outside strings, so config.json can carry guidance."""
    out, in_str, i = [], False, 0
    while i < len(text):
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < len(text):
                i += 1
                out.append(text[i])
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif c == "/" and text[i + 1:i + 2] == "/":
            while i < len(text) and text[i] != "\n":
                i += 1
            out.append("\n")
        else:
            out.append(c)
        i += 1
    return "".join(out)


PARAM = re.compile(r"^([A-Z_][A-Z0-9_]*) = (?:'[^']*'|\d+|True|False)(\s+#.*)?$")


def is_set(v):
    if isinstance(v, bool):
        return True
    return v not in (None, "") and "<" not in str(v)


# dataSources set to 'csv' whose upload folder Lake_Orchestrator checks before a run.
CSV_CHECKED = ("productFeedback", "studioCredits", "coworkCredits", "agent365")


def inline_secret(cfg):
    """No Key Vault URI but a clientSecret in config.json: the secret goes into the notebooks (not recommended)."""
    return not is_set(cfg.get("keyVault", {}).get("uri")) and is_set(cfg.get("clientSecret"))


def prefill_values(cfg):
    """Parameter values for the bound copies, taken from config.json (and out/SOURCE.lock.json for modules)."""
    kv = cfg.get("keyVault", {})
    lh = cfg.get("lakehouse", {})
    az = cfg.get("azure", {})
    subs = [az.get("subscriptionId")] + [p if isinstance(p, str) else p.get("subscriptionId") for p in az.get("paygSubscriptions", [])]
    urls = [e.get("url") for e in cfg.get("dataverseEnvironments", [])]
    lock = ROOT / "out" / "SOURCE.lock.json"
    modules = json.loads(lock.read_text(encoding="utf-8")).get("modules", []) if lock.exists() else []
    if isinstance(modules, dict):
        modules = ["core"] + [k for k, on in modules.items() if on and k != "core"]
    modules = ["copilotInteractions" if m == "core" else m for m in modules]
    inline = inline_secret(cfg)
    values = {
        "TENANT_ID": cfg.get("tenantId"),
        "CLIENT_ID": cfg.get("appId"),
        "KEY_VAULT_URI": None if inline else kv.get("uri"),
        "SECRET_NAME": kv.get("secretName"),
        "CLIENT_SECRET": cfg.get("clientSecret") if inline else None,
        "SECRET_IN_NOTEBOOKS": inline,
        "SQL_ENDPOINT": lh.get("sqlEndpoint"),
        "SCALE": cfg.get("scale"),
        "BACKFILL_DAYS": cfg.get("backfillDays"),
        "MODULES": ",".join(modules),
        "AGENT365_SOURCE": cfg.get("dataSources", {}).get("agent365"),
        "CSV_SOURCES": ",".join(k for k, v in cfg.get("dataSources", {}).items()
                                if v == "csv" and k in CSV_CHECKED) or "none",
        "AZURE_SUBSCRIPTION_IDS": ",".join(dict.fromkeys(s for s in subs if is_set(s))),
        "DATAVERSE_URLS": ",".join(u for u in urls if is_set(u)),
    }
    return {k: v for k, v in values.items() if is_set(v)}


def prefill(nb, values):
    """Fill the parameters cell of a notebook with values from config.json. Returns the names filled."""
    filled = []
    for cell in nb["cells"]:
        if "parameters" not in cell["metadata"].get("tags", []):
            continue
        src = []
        for line in cell["source"]:
            body = line.rstrip("\n")
            m = PARAM.match(body)
            if m and m.group(1) in values:
                v = values[m.group(1)]
                lit = str(v) if isinstance(v, bool) else str(int(v)) if isinstance(v, int) else repr(str(v))
                body = f"{m.group(1)} = {lit}{m.group(2) or ''}"
                filled.append(m.group(1))
            src.append(body + ("\n" if line.endswith("\n") else ""))
        cell["source"] = src
    return filled


def lines(text):
    out = text.split("\n")
    while out and not out[-1].strip():
        out.pop()
    while out and not out[0].strip():
        out.pop(0)
    return [l + "\n" for l in out[:-1]] + out[-1:] if out else []


def convert(src):
    cells, kind, buf = [], None, []

    def flush():
        if kind is None:
            return
        body = "\n".join(buf)
        if kind == "markdown":
            body = "\n".join(re.sub(r"^# ?", "", l) for l in buf)
            cells.append({"cell_type": "markdown", "metadata": {}, "source": lines(body)})
        else:
            meta = {"tags": ["parameters"]} if kind == "parameters" else {}
            cells.append({"cell_type": "code", "metadata": meta, "execution_count": None, "outputs": [], "source": lines(body)})

    for line in src.read_text(encoding="utf-8").split("\n"):
        m = MARK.match(line)
        if m:
            flush()
            kind, buf = (m.group(1) or "code"), []
        elif kind is not None:
            buf.append(line)
    flush()
    return {"cells": cells, "metadata": METADATA, "nbformat": 4, "nbformat_minor": 5}


if __name__ == "__main__":
    import sys

    cfg_path = pathlib.Path(sys.argv[sys.argv.index("--config") + 1]) if "--config" in sys.argv else ROOT / "config.json"
    cfg = json.loads(strip_json_comments(cfg_path.read_text(encoding="utf-8"))) if cfg_path.exists() else None
    lh = (cfg or {}).get("lakehouse", {})
    ws = (cfg or {}).get("workspace", {})
    bind = cfg and "<" not in str(lh.get("id", "<")) and "<" not in str(ws.get("id", "<"))

    for name, target in TARGETS.items():
        nb = convert(ROOT / "notebook-src" / name)
        out = ROOT / target
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{target}: {len(nb['cells'])} cells")
        if bind:
            # Copy bound to your Lakehouse, next to the synced data notebooks, so out/notebooks is the one
            # folder you import. The committed copies stay unbound.
            bound = json.loads(json.dumps(nb))
            bound["metadata"] = dict(METADATA, dependencies={"lakehouse": {
                "default_lakehouse": lh["id"], "default_lakehouse_name": lh.get("name", ""),
                "default_lakehouse_workspace_id": ws["id"], "known_lakehouses": [{"id": lh["id"]}]}})
            # Setup notebooks get their parameters from config.json, so nothing is copied by hand.
            if name in ("Lake_Setup.py", "Lake_Deploy_Models.py"):
                filled = prefill(bound, prefill_values(cfg))
                print(f"  out/notebooks/{pathlib.Path(target).name}: filled {', '.join(filled) or 'nothing'}")
            dest = ROOT / "out" / "notebooks" / pathlib.Path(target).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(bound, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if bind:
        print(f"Bound copies for Lakehouse {lh.get('name')} ({lh['id']}) written to out/notebooks/")
        if inline_secret(cfg):
            print("WARNING: the client secret is written into out/notebooks (no Key Vault). Don't share or commit them.")
    else:
        print("No filled-in config.json: notebooks are unbound (fine for the repo copies; npm run deploy builds bound ones).")

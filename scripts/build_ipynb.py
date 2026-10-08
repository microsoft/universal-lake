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
    "01_Validate_Credentials.py": "01-app-registration/01_Validate_Credentials.ipynb",
    "02_Init_Lakehouse.py": "02-lakehouse/02_Init_Lakehouse.ipynb",
    "05_Promote_Medallion.py": "05-process/05_Promote_Medallion.ipynb",
    "06_Deploy_Models.py": "06-semantic-model/06_Deploy_Models.ipynb",
    "07_Orchestrator.py": "07-orchestrate/07_Orchestrator.ipynb",
    "lake_ops.py": "07-orchestrate/lake_ops.ipynb",
}
METADATA = {
    "kernel_info": {"name": "synapse_pyspark"},
    "kernelspec": {"name": "synapse_pyspark", "display_name": "Synapse PySpark", "language": "Python"},
    "language_info": {"name": "python"},
    "microsoft": {"language": "python", "language_group": "synapse_pyspark"},
}
MARK = re.compile(r"^# %%(?: \[(markdown|parameters)\])?\s*$")


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
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else None
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
            # Copy bound to your Lakehouse, next to the synced installer notebooks, so out/notebooks is the one
            # folder you import. The committed copies stay unbound.
            bound = dict(nb, metadata=dict(METADATA, dependencies={"lakehouse": {
                "default_lakehouse": lh["id"], "default_lakehouse_name": lh.get("name", ""),
                "default_lakehouse_workspace_id": ws["id"], "known_lakehouses": [{"id": lh["id"]}]}}))
            dest = ROOT / "out" / "notebooks" / pathlib.Path(target).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(bound, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if bind:
        print(f"Bound copies for Lakehouse {lh.get('name')} ({lh['id']}) written to out/notebooks/")
    else:
        print("No filled-in config.json: notebooks are unbound; attach the Lakehouse in Fabric after import.")

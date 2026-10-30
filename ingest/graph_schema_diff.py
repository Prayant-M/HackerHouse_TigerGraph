"""Graph schema drift (C12 on graphs): diff two versions of a bank's GSQL
schema, say what each change breaks in our mapping, and wait for approval.

`00_drift.py` gates *file* drift (columns, types, distributions). A bank that
already runs a graph changes its *graph* instead: a vertex type renamed, an
attribute dropped or retyped, an edge re-pointed. This compares the old and
new schema in two ways:

1. **Structure** — vertex and edge types added, removed or (proposed) renamed
   by attribute overlap; attributes added, removed or retyped; primary-id
   changes; edge endpoint and reverse-name changes.
2. **Mapping impact** — both versions are run through graph_schema_mapper and
   every canonical concept, edge and attribute whose target moved, vanished
   or appeared is listed, with severity: `breaking` (a mapped target is gone
   or changed type), `remap` (the mapper found a new target), `info`.

It validates the new schema (reserved words, endpoints, key types), writes a
proposal next to the file-drift ones, and exits 4 until a fraud manager
approves it with a token. The approval is signed into the approval ledger and,
on TigerGraph, written as a SchemaChange vertex. While a proposal is pending,
`00_drift.gate_open()` keeps the loaders closed.

    python ingest/graph_schema_diff.py OLD.gsql NEW.gsql
    python ingest/graph_schema_diff.py OLD.gsql NEW.gsql --approve --token <fraud-manager token>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ingest"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

import graph_schema_mapper as gsm  # noqa: E402

OUT = DEFAULT_OUT = ROOT / "data" / "drift"
REPORT = ROOT / "eval" / "reports" / "graph_schema_diff.md"
RENAME_MIN_OVERLAP = 0.6


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def structure(old: gsm.Schema, new: gsm.Schema) -> dict:
    ov, nv = set(old.vertices), set(new.vertices)
    removed, added = sorted(ov - nv), sorted(nv - ov)
    renames = []
    for r in list(removed):
        a = set(old.vertices[r].attrs) | {old.vertices[r].pk[0]}
        best = max(((n, _jaccard(a, set(new.vertices[n].attrs) | {new.vertices[n].pk[0]}))
                    for n in added if n not in {x["to"] for x in renames}),
                   key=lambda x: x[1], default=None)
        if best and best[1] >= RENAME_MIN_OVERLAP:
            renames.append({"from": r, "to": best[0], "attribute_overlap": round(best[1], 2)})
    ren = {x["from"]: x["to"] for x in renames}
    vchanges = []
    for name in sorted(ov):
        tgt = ren.get(name, name)
        if tgt not in new.vertices:
            continue
        a, b = old.vertices[name], new.vertices[tgt]
        ch = {"vertex": name if tgt == name else f"{name} -> {tgt}"}
        if a.pk != b.pk:
            ch["primary_id"] = [list(a.pk), list(b.pk)]
        ch["attrs_added"] = sorted(set(b.attrs) - set(a.attrs))
        ch["attrs_removed"] = sorted(set(a.attrs) - set(b.attrs))
        ch["attrs_retyped"] = sorted(f"{k}: {a.attrs[k]} -> {b.attrs[k]}"
                                     for k in set(a.attrs) & set(b.attrs)
                                     if a.attrs[k] != b.attrs[k])
        if len(ch) > 1 and any(ch[k] for k in ch if k != "vertex"):
            vchanges.append(ch)
    oe, ne = set(old.edges), set(new.edges)
    echanges = []
    for name in sorted(oe & ne):
        a, b = old.edges[name], new.edges[name]
        ch = {"edge": name}
        pa = sorted((ren.get(f, f), ren.get(t, t)) for f, t in a.pairs)
        if pa != sorted(b.pairs):
            ch["endpoints"] = [[list(p) for p in a.pairs], [list(p) for p in b.pairs]]
        if a.reverse != b.reverse:
            ch["reverse"] = [a.reverse, b.reverse]
        if a.directed != b.directed:
            ch["directed"] = [a.directed, b.directed]
        if a.attrs != b.attrs:
            ch["attrs"] = [a.attrs, b.attrs]
        if len(ch) > 1:
            echanges.append(ch)
    return {"vertices_added": [n for n in added if n not in ren.values()],
            "vertices_removed": [n for n in removed if n not in ren],
            "vertices_renamed": renames, "vertex_changes": vchanges,
            "edges_added": sorted(ne - oe), "edges_removed": sorted(oe - ne),
            "edge_changes": echanges}


def _target(entry: dict) -> str:
    if not entry:
        return ""
    if "targets" in entry:
        return ",".join(entry.get("targets") or []) or entry.get("kind", "")
    if "path" in entry:
        return " > ".join(entry.get("path") or []) or entry.get("kind", "")
    return entry.get("target") or entry.get("kind", "")


def impact(r_old: dict, r_new: dict, st: dict, new: gsm.Schema) -> list[dict]:
    """Per canonical concept / edge / attribute: what moved, and how bad it is."""
    gone_vertices = set(st["vertices_removed"]) | {x["from"] for x in st["vertices_renamed"]}
    retyped = {}
    for ch in st["vertex_changes"]:
        v = ch["vertex"].split(" -> ")[0]
        for x in ch["attrs_retyped"]:
            retyped[f"{v}.{x.split(':')[0]}"] = x
    removed_attrs = {f"{ch['vertex'].split(' -> ')[0]}.{a}"
                     for ch in st["vertex_changes"] for a in ch["attrs_removed"]}
    def unmapped(t: str) -> bool:
        return (not t) or t.startswith("unmapped")

    rows = []
    for section, label in (("concepts", "concept"), ("edges", "edge"), ("attributes", "attribute")):
        o, n = r_old[section], r_new[section]
        for key in sorted(set(o) | set(n)):
            a, b = _target(o.get(key, {})), _target(n.get(key, {}))
            sev = ""
            why = ""
            if a in retyped:
                sev, why = "breaking", (f"old target retyped ({retyped[a]})"
                                        + (f"; the mapper falls back to {b}" if a != b else ""))
            elif a in removed_attrs:
                sev, why = "breaking", ("old target attribute removed"
                                        + (f"; the mapper falls back to {b}" if b else ""))
            elif a != b:
                if unmapped(b) and not unmapped(a):
                    sev, why = "breaking", "was mapped, now nothing in the new schema carries it"
                elif unmapped(a) and not unmapped(b):
                    sev, why = "info", "newly mappable"
                else:
                    sev, why = "remap", "the mapper chose a different target in the new schema"
                    if any(t in gone_vertices for t in a.replace(" > ", ",").split(",")):
                        why += " (the old target vertex type is gone or renamed)"
            if sev:
                rows.append({"kind": label, "name": key, "old": a, "new": b,
                             "severity": sev, "why": why})
    return rows


def diff(old_path: Path, new_path: Path) -> dict:
    t0 = time.time()
    old, new = gsm.parse(old_path), gsm.parse(new_path)
    r_old, r_new = gsm.run(old_path), gsm.run(new_path)
    st = structure(old, new)
    rows = impact(r_old, r_new, st, new)
    body = {"old": str(old_path), "new": str(new_path), "graph": new.graph,
            "structure": st, "impact": rows, "validation_new": r_new["validation"],
            "mapping_score_new": {k: r_new["score"][k] for k in ("correct", "n")}
            if r_new["score"].get("n") else None}
    pid = "GSCHEMA-" + hashlib.sha256(json.dumps(body, sort_keys=True, default=str)
                                      .encode()).hexdigest()[:12]
    n_break = sum(r["severity"] == "breaking" for r in rows)
    body.update(id=pid, created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                detect_seconds=round(time.time() - t0, 2),
                summary=(f"{new.graph}: +{len(st['vertices_added'])} -{len(st['vertices_removed'])} "
                         f"~{len(st['vertices_renamed'])} vertex types, "
                         f"{len(st['vertex_changes'])} changed; +{len(st['edges_added'])} "
                         f"-{len(st['edges_removed'])} edge types, {len(st['edge_changes'])} "
                         f"changed; mapping impact: {n_break} breaking, "
                         f"{sum(r['severity'] == 'remap' for r in rows)} remap"),
                mapping=r_new["concepts"])
    return body


def render(p: dict) -> str:
    st = p["structure"]
    md = [f"# Graph schema drift proposal {p['id']}", "", p["summary"], "",
          f"`{Path(p['old']).name}` → `{Path(p['new']).name}`; detected in "
          f"{p['detect_seconds']} s.", "", "## Structure", ""]
    for k in ("vertices_added", "vertices_removed", "edges_added", "edges_removed"):
        md.append(f"- {k.replace('_', ' ')}: {', '.join(st[k]) or 'none'}")
    md.append("- vertices renamed (proposed by attribute overlap): " + (", ".join(
        f"{x['from']} → {x['to']} ({x['attribute_overlap']:.0%})"
        for x in st["vertices_renamed"]) or "none"))
    for ch in st["vertex_changes"]:
        parts = [f"{k.replace('attrs_', '')}: {', '.join(v)}" for k, v in ch.items()
                 if k.startswith("attrs_") and v]
        if ch.get("primary_id"):
            parts.append(f"primary id {ch['primary_id'][0]} → {ch['primary_id'][1]}")
        md.append(f"- `{ch['vertex']}`: " + "; ".join(parts))
    for ch in st["edge_changes"]:
        md.append(f"- edge `{ch['edge']}`: " + "; ".join(
            f"{k} {v[0]} → {v[1]}" for k, v in ch.items() if k != "edge"))
    md += ["", "## What it breaks in our mapping", "",
           "| severity | kind | canonical | old target | new target | why |",
           "|---|---|---|---|---|---|"]
    order = {"breaking": 0, "remap": 1, "info": 2}
    for r in sorted(p["impact"], key=lambda r: order[r["severity"]]):
        md.append(f"| {r['severity']} | {r['kind']} | {r['name']} | {r['old'] or '—'} | "
                  f"{r['new'] or '—'} | {r['why']} |")
    if not p["impact"]:
        md.append("| — | — | — | — | — | no mapping changes |")
    v = p["validation_new"]
    md += ["", "## New schema validation", "",
           f"- ok: {v['ok']}; problems: {len(v['problems'])}; warnings: {len(v['warnings'])}"]
    md += [f"  - problem: {x}" for x in v["problems"]]
    if p.get("mapping_score_new"):
        s = p["mapping_score_new"]
        md.append(f"- mapping against the new file's ground truth: {s['correct']}/{s['n']}")
    return "\n".join(md) + "\n"


def approve(pid: str, token: str) -> dict:
    from fraudagent.governance import approvals as gov

    principal = gov.authenticate(f"Bearer {token}")
    if principal.role != "fraud_manager":
        gov.refuse(principal, pid, -1, 403, "graph schema change needs a fraud manager")
        raise SystemExit("403: only a fraud manager may approve a graph schema change")
    prop = json.loads((OUT / f"{pid}.json").read_text(encoding="utf-8"))
    if not prop["validation_new"]["ok"]:
        gov.refuse(principal, pid, -1, 409, "new schema fails validation")
        raise SystemExit("409: the new schema fails validation; fix it before approving")
    rec = gov._append({"kind": "graph_schema_change", "case_id": pid, "index": -1,
                       "approved": True, "actor_id": principal.actor_id,
                       "actor_role": principal.role,
                       "at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())})
    try:                                               # pragma: no cover - network
        from fraudagent.graphstore import get_store

        # Only a change to this bank's own graph is recorded in it; a proposal
        # in a scratch --out-dir (another bank's schema, a test) stays local.
        store = get_store() if OUT.resolve() == DEFAULT_OUT.resolve() else None
        if store is not None and store.backend == "tigergraph":
            store.conn.runInstalledQuery("governance_write", {
                "kind": "schema_change", "record_json": json.dumps({
                    "id": pid, "created_at": prop["created_at"].replace("T", " ")[:19],
                    "summary": prop["summary"], "mapping": json.dumps(prop["mapping"]),
                    "approved_by": principal.actor_id, "approved_at": rec["at"],
                    "signature": rec["signature"]})}, usePost=True)
    except Exception as exc:
        print(f"[graph-drift] graph write skipped: {exc}")
    (OUT / f"{pid}.approved").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--token", default=os.environ.get("APPROVAL_TOKEN", ""))
    ap.add_argument("--out-dir", default="",
                    help="where the proposal goes (default data/drift, which gates the loaders; "
                         "use a scratch folder for a schema that is not this bank's graph)")
    a = ap.parse_args(argv)
    global OUT
    if a.out_dir:
        OUT = Path(a.out_dir)
    OUT.mkdir(parents=True, exist_ok=True)
    prop = diff(Path(a.old), Path(a.new))
    (OUT / f"{prop['id']}.json").write_text(json.dumps(prop, indent=1, default=str),
                                            encoding="utf-8")
    md = render(prop)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(md, encoding="utf-8")
    print(md)
    if (OUT / f"{prop['id']}.approved").exists():
        print(f"[graph-drift] {prop['id']} already approved")
        return 0
    if not a.approve:
        print(f"[graph-drift] proposal {prop['id']} is waiting for a fraud manager; loaders stay "
              f"closed until `--approve --token <fraud-manager token>`")
        return 4
    if not a.token:
        raise SystemExit("--approve needs --token (a fraud-manager approval token)")
    rec = approve(prop["id"], a.token)
    print(f"[graph-drift] {prop['id']} approved by {rec['actor_id']} ({rec['actor_role']}); "
          f"ledger seq {rec['seq']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

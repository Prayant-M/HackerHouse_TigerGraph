"""Stage 3 — split the dataset README into the GraphRAG document corpus.

The bank's fraud policy, the five documented typologies, the regulatory
references and the answer format all ship inside `Datasets/README.md`. We cut
them into addressable, citable chunks so the agent can retrieve *clauses*
rather than being handed a wall of prose, and so every recommendation can name
the rule it came from.

Output: data/policy/*.md  +  data/policy/chunks.jsonl

Run:  python ingest/03_extract_policy.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Windows consoles still default to cp1252, which cannot encode the arrows and
# box characters used below; without this a clean run dies on its own log line.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - non-reconfigurable stream
    pass


from fraudagent.config import PATHS  # noqa: E402


def log(msg: str) -> None:
    print(f"[policy] {msg}", flush=True)


def split_sections(text: str) -> dict[str, str]:
    """Top-level `# ` sections of the dataset README."""
    parts: dict[str, str] = {}
    current, buf = "preamble", []
    for line in text.splitlines():
        if line.startswith("# "):
            parts[current] = "\n".join(buf).strip()
            current, buf = line[2:].strip(), []
        else:
            buf.append(line)
    parts[current] = "\n".join(buf).strip()
    return parts


RULE_RE = re.compile(r"^\*\*(R\d+)\.\s*(.+?)\*\*\s*(.*)$", re.S)


def main() -> None:
    PATHS.ensure()
    PATHS.policy.mkdir(parents=True, exist_ok=True)
    text = PATHS.dataset_readme.read_text(encoding="utf-8")
    sections = split_sections(text)
    log(f"sections found: {list(sections)}")

    chunks: list[dict] = []

    # ---------------------------------------------------------- policy ----
    policy = sections.get("Fraud Policy", "")
    (PATHS.policy / "fraud_policy.md").write_text(
        "# Fraud Policy\n\n" + policy, encoding="utf-8")

    # numbered rules R1..R10 -> one chunk each, verbatim source text
    rules_block = policy.split("### 3. Rules", 1)[-1].split("### 3a.", 1)[0]
    for para in re.split(r"\n\s*\n", rules_block):
        para = para.strip()
        m = re.match(r"^\*\*(R\d+)\.\s*(.+?)\*\*\s*(.*)$", para, re.S)
        if m:
            rid, title, body = m.group(1), m.group(2).strip(". "), m.group(3).strip()
            chunks.append({
                "doc_id": f"POLICY-{rid}",
                "kind": "policy_rule",
                "section": f"Fraud Policy / Rules / {rid}",
                "title": f"{rid}. {title}",
                "text": f"{rid}. {title}. {body}",
            })

    for name, marker, end in [
        ("actions", "### 1. Actions", "### 2. Approval routing"),
        ("approval_routing", "### 2. Approval routing", "### 3. Rules"),
        ("case_vs_report", "### 3a. A case is not a report", "### 3b."),
        ("action_can_change", "### 3b. The next best action can change", "### 4. Exposure"),
        ("exposure", "### 4. Exposure", "### 5. Gathering more evidence"),
        ("evidence_gathering", "### 5. Gathering more evidence", "### 6. Stopping"),
        ("stopping", "### 6. Stopping", "### 7. Explaining"),
        ("explaining", "### 7. Explaining", None),
    ]:
        if marker not in policy:
            continue
        body = policy.split(marker, 1)[1]
        if end and end in body:
            body = body.split(end, 1)[0]
        chunks.append({
            "doc_id": f"POLICY-{name.upper()}",
            "kind": "policy_section",
            "section": f"Fraud Policy / {marker.strip('# ')}",
            "title": marker.strip("# "),
            "text": body.strip(),
        })

    # -------------------------------------------------------- typologies ----
    # The dataset intro lives under the README's own H1, not under "preamble".
    body = next((v for v in sections.values() if "## The five known fraud patterns" in v),
                sections.get("preamble", ""))
    pat_block = ""
    if "## The five known fraud patterns" in body:
        pat_block = body.split("## The five known fraud patterns", 1)[1]
        pat_block = pat_block.split("## Regulatory references", 1)[0]
    (PATHS.policy / "typologies.md").write_text(
        "# Known fraud patterns\n\n" + pat_block.strip(), encoding="utf-8")

    pattern_ids = {
        "1": "card_testing", "2": "card_not_present_fraud",
        "3": "card_not_present_new_device", "4": "out_of_region_use",
        "5": "account_takeover",
    }
    for para in re.split(r"\n\s*\n", pat_block):
        m = re.match(r"^\*\*(\d)\.\s*(.+?)\.\*\*\s*(.*)$", para.strip(), re.S)
        if m and m.group(1) in pattern_ids:
            pid = pattern_ids[m.group(1)]
            chunks.append({
                "doc_id": f"PATTERN-{pid}",
                "kind": "typology",
                "section": "Known fraud patterns",
                "title": m.group(2).strip(),
                "text": f"{m.group(2).strip()}. {m.group(3).strip()}",
                "pattern": pid,
            })

    # ------------------------------------------------------- regulatory ----
    reg_block = ""
    if "## Regulatory references" in body:
        reg_block = body.split("## Regulatory references", 1)[1].split("## Things to know", 1)[0]
    (PATHS.policy / "regulatory_references.md").write_text(
        "# Regulatory references\n\n" + reg_block.strip(), encoding="utf-8")
    for m in re.finditer(r"- \[(.+?)\]\((https?://[^)]+)\)", reg_block):
        title, url = m.group(1), m.group(2)
        body_text = reg_block[max(0, m.start() - 400): m.start()]
        issuer = ""
        for cand in ("FinCEN", "FATF", "FFIEC", "OFAC"):
            if f"**{cand}" in body_text:
                issuer = cand
        chunks.append({
            "doc_id": f"REG-{re.sub(r'[^A-Za-z0-9]+', '-', title)[:60].strip('-')}",
            "kind": "regulatory_reference",
            "section": f"Regulatory references / {issuer or 'general'}",
            "title": title,
            "text": f"{issuer} — {title}. Source: {url}",
            "url": url,
            "issuer": issuer,
        })

    # -------------------------------------------------- answer + guidance ----
    answer = sections.get("Answer Format", "")
    (PATHS.policy / "answer_format.md").write_text(
        "# Answer Format\n\n" + answer, encoding="utf-8")
    things = ""
    if "## Things to know" in body:
        things = body.split("## Things to know", 1)[1].split("## Rules", 1)[0]
        chunks.append({
            "doc_id": "GUIDE-THINGS-TO-KNOW",
            "kind": "guidance",
            "section": "Things to know",
            "title": "Investigation guidance from the dataset authors",
            "text": things.strip(),
        })
    (PATHS.policy / "guidance.md").write_text("# Things to know\n\n" + things.strip(),
                                              encoding="utf-8")

    out = PATHS.policy / "chunks.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    log(f"wrote {out} ({len(chunks)} chunks)")
    by_kind: dict[str, int] = {}
    for c in chunks:
        by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
    log(f"chunk kinds: {by_kind}")


if __name__ == "__main__":
    main()

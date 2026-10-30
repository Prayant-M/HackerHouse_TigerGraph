"""Someone else's *graph* schema (C13 on graphs): validate a foreign GSQL schema
and work out how it maps onto our canonical fraud model, with evidence.

Input: a GSQL file that creates a graph (CREATE GRAPH + a schema-change job
with ADD VERTEX / ADD EDGE). Output, per file:

1. **Validation** — every edge endpoint is a declared vertex, no duplicate
   type or reverse-edge names, primary-id types, names that collide with GSQL
   keywords, and semantic smells a fraud agent cares about (timestamps stored
   as strings, money as non-numeric, no time-of-day anywhere).
2. **Mapping** — each canonical concept (Person, Account, Transaction, Device,
   IPAddress, LoginEvent, Beneficiary, Card, Merchant, InvestigationCase) to a
   vertex type, a filtered vertex type, an attribute, or `unmapped`; each
   canonical edge to a schema edge, its reverse, or a multi-hop path; each key
   attribute to a schema attribute. Every choice carries its evidence: the
   name tokens (with ISO 20022 / BIAN / T24 abbreviations expanded), the
   attributes that support it, the structural reason, and the traps rejected.
3. **Score** — when the file carries an "Expected mapping (ground truth)"
   block, the mapping is scored against it, line by line.

    python ingest/graph_schema_mapper.py schemas/*.gsql
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

# ------------------------------------------------------------------ parse ----
@dataclass
class Vertex:
    name: str
    pk: tuple[str, str]
    attrs: dict[str, str]


@dataclass
class Edge:
    name: str
    directed: bool
    pairs: list[tuple[str, str]]
    attrs: dict[str, str]
    reverse: str = ""


@dataclass
class Schema:
    graph: str
    vertices: dict[str, Vertex] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)
    truth: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


_ATTR = re.compile(r"(\w+)\s+(STRING|INT|UINT|DOUBLE|FLOAT|BOOL|DATETIME|LIST<\w+>|SET<\w+>)"
                   r"(?:\s+DEFAULT\s+\S+)?", re.I)


def parse(path: Path) -> Schema:
    text = path.read_text(encoding="utf-8")
    g = re.search(r"CREATE\s+GRAPH\s+(\w+)", text)
    s = Schema(graph=g.group(1) if g else path.stem)
    body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    for m in re.finditer(r"ADD\s+VERTEX\s+(\w+)\s*\((.*?)\)\s*(WITH[^;]*)?;", body, re.S | re.I):
        name, inner = m.group(1), m.group(2)
        pk = re.search(r"PRIMARY_ID\s+(\w+)\s+(\w+)", inner, re.I)
        attrs = {a: t.upper() for a, t in _ATTR.findall(re.sub(r"PRIMARY_ID\s+\w+\s+\w+,?", "", inner))}
        if name in s.vertices:
            s.problems.append(f"duplicate vertex type {name}")
        s.vertices[name] = Vertex(name, (pk.group(1), pk.group(2).upper()) if pk else ("", ""), attrs)
    for m in re.finditer(r"ADD\s+(DIRECTED|UNDIRECTED)\s+EDGE\s+(\w+)\s*\((.*?)\)\s*"
                         r"(WITH\s+REVERSE_EDGE\s*=\s*\"(\w+)\")?\s*;", body, re.S | re.I):
        kind, name, inner, _, rev = m.groups()
        pairs = re.findall(r"FROM\s+(\w+)\s*,\s*TO\s+(\w+)", inner, re.I)
        rest = re.sub(r"FROM\s+\w+\s*,\s*TO\s+\w+\s*\|?", "", inner, flags=re.I)
        attrs = {a: t.upper() for a, t in _ATTR.findall(rest)}
        if name in s.edges:
            s.problems.append(f"duplicate edge type {name}")
        s.edges[name] = Edge(name, kind.upper() == "DIRECTED", pairs, attrs, rev or "")
    s.truth = parse_truth(text)
    return s


def parse_truth(text: str) -> list[dict]:
    out, on = [], False
    for line in text.splitlines():
        if "Expected mapping" in line:
            on = True
            continue
        if not on:
            continue
        if not line.startswith("#"):
            break
        m = re.match(r"#\s{2,}(\S+(?:,\s*\S+)*)\s+(exact|approximate|unmapped)\s*(.*)$", line)
        if m:
            for concept in re.split(r",\s*", m.group(1)):
                out.append({"concept": concept, "kind": m.group(2), "target": m.group(3).strip()})
        elif out and line.strip("# ").strip():
            out[-1]["target"] += " " + line.strip("# ").strip()
    return out


# --------------------------------------------------------------- validate ----
# TigerGraph GSQL reserved words: a type or attribute with one of these names is
# rejected by the DDL parser (checked live: CUSTOMER.TARGET fails, TARGET_MARKET loads)
GSQL_KEYWORDS = {"accum", "and", "any", "as", "asc", "avg", "bag", "batch", "between", "bool", "both", "break", "by", "case", "catch", "coalesce", "compress", "continue", "count", "create", "datetime", "datetime_add", "datetime_sub", "delete", "desc", "distributed", "do", "double", "edge", "else", "end", "escape", "exception", "false", "file", "filter", "float", "foreach", "for", "from", "graph", "group", "having", "if", "in", "insert", "int", "interpret", "intersect", "interval", "into", "is", "isempty", "jsonarray", "jsonobject", "lasthop", "leading", "like", "limit", "list", "loadaccum", "log", "map", "max", "min", "minus", "not", "now", "null", "offset", "or", "order", "path", "per", "pinned", "post_accum", "primary_id", "print", "query", "raise", "range", "replace", "return", "returns", "sample", "select", "selectvertex", "set", "static", "string", "sum", "target", "to_csv", "to_datetime", "trailing", "trim", "true", "try", "tuple", "typedef", "uint", "union", "update", "values", "vertex", "when", "where", "while", "with"}


def validate(s: Schema) -> dict:
    problems, warnings = list(s.problems), []
    names = set(s.vertices)
    rev_names = set()
    for e in s.edges.values():
        for a in e.attrs:
            if a.lower() in GSQL_KEYWORDS:
                problems.append(f"edge {e.name}.{a} is a GSQL reserved word")
        for a, b in e.pairs:
            for v in (a, b):
                if v not in names:
                    problems.append(f"edge {e.name}: endpoint {v} is not a declared vertex type")
        if e.reverse:
            if e.reverse in s.edges or e.reverse in names or e.reverse in rev_names:
                problems.append(f"reverse edge name {e.reverse} collides with another type")
            rev_names.add(e.reverse)
        if not e.directed and e.reverse:
            problems.append(f"undirected edge {e.name} declares a reverse edge")
    for n in list(names) + list(s.edges) + list(rev_names):
        if n.lower() in GSQL_KEYWORDS:
            problems.append(f"type name {n} is a GSQL keyword")
    for v in s.vertices.values():
        for a in v.attrs:
            if a.lower() in GSQL_KEYWORDS:
                problems.append(f"{v.name}.{a} is a GSQL reserved word: the schema-change job "
                                f"will be rejected (rename it, e.g. {a}_CODE)")
        if v.pk[1] not in {"STRING", "INT", "UINT"}:
            problems.append(f"{v.name}: primary id type {v.pk[1]} is not STRING/INT/UINT")
        if v.pk[1] in {"INT", "UINT"}:
            warnings.append(f"{v.name}: INT primary id {v.pk[0]} — ids must be cast when joined "
                            f"to string ids from other systems")
        for a, t in v.attrs.items():
            tok = tokens(a)
            if t == "STRING" and tok & {"date", "time", "datetime", "timestamp"}:
                warnings.append(f"{v.name}.{a}: a date/time stored as STRING (needs parsing; "
                                f"as_of filters cannot use it directly)")
            if t not in {"DOUBLE", "FLOAT", "INT"} and tok & {"amount"} and "currency" not in tok:
                warnings.append(f"{v.name}.{a}: an amount stored as {t}")
    orphan = [v for v in names if not any(v in p for e in s.edges.values() for p in e.pairs)]
    for v in orphan:
        warnings.append(f"vertex type {v} has no edges")
    has_time = any(t == "DATETIME" and tokens(a) & {"time", "datetime", "timestamp", "dttm"}
                   for v in s.vertices.values() for a, t in v.attrs.items())
    if not has_time:
        warnings.append("no DATETIME attribute with a time of day anywhere: event ordering "
                        "and the temporal wall must parse strings")
    return {"ok": not problems, "problems": problems, "warnings": warnings,
            "n_vertices": len(s.vertices), "n_edges": len(s.edges)}


# ----------------------------------------------------------------- tokens ----
ABBREV = {
    # ISO 20022
    "dbtr": "debtor payer", "cdtr": "creditor payee", "pty": "party", "cshacct": "cash account",
    "acct": "account", "agt": "agent bank", "ultmt": "ultimate", "trf": "transfer",
    "tx": "transaction", "txinf": "transaction return", "inf": "information", "pmt": "payment",
    "pmtinf": "payment order initiation", "cdttrftxinf": "credit transfer transaction",
    "amt": "amount", "sttlm": "settlement", "intrbk": "interbank", "dt": "date", "dttm": "datetime",
    "cre": "creation", "tm": "time", "nm": "name", "sts": "status", "ccy": "currency", "ownr": "owner",
    "svcr": "servicer", "cstmr": "customer", "rtr": "return", "rgltry": "regulatory",
    "rptg": "reporting", "opng": "opening", "accptnc": "acceptance", "instd": "instructed",
    "svclvl": "service level", "lclinstrm": "local instrument", "prvtid": "private id",
    "pstladr": "postal address", "grphdr": "group header", "aml": "aml", "alrt": "alert",
    "ind": "indicator", "bicfi": "bic", "finInstnid": "institution", "orgnl": "original",
    "id": "id", "schmenm": "scheme", "cd": "code", "nidn": "national id",
    # T24
    "ft": "funds transfer", "tt": "teller cash", "dr": "debit", "cr": "credit", "dao": "officer",
    "stmt": "statement ledger", "eb": "electronic banking", "ben": "beneficiary",
    "no": "number", "ref": "reference", "kyc": "kyc", "lcy": "local currency",
    "fcy": "foreign currency", "pan": "card number", "msecs": "time",
    # generic
    "txn": "transaction", "ip": "ip address", "mcc": "merchant category", "pos": "point of sale",
    "iban": "iban account", "bic": "bic bank", "dob": "birth date",
}


def tokens(name: str) -> set[str]:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    out: set[str] = set()
    for t in re.split(r"[^A-Za-z0-9]+", s):
        t = t.lower()
        if not t:
            continue
        out.add(t)
        if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
            out.add(t[:-1])  # Debits -> debit, Credits -> credit
        if t in ABBREV:
            out.update(ABBREV[t].split())
    whole = re.sub(r"[^a-z]", "", name.lower())
    if whole in ABBREV:
        out.update(ABBREV[whole].split())
    return out


def vtokens(v: Vertex) -> set[str]:
    t = tokens(v.name)
    for a in v.attrs:
        t |= {f"@{x}" for x in tokens(a)}
    return t


# ---------------------------------------------------------------- concepts ----
CONCEPTS = {
    "Person": {"name": {"party", "customer", "person", "individual", "client"},
               "attr": {"birth", "dob", "nationality", "residence", "legal", "kyc", "verification"},
               "not": {"plan", "officer", "user", "beneficiary", "relationship", "authentication",
                       "address", "contact", "private"}},
    "Account": {"name": {"account", "facility", "acct"},
                "attr": {"iban", "currency", "opening", "balance", "status", "start"},
                "not": {"officer", "plan", "user", "statement", "ledger"}},
    "Transaction": {"name": {"transfer", "transaction", "execution", "payment", "teller"},
                    "attr": {"amount", "settlement", "date", "datetime", "currency"},
                    "not": {"order", "initiation", "return", "statement", "ledger", "entry",
                            "header", "card", "diagnosis", "authentication"}},
    "Card": {"name": {"card", "issued"}, "attr": {"card", "scheme", "expiry", "pan", "masked"},
             "not": {"transaction", "access"}},
    "Device": {"name": {"device", "terminal"}, "attr": {"fingerprint", "operating", "os"},
               "not": {"issued", "allocation", "card"}},
    "IPAddress": {"name": {"network", "ip"}, "attr": {"ip", "geolocation", "anonymizer"},
                  "not": set()},
    "LoginEvent": {"name": {"authentication", "login", "sign", "protocol", "session"},
                   "attr": {"authentication", "channel", "method", "result", "terminal"},
                   "not": {"activity", "history"}},
    "Merchant": {"name": {"merchant", "acquirer"}, "attr": {"merchant", "category"}, "not": set()},
    "InvestigationCase": {"name": {"case", "investigation"}, "attr": {"case", "status", "resolution"},
                          "not": {"diagnosis", "assessment", "reporting", "alert"}},
    "Beneficiary": {"name": {"beneficiary", "counterparty", "payee"},
                    "attr": {"beneficiary", "bic", "sort"}, "not": set()},
}


def score_vertex(v: Vertex, concept: str, s: Schema) -> tuple[float, list[str]]:
    c = CONCEPTS[concept]
    nt, at = tokens(v.name), {x[1:] for x in vtokens(v) if x.startswith("@")}
    why, sc = [], 0.0
    hit = nt & c["name"]
    if hit:
        sc += 2.0
        why.append(f"name tokens {sorted(hit)}")
    ahit = at & c["attr"]
    if ahit:
        sc += 0.4 * min(len(ahit), 4)
        why.append(f"attributes {sorted(ahit)}")
    bad = nt & c["not"]
    if bad:
        sc -= 2.5
        why.append(f"rejected cues {sorted(bad)}")
    if concept == "Transaction":
        money = [a for a, t in v.attrs.items() if t in {"DOUBLE", "FLOAT"} and "amount" in tokens(a)]
        acct_edges = sum(1 for e in s.edges.values() for a, b in e.pairs
                         if (a == v.name or b == v.name) and tokens(b if a == v.name else a)
                         & {"account", "facility"})
        if money:
            sc += 1.0
            why.append(f"money attribute {money[0]}")
        if acct_edges >= 2:
            sc += 1.0
            why.append(f"{acct_edges} edges to accounts (debit and credit sides)")
        if any(tokens(a) & {"original"} for a in v.attrs):
            sc -= 1.5
            why.append("refers to an original transaction (a return)")
    if concept == "Person" and any(t in {"DATETIME", "STRING"} and tokens(a) & {"birth"}
                                   for a, t in v.attrs.items()):
        sc += 1.0
        why.append("has a date of birth")
    return sc, why


def map_concepts(s: Schema) -> dict:
    out = {}
    for concept in CONCEPTS:
        ranked = sorted(((score_vertex(v, concept, s), v.name) for v in s.vertices.values()),
                        key=lambda x: -x[0][0])
        best = [(n, sc, why) for (sc, why), n in ranked if sc >= 2.2]
        if concept in {"Account", "Transaction"} and len(best) > 1:
            # several vertex types can play one concept (current + savings;
            # funds transfer + teller); keep all within 1.0 of the best
            top = best[0][1]
            best = [b for b in best if b[1] >= top - 1.0 and b[1] >= 3.0]
        if best:
            out[concept] = {"kind": "vertex", "targets": [b[0] for b in best[:3]],
                            "score": round(best[0][1], 2), "evidence": best[0][2]}
        else:
            out[concept] = {"kind": "unmapped", "targets": [], "evidence": []}
    _role_filters(s, out)
    _attribute_fallbacks(s, out)
    _card_payments(s, out)
    return out


def _card_payments(s: Schema, out: dict) -> None:
    """Card payments are often their own event type (BIAN CardTransaction):
    an event with an amount and a time that points at the card. It joins
    Transaction as an approximate member."""
    if out["Transaction"]["kind"] == "unmapped" or out["Card"]["kind"] != "vertex":
        return
    cards = set(out["Card"]["targets"])
    for v in s.vertices.values():
        if v.name in out["Transaction"]["targets"]:
            continue
        tk = tokens(v.name) | {x for a in v.attrs for x in tokens(a)}
        money = any(t in {"DOUBLE", "FLOAT"} and "amount" in tokens(a) for a, t in v.attrs.items())
        to_card = any(v.name == a and b in cards for e in s.edges.values() for a, b in e.pairs)
        if money and to_card and "transaction" in tokens(v.name) and not tk & {"original", "return"}:
            out["Transaction"]["targets"].append(v.name)
            out["Transaction"].setdefault("approximate", []).append(v.name)
            out["Transaction"]["evidence"].append(
                f"{v.name} added as card payments (amount + edge to {sorted(cards)[0]})")


def _role_filters(s: Schema, out: dict) -> None:
    """One party type for customers and counterparties: Person and Beneficiary
    become filters on it."""
    party = next((v for v in s.vertices.values() if tokens(v.name) & {"party"}), None)
    if party is None:
        return
    flag = next((a for a, t in party.attrs.items() if t == "BOOL" and tokens(a) & {"customer"}), None)
    ptype = next((a for a in party.attrs if tokens(a) & {"type"} and tokens(a) & {"party"}), None)
    if out["Person"]["targets"] == [party.name] or not out["Person"]["targets"]:
        if flag:
            out["Person"] = {"kind": "filtered vertex", "targets": [party.name],
                             "filter": f"{flag} = true",
                             "evidence": [f"{party.name} holds every party; {flag} separates "
                                          f"customers from external parties"]}
        elif ptype:
            out["Person"] = {"kind": "filtered vertex", "targets": [party.name],
                             "filter": f"{ptype} in (Individual, Organisation)",
                             "evidence": [f"{party.name} holds every party; {ptype} separates "
                                          f"customers from counterparties"]}
    if out["Beneficiary"]["kind"] == "unmapped" or out["Beneficiary"]["targets"] == [party.name]:
        if flag:
            out["Beneficiary"] = {"kind": "filtered vertex (approximate)", "targets": [party.name],
                                  "filter": f"{flag} = false, reached by the creditor edge",
                                  "evidence": ["beneficiary is a role of a party, not a type"]}
        elif ptype:
            out["Beneficiary"] = {"kind": "filtered vertex (approximate)", "targets": [party.name],
                                  "filter": f"{ptype} = Counterparty",
                                  "evidence": ["counterparties are directory entries too"]}


def _attribute_fallbacks(s: Schema, out: dict) -> None:
    """A concept with no vertex type may still exist as an attribute (T24 keeps
    the terminal and IP address on the PROTOCOL record)."""
    for concept, cues in (("Device", {"terminal", "device"}), ("IPAddress", {"ip"})):
        if out[concept]["kind"] != "unmapped":
            continue
        for v in s.vertices.values():
            for a in v.attrs:
                if tokens(a) & cues and not tokens(a) & {"hash", "issued"}:
                    out[concept] = {"kind": "attribute (approximate)",
                                    "targets": [f"{v.name}.{a}"],
                                    "evidence": [f"no {concept} vertex type; {v.name}.{a} "
                                                 f"carries it per event"]}
                    break
            if out[concept]["kind"] != "unmapped":
                break


# ------------------------------------------------------------------- edges ----
EDGE_SPEC = {
    "OWNS": ("Person", "Account", {"owner", "holder", "customer", "plan", "covers", "relationship"},
             {"officer", "company"}),
    "INITIATED": ("Account", "Transaction", {"debit", "debtor", "dbtr"},
                  {"ultimate", "order", "charges"}),
    "PAYS_TO_ACCOUNT": ("Transaction", "Account", {"credit", "creditor", "cdtr", "credits"},
                        {"ultimate"}),
    "PAYS": ("Transaction", "Beneficiary", {"beneficiary", "creditor", "counterparty", "cdtr"},
             {"ultimate", "account", "acct", "agent"}),
    "FROM_DEVICE": ("Transaction", "Device", {"device"}, set()),
    "FROM_IP": ("Transaction", "IPAddress", {"address", "ip"}, set()),
    "AT": ("Transaction", "Merchant", {"merchant"}, set()),
    "VIA": ("Transaction", "Card", {"device", "card", "uses"}, set()),
    "HOLDS": ("Account", "Card", {"issued", "card", "facility"}, set()),
    "LOGGED_IN": ("LoginEvent", "Account", {"party", "user", "authentication"}, set()),
    "LOGIN_FROM_DEVICE": ("LoginEvent", "Device", {"device", "used"}, set()),
    "LOGIN_FROM_IP": ("LoginEvent", "IPAddress", {"address", "from"}, set()),
    "INVESTIGATED_IN": ("Account", "InvestigationCase", {"case", "concerns"}, set()),
}


def adjacency(s: Schema) -> dict[str, list[tuple[str, str, str]]]:
    """vertex -> [(neighbour, edge_name, direction)] with reverse edges named."""
    adj: dict[str, list] = defaultdict(list)
    for e in s.edges.values():
        for a, b in e.pairs:
            adj[a].append((b, e.name, "fwd"))
            back = e.reverse or e.name if (e.reverse or not e.directed) else None
            if back:
                adj[b].append((a, back, "rev"))
    return adj


def find_paths(s: Schema, src: set[str], dst: set[str], max_hops: int = 4) -> list[list[tuple]]:
    adj = adjacency(s)
    out = []
    frontier = [[(x, None, None)] for x in src]
    for _ in range(max_hops):
        nxt = []
        for path in frontier:
            here = path[-1][0]
            for nb, ename, d in adj.get(here, []):
                if any(nb == p[0] for p in path):
                    continue
                np_ = path + [(nb, ename, d)]
                if nb in dst:
                    out.append(np_)
                else:
                    nxt.append(np_)
        frontier = nxt
    return out


def map_edges(s: Schema, concepts: dict) -> dict:
    def tset(c):
        t = concepts[c]["targets"]
        return {x.split(".")[0] for x in t} if concepts[c]["kind"] != "unmapped" else set()

    out = {}
    for ename, (a, b, good, bad) in EDGE_SPEC.items():
        src, dst = tset(a), tset(b)
        if not src or not dst or concepts[a]["kind"].startswith("attribute") or \
                concepts[b]["kind"].startswith("attribute"):
            out[ename] = {"kind": "unmapped", "path": [],
                          "evidence": [f"{a} or {b} is unmapped or only an attribute"]}
            continue
        paths = find_paths(s, src, dst)
        if src == dst:
            paths = [p for p in paths if len(p) > 1]
        scored = []
        for p in paths:
            names = [x[1] for x in p[1:]]
            tk = set().union(*(tokens(n) for n in names))
            sc = 2.0 * len(tk & good) - 3.0 * len(tk & bad) - 0.8 * (len(names) - 1)
            scored.append((sc, p))
        scored.sort(key=lambda x: -x[0])
        if not scored or scored[0][0] < 0:
            out[ename] = {"kind": "unmapped", "path": [],
                          "evidence": ["no path whose edge names support it"]}
            continue
        sc, p = scored[0]
        hops = [x[1] for x in p[1:]]
        # equally supported one-hop alternatives are kept too (owner + joint
        # holder; funds transfer + teller both debiting an account)
        also, seen_pairs = [], {(p[0][0], p[-1][0])}
        for s2, q in scored[1:]:
            if len(q) != 2 or len(p) != 2 or s2 < 0:
                continue
            pair = (q[0][0], q[-1][0])
            if pair == (p[0][0], p[-1][0]):
                if s2 == sc and q[1][1] not in hops:
                    also.append(q)
                continue
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)  # best edge for another source/target type
            if q[1][1] not in hops and q[1][1] not in {x[1][1] for x in also}:
                also.append(q)
        for q in also:
            hops.append(q[1][1])
        rejected = [" -> ".join(x[1] for x in q[1:]) for s2, q in scored[1:4]
                    if s2 < sc and q[1][1] not in hops]
        out[ename] = {"kind": "exact" if len(p) == 2 else "path", "path": hops,
                      "vertices": [x[0] for x in p] + [q[0][0] for q in also],
                      "score": round(sc, 2),
                      "evidence": [f"{len(p) - 1} hop(s) from {a} to {b}: "
                                   f"{' -> '.join(x[1] for x in p[1:])}"]
                      + ([f"also: {', '.join(q[1][1] for q in also)}"] if also else [])
                      + ([f"rejected: {', '.join(rejected)}"] if rejected else [])}
    return out


# -------------------------------------------------------------- attributes ----
ATTR_SPEC = {
    "Transaction.amount": ("Transaction", {"amount"}, {"instructed", "credit", "fcy", "order"},
                           {"DOUBLE", "FLOAT"}),
    "Transaction.timestamp": ("Transaction", {"datetime", "time", "acceptance", "date"},
                              {"value", "settlement", "processing"}, None),
    "Transaction.channel": ("Transaction", {"mechanism", "channel", "service", "type", "code"},
                            {"category", "purpose"}, None),
    "Account.open_date": ("Account", {"opening", "start"}, set(), None),
    "Account.status": ("Account", {"status", "restrict", "sts"}, set(), None),
    "Person.kyc_verified_at": ("Person", {"verification", "kyc", "review"}, {"complete"}, None),
}


def map_attributes(s: Schema, concepts: dict) -> dict:
    out = {}
    for key, (concept, good, bad, types) in ATTR_SPEC.items():
        best = None
        for vt in concepts[concept]["targets"] if concepts[concept]["kind"] != "unmapped" else []:
            v = s.vertices.get(vt.split(".")[0])
            if not v:
                continue
            for a, t in v.attrs.items():
                tk = tokens(a)
                sc = 2.0 * len(tk & good) - 2.5 * len(tk & bad)
                if types and t in types:
                    sc += 1.0
                if key == "Transaction.timestamp" and t == "DATETIME":
                    sc += 1.0
                if key == "Transaction.timestamp" and "time" in tk:
                    sc += 1.0
                if sc > 0 and (best is None or sc > best[0]):
                    best = (sc, f"{v.name}.{a}", t)
        out[key] = ({"kind": "attribute", "target": best[1], "type": best[2],
                     "note": "stored as STRING: needs parsing" if best[2] == "STRING" and
                     ("date" in key or "timestamp" in key) else ""}
                    if best else {"kind": "unmapped", "target": ""})
    # account_under_investigation: a case edge, else a flag, else a block code
    case = concepts["InvestigationCase"]
    if case["kind"] == "vertex":
        accts = set(concepts["Account"]["targets"])
        e = next((e.name for e in s.edges.values() for a, b in e.pairs
                  if a in case["targets"] and b in accts), None)
        out["account_under_investigation"] = {"kind": "edge", "target": e or "",
                                              "note": "from an open case"}
    else:
        flag = next((f"{v.name}.{a}" for v in s.vertices.values() for a, t in v.attrs.items()
                     if tokens(a) & {"aml", "alert", "restrict", "block"} and
                     tokens(v.name) & {"account", "acct", "cash"}), None)
        out["account_under_investigation"] = ({"kind": "attribute (approximate)", "target": flag,
                                               "note": "a flag / block code, not a case"}
                                              if flag else {"kind": "unmapped", "target": ""})
    _extra_attributes(s, concepts, out)
    return out


def _vertices_of(s: Schema, concepts: dict, concept: str) -> list[Vertex]:
    m = concepts[concept]
    if m["kind"] == "unmapped" or m["kind"].startswith("attribute"):
        return []
    return [s.vertices[t] for t in m["targets"] if t in s.vertices]


def _pick(cands: list[tuple[float, str, str]], note: str = "") -> dict:
    cands = [c for c in cands if c[0] > 0]
    if not cands:
        return {"kind": "unmapped", "target": ""}
    sc, tgt, kind = max(cands)
    return {"kind": kind, "target": tgt, "note": note}


def _extra_attributes(s: Schema, concepts: dict, out: dict) -> None:
    acct, person = _vertices_of(s, concepts, "Account"), _vertices_of(s, concepts, "Person")
    # Account.kyc_score: a numeric score; a party-level rating is approximate;
    # a YES/NO completion flag is not a score
    c = []
    for v in acct + person:
        for a, t in v.attrs.items():
            tk = tokens(a)
            if tk & {"kyc", "risk"} and tk & {"score"} and t in {"DOUBLE", "FLOAT", "INT"}:
                c.append((3.0, f"{v.name}.{a}", "attribute"))
            elif tk & {"risk"} and tk & {"rating", "class"} and not tk & {"calc", "manual"}:
                c.append((1.0, f"{v.name}.{a}", "attribute (approximate)"))
    out["Account.kyc_score"] = _pick(c, "a rating, not a score" if c and c[0][0] < 2 else "")
    # Person.anonymized_ssn_hash: a hashed national id, on the person or on an
    # identity vertex linked to it
    c = []
    for v in person:
        for a in v.attrs:
            if tokens(a) & {"identification", "ssn", "legal"} and "hash" in tokens(a):
                c.append((2.0, f"{v.name}.{a}", "attribute"))
    for v in s.vertices.values():
        if tokens(v.name) & {"private", "identity"} and any(person and p.name in pr
                                                            for e in s.edges.values()
                                                            for pr in e.pairs for p in person) \
                and any("hash" in tokens(a) for a in v.attrs):
            a = next(a for a in v.attrs if "hash" in tokens(a))
            sch = next((x for x in v.attrs if tokens(x) & {"scheme"}), None)
            c.append((2.5, f"{v.name}.{a}", "attribute (approximate)"))
            if sch:
                c[-1] = (2.5, f"{v.name}.{a} where {sch} = NIDN", "attribute (approximate)")
    out["Person.anonymized_ssn_hash"] = _pick(c)
    # Beneficiary.name_hash and bank_identifier
    ben = _vertices_of(s, concepts, "Beneficiary")
    c = [(2.0, f"{v.name}.{a}", "attribute") for v in ben for a in v.attrs
         if tokens(a) & {"name", "nm"} and "hash" in tokens(a)]
    out["Beneficiary.name_hash"] = _pick(c)
    role = concepts["Beneficiary"]["kind"].startswith("filtered")
    c = [] if role else [(2.0 + len(tokens(a) & {"bic", "sort"}), f"{v.name}.{a}", "attribute")
                         for v in ben for a in v.attrs if tokens(a) & {"bic", "sort", "bank"}]
    if not c:  # the bank is its own vertex, reached from the transfer's creditor-agent edge
        for e in s.edges.values():
            tk = tokens(e.name)
            if tk & {"creditor"} and tk & {"agent"} and not tk & {"ultimate"}:
                for _, dst in e.pairs:
                    bic = next((a for a in s.vertices[dst].attrs if "bic" in tokens(a)), None)
                    if bic:
                        c.append((2.0, f"{dst}.{bic} via {e.name}", "attribute (via edge)"))
    out["Beneficiary.bank_identifier"] = _pick(c)
    # InvestigationCase.status
    case = _vertices_of(s, concepts, "InvestigationCase")
    c = [(2.0, f"{v.name}.{a}", "attribute") for v in case for a in v.attrs if "status" in tokens(a)]
    out["InvestigationCase.status"] = _pick(c)


# ------------------------------------------------------------------- score ----
def score_against_truth(s: Schema, concepts: dict, edges: dict, attrs: dict) -> dict:
    """Score each prediction against the ground-truth line in the file header.

    Concepts: the predicted vertex types must all be ones the truth names
    (types the truth mentions only to rule out, "(not X)", do not count).
    Edges: a predicted edge the truth names, or a path through every vertex
    type the truth names when it gives a path of types. Attributes: the
    predicted attribute's name appears in the truth line.
    """
    rows = []
    vnames = set(s.vertices)
    enames = set(s.edges) | {e.reverse for e in s.edges.values() if e.reverse}
    for t in s.truth:
        c = t["concept"]
        text = re.sub(r"\(not [^)]*\)", "", t["target"])
        text = re.sub(r"not\s+\w+", "", text)
        words = set(re.findall(r"[A-Za-z_][\w]*", text))
        want_v, want_e = words & vnames, words & enames
        if c in concepts:
            got = concepts[c]
            pv = {x.split(".")[0] for x in got["targets"]}
            if t["kind"] == "unmapped":
                ok = got["kind"] == "unmapped"
            elif got["kind"].startswith("attribute"):
                ok = any(x.split(".")[-1] in words for x in got["targets"])
            else:
                ok = bool(pv) and pv <= want_v
            pred = f"{got['kind']}: {', '.join(got['targets']) or '—'}" + (
                f" [{got['filter']}]" if got.get("filter") else "")
        elif c in edges:
            got = edges[c]
            if t["kind"] == "unmapped":
                ok = got["kind"] == "unmapped"
            elif want_e:
                def base(x: str) -> str:
                    return x[len("reverse_"):] if x.startswith("reverse_") else x
                we, gp = {base(x) for x in want_e}, [base(x) for x in got["path"]]
                ok = bool(set(gp) & we) and (got["kind"] == "path" or set(gp) <= we)
            else:
                ok = got["kind"] != "unmapped" and want_v <= set(got.get("vertices", []))
            pred = f"{got['kind']}: {' -> '.join(got['path']) or '—'}"
        else:
            got = attrs.get(c)
            if got is None:
                rows.append({**t, "predicted": "not attempted", "ok": None})
                continue
            if t["kind"] == "unmapped":
                ok = got["kind"] == "unmapped"
            else:
                tgt = (got.get("target") or "").split(" ")[0]
                attr = tgt.split(".")[-1]
                ok = bool(attr) and (attr in words or any(attr.endswith("_" + w) for w in words))
            pred = f"{got['kind']}: {got.get('target') or '—'}" + (
                f" ({got['note']})" if got.get("note") else "")
        rows.append({**t, "predicted": pred, "ok": ok})
    scored = [r for r in rows if r["ok"] is not None]
    return {"rows": rows, "n": len(scored), "correct": sum(1 for r in scored if r["ok"]),
            "not_attempted": [r["concept"] for r in rows if r["ok"] is None]}


# -------------------------------------------------------------------- main ----
def run(path: Path) -> dict:
    s = parse(path)
    val = validate(s)
    concepts = map_concepts(s)
    edges = map_edges(s, concepts)
    attrs = map_attributes(s, concepts)
    sc = score_against_truth(s, concepts, edges, attrs)
    return {"file": str(path), "graph": s.graph, "validation": val, "concepts": concepts,
            "edges": edges, "attributes": attrs, "score": sc,
            "vertices": {v.name: {"pk": v.pk, "attrs": v.attrs} for v in s.vertices.values()},
            "edge_types": {e.name: {"directed": e.directed, "pairs": e.pairs, "reverse": e.reverse}
                           for e in s.edges.values()}}


def report(results: list[dict]) -> str:
    md = ["# Foreign graph schemas — validation and mapping", "",
          "Generated by `python ingest/graph_schema_mapper.py`. Each schema is parsed, validated, "
          "mapped onto the canonical fraud model with evidence, and scored against the ground "
          "truth in its own header.", "",
          "| schema | graph | vertex types | edge types | validation | mapping vs ground truth |",
          "|---|---|--:|--:|---|--:|"]
    for r in results:
        v, sc = r["validation"], r["score"]
        md.append(f"| `{Path(r['file']).name}` | {r['graph']} | {v['n_vertices']} | {v['n_edges']} | "
                  f"{'OK' if v['ok'] else 'PROBLEMS: ' + str(len(v['problems']))} "
                  f"({len(v['warnings'])} warnings) | **{sc['correct']}/{sc['n']}** |")
    for r in results:
        md += ["", f"## {r['graph']} (`{Path(r['file']).name}`)", "", "### Validation", ""]
        md += [f"- **problem:** {p}" for p in r["validation"]["problems"]] or ["- no structural problems"]
        md += [f"- warning: {w}" for w in r["validation"]["warnings"]]
        lv = r.get("live")
        if lv:
            md += ["", "### Live check in TigerGraph", ""]
            if not lv.get("ran"):
                md.append(f"- not run: {lv.get('reason')}")
            else:
                md.append(f"- file run unchanged: **{'accepted' if lv.get('ok') else 'NOT accepted'}**; "
                          f"TigerGraph built {lv.get('vertex_types')} vertex and "
                          f"{lv.get('edge_types')} edge types; test graph dropped: {lv.get('dropped')}")
                md += [f"- error: {x}" for x in lv.get("errors", [])]
                md += [f"- difference: {x}" for x in lv.get("diffs", [])]
                if lv.get("ok"):
                    md.append("- every vertex attribute type, edge endpoint pair and reverse-edge "
                              "name matches what the parser read")
        md += ["", "### Mapping vs ground truth", "",
               "| concept | expected | predicted | match |", "|---|---|---|---|"]
        for row in r["score"]["rows"]:
            mark = "✅" if row["ok"] else ("—" if row["ok"] is None else "❌")
            md.append(f"| {row['concept']} | {row['kind']}: {row['target'][:70]} | "
                      f"{row['predicted'][:80]} | {mark} |")
        md += ["", "### Evidence for the concept choices", ""]
        for c, m in r["concepts"].items():
            md.append(f"- **{c}** → {m['kind']} {', '.join(m['targets']) or ''}"
                      f"{' [' + m['filter'] + ']' if m.get('filter') else ''}: "
                      f"{'; '.join(m['evidence']) or 'no supporting type'}")
        md += ["", "### Edges", ""]
        for e, m in r["edges"].items():
            md.append(f"- **{e}** → {m['kind']}: {'; '.join(m['evidence'])}")
    return "\n".join(md) + "\n"


def live_check(path: Path, s: Schema) -> dict:
    """Run the file unchanged in TigerGraph, read back the schema TigerGraph
    built, compare it with what the parser read, then drop the graph. A graph
    that already exists is never touched."""
    sys.path.insert(0, str(ROOT / "graph"))
    from install import connect  # noqa: E402

    import time

    def retry(fn, *a):
        # Savanna's DNS name occasionally fails to resolve for a few seconds
        for i in range(6):
            try:
                return fn(*a)
            except Exception as exc:  # noqa: BLE001
                if i == 5 or not re.search(r"NameResolution|Connection|Timeout", str(exc)):
                    raise
                time.sleep(5 * (i + 1))

    conn = retry(connect)
    gsql = lambda text: retry(conn.gsql, text)  # noqa: E731
    existing = gsql("SHOW GRAPH *")
    if re.search(rf"\b{s.graph}\b", existing or ""):
        return {"ran": False, "reason": f"graph {s.graph} already exists; not touched"}
    out = gsql(path.read_text(encoding="utf-8"))
    res = {"ran": True, "gsql_output_tail": out[-600:],
           "errors": [l for l in out.splitlines() if re.search(r"error|fail|invalid|conflict", l, re.I)
                      and not re.search(r"failed: 0", l)]}
    try:
        conn.graphname = s.graph
        sch = retry(lambda: conn.getSchema(force=True))
        got_v = {v["Name"]: {a["AttributeName"]: a["AttributeType"]["Name"].upper()
                             for a in v["Attributes"]} for v in sch.get("VertexTypes", [])}
        got_e = {e["Name"]: e for e in sch.get("EdgeTypes", [])}
        diffs = []
        for n, v in s.vertices.items():
            if n not in got_v:
                diffs.append(f"vertex {n} missing in TigerGraph")
                continue
            for a, t in v.attrs.items():
                if got_v[n].get(a) != t:
                    diffs.append(f"{n}.{a}: parsed {t}, TigerGraph {got_v[n].get(a)}")
        for n, e in s.edges.items():
            ge = got_e.get(n)
            if ge is None:
                diffs.append(f"edge {n} missing in TigerGraph")
                continue
            pairs = {(p["From"], p["To"]) for p in ge.get("EdgePairs", [])} or \
                {(ge["FromVertexTypeName"], ge["ToVertexTypeName"])}
            if pairs != set(e.pairs):
                diffs.append(f"edge {n}: parsed {sorted(e.pairs)}, TigerGraph {sorted(pairs)}")
            rev = (ge.get("Config") or {}).get("REVERSE_EDGE", "")
            if e.reverse and rev != e.reverse:
                diffs.append(f"edge {n}: reverse parsed {e.reverse}, TigerGraph {rev}")
        res.update({"vertex_types": len(got_v), "edge_types": len(got_e), "diffs": diffs,
                    "ok": not res["errors"] and not diffs and len(got_v) == len(s.vertices)
                    and len(got_e) == len(s.edges)})
    finally:
        conn.graphname = None
        drop = gsql(f"DROP GRAPH {s.graph}")
        res["dropped"] = "dropped" in drop.lower() or "successfully" in drop.lower()
        res["drop_output"] = drop[-200:]
    return res


def main() -> int:
    args = sys.argv[1:]
    live = "--live" in args
    paths = [Path(p) for p in args if p != "--live"] or sorted((ROOT / "schemas").glob("*.gsql"))
    results = [run(p) for p in paths]
    if live:
        for r, p in zip(results, paths):
            r["live"] = live_check(p, parse(p))
            lv = r["live"]
            print(f"{r['graph']:<16} live: ran={lv.get('ran')} ok={lv.get('ok')} "
                  f"v={lv.get('vertex_types')} e={lv.get('edge_types')} "
                  f"errors={len(lv.get('errors', []))} diffs={len(lv.get('diffs', []))} "
                  f"dropped={lv.get('dropped')}")
    out = ROOT / "eval" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / "graph_schema_mapping.json").write_text(json.dumps(results, indent=1, default=str),
                                                   encoding="utf-8")
    md = report(results)
    (out / "graph_schema_mapping.md").write_text(md, encoding="utf-8")
    for r in results:
        sc, v = r["score"], r["validation"]
        print(f"{r['graph']:<16} valid={v['ok']} problems={len(v['problems'])} "
              f"warnings={len(v['warnings'])} mapping {sc['correct']}/{sc['n']}")
    return 0 if all(r["validation"]["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

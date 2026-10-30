"""Generate the three approval tokens (analyst, team lead, fraud manager).

Prints each plaintext token ONCE, to hand to a person (or a judge) on paper or
in a DM, and the `APPROVAL_TOKENS=` line holding only their SHA-256 hashes, to
paste into `.env`. Plaintext tokens are never written to disk by this script.

    python scripts/make_tokens.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fraudagent.governance.approvals import env_line, make_tokens  # noqa: E402

toks = make_tokens([("analyst-01", "analyst"), ("lead-01", "team_lead"),
                    ("manager-01", "fraud_manager")])
print("Hand these out (shown once):")
for t in toks:
    print(f"  {t['role']:<14} {t['actor_id']:<11} {t['token']}")
print("\nPaste into .env (hashes only):")
print(env_line(toks))

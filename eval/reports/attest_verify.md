# Attestation re-run

`eval/attest_verify.py` against backend `tigergraph` at 2026-10-30 14:32:10Z (597 s). Current data snapshot `bc3011b15aff8ad88490fd4e127bf3de`.

| case | attestations | calls re-run | memory growth | snapshot | result |
|---|--:|--:|--:|---|---|
| HHF-001 | 16 | 28 | 1 | same | PASS |
| HHF-002 | 14 | 29 | 1 | same | PASS |
| HHF-003 | 13 | 27 | 1 | same | PASS |
| HHF-004 | 8 | 25 | 0 | same | PASS |
| HHF-005 | 9 | 25 | 0 | same | PASS |
| HHF-006 | 10 | 25 | 0 | same | PASS |
| HHF-007 | 12 | 25 | 0 | same | PASS |
| HHF-008 | 11 | 25 | 0 | same | PASS |
| HHF-009 | 10 | 24 | 0 | same | PASS |
| HHF-010 | 11 | 24 | 0 | same | PASS |
| HHF-011 | 14 | 24 | 0 | same | PASS |
| HHF-012 | 9 | 24 | 0 | same | PASS |
| HHF-013 | 8 | 24 | 0 | same | PASS |
| HHF-014 | 11 | 24 | 0 | same | PASS |
| HHF-015 | 10 | 24 | 0 | same | PASS |
| HHF-016 | 12 | 26 | 0 | same | PASS |
| HHF-017 | 10 | 25 | 0 | same | PASS |
| HHF-018 | 11 | 25 | 0 | same | PASS |

**18 of 18 answer files pass.** "Memory growth" counts read-back calls (case_chain, compromise_watch) whose answer now includes cases written later; they are reported, not failed.

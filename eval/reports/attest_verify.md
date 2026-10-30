# Attestation re-run

`eval/attest_verify.py` against backend `tigergraph` at 2026-10-30 06:00:16Z (34 s). Current data snapshot `bc3011b15aff8ad88490fd4e127bf3de`.

| case | attestations | calls re-run | memory growth | snapshot | result |
|---|--:|--:|--:|---|---|
| HHF-001 | 13 | 26 | 0 | same | PASS |

**1 of 1 answer files pass.** "Memory growth" counts read-back calls (case_chain, compromise_watch) whose answer now includes cases written later; they are reported, not failed.

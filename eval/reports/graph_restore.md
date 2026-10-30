# Graph restore

Cases whose answer files say `written_to_graph: true` but which were missing from TigerGraph (the graph was wiped and reloaded after Round 1) were written back from their saved answer files through `case_write`, the agent's single write path. Decisions were not re-run. Each write was read back with `case_chain`. `tool_calls` is the answer file's own count (the live write recorded the store's internal call counter, which the answer file does not keep).

| case | graph id | read back | transactions | cards | SAR |
|---|---|---|--:|--:|--:|
| HHG-001 | CASE-HHG-001 | yes | 0/0 | 0/0 | 0/0 |
| HHG-002 | CASE-HHG-002 | yes | 0/0 | 0/0 | 0/0 |
| HHG-003 | CASE-HHG-003 | yes | 3/3 | 0/0 | 0/0 |
| HHG-004 | CASE-HHG-004 | yes | 1/1 | 0/0 | 0/0 |
| HHG-005 | CASE-HHG-005 | yes | 0/0 | 0/0 | 0/0 |
| HHG-006 | CASE-HHG-006 | yes | 4/4 | 0/0 | 1/1 |
| HHG-007 | CASE-HHG-007 | yes | 0/0 | 0/0 | 0/0 |
| HHG-008 | CASE-HHG-008 | yes | 6/6 | 0/0 | 0/0 |
| HHG-009 | CASE-HHG-009 | yes | 1/1 | 0/0 | 0/0 |
| HHG-010 | CASE-HHG-010 | yes | 0/0 | 0/0 | 0/0 |
| HHG-011 | CASE-HHG-011 | yes | 1/1 | 0/0 | 0/0 |
| HHG-012 | CASE-HHG-012 | yes | 0/0 | 0/0 | 0/0 |
| HHG-013 | CASE-HHG-013 | yes | 0/0 | 0/0 | 0/0 |
| HHG-016 | CASE-HHG-016 | yes | 1/1 | 0/0 | 0/0 |
| HHG-018 | CASE-HHG-018 | yes | 0/0 | 0/0 | 0/0 |
| HHG-019 | CASE-HHG-019 | yes | 1/1 | 0/0 | 0/0 |
| HHG-020 | CASE-HHG-020 | yes | 0/0 | 0/0 | 0/0 |

After restore: 38 of 38 answered cases are in the graph.

"""Tests never call a paid model.

The LLM only writes prose, and every assertion here is about decisions, so the
deterministic templates are both sufficient and reproducible. Set before any
test module builds the shared client.
"""

import os

os.environ["AGENT_USE_LLM"] = "0"

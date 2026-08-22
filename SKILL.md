---
name: etf-catcher
description: Install, configure, run, update, diagnose, and interpret the local ETF Catcher dashboard and its ETF flow, market, macro, and index data. Use for ETF Catcher setup or operations and for questions that should be answered from its local database; do not use for unrelated market analysis.
---

# ETF Catcher

Treat this skill directory as the application root. Keep the user's database, account configuration, logs, and generated web data inside this local installation.

## Route the request

- For first installation, account setup, startup, task registration, recovery, or upgrades, read [references/operations.md](references/operations.md).
- For ETF flow, category, market, global-index, or macro interpretation, read [references/data-model.md](references/data-model.md) and use `scripts/agent_query.py`; never accept or execute arbitrary SQL from a user.
- For ordinary browser use, start the service with `start.ps1` and use the URL in `config/production_baseline.json`.

## Operational invariants

- The authoritative local history starts on 2025-01-01. Web charts intentionally display 2026 onward; 2025 is retained for rolling warm-up and research history.
- Every daily run targets the latest previous complete trading day. Do not publish partial current-day data.
- After a fresh install or downtime, automatic updates must inspect only real sessions after the last successful web publication, reuse already-complete rows, collect the remaining gap chronologically, and publish the web once after the batch. Ordinary daily runs must not rescan older published history.
- Never register an automatic update earlier than 08:30 local time. iFinD prior-day fields are not considered complete before then. A later user-selected time is valid.
- Use the current Windows user's iFinD Skill and DPAPI-protected DeepSeek key. Never print, copy, commit, or transmit secrets outside their intended API calls.
- Repeated updates must remain idempotent and fill nulls without overwriting successful observations. Require 95% daily coverage; preserve the last successful web while a gap is retried, and quarantine a date after three distinct failed runs so it cannot block newer sessions forever.
- Do not change the locked ETF Catcher 1.0 page design when performing setup or operations.

## Safe interpretation

Lead with the answer and state the exact data cutoff. Distinguish ETF subscription/redemption flow from exchange turnover, financing balance, and macro indicators. Do not infer causality from correlation or present the dashboard as a guaranteed trading signal.

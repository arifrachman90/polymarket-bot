# Agent Bootstrap — Polymarket Bot

Use this file when handing the repo to a fresh AI agent on a new VPS or runtime.

## Goal
Get Bob's Polymarket setup working for live trading **without repeating old trial-and-error**.

## Read this first
1. `polymarket_bot/HANDOFF_2026-04-01.md`
2. `polymarket_bot/README.md`
3. `polymarket_bot/FULL_AUTO_SPEC.md`
4. `here-now-test/index.html` (if live board restore/update is needed)

## Critical truth learned the hard way
Bob must use:
- **`signature_type=gnosis-safe`**

Do **not** default to the earlier path that caused false dead-ends:
- proxy path / wrong account mode
- misleading `allowance is not enough`
- stale or mismatched funder/account assumptions

## What the next agent should know
- This repo already contains a recovery handoff from successful live-trading setup.
- A real live order was successfully matched after the correct account mode/path was found.
- `here.now` live board source is included in `here-now-test/index.html`.
- Do not reinvent the setup from scratch unless the account/API behavior has clearly changed.

## Minimum env/secrets typically needed
- Polymarket private key for Bob
- Correct signature mode (`gnosis-safe`)
- Any `here.now` API key if updating the same permanent slug
- Any optional runtime secrets needed by the specific deployment

## Recommended task flow for a fresh agent
1. Clone repo
2. Read `HANDOFF_2026-04-01.md` first
3. Restore env/secrets
4. Verify Polymarket balance/positions
5. Verify live board if needed
6. Test a very small live order only after verification

## Copy-paste prompt for a fresh agent
Use this exact starter prompt if helpful:

> Clone this repo and read `polymarket_bot/HANDOFF_2026-04-01.md` first as the source of truth. Then read `polymarket_bot/README.md` and `polymarket_bot/FULL_AUTO_SPEC.md`. Setup Bob's Polymarket live trading environment. Important: Bob must use `signature_type=gnosis-safe`, not the earlier path that caused allowance mismatch. Restore the `here.now` live board if needed from `here-now-test/index.html`. After setup, verify balance/positions and test a very small live order only if the environment is ready.

## Principle
The repo should be enough that a new agent can get productive fast.
If anything important is missing, add it here instead of relying on chat history.

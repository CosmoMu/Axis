# Owner-only Moomoo Personal Execution Runbook

This runbook is for the private AXIS Owner account only. It must never be used to connect or trade a
member account.

## Safe initial state

Use these values until every DRY_RUN item is accepted:

```dotenv
FEATURE_PERSONAL_EXECUTION_ENABLED=true
PERSONAL_EXECUTION_MODE=DRY_RUN
PERSONAL_BROKER_ENV=SIMULATE
PERSONAL_AUTO_TRADING_ENABLED=false
PERSONAL_DRY_RUN_VALIDATED=false
```

`MOOMOO_ACC_ID` and `MOOMOO_SECURITY_FIRM` belong only in `.env` or the deployment Secret Store.
Never paste them into tickets, Discord, command output, documentation, or Git.

## OpenD prerequisites

1. Run a supported Moomoo OpenD and log in manually.
2. Keep OpenD on the configured local host/port (default `127.0.0.1:11111`).
3. Confirm the SDK version pinned in `pyproject.toml` is installed.
4. Select exactly one non-master US securities account. Do not guess when multiple accounts exist.
5. Do not automate `unlock_trade`. LIVE unlock is a manual OpenD action by Owner.

## Validation order

```bash
.venv/bin/pytest -q tests/test_personal_execution.py tests/test_moomoo_personal_execution.py
.venv/bin/python scripts/verify_personal_execution.py
```

The verifier performs read-only account, position, order, and fill queries. It exits with a blocker if
OpenD is unavailable, account selection is ambiguous, or the runtime is not in DRY_RUN. It makes no
broker write.

Then use `💹・moomoo-trading`:

1. Confirm card displays `DRY_RUN · SIMULATE` and the broker is connected.
2. Enable Manual Sync and verify option positions; non-option instruments must be ignored.
3. Enable Auto Follow and leave scope OWNER_ONLY.
4. Publish a controlled Owner-authored test of the production path and confirm a
   `DRY_RUN_VALIDATED` order exists with no broker order, fill, or new broker position.
5. Test AUTO/FOLLOW/SKIP review override, duplicate-contract block, max-chase block, quote age,
   spread, budget, Short-Term TTL, and Swing TTL.
6. Validate risk stages and the 09:30–09:35 ET opening guard with a SIMULATE position.
7. Restart AXIS BOT and confirm panel, idempotency, mappings, and reconciliation recover without
   duplicate events.
8. Verify System Alerts failure and recovery cards and the private daily summary.

## LIVE gate

Do not switch to LIVE in the same action that completes DRY_RUN. First record every remaining blocker
and obtain a separate Owner decision. LIVE requires all of:

- DRY_RUN and SIMULATE lifecycle accepted.
- Real OpenD read-only reconciliation accepted.
- Correct target account and security firm explicitly stored as secrets.
- Discord desktop/mobile Owner-only permission and control review accepted.
- Backup/restore and kill-switch rehearsal complete.
- `PERSONAL_DRY_RUN_VALIDATED=true` set only after acceptance.
- `PERSONAL_BROKER_ENV=REAL`, `PERSONAL_EXECUTION_MODE=LIVE`, and
  `PERSONAL_AUTO_TRADING_ENABLED=true` intentionally enabled together.

If any item is missing, startup fails closed. Reverting any write incident starts with
`PERSONAL_AUTO_TRADING_ENABLED=false`, followed by Pause Entries and Pause Management. AXIS may
cancel only orders it created and identified as AXIS-owned.

## Incident handling

- Personal execution failures do not suppress public signal delivery.
- OpenD/account/quote/order failures go to Owner-only System Alerts and receive a recovery card after
  successful reconciliation.
- Broker data wins over AXIS cache. Manual add creates a new risk epoch; manual partial/full exits are
  synchronized, not reversed.
- Never repair broker history by inserting fake production fills. Corrections require an auditable
  reconciliation event.

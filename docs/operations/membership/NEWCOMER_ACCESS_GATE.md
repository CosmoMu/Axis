# Newcomer Access Gate

## Purpose

`Newcomer` is a security-isolation Role for Discord users who have never passed AXIS approval. It
is not a visitor, Trial, or expired-member Role. Approval is permanent and membership access is a
separate entitlement decision.

## Permission model

The Discord blueprint fails closed for `Newcomer`. The Role has explicit channel overwrites:

- ALLOW View Channel + Read Message History: `👋・welcome`, `📊・results`,
  `🏆・member-wins`.
- DENY View Channel: subscriptions, lobby, every Member/Manager/Owner/LAB channel and every other
  registered channel.
- DENY Send Messages and Attach Files everywhere, including results and member-wins.

Never rely on hidden buttons or URLs. `Newcomer` inherits `@everyone`, so every newly allowed
channel must explicitly add `newcomer_view: true`; all unspecified channels remain denied by
`desired_channel_permissions()`.

## Role lifecycle

- First join after the production gate cutover: add `Newcomer`.
- Never approved or rejected/flagged without later approval: keep `Newcomer`.
- Approved: remove `Newcomer`; add `Member` only when an active entitlement exists.
- Trial/member expiry: remove `Member`, never re-add `Newcomer`.
- Approved rejoin: never add `Newcomer`; restore `Member` only for active access.

The five-minute reconciliation repairs role drift. The cutover timestamp in
`guild_config.newcomer_gate_activated_at` lets restart recovery distinguish pre-gate production
users from users who joined while the Bot was offline.

## Production rollout and repair

Always run the inventory first:

```bash
.venv/bin/python scripts/reconcile_newcomers.py --baseline-existing
```

Review both reported groups. Apply only after confirming the Guild:

```bash
.venv/bin/python scripts/reconcile_newcomers.py \
  --baseline-existing --apply --confirm-guild-id 1543309921066684567
```

This baselines pre-gate users as approved without creating a Trial, then records the gate cutover.
To repair a missing Role, restart/redeploy the Bot or wait for reconciliation. Inspect
`newcomer_profiles.role_sync_status`; `FAILED` produces a deduplicated system alert and is retried.

### Legacy overwrite bootstrap recovery

Some pre-gate channels may explicitly deny `Manage Channels` / `Manage Roles` to `@everyone`, which
also removes the Bot's otherwise valid Guild-level capability. If the first apply creates Newcomer
but Discord returns 50013 before permissions are reconciled, the Owner may temporarily enable
Administrator for AXIS BOT, rerun the exact dry-run/apply, verify every AXIS channel now explicitly
allows the Bot's two management permissions, and immediately disable Administrator. Never leave
Administrator enabled; the steady-state Blueprint does not require it.

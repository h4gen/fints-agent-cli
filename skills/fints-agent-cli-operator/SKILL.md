---
name: fints-agent-cli-operator
description: Use this when someone wants to do everyday online banking from terminal: connect their bank once, check balances, read transactions, and send transfers with clear next-step instructions.
homepage: https://github.com/h4gen/fints-agent-cli
user-invocable: true
metadata: {"openclaw":{"emoji":"🏦","category":"banking","tags":["banking","payments","assistant","operations"],"requires":{"bins":["fints-agent-cli"]},"install":{"package_managers":[{"tool":"uv","cmd":"uv tool install fints-agent-cli"},{"tool":"pipx","cmd":"pipx install fints-agent-cli"}],"verify":"fints-agent-cli --help"}}}
---

# fints-agent-cli Operator

Use this skill when the user asks to operate banking tasks through `fints-agent-cli`.

This skill teaches **how to use the CLI/library** end-to-end, including expected outputs and next actions.

## Use Cases

- Set up a user for first-time FinTS access.
- Retrieve accounts and balances.
- Retrieve transactions for one account and date range.
- Submit SEPA transfers (sync or async).
- Continue pending async transfer approvals.
- Recover from common setup/auth/account-selection problems.

## Install Instructions

### 1) Install this skill in OpenClaw

Choose one location:
- Workspace skill: `<workspace>/skills/fints-agent-cli-operator/SKILL.md`
- Shared local skill: `~/.openclaw/skills/fints-agent-cli-operator/SKILL.md`

Then refresh/reload skills (or restart OpenClaw gateway if needed).

### 2) Install the CLI binary

Recommended:

```bash
uv tool install fints-agent-cli
```

Alternative:

```bash
pipx install fints-agent-cli
```

Verify installation:

```bash
fints-agent-cli --help
```

Expected: command help is printed with subcommands such as `onboard`, `accounts`, `transactions`, `transfer`.


## OpenClaw Enablement (Optional)

If your OpenClaw setup requires explicit skill entries, enable it in `openclaw.json`:

```json
{
  "skills": {
    "entries": {
      "fints-agent-cli-operator": {
        "enabled": true
      }
    }
  }
}
```

## Bank Support Policy

- Only providers with known FinTS endpoints are supported.
- Registry is mainly German banks.
- Never guess endpoint URLs.

Always verify provider availability first:

```bash
fints-agent-cli providers-list --search <bank-name-or-bank-code>
fints-agent-cli providers-show --provider <provider-id>
```

If no provider matches:
- report unsupported provider
- stop setup flow

## Standard Operating Flow

### Step A: Onboard once

```bash
fints-agent-cli onboard
```

Expected success lines include:
- `Config saved: ...`
- `PIN saved in Keychain: ...`
- `Onboarding + bootstrap completed.`

### Step B: Verify account access

```bash
fints-agent-cli accounts
```

Expected output rows:
- `<IBAN>\t<Amount>\t<Currency>`

Capture IBAN for deterministic follow-up commands.

### Step C: Fetch transactions

Deterministic form:

```bash
fints-agent-cli transactions --iban <IBAN> --days 30 --format json
```

Expected fields:
- `date`
- `amount`
- `counterparty`
- `counterparty_iban` (if provided by bank payload)
- `purpose`

### Step D: Send transfer (sync)

```bash
fints-agent-cli transfer \
  --from-iban <FROM_IBAN> \
  --to-iban <TO_IBAN> \
  --to-name "<RECIPIENT_NAME>" \
  --amount <AMOUNT_DECIMAL> \
  --reason "<REFERENCE>" \
  --yes --auto
```

Local validation only (no submission):

```bash
fints-agent-cli transfer ... --dry-run
```

### Step E: Send transfer (async)

Submit:

```bash
fints-agent-cli transfer-submit \
  --from-iban <FROM_IBAN> \
  --to-iban <TO_IBAN> \
  --to-name "<RECIPIENT_NAME>" \
  --amount <AMOUNT_DECIMAL> \
  --reason "<REFERENCE>" \
  --yes --auto
```

Expected:
- `Pending ID: <id>`

Continue/poll:

```bash
fints-agent-cli transfer-status --id <PENDING_ID> --wait
```

Expected final:
- `Final result:`
- optional bank response lines

## Error Recovery Playbook

Case: `Please run bootstrap first.`

```bash
fints-agent-cli bootstrap
```

Case: `IBAN not found: ...`

```bash
fints-agent-cli accounts
```

Then retry with exact IBAN.

Case: missing or sparse transactions

```bash
fints-agent-cli transactions --iban <IBAN> --days 365
fints-agent-cli --debug transactions --iban <IBAN> --days 365
```

Then compare classes vs bank app (card vs giro vs pending/booked).

Case: async transfer still pending

```bash
fints-agent-cli transfer-status --id <PENDING_ID> --wait
```

Do not blindly resubmit same payment.

Case: local state broken

```bash
fints-agent-cli reset-local
fints-agent-cli onboard
```

## Runtime Policy for Agents

- Keep normal runs non-debug.
- Use `--debug` only for diagnosis.
- Prefer explicit `--iban` / `--from-iban`.
- Prefer `--yes --auto` when user intent is explicit.
- Never print secrets or PIN values.

## Reporting Contract

After each operation, report:
1. Command executed.
2. Success/failure.
3. Key extracted facts (selected IBAN, row count, pending id, final status).
4. Exact next command.

## Skill Directory Reference

- `{baseDir}`

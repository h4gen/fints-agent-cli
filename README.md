# fints-agent-cli

A command-line banking helper for FinTS-enabled banks.

This repository now has two docs entry points:
- `/Users/hagen/Projects/bank_cli/README.md` for quick start
- `/Users/hagen/Projects/bank_cli/docs/AGENT_RUNBOOK.md` for full, deterministic agent operation with expected outputs and next actions

If you are building automation or running this as an agent, start with:
- `/Users/hagen/Projects/bank_cli/docs/AGENT_RUNBOOK.md`

## What This Tool Does

`fints-agent-cli` talks to your bank via FinTS and lets you work from Terminal.

Typical flow:
1. Run one-time onboarding
2. Check balances and transactions
3. Send transfers and confirm in your banking app

## Safety & Privacy

- Your PIN is stored in macOS Keychain (not plain text files).
- You can force manual PIN entry anytime with `--no-keychain`.
- Normal output is quiet by default; debug logs are only enabled with `--debug`.

## Install

### Easy install (recommended)

```bash
uv tool install fints-agent-cli
```

or

```bash
pipx install fints-agent-cli
```

### Run from this repo (developer mode)

```bash
uv sync
uv run fints-agent-cli --help
```

## First-Time Setup (Copy/Paste)

Run:

```bash
fints-agent-cli onboard
```

It asks only for:
- bank/provider (name, id, or bank code)
- your user/login id
- your PIN

That is enough for most users.

## Daily Use (Copy/Paste)

Show accounts + balances:

```bash
fints-agent-cli accounts
```

Show recent transactions (last 30 days):

```bash
fints-agent-cli transactions --days 30
```

Show transactions for a specific account:

```bash
fints-agent-cli transactions --iban DE00123456780123456789 --days 30
```

## Sending a Transfer

### Simple transfer (one command)

```bash
fints-agent-cli transfer \
  --from-iban DE85120300001059281186 \
  --to-iban DE00123456780123456789 \
  --to-name "Recipient GmbH" \
  --amount 12.34 \
  --reason "Invoice 123" \
  --yes --auto
```

What happens:
- command submits the transfer
- if the bank requires app approval, approve in your banking app
- CLI continues automatically when possible

### Dry run (no money sent)

```bash
fints-agent-cli transfer ... --dry-run
```

## Async Transfer Mode (Submit now, check later)

Start transfer:

```bash
fints-agent-cli transfer-submit ...
```

Check status later:

```bash
fints-agent-cli transfer-status --wait
```

## Most Useful Commands

```text
onboard             One-time interactive setup
accounts            List accounts and balances
transactions        Fetch transactions
transfer            Send transfer (sync)
transfer-submit     Start transfer (async)
transfer-status     Check async transfer status
keychain-setup      Save/overwrite PIN in Keychain
reset-local         Delete local app config/state
providers-list      List supported FinTS banks
providers-show      Show one provider config
```

## If Something Fails

Enable debug output for one command:

```bash
fints-agent-cli --debug transactions --days 30
```

Re-run TAN setup if needed:

```bash
fints-agent-cli bootstrap
```

Reset local config/state:

```bash
fints-agent-cli reset-local
```

## Advanced Notes

- Provider registry is static and includes only banks with known FinTS endpoints.
- AqBanking is not required for normal use.
- Optional env vars:
  - `FINTS_AGENT_CLI_PRODUCT_ID`
  - `AQBANKING_BANKINFO_DE`
- Full operator playbook:
  - `/Users/hagen/Projects/bank_cli/docs/AGENT_RUNBOOK.md`

## Development

Run tests:

```bash
uv sync --group dev
uv run pytest
```

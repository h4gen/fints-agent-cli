# fints-agent-cli

FinTS banking CLI for humans and agents.

Use it to:
- onboard once
- fetch accounts and balances
- fetch transactions
- send SEPA transfers
- handle app-based SCA approval flows


## Install

Recommended:

```bash
uv tool install fints-agent-cli
```

Alternative:

```bash
pipx install fints-agent-cli
```

From source repo:

```bash
uv sync
uv run fints-agent-cli --help
```

## 60-Second Start

### 1) One-time onboarding

```bash
fints-agent-cli onboard
```

You will be asked for:
- provider (id/name/bank code)
- user id/login
- PIN

The PIN is saved in macOS Keychain.

### 2) Verify account access

```bash
fints-agent-cli accounts
```

Expected output format:
- `<IBAN>\t<Amount>\t<Currency>`

### 3) Fetch transactions

```bash
fints-agent-cli transactions --days 30
```

For deterministic account selection:

```bash
fints-agent-cli transactions --iban <IBAN> --days 30
```

## Transfers

### Synchronous transfer (single flow)

```bash
fints-agent-cli transfer \
  --from-iban <FROM_IBAN> \
  --to-iban <TO_IBAN> \
  --to-name "Recipient Name" \
  --amount 12.34 \
  --reason "Reference" \
  --yes --auto
```

### Dry run (local validation only, no submission)

```bash
fints-agent-cli transfer ... --dry-run
```

### Async transfer flow

```bash
fints-agent-cli transfer-submit ...
fints-agent-cli transfer-status --wait
```

## Who This Is For

- End users who can run a few terminal commands.
- AI/automation agents that need deterministic CLI behavior.

If you are running this as an agent, read first:
- `/Users/hagen/Projects/bank_cli/docs/AGENT_RUNBOOK.md`

## Supported Banks

This project only includes providers with a known FinTS endpoint.

Current registry characteristics:
- FinTS-focused registry
- primarily German banks (FinTS ecosystem)
- includes seeded direct banks such as `dkb`, `ing`, `comdirect`, `consorsbank`
- plus many additional German institutions from bundled provider data

Check what is available on your installed version:

```bash
fints-agent-cli providers-list --limit 40
fints-agent-cli providers-list --search dkb
fints-agent-cli providers-list --search ing
fints-agent-cli providers-show --provider dkb
```

If your bank is not listed by `providers-list`, this tool currently cannot configure it automatically.


## Commands Overview

```text
onboard             Interactive setup
bootstrap           Re-run TAN/SCA setup
accounts            Accounts + balances
transactions        Transactions (pretty/tsv/json)
transfer            Sync transfer flow
transfer-submit     Start async transfer
transfer-status     Continue/check async transfer
providers-list      List known providers
providers-show      Show provider details
keychain-setup      Save/update PIN in Keychain
reset-local         Delete local config/state/pending files
capabilities        Live FinTS capability discovery
```

## Troubleshooting

Use debug only for diagnosis:

```bash
fints-agent-cli --debug transactions --days 30
```

Re-run auth setup:

```bash
fints-agent-cli bootstrap
```

Reset local state:

```bash
fints-agent-cli reset-local
```

## Security Notes

- PIN is read from macOS Keychain by default.
- You can force manual PIN entry per command with `--no-keychain`.
- Avoid storing PIN in shell history or plain text files.

## Agent Notes

Agent-friendly guidance with expected outputs and recovery actions:
- `/Users/hagen/Projects/bank_cli/docs/AGENT_RUNBOOK.md`

## Development

```bash
uv sync --group dev
uv run pytest
```

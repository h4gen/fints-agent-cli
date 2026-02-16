# fints-agent-cli

Generic FinTS CLI based on `python-fints` with a static provider registry, account/balance retrieval, transaction output, and SEPA transfer workflows.

## Installation

```bash
# local project env
uv sync

# run from repo
uv run fints-agent-cli --help

# install globally (uv tool)
uv tool install /Users/hagen/Projects/bank_cli

# or with pipx
pipx install /Users/hagen/Projects/bank_cli
```

## Quickstart

```bash
fints-agent-cli onboard
fints-agent-cli accounts
fints-agent-cli transactions --days 30
fints-agent-cli capabilities
```

The `onboard` flow asks for only:
- provider (`id`, bank code, or name)
- user ID (login name)
- PIN (stored in macOS Keychain)

By default, onboarding also runs TAN bootstrap. Use `--no-bootstrap` to skip.

## Commands

```text
providers-list      List banks from static registry
providers-show      Show one provider config
init                Write config directly (non-interactive)
onboard             Interactive setup
reset-local         Delete local config/state/pending files
bootstrap           Rerun TAN setup
accounts            List accounts + balances
transactions        Fetch transactions
capabilities        Live FinTS capability discovery
transfer            Send SEPA transfer (sync)
transfer-submit     Start transfer asynchronously
transfer-status     Continue/check async transfer
keychain-setup      Save/overwrite PIN in Keychain
```

## Transfers

Sync transfer:

```bash
fints-agent-cli transfer \
  --from-iban DE85120300001059281186 \
  --to-iban DE00123456780123456789 \
  --to-name "Recipient GmbH" \
  --amount 12.34 \
  --reason "Test" \
  --yes --auto
```

Async flow:

```bash
fints-agent-cli transfer-submit ...
fints-agent-cli transfer-status --wait
```

Useful flags:
- `--dry-run` validates locally without submitting
- `--auto` minimizes prompts (`-y`, auto VoP, auto polling where applicable)
- `--poll-interval` and `--poll-timeout` tune async polling

## Logging

By default, output is quiet. Enable debug logs only when needed:

```bash
fints-agent-cli --debug <command> ...
```

## Tests

```bash
uv sync --group dev
uv run pytest
```

## Notes

- Registry includes only providers with a known FinTS endpoint (`fints_url`).
- AqBanking is not required for normal use.
- Optional environment variables:
  - `FINTS_AGENT_CLI_PRODUCT_ID`
  - `AQBANKING_BANKINFO_DE`

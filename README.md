# fints-agent-cli

Generic FinTS CLI based on `python-fints` with a provider registry, account/balance retrieval, transaction export, and SEPA transfers.

## Installation

```bash
# local project environment
uv sync

# install as global tool
uv tool install /Users/hagen/Projects/bank_cli

# or with pipx
pipx install /Users/hagen/Projects/bank_cli
```

After installation, use the command `fints-agent-cli`.

## Tests

```bash
uv sync --group dev
uv run pytest
```

## Quickstart

```bash
fints-agent-cli onboard
fints-agent-cli accounts
fints-agent-cli transactions --days 90
fints-agent-cli capabilities
```

The `onboard` wizard asks for:
- provider
- user ID
- PIN (stored directly in macOS Keychain)
- optional bootstrap execution (TAN setup)

## Transfer

```bash
fints-agent-cli transfer \
  --from-iban DE85120300001059281186 \
  --to-iban DE00123456780123456789 \
  --to-name "Recipient GmbH" \
  --amount 12.34 \
  --reason "Test" \
  --yes
```

Async flow:

```bash
fints-agent-cli transfer-submit ...
fints-agent-cli transfer-status --wait
```

## Notes

- The registry only includes banks with a real FinTS endpoint (`fints_url`).
- AqBanking is **not** required for normal onboarding.
- Optional override for local bankinfo data path:
  - `AQBANKING_BANKINFO_DE=/path/to/banks.data`
- Product ID environment variable:
  - `FINTS_AGENT_CLI_PRODUCT_ID`

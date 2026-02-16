# fints-agent-cli

Generische FinTS CLI auf Basis von `python-fints` mit Provider-Registry, Konten/Umsaetzen und SEPA-Transfer.

## Installation

```bash
# lokal im Projekt
uv sync

# als Tool (global)
uv tool install /Users/hagen/Projects/bank_cli

# oder mit pipx
pipx install /Users/hagen/Projects/bank_cli
```

Danach ist der Befehl `fints-agent-cli` verfuegbar.

## Tests

```bash
uv sync --group dev
uv run pytest
```

## Schnellstart

```bash
fints-agent-cli onboard
fints-agent-cli accounts
fints-agent-cli transactions --days 90
fints-agent-cli capabilities
```

Der `onboard`-Wizard fragt alle Werte Schritt fuer Schritt ab:
- Provider
- User-ID
- PIN (wird direkt in macOS Keychain gespeichert)
- optional direktes Bootstrap (TAN-Verfahren)

## Transfer

```bash
fints-agent-cli transfer \
  --from-iban DE85120300001059281186 \
  --to-iban DE00123456780123456789 \
  --to-name "Empfaenger GmbH" \
  --amount 12.34 \
  --reason "Test" \
  --yes
```

Async-Flow:

```bash
fints-agent-cli transfer-submit ...
fints-agent-cli transfer-status --wait
```

## Hinweise

- Die Registry listet nur Banken mit echtem FinTS-Endpunkt (`fints_url`).
- AqBanking ist **nicht** nötig fürs normale Onboarding.
- Optionaler Override fuer den Datenpfad:
  - `AQBANKING_BANKINFO_DE=/pfad/zu/banks.data`
- Product-ID via ENV:
  - `FINTS_AGENT_CLI_PRODUCT_ID`

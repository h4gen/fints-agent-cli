# fints-agent-cli Agent Runbook

This runbook is for autonomous or semi-autonomous agents.

Goal: execute banking tasks with minimal ambiguity.

## 0. Scope and Bank Coverage

This CLI operates only on providers with known FinTS endpoints.

Coverage model:
- registry is FinTS-only
- currently focused on Germany (FinTS ecosystem reality)
- seeded direct-bank ids include `dkb`, `ing`, `comdirect`, `consorsbank`
- additional German providers are bundled in provider data

Always verify coverage from the running binary before onboarding:

```bash
fints-agent-cli providers-list --limit 50
fints-agent-cli providers-list --search <bank-name-or-code>
fints-agent-cli providers-show --provider <provider-id>
```

If a provider is not returned by `providers-list`, do not guess URLs.
Treat as unsupported until provider data is updated.

## 1. Operating Model

`fints-agent-cli` communicates with banks via FinTS and uses:
- local config in `~/.config/fints-agent-cli/`
- local client state in `~/.config/fints-agent-cli/` (dialog/system state)
- macOS Keychain for PIN retrieval

Important behavior:
- Without `--debug`, logs are intentionally quiet.
- With `--debug`, protocol/log output can be verbose.
- Decoupled SCA (app confirmation) can be auto-polled.

## 2. Preconditions Checklist

Before running task commands, ensure:
1. CLI is installed and executable.
2. User has a FinTS-capable bank account.
3. User has completed onboarding at least once.
4. PIN is in Keychain (or operator will provide PIN manually).

Validation commands:

```bash
fints-agent-cli --help
fints-agent-cli providers-list --search dkb
```

Expected result:
- `--help` prints command list.
- `providers-list` returns at least one matching provider row.

If provider is missing:
- stop and select another provider id/name/bank code
- do not attempt random endpoint guessing

## 3. One-Time Onboarding Flow

Command:

```bash
fints-agent-cli onboard
```

Prompt sequence (typical):
1. Provider (id/bank-code/name)
2. User ID
3. PIN (hidden input)
4. TAN bootstrap steps (if `--no-bootstrap` not set)

Expected success output (typical):
- `Config saved: .../config.json`
- `PIN saved in Keychain: service=... account=...`
- `Onboarding + bootstrap completed.`

If onboarding fails:
1. rerun with debug:
   ```bash
   fints-agent-cli --debug onboard
   ```
2. verify provider:
   ```bash
   fints-agent-cli providers-list --search <bank-name-or-code>
   ```
3. retry bootstrap:
   ```bash
   fints-agent-cli bootstrap
   ```

## 4. Accounts and Balances

Command:

```bash
fints-agent-cli accounts
```

Expected output pattern:
- one line per account
- format: `<iban><tab><amount><tab><currency>`

Operator action:
- if multiple current accounts exist, record relevant IBAN for later `transactions --iban` and transfers.

If command returns auth/SCA challenge:
- approve in bank app
- rerun command (or use command flow that auto-polls during SCA where supported)

## 5. Transactions Retrieval

Base command:

```bash
fints-agent-cli transactions --days 30
```

Preferred explicit account command:

```bash
fints-agent-cli transactions --iban <IBAN> --days 30
```

Formats:

```bash
fints-agent-cli transactions --format pretty
fints-agent-cli transactions --format tsv
fints-agent-cli transactions --format json
```

Expected fields include:
- `date`
- `amount`
- `counterparty`
- `counterparty_iban` (if available from bank data)
- `purpose`

Interpretation note:
- `counterparty_iban` depends on bank payload quality.
- Card transactions may still have no counterparty IBAN.

If transaction list is unexpectedly short:
1. increase range:
   ```bash
   fints-agent-cli transactions --iban <IBAN> --days 365
   ```
2. run with debug once:
   ```bash
   fints-agent-cli --debug transactions --iban <IBAN> --days 365
   ```
3. compare with web/app channel and document missing classes (card vs giro, pending vs booked)

## 6. Transfer (Synchronous)

Command template:

```bash
fints-agent-cli transfer \
  --from-iban <SENDER_IBAN> \
  --to-iban <RECIPIENT_IBAN> \
  --to-name "<RECIPIENT_NAME>" \
  --amount <AMOUNT_DECIMAL> \
  --reason "<REFERENCE>" \
  --yes --auto
```

Execution behavior:
- validates arguments locally
- sends transfer request
- handles VoP if bank requests it
- handles app-based decoupled SCA polling when enabled

Expected terminal pattern:
- preview/result text
- final status line and optional response lines (`code`, `text`)

Safety preflight without sending:

```bash
fints-agent-cli transfer ... --dry-run
```

## 7. Transfer (Asynchronous)

Submit now:

```bash
fints-agent-cli transfer-submit \
  --from-iban <SENDER_IBAN> \
  --to-iban <RECIPIENT_IBAN> \
  --to-name "<RECIPIENT_NAME>" \
  --amount <AMOUNT_DECIMAL> \
  --reason "<REFERENCE>" \
  --yes --auto
```

Expected output:
- `Pending ID: <id>`

Poll status:

```bash
fints-agent-cli transfer-status --id <id> --wait
```

Expected final output:
- `Final result:`
- status object/string
- optional response lines

If still pending:
- wait and rerun `transfer-status --wait`
- do not resubmit identical transfer blindly

## 8. Keychain and PIN Handling

Set/update PIN entry:

```bash
fints-agent-cli keychain-setup --user-id <login>
```

By default, commands try Keychain first.

Force manual PIN prompt for one run:

```bash
fints-agent-cli accounts --no-keychain
```

## 9. Logging Policy

Default mode:
- use non-debug commands for normal operation.

Incident mode:
- rerun the failing command with `--debug` exactly once and capture output.

Examples:

```bash
fints-agent-cli --debug accounts
fints-agent-cli --debug transactions --iban <IBAN> --days 90
fints-agent-cli --debug transfer-status --id <id> --wait
```

## 10. Recovery and Reset

Re-run TAN setup:

```bash
fints-agent-cli bootstrap
```

Reset local CLI state:

```bash
fints-agent-cli reset-local
```

Use reset only when:
- local state is broken
- onboarding/bootstrap will be repeated immediately after

## 11. Decision Table

Case: `Please run bootstrap first.`
- Action: run `fints-agent-cli bootstrap`

Case: IBAN not found
- Action: run `fints-agent-cli accounts`, copy correct IBAN, retry with `--iban` or `--from-iban`

Case: transfer async shows pending repeatedly
- Action: continue `transfer-status --id <id> --wait`; verify app approval status

Case: no Keychain PIN found
- Action: run `fints-agent-cli keychain-setup --user-id <login>` or retry with `--no-keychain`

Case: sparse/missing transactions
- Action: increase `--days`, force specific `--iban`, run once with `--debug`, compare booking classes

## 12. Minimal Agent Script Sequence

For a fresh environment:

```bash
fints-agent-cli onboard
fints-agent-cli accounts
fints-agent-cli transactions --days 30
```

For recurring operations:

```bash
fints-agent-cli accounts
fints-agent-cli transactions --iban <IBAN> --days 7 --format json
```

For payments:

```bash
fints-agent-cli transfer ... --yes --auto
```

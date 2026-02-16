#!/usr/bin/env python3
import argparse
import getpass
import json
import logging
import os
import pickle
import re
import subprocess
import time
import uuid
import urllib.parse
import warnings
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from fints.client import FinTS3PinTanClient, NeedRetryResponse, NeedTANResponse, NeedVOPResponse
from fints.exceptions import FinTSClientError
from fints.parser import FinTSParserWarning
from fints.utils import minimal_interactive_cli_bootstrap


DEFAULT_BLZ = "12030000"
DEFAULT_SERVER = "https://fints.dkb.de/fints"
DEFAULT_PRODUCT_ID = "6151256F3D4F9975B877BD4A2"
DEFAULT_DECOUPLED_POLL_INTERVAL = 2.0
DEFAULT_DECOUPLED_TIMEOUT = 300
ENV_PRODUCT_ID = "FINTS_AGENT_CLI_PRODUCT_ID"

APP_DIR = Path.home() / ".config" / "fints-agent-cli"
CFG_PATH = APP_DIR / "config.json"
STATE_PATH = APP_DIR / "client_state.bin"
PENDING_DIR = APP_DIR / "pending"
BUNDLED_PROVIDERS_PATH = Path(__file__).resolve().with_name("providers.json")
USER_PROVIDERS_PATH = APP_DIR / "providers.json"
AQBANKING_BANKINFO_DE_CANDIDATES = [
    Path("/opt/homebrew/Cellar/aqbanking/6.9.1/share/aqbanking/bankinfo/de/banks.data"),
    Path("/opt/homebrew/share/aqbanking/bankinfo/de/banks.data"),
    Path("/usr/local/share/aqbanking/bankinfo/de/banks.data"),
    Path("/usr/share/aqbanking/bankinfo/de/banks.data"),
]


@dataclass
class Config:
    blz: str = DEFAULT_BLZ
    server: str = DEFAULT_SERVER
    user_id: Optional[str] = None
    customer_id: Optional[str] = None
    product_id: Optional[str] = None
    provider_id: Optional[str] = "dkb"
    provider_name: Optional[str] = "DKB"
    keychain_service: str = "fints-agent-cli-pin"
    keychain_account: Optional[str] = None

    @staticmethod
    def load() -> "Config":
        if CFG_PATH.exists():
            data = json.loads(CFG_PATH.read_text(encoding="utf-8"))
            return Config(**data)
        return Config()

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CFG_PATH.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        try:
            os.chmod(CFG_PATH, 0o600)
        except OSError:
            pass


def load_state() -> Optional[bytes]:
    if STATE_PATH.exists():
        return STATE_PATH.read_bytes()
    return None


def save_state(blob: bytes) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_bytes(blob)
    try:
        os.chmod(STATE_PATH, 0o600)
    except OSError:
        pass


def pending_path(pending_id: str) -> Path:
    return PENDING_DIR / f"{pending_id}.pkl"


def save_pending(pending_id: str, payload: dict) -> None:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    path = pending_path(pending_id)
    with path.open("wb") as f:
        pickle.dump(payload, f)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_pending(pending_id: str) -> dict:
    path = pending_path(pending_id)
    if not path.exists():
        raise SystemExit(f"Pending ID not found: {pending_id}")
    with path.open("rb") as f:
        return pickle.load(f)


def delete_pending(pending_id: str) -> None:
    path = pending_path(pending_id)
    if path.exists():
        path.unlink()


def list_pending_ids() -> list[str]:
    if not PENDING_DIR.exists():
        return []
    ids = []
    for p in PENDING_DIR.glob("*.pkl"):
        ids.append(p.stem)
    return sorted(ids, key=lambda x: pending_path(x).stat().st_mtime, reverse=True)


def _default_seed_providers() -> list[dict]:
    return [
        {
            "id": "dkb",
            "name": "DKB",
            "country": "DE",
            "blz": "12030000",
            "bic": "BYLADEM1001",
            "fints_url": "https://fints.dkb.de/fints",
            "auth_mode": "PINTAN",
            "source": "manual",
            "supports": {
                "accounts": "yes",
                "balance": "yes",
                "transactions": "yes",
                "transfer": "yes",
                "instant": "unknown",
                "vop": "unknown",
            },
        },
        {
            "id": "ing",
            "name": "ING",
            "country": "DE",
            "blz": "50010517",
            "bic": "INGDDEFFXXX",
            "fints_url": "https://fints.ing.de/fints/",
            "auth_mode": "PINTAN",
            "source": "aqbanking-bankinfo-de",
            "supports": {
                "accounts": "yes",
                "balance": "yes",
                "transactions": "yes",
                "transfer": "yes",
                "instant": "unknown",
                "vop": "unknown",
            },
        },
        {
            "id": "comdirect",
            "name": "comdirect",
            "country": "DE",
            "blz": "20041111",
            "bic": "COBADEHDXXX",
            "fints_url": "https://fints.comdirect.de/fints",
            "auth_mode": "PINTAN",
            "source": "aqbanking-bankinfo-de",
            "supports": {
                "accounts": "yes",
                "balance": "yes",
                "transactions": "yes",
                "transfer": "yes",
                "instant": "unknown",
                "vop": "unknown",
            },
        },
        {
            "id": "consorsbank",
            "name": "Consorsbank",
            "country": "DE",
            "blz": "70120400",
            "bic": "CSDBDE71XXX",
            "fints_url": "https://brokerage-hbci.consorsbank.de/hbci",
            "auth_mode": "PINTAN",
            "source": "aqbanking-bankinfo-de",
            "supports": {
                "accounts": "yes",
                "balance": "yes",
                "transactions": "yes",
                "transfer": "yes",
                "instant": "unknown",
                "vop": "unknown",
            },
        },
        {
            "id": "norisbank",
            "name": "norisbank",
            "country": "DE",
            "blz": "10077777",
            "bic": "NORSDE51XXX",
            "fints_url": "https://fints.norisbank.de/",
            "auth_mode": "PINTAN",
            "source": "aqbanking-bankinfo-de",
            "supports": {
                "accounts": "yes",
                "balance": "yes",
                "transactions": "yes",
                "transfer": "yes",
                "instant": "unknown",
                "vop": "unknown",
            },
        },
    ]


def _decode_text(value: str) -> str:
    return urllib.parse.unquote(value or "").strip()


def _provider_id_for_blz(blz: str) -> str:
    return f"de-{blz}"


def detect_aqbanking_bankinfo_path() -> Optional[Path]:
    env = os.getenv("AQBANKING_BANKINFO_DE", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return p
    for path in AQBANKING_BANKINFO_DE_CANDIDATES:
        if path.exists():
            return path
    return None


def import_aqbanking_bankinfo(path: Optional[Path] = None) -> list[dict]:
    path = path or detect_aqbanking_bankinfo_path()
    if path is None:
        return []
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    raw_blocks = text.split('\n\nbankId="')
    if raw_blocks and raw_blocks[0].startswith("#"):
        raw_blocks = raw_blocks[1:]

    providers: dict[str, dict] = {}
    for idx, block in enumerate(raw_blocks):
        if idx > 0 or not block.startswith('bankId="'):
            block = 'bankId="' + block
        bank_id = re.search(r'bankId="([0-9]+)"', block)
        if not bank_id:
            continue
        blz = bank_id.group(1)
        name_m = re.search(r'bankName="([^"]*)"', block)
        bic_m = re.search(r'bic="([^"]*)"', block)
        name = _decode_text(name_m.group(1) if name_m else "")
        bic = _decode_text(bic_m.group(1) if bic_m else "")

        svc_matches = re.finditer(
            r'element\s*\{\s*type="([^"]+)"\s*address="([^"]*)"\s*pversion="([^"]*)"\s*mode="([^"]*)"\s*userFlags="([^"]*)"\s*\}',
            block,
            re.S,
        )
        for svc in svc_matches:
            typ, addr, pversion, mode, user_flags = svc.groups()
            typ = _decode_text(typ).upper()
            addr = _decode_text(addr)
            mode = _decode_text(mode).upper()
            pversion = _decode_text(pversion)
            if typ != "HBCI" or mode != "PINTAN" or not addr:
                continue
            pid = _provider_id_for_blz(blz)
            old = providers.get(pid)
            if old and old.get("source") == "manual":
                continue
            providers[pid] = {
                "id": pid,
                "name": name or f"Bank {blz}",
                "country": "DE",
                "blz": blz,
                "bic": bic or None,
                "fints_url": addr,
                "auth_mode": mode,
                "hbci_version_hint": pversion or None,
                "user_flags": user_flags or None,
                "source": "aqbanking-bankinfo-de",
                "supports": {
                    "accounts": "unknown",
                    "balance": "unknown",
                    "transactions": "unknown",
                    "transfer": "unknown",
                    "instant": "unknown",
                    "vop": "unknown",
                },
            }
            break
    return sorted(providers.values(), key=lambda p: (p.get("name", ""), p.get("blz", "")))


def save_providers(providers: list[dict]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    USER_PROVIDERS_PATH.write_text(
        json.dumps({"generated_at": datetime.now().isoformat(), "providers": providers}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        os.chmod(USER_PROVIDERS_PATH, 0o600)
    except OSError:
        pass


def merge_providers(*provider_lists: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for items in provider_lists:
        for item in items:
            if not item.get("id"):
                continue
            merged[item["id"]] = {**merged.get(item["id"], {}), **item}
    providers = [p for p in merged.values() if p.get("fints_url")]
    return sorted(providers, key=lambda p: (p.get("name", ""), p.get("id", "")))


def normalize_provider_labels(providers: list[dict]) -> list[dict]:
    # Keep canonical short labels for common providers even when imported data differs.
    for p in providers:
        if p.get("id") == "dkb":
            p["name"] = "DKB"
    return providers


def load_providers() -> list[dict]:
    if USER_PROVIDERS_PATH.exists():
        data = json.loads(USER_PROVIDERS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return normalize_provider_labels(data)
        return normalize_provider_labels(data.get("providers", []))

    if BUNDLED_PROVIDERS_PATH.exists():
        data = json.loads(BUNDLED_PROVIDERS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return normalize_provider_labels(data)
        if isinstance(data, dict):
            providers = data.get("providers", [])
            if providers:
                return normalize_provider_labels(providers)

    providers = merge_providers(_default_seed_providers(), import_aqbanking_bankinfo())
    save_providers(providers)
    return normalize_provider_labels(providers)


def resolve_provider(provider_ref: str, providers: list[dict]) -> dict:
    ref = (provider_ref or "").strip()
    if not ref:
        raise SystemExit("Missing --provider.")

    by_id = {p.get("id"): p for p in providers}
    if ref in by_id:
        return by_id[ref]

    for p in providers:
        if p.get("blz") == ref:
            return p

    low = ref.lower()
    matches = [p for p in providers if low in (p.get("name", "").lower())]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(f"{m.get('id')} ({m.get('name')})" for m in matches[:8])
        raise SystemExit(f"Ambiguous provider: {ref}. Matches: {names}")
    raise SystemExit(f"Provider not found: {ref}")


def ensure_product_id(cfg: Config, cli_product_id: Optional[str]) -> None:
    if cli_product_id:
        cfg.product_id = cli_product_id
    if not cfg.product_id:
        cfg.product_id = os.getenv(ENV_PRODUCT_ID, "").strip() or None
    if not cfg.product_id:
        cfg.product_id = DEFAULT_PRODUCT_ID


def apply_provider_to_config(cfg: Config, provider: dict) -> None:
    if not provider.get("fints_url"):
        raise SystemExit(
            f"Provider '{provider.get('id')}' hat keinen FinTS-Endpunkt. "
            "This CLI mode only supports FinTS/HBCI PIN/TAN."
        )
    cfg.provider_id = provider.get("id")
    cfg.provider_name = provider.get("name")
    blz = provider.get("blz")
    url = provider.get("fints_url")
    if blz:
        cfg.blz = blz
    if url:
        cfg.server = url


def serialize_supported_operations(info_map) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for key, value in (info_map or {}).items():
        name = getattr(key, "name", str(key))
        out[str(name).lower()] = bool(value)
    return out


def build_client(cfg: Config, pin: str) -> FinTS3PinTanClient:
    return FinTS3PinTanClient(
        cfg.blz,
        cfg.user_id,
        pin,
        cfg.server,
        customer_id=cfg.customer_id,
        product_id=cfg.product_id,
        from_data=load_state(),
    )


def build_client_with_state(cfg: Config, pin: str, state_blob: Optional[bytes]) -> FinTS3PinTanClient:
    return FinTS3PinTanClient(
        cfg.blz,
        cfg.user_id,
        pin,
        cfg.server,
        customer_id=cfg.customer_id,
        product_id=cfg.product_id,
        from_data=state_blob,
    )


def pin_key(cfg: Config) -> str:
    user = cfg.user_id or "user"
    return f"PIN_{cfg.blz}_{user}"


def clean_text(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return " ".join(text.split())


def normalize_iban(value: str) -> str:
    return re.sub(r"\s+", "", (value or "")).upper()


def validate_iban(value: str) -> bool:
    iban = normalize_iban(value)
    if len(iban) < 15 or len(iban) > 34:
        return False
    if not re.match(r"^[A-Z0-9]+$", iban):
        return False
    moved = iban[4:] + iban[:4]
    converted = ""
    for ch in moved:
        if ch.isdigit():
            converted += ch
        else:
            converted += str(ord(ch) - 55)
    try:
        return int(converted) % 97 == 1
    except ValueError:
        return False


def validate_bic(value: str) -> bool:
    bic = (value or "").strip().upper()
    return bool(re.match(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$", bic))


def _normalize_iban_candidate(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = " ".join(str(x) for x in value if x is not None)
    text = str(value).strip().upper()
    if not text:
        return ""
    compact = normalize_iban(text)
    if validate_iban(compact):
        return compact
    return ""


def extract_counterparty_iban(data: dict, purpose: str = "") -> str:
    if not isinstance(data, dict):
        data = {}
    direct_keys = [
        "recipient_iban",
        "applicant_iban",
        "counterparty_iban",
        "remote_iban",
        "iban",
        "creditor_iban",
        "debtor_iban",
    ]
    for key in direct_keys:
        iban = _normalize_iban_candidate(data.get(key))
        if iban:
            return iban

    for key, raw in data.items():
        if "iban" not in str(key).lower():
            continue
        iban = _normalize_iban_candidate(raw)
        if iban:
            return iban

    # Fallback for purpose lines that contain "IBAN <...>" or plain IBAN-like tokens.
    haystack = f"{purpose} {data.get('purpose', '')}".upper()
    for match in re.finditer(r"[A-Z]{2}[0-9A-Z ]{13,40}", haystack):
        candidate = normalize_iban(match.group(0))
        if validate_iban(candidate):
            return candidate
    return ""


def print_transactions(rows, out_format: str, max_purpose: int) -> None:
    if out_format == "json":
        print(json.dumps(rows, ensure_ascii=False))
        return

    if out_format == "tsv":
        print("date\tamount\tcounterparty\tcounterparty_iban\tpurpose")
        for row in rows:
            print(
                f"{row['date']}\t{row['amount']}\t{row['counterparty']}\t"
                f"{row.get('counterparty_iban', '')}\t{row['purpose']}"
            )
        return

    date_w = 10
    amount_w = max(12, max((len(r["amount"]) for r in rows), default=12))
    cp_w = max(16, min(40, max((len(r["counterparty"]) for r in rows), default=16)))
    iban_w = max(12, min(34, max((len(r.get("counterparty_iban", "")) for r in rows), default=12)))
    header = (
        f"{'Date':<{date_w}}  {'Amount':>{amount_w}}  {'Counterparty':<{cp_w}}  "
        f"{'IBAN':<{iban_w}}  Purpose"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        purpose = row["purpose"]
        if max_purpose > 0 and len(purpose) > max_purpose:
            purpose = purpose[: max_purpose - 3] + "..."
        cp = row["counterparty"][:cp_w]
        iban = row.get("counterparty_iban", "")[:iban_w]
        print(
            f"{row['date']:<{date_w}}  {row['amount']:>{amount_w}}  "
            f"{cp:<{cp_w}}  {iban:<{iban_w}}  {purpose}"
        )


def keychain_get_pin(service: str, account: str) -> Optional[str]:
    proc = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    val = proc.stdout.strip()
    return val or None


def keychain_store_pin(service: str, account: str, pin: str) -> None:
    proc = subprocess.run(
        ["security", "add-generic-password", "-U", "-a", account, "-s", service, "-w", pin],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        raise SystemExit(f"Failed to save to Keychain: {err or 'no details'}")


def resolve_keychain(args, cfg: Config) -> tuple[str, str]:
    service = (getattr(args, "keychain_service", None) or cfg.keychain_service).strip()
    account = (
        getattr(args, "keychain_account", None)
        or cfg.keychain_account
        or cfg.user_id
        or ""
    ).strip()
    if not service or not account:
        raise SystemExit("Missing Keychain service/account.")
    return service, account


def get_pin(args, cfg: Config) -> str:
    if getattr(args, "no_keychain", False):
        return getpass.getpass("Bank PIN: ")
    try:
        service, account = resolve_keychain(args, cfg)
    except SystemExit:
        return getpass.getpass("Bank PIN: ")
    pin = keychain_get_pin(service, account)
    if pin:
        return pin
    return getpass.getpass("Bank PIN: ")


def complete_tan(
    client: FinTS3PinTanClient,
    resp,
    *,
    auto_approve_vop: bool = False,
    decoupled_auto_poll: bool = True,
    decoupled_poll_interval: float = DEFAULT_DECOUPLED_POLL_INTERVAL,
    decoupled_timeout: int = DEFAULT_DECOUPLED_TIMEOUT,
):
    decoupled_attempts = 0
    decoupled_started = None
    while True:
        if isinstance(resp, NeedVOPResponse):
            print("Received bank VoP warning (payee verification).")
            if auto_approve_vop:
                print("VoP auto-approved.")
            else:
                input("Continue with VoP confirmation? Enter = yes, Ctrl+C = abort: ")
            resp = client.approve_vop_response(resp)
            continue

        if not isinstance(resp, NeedTANResponse):
            return resp

        # Do not print raw bank challenge text (often localized); keep CLI output consistently English.
        print("\nSCA challenge: Please confirm this action in your banking app.")
        if getattr(resp, "decoupled", False):
            # Always poll in decoupled mode: no Enter required.
            if decoupled_started is None:
                decoupled_started = time.time()
                print(
                    f"Waiting for app approval (poll every {decoupled_poll_interval:.1f}s, "
                    f"timeout {decoupled_timeout}s) ..."
                )
            else:
                if int(time.time() - decoupled_started) >= decoupled_timeout:
                    raise SystemExit("SCA app approval timeout. Please restart.")
                time.sleep(decoupled_poll_interval)
            try:
                resp = client.send_tan(resp, "")
            except FinTSClientError as exc:
                decoupled_attempts += 1
                if decoupled_attempts >= 200:
                    raise SystemExit("SCA app approval did not complete (polling).") from exc
                continue
            continue
        tan = getpass.getpass("TAN: ")
        try:
            resp = client.send_tan(resp, tan)
        except FinTSClientError as exc:
            raise SystemExit(f"TAN failed: {exc}") from exc


def complete_vop_only(client: FinTS3PinTanClient, resp, *, auto_approve_vop: bool = False):
    while isinstance(resp, NeedVOPResponse):
        print("Received bank VoP warning (payee verification).")
        if auto_approve_vop:
            print("VoP auto-approved.")
        else:
            input("Continue with VoP confirmation? Enter = yes, Ctrl+C = abort: ")
        resp = client.approve_vop_response(resp)
    return resp


def pick_account(accounts, from_iban: Optional[str]):
    if not accounts:
        raise SystemExit("No SEPA accounts found.")
    if from_iban:
        needle = from_iban.replace(" ", "").upper()
        for acc in accounts:
            if acc.iban.replace(" ", "").upper() == needle:
                return acc
        raise SystemExit(f"from-iban not found: {from_iban}")
    if len(accounts) == 1:
        return accounts[0]
    print("Multiple accounts found. Please set --from-iban:")
    for acc in accounts:
        print(" -", acc.iban)
    raise SystemExit(2)


def ensure_init_ok(client: FinTS3PinTanClient) -> None:
    while isinstance(getattr(client, "init_tan_response", None), NeedTANResponse):
        client.init_tan_response = complete_tan(client, client.init_tan_response)


def cmd_providers_list(args, _cfg: Config) -> int:
    providers = load_providers()
    rows = providers
    if args.search:
        needle = args.search.lower()
        rows = [
            p for p in rows if needle in p.get("name", "").lower() or needle in p.get("id", "").lower() or needle in p.get("blz", "")
        ]
    if args.country:
        rows = [p for p in rows if p.get("country") == args.country]
    rows = rows[: args.limit]
    print("id\tblz\tname\turl")
    for p in rows:
        print(f"{p.get('id','')}\t{p.get('blz','')}\t{p.get('name','')}\t{p.get('fints_url','')}")
    print(f"\nMatches: {len(rows)}")
    return 0


def cmd_providers_show(args, _cfg: Config) -> int:
    providers = load_providers()
    provider = resolve_provider(args.provider, providers)
    print(json.dumps(provider, indent=2, ensure_ascii=False))
    return 0


def cmd_capabilities(args, cfg: Config) -> int:
    if not cfg.user_id:
        raise SystemExit("Please run bootstrap first.")
    ensure_product_id(cfg, args.product_id)
    pin = get_pin(args, cfg)
    client = build_client(cfg, pin)

    with client:
        ensure_init_ok(client)
        info = client.get_information()

    bank_info = info.get("bank", {})
    out = {
        "provider_id": cfg.provider_id,
        "provider_name": cfg.provider_name,
        "bank_name": bank_info.get("name"),
        "bank_supported_operations": serialize_supported_operations(bank_info.get("supported_operations", {})),
        "accounts": [],
    }
    for acc in info.get("accounts", []):
        if args.iban and normalize_iban(acc.get("iban", "")) != normalize_iban(args.iban):
            continue
        out["accounts"].append(
            {
                "iban": acc.get("iban"),
                "product_name": acc.get("product_name"),
                "currency": acc.get("currency"),
                "supported_operations": serialize_supported_operations(acc.get("supported_operations", {})),
            }
        )

    print(json.dumps(out, indent=2, ensure_ascii=False))
    save_state(client.deconstruct(including_private=True))
    cfg.save()
    return 0


def cmd_bootstrap(args, cfg: Config) -> int:
    if args.provider:
        provider = resolve_provider(args.provider, load_providers())
        apply_provider_to_config(cfg, provider)
        print(
            f"Provider set: {provider.get('id')} - {provider.get('name')} "
            f"({provider.get('blz')} -> {provider.get('fints_url')})"
        )

    if args.user_id:
        cfg.user_id = args.user_id
    if args.customer_id is not None:
        cfg.customer_id = args.customer_id
    if args.server:
        cfg.server = args.server
    if args.blz:
        cfg.blz = args.blz
    ensure_product_id(cfg, args.product_id)
    if not cfg.user_id:
        raise SystemExit("Missing --user-id")

    pin = get_pin(args, cfg)
    client = build_client(cfg, pin)
    minimal_interactive_cli_bootstrap(client)
    save_state(client.deconstruct(including_private=True))
    cfg.save()
    print("Bootstrap ok.")
    return 0


def cmd_accounts(args, cfg: Config) -> int:
    if not cfg.user_id:
        raise SystemExit("Please run bootstrap first.")
    ensure_product_id(cfg, args.product_id)
    pin = get_pin(args, cfg)
    client = build_client(cfg, pin)
    with client:
        ensure_init_ok(client)
        accounts = complete_tan(client, client.get_sepa_accounts())
        for acc in accounts:
            bal = complete_tan(client, client.get_balance(acc))
            amount = getattr(bal, "amount", None)
            currency = getattr(amount, "currency", "")
            print(f"{acc.iban}\t{amount}\t{currency}")
    save_state(client.deconstruct(including_private=True))
    cfg.save()
    return 0


def cmd_transactions(args, cfg: Config) -> int:
    if not cfg.user_id:
        raise SystemExit("Please run bootstrap first.")
    ensure_product_id(cfg, args.product_id)
    pin = get_pin(args, cfg)
    client = build_client(cfg, pin)

    from_date = date.today() - timedelta(days=args.days)
    to_date = date.today()
    with client:
        ensure_init_ok(client)
        accounts = complete_tan(client, client.get_sepa_accounts())
        account = None
        for acc in accounts:
            if args.iban and acc.iban.replace(" ", "") == args.iban.replace(" ", ""):
                account = acc
                break
        if args.iban and not account:
            raise SystemExit(f"IBAN not found: {args.iban}")
        if not account:
            # Default: first account
            account = accounts[0]
        tx = client.get_transactions(account, start_date=from_date, end_date=to_date)
        tx = complete_tan(client, tx)
        rows = []
        for item in tx:
            if hasattr(item, "data"):
                raw_purpose = item.data.get("purpose")
                if isinstance(raw_purpose, list):
                    purpose = " ".join(str(x) for x in raw_purpose if x is not None)
                elif raw_purpose is None:
                    purpose = ""
                else:
                    purpose = str(raw_purpose)
                amount = item.data.get("amount", "")
                booking_date = item.data.get("date", "")
                counterparty_iban = extract_counterparty_iban(item.data, purpose)
                counterparty = (
                    item.data.get("applicant_name")
                    or item.data.get("recipient_name")
                    or item.data.get("name")
                    or ""
                )
                if isinstance(counterparty, list):
                    counterparty = " ".join(str(x) for x in counterparty if x is not None)
                counterparty = str(counterparty)
            else:
                purpose = ""
                amount = ""
                booking_date = ""
                counterparty = ""
                counterparty_iban = ""
            rows.append(
                {
                    "date": clean_text(booking_date),
                    "amount": clean_text(amount),
                    "counterparty": clean_text(counterparty),
                    "counterparty_iban": clean_text(counterparty_iban),
                    "purpose": clean_text(purpose),
                }
            )
        print_transactions(rows, args.format, args.max_purpose)
    save_state(client.deconstruct(including_private=True))
    cfg.save()
    return 0


def validate_transfer_args(args) -> Decimal:
    try:
        amount = Decimal(args.amount)
    except InvalidOperation as exc:
        raise SystemExit(f"Invalid amount: {args.amount}") from exc
    if amount <= 0:
        raise SystemExit("Amount must be > 0.")
    if not validate_iban(args.to_iban):
        raise SystemExit(f"Invalid recipient IBAN: {args.to_iban}")
    if args.to_bic and not validate_bic(args.to_bic):
        raise SystemExit(f"Invalid recipient BIC: {args.to_bic}")
    if len((args.to_name or "").strip()) < 2:
        raise SystemExit("Recipient name is too short.")
    if len((args.reason or "").strip()) < 2:
        raise SystemExit("Purpose is too short.")
    if len(args.reason) > 140:
        raise SystemExit("Purpose is too long (max 140 chars).")
    return amount


def submit_transfer_request(client: FinTS3PinTanClient, cfg: Config, args, amount: Decimal, account):
    return client.simple_sepa_transfer(
        account=account,
        iban=args.to_iban,
        bic=args.to_bic,
        recipient_name=args.to_name,
        amount=amount,
        account_name=args.sender_name or cfg.user_id or "Bankkonto",
        reason=args.reason,
        instant_payment=bool(args.instant),
    )


def cmd_transfer(args, cfg: Config) -> int:
    if not cfg.user_id:
        raise SystemExit("Please run bootstrap first.")
    ensure_product_id(cfg, args.product_id)
    amount = validate_transfer_args(args)

    pin = get_pin(args, cfg)
    client = build_client(cfg, pin)
    with client:
        ensure_init_ok(client)
        accounts = complete_tan(client, client.get_sepa_accounts())
        account = pick_account(accounts, args.from_iban)
        auto_mode = bool(args.auto)
        auto_approve_vop = auto_mode or bool(args.auto_vop)
        auto_poll = auto_mode or bool(args.auto_poll)
        if args.dry_run:
            print("DRY-RUN OK (no order sent)")
            print("  From:  ", account.iban)
            print("  To:    ", normalize_iban(args.to_iban), f"({args.to_name})")
            print("  Amount:", amount, "EUR")
            print("  Purpose:", args.reason)
            print("  Instant:", bool(args.instant))
            return 0

        if not (args.yes or auto_mode):
            print("\nTransfer (preview)")
            print("  From:  ", account.iban)
            print("  To:    ", args.to_iban, f"({args.to_name})")
            print("  Amount:", amount, "EUR")
            print("  Purpose:", args.reason)
            print("  Instant:", bool(args.instant))
            input("Send? Enter = yes, Ctrl+C = abort: ")

        resp = submit_transfer_request(client, cfg, args, amount, account)
        resp = complete_tan(
            client,
            complete_vop_only(client, resp, auto_approve_vop=auto_approve_vop),
            auto_approve_vop=auto_approve_vop,
            decoupled_auto_poll=auto_poll,
            decoupled_poll_interval=args.poll_interval,
            decoupled_timeout=args.poll_timeout,
        )
        print("\nResult:")
        print(getattr(resp, "status", resp))
        responses = getattr(resp, "responses", None)
        if responses:
            for line in responses:
                code = getattr(line, "code", None)
                text = getattr(line, "text", None)
                if code or text:
                    print(" -", code, text)
    save_state(client.deconstruct(including_private=True))
    cfg.save()
    return 0


def cmd_transfer_submit(args, cfg: Config) -> int:
    if not cfg.user_id:
        raise SystemExit("Please run bootstrap first.")
    ensure_product_id(cfg, args.product_id)
    amount = validate_transfer_args(args)

    pin = get_pin(args, cfg)
    client = build_client(cfg, pin)
    with client:
        ensure_init_ok(client)
        accounts = complete_tan(client, client.get_sepa_accounts())
        account = pick_account(accounts, args.from_iban)
        auto_mode = bool(args.auto)
        auto_approve_vop = auto_mode or bool(args.auto_vop)

        if not (args.yes or auto_mode):
            print("\nTransfer (submit preview)")
            print("  From:  ", account.iban)
            print("  To:    ", args.to_iban, f"({args.to_name})")
            print("  Amount:", amount, "EUR")
            print("  Purpose:", args.reason)
            print("  Instant:", bool(args.instant))
            input("Start submit? Enter = yes, Ctrl+C = abort: ")

        resp = submit_transfer_request(client, cfg, args, amount, account)
        resp = complete_vop_only(client, resp, auto_approve_vop=auto_approve_vop)

        if isinstance(resp, NeedTANResponse):
            if not getattr(resp, "decoupled", False):
                raise SystemExit(
                    "Async status polling is only supported for decoupled SCA (app approval)."
                )
            pending_id = uuid.uuid4().hex[:10]
            payload = {
                "version": 1,
                "kind": "transfer",
                "created_at": time.time(),
                "retry_blob": resp.get_data(),
                "dialog_data": client.pause_dialog(),
                "client_state": client.deconstruct(including_private=True),
                "meta": {
                    "from_iban": account.iban,
                    "to_iban": normalize_iban(args.to_iban),
                    "to_name": args.to_name,
                    "amount": str(amount),
                    "reason": args.reason,
                },
            }
            save_pending(pending_id, payload)
            save_state(payload["client_state"])
            cfg.save()
            print("\nTransfer submitted.")
            print(f"Pending ID: {pending_id}")
            print(f"Check status: uv run fints-agent-cli transfer-status --id {pending_id}")
            return 0

        print("\nResult (without pending):")
        print(getattr(resp, "status", resp))
        responses = getattr(resp, "responses", None)
        if responses:
            for line in responses:
                code = getattr(line, "code", None)
                text = getattr(line, "text", None)
                if code or text:
                    print(" -", code, text)
    save_state(client.deconstruct(including_private=True))
    cfg.save()
    return 0


def cmd_transfer_status(args, cfg: Config) -> int:
    if not cfg.user_id:
        raise SystemExit("Please run bootstrap first.")
    ensure_product_id(cfg, args.product_id)

    pending_id = args.id
    if not pending_id:
        ids = list_pending_ids()
        if not ids:
            raise SystemExit("No pending transfers found.")
        pending_id = ids[0]

    payload = load_pending(pending_id)
    pin = get_pin(args, cfg)
    client = build_client_with_state(cfg, pin, payload.get("client_state"))
    retry = NeedRetryResponse.from_data(payload["retry_blob"])

    with client.resume_dialog(payload["dialog_data"]):
        if args.wait:
            resp = complete_tan(
                client,
                retry,
                auto_approve_vop=True,
                decoupled_auto_poll=True,
                decoupled_poll_interval=args.poll_interval,
                decoupled_timeout=args.poll_timeout,
            )
        else:
            try:
                resp = client.send_tan(retry, "")
            except FinTSClientError as exc:
                print(f"Still pending/no final status: {exc}")
                return 0

        if isinstance(resp, NeedTANResponse):
            payload["retry_blob"] = resp.get_data()
            payload["dialog_data"] = client.pause_dialog()
            payload["client_state"] = client.deconstruct(including_private=True)
            payload["updated_at"] = time.time()
            save_pending(pending_id, payload)
            save_state(payload["client_state"])
            cfg.save()
            print(f"Pending ID {pending_id}: not final yet.")
            return 0

        print("\nFinal result:")
        print(getattr(resp, "status", resp))
        responses = getattr(resp, "responses", None)
        if responses:
            for line in responses:
                code = getattr(line, "code", None)
                text = getattr(line, "text", None)
                if code or text:
                    print(" -", code, text)

    save_state(client.deconstruct(including_private=True))
    delete_pending(pending_id)
    cfg.save()
    return 0


def cmd_keychain_setup(args, cfg: Config) -> int:
    if args.user_id:
        cfg.user_id = args.user_id
    account = (args.keychain_account or cfg.keychain_account or cfg.user_id or "").strip()
    service = (args.keychain_service or cfg.keychain_service).strip()
    if not account:
        raise SystemExit("Missing account: set --keychain-account or --user-id.")

    pin = getpass.getpass("Bank PIN (will be stored in Keychain): ")
    keychain_store_pin(service, account, pin)
    cfg.keychain_service = service
    cfg.keychain_account = account
    cfg.save()
    print(f"Keychain setup OK. Service={service}, Account={account}, Key={pin_key(cfg)}")
    return 0


def cmd_init(args, cfg: Config) -> int:
    if args.provider:
        provider = resolve_provider(args.provider, load_providers())
        apply_provider_to_config(cfg, provider)
    if args.user_id:
        cfg.user_id = args.user_id
    if args.customer_id is not None:
        cfg.customer_id = args.customer_id
    if args.product_id is not None:
        cfg.product_id = args.product_id
    if args.keychain_service:
        cfg.keychain_service = args.keychain_service
    if args.keychain_account:
        cfg.keychain_account = args.keychain_account
    cfg.save()
    print(f"Config saved at: {CFG_PATH}")
    print(json.dumps(asdict(cfg), indent=2, ensure_ascii=False))
    return 0


def _prompt_value(prompt: str, default: Optional[str] = None, required: bool = False) -> str:
    while True:
        suffix = f" [{default}]" if default not in (None, "") else ""
        value = input(f"{prompt}{suffix}: ").strip()
        if not value and default not in (None, ""):
            value = str(default)
        if value or not required:
            return value
        print("Value required.")


def _prompt_yes_no(prompt: str, default_yes: bool = True) -> bool:
    default_hint = "Y/n" if default_yes else "y/N"
    value = input(f"{prompt} [{default_hint}]: ").strip().lower()
    if not value:
        return default_yes
    return value in ("y", "yes", "j", "ja")


def cmd_onboard(args, cfg: Config) -> int:
    print("Onboarding started.")

    providers = load_providers()
    provider_default = args.provider or cfg.provider_id or "dkb"
    while True:
        provider_ref = _prompt_value("Provider (id/bank-code/name)", provider_default, required=True)
        try:
            provider = resolve_provider(provider_ref, providers)
            break
        except SystemExit as exc:
            print(str(exc))
            print("Tip: fints-agent-cli providers-list --search <name>")
            provider_default = ""

    apply_provider_to_config(cfg, provider)
    print(
        f"Provider: {provider.get('id')} - {provider.get('name')} "
        f"({provider.get('blz')} -> {provider.get('fints_url')})"
    )

    cfg.user_id = getattr(args, "user_id", None) or _prompt_value("User ID (login name)", cfg.user_id, required=True)
    cfg.customer_id = getattr(args, "customer_id", None) or cfg.customer_id or None
    cfg.product_id = (
        getattr(args, "product_id", None)
        or cfg.product_id
        or os.getenv(ENV_PRODUCT_ID, "").strip()
        or DEFAULT_PRODUCT_ID
    )
    cfg.keychain_service = getattr(args, "keychain_service", None) or cfg.keychain_service or "fints-agent-cli-pin"
    cfg.keychain_account = getattr(args, "keychain_account", None) or cfg.keychain_account or cfg.user_id

    pin = getpass.getpass("PIN (will be stored in Keychain): ")
    if not pin:
        raise SystemExit("PIN must not be empty.")
    keychain_store_pin(cfg.keychain_service, cfg.keychain_account, pin)
    cfg.save()
    print(f"Config saved: {CFG_PATH}")
    print(f"PIN saved in Keychain: service={cfg.keychain_service} account={cfg.keychain_account}")

    if args.no_bootstrap:
        print("Onboarding complete (without bootstrap).")
        print("Next step: fints-agent-cli bootstrap")
        return 0

    client = build_client(cfg, pin)
    minimal_interactive_cli_bootstrap(client)
    save_state(client.deconstruct(including_private=True))
    cfg.save()
    print("Onboarding + bootstrap completed.")
    return 0


def cmd_reset_local(args, _cfg: Config) -> int:
    targets = [CFG_PATH, STATE_PATH, USER_PROVIDERS_PATH]
    pending_paths = list(PENDING_DIR.glob("*.pkl")) if PENDING_DIR.exists() else []

    if not args.yes:
        print("Local files that will be removed:")
        for p in targets:
            if p.exists():
                print(f" - {p}")
        for p in pending_paths:
            print(f" - {p}")
        if not any(p.exists() for p in targets) and not pending_paths:
            print("Nothing to remove.")
            return 0
        if not _prompt_yes_no("Delete all local data?", default_yes=False):
            print("Aborted.")
            return 1

    removed = 0
    for p in targets:
        if p.exists():
            p.unlink()
            removed += 1
    for p in pending_paths:
        if p.exists():
            p.unlink()
            removed += 1
    if PENDING_DIR.exists():
        try:
            PENDING_DIR.rmdir()
        except OSError:
            pass
    print(f"Local settings removed ({removed} files).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="fints-agent-cli",
        description="FinTS Banking CLI (accounts, transactions, transfers).",
        epilog=(
            "Quickstart:\n"
            "  fints-agent-cli onboard\n"
            "  fints-agent-cli accounts\n"
            "  fints-agent-cli transactions --days 30\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logs (only when needed)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_plist = sub.add_parser(
        "providers-list",
        help="List banks",
        description="List known FinTS banks from the static provider registry.",
    )
    p_plist.add_argument("--search", default=None, help="Filter by name/id/bank code, e.g. 'dkb'")
    p_plist.add_argument("--country", default=None, help="Optional country code, e.g. DE")
    p_plist.add_argument("--limit", type=int, default=80, help="Maximum number of matches")

    p_pshow = sub.add_parser(
        "providers-show",
        help="Show bank details",
        description="Show all stored provider parameters (bank code, URL, etc.).",
    )
    p_pshow.add_argument("--provider", required=True, help="Provider ID, bank code, or name")

    p_init = sub.add_parser(
        "init",
        help="Set config directly",
        description="Set configuration values without the interactive wizard.",
    )
    p_init.add_argument("--provider", default=None, help="Provider ID, bank code, or name")
    p_init.add_argument("--user-id", default=None, help="Bank login name")
    p_init.add_argument("--customer-id", default=None, help="Optional, if required by bank")
    p_init.add_argument("--product-id", default=None, help="Optional; otherwise internal default")
    p_init.add_argument("--keychain-service", default=None, help="macOS Keychain service name")
    p_init.add_argument("--keychain-account", default=None, help="macOS Keychain account name")

    p_onb = sub.add_parser(
        "onboard",
        help="Interactive setup",
        description=(
            "One-time setup for normal users.\n"
            "Asks for provider, user ID and PIN, stores the PIN in Keychain,\n"
            "and optionally starts TAN bootstrap immediately."
        ),
        epilog="Example:\n  fints-agent-cli onboard",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p_onb.add_argument("--provider", default=None, help="Provider ID, bank code, or name (optional; otherwise prompt)")
    p_onb.add_argument("--user-id", default=None, help="Bank login name (optional; otherwise prompt)")
    p_onb.add_argument("--no-bootstrap", action="store_true", help="Only config+keychain, no TAN bootstrap")

    p_reset = sub.add_parser(
        "reset-local",
        help="Delete local data",
        description="Deletes local config/state/pending files under ~/.config/fints-agent-cli.",
    )
    p_reset.add_argument("-y", "--yes", action="store_true", help="Delete without confirmation")

    p_boot = sub.add_parser(
        "bootstrap",
        help="Rerun TAN setup",
        description="Runs FinTS TAN mechanism setup again.",
    )
    p_boot.add_argument("--user-id", help="Bank login name")
    p_boot.add_argument("--customer-id", default=None, help="Optional, if required by bank")
    p_boot.add_argument("--product-id", default=None, help="Optional; otherwise internal default")
    p_boot.add_argument("--provider", default=None, help="Provider ID, bank code, or name (sets bank code + URL)")
    p_boot.add_argument("--blz", default=None, help="Override bank code")
    p_boot.add_argument("--server", default=None, help="Override FinTS URL")
    p_boot.add_argument("--keychain-service", default=None, help="Override keychain service")
    p_boot.add_argument("--keychain-account", default=None, help="Override keychain account")
    p_boot.add_argument("--no-keychain", action="store_true", help="Do not read PIN from Keychain")

    p_acc = sub.add_parser("accounts", help="Accounts + balances", description="List accounts and current balances.")
    p_acc.add_argument("--product-id", default=None, help="Optional; otherwise internal default")
    p_acc.add_argument("--keychain-service", default=None, help="Override keychain service")
    p_acc.add_argument("--keychain-account", default=None, help="Override keychain account")
    p_acc.add_argument("--no-keychain", action="store_true", help="Do not read PIN from Keychain")

    p_tx = sub.add_parser(
        "transactions",
        help="Fetch transactions",
        description="Fetch transactions for one account (or default account).",
    )
    p_tx.add_argument("--product-id", default=None, help="Optional; otherwise internal default")
    p_tx.add_argument("--iban", default=None, help="Account IBAN; default account is used if omitted")
    p_tx.add_argument("--days", type=int, default=90, help="Lookback window in days")
    p_tx.add_argument("--format", choices=["pretty", "tsv", "json"], default="pretty", help="Output format")
    p_tx.add_argument("--max-purpose", type=int, default=110, help="Max purpose text length (pretty)")
    p_tx.add_argument("--keychain-service", default=None, help="Override keychain service")
    p_tx.add_argument("--keychain-account", default=None, help="Override keychain account")
    p_tx.add_argument("--no-keychain", action="store_true", help="Do not read PIN from Keychain")

    p_cap = sub.add_parser("capabilities", help="Live discovery of FinTS operations (BPD/UPD)")
    p_cap.add_argument("--product-id", default=None, help="Optional; otherwise internal default")
    p_cap.add_argument("--iban", default=None, help="Optionally filter to one IBAN")
    p_cap.add_argument("--keychain-service", default=None)
    p_cap.add_argument("--keychain-account", default=None)
    p_cap.add_argument("--no-keychain", action="store_true")

    p_tr = sub.add_parser("transfer", help="Send SEPA transfer", description="Sends a SEPA transfer.")
    p_tr.add_argument("--product-id", default=None, help="Optional; otherwise internal default")
    p_tr.add_argument("--from-iban", default=None, help="Sender IBAN (recommended with multiple accounts)")
    p_tr.add_argument("--to-iban", required=True, help="Recipient IBAN")
    p_tr.add_argument("--to-bic", default=None, help="Recipient BIC (optional)")
    p_tr.add_argument("--to-name", required=True, help="Recipient name")
    p_tr.add_argument("--amount", required=True, help="e.g. 12.34")
    p_tr.add_argument("--reason", required=True, help="Purpose")
    p_tr.add_argument("--sender-name", default=None, help="Sender name in payment order (optional)")
    p_tr.add_argument("--instant", action="store_true", help="Request instant transfer")
    p_tr.add_argument("--dry-run", action="store_true", help="Validate locally only, send nothing")
    p_tr.add_argument("--auto", action="store_true", help="No prompts: -y + auto VoP + auto app polling")
    p_tr.add_argument("--auto-vop", action="store_true", help="Auto-approve VoP prompts")
    p_tr.add_argument("--auto-poll", action="store_true", help="Auto-poll decoupled SCA")
    p_tr.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds")
    p_tr.add_argument("--poll-timeout", type=int, default=180, help="Polling timeout in seconds")
    p_tr.add_argument("-y", "--yes", action="store_true", help="Skip prompts")
    p_tr.add_argument("--keychain-service", default=None, help="Override keychain service")
    p_tr.add_argument("--keychain-account", default=None, help="Override keychain account")
    p_tr.add_argument("--no-keychain", action="store_true", help="Do not read PIN from Keychain")

    p_tsub = sub.add_parser(
        "transfer-submit",
        help="Start transfer asynchronously",
        description="Starts order and returns pending ID for later status checks.",
    )
    p_tsub.add_argument("--product-id", default=None, help="Optional; otherwise internal default")
    p_tsub.add_argument("--from-iban", default=None)
    p_tsub.add_argument("--to-iban", required=True, help="Recipient IBAN")
    p_tsub.add_argument("--to-bic", default=None, help="Recipient BIC (optional)")
    p_tsub.add_argument("--to-name", required=True, help="Recipient name")
    p_tsub.add_argument("--amount", required=True, help="e.g. 12.34")
    p_tsub.add_argument("--reason", required=True, help="Purpose")
    p_tsub.add_argument("--sender-name", default=None, help="Sender name in payment order (optional)")
    p_tsub.add_argument("--instant", action="store_true", help="Request instant transfer")
    p_tsub.add_argument("--auto", action="store_true", help="No prompts: -y + auto VoP")
    p_tsub.add_argument("--auto-vop", action="store_true", help="Auto-approve VoP prompts")
    p_tsub.add_argument("-y", "--yes", action="store_true", help="Skip prompts")
    p_tsub.add_argument("--keychain-service", default=None, help="Override keychain service")
    p_tsub.add_argument("--keychain-account", default=None, help="Override keychain account")
    p_tsub.add_argument("--no-keychain", action="store_true", help="Do not read PIN from Keychain")

    p_tstatus = sub.add_parser(
        "transfer-status",
        help="Status of an async transfer",
        description="Checks/continues a previously started async transfer by pending ID.",
    )
    p_tstatus.add_argument("--product-id", default=None, help="Optional; otherwise internal default")
    p_tstatus.add_argument("--id", default=None, help="Pending ID (default: newest)")
    p_tstatus.add_argument("--wait", action="store_true", help="Auto-poll until final or timeout")
    p_tstatus.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds")
    p_tstatus.add_argument("--poll-timeout", type=int, default=180, help="Polling timeout in seconds")
    p_tstatus.add_argument("--keychain-service", default=None, help="Override keychain service")
    p_tstatus.add_argument("--keychain-account", default=None, help="Override keychain account")
    p_tstatus.add_argument("--no-keychain", action="store_true", help="Do not read PIN from Keychain")

    p_kc = sub.add_parser(
        "keychain-setup",
        help="Store PIN in Keychain",
        description="Stores PIN in macOS Keychain for later automatic use.",
    )
    p_kc.add_argument("--user-id", default=None, help="Bank login name")
    p_kc.add_argument("--keychain-service", default=None, help="Keychain service name")
    p_kc.add_argument("--keychain-account", default=None, help="Keychain account name")

    args = parser.parse_args()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
        warnings.simplefilter("default", FinTSParserWarning)
    else:
        logging.basicConfig(level=logging.CRITICAL)
        logging.getLogger("fints").setLevel(logging.CRITICAL)
        warnings.filterwarnings("ignore", category=FinTSParserWarning)

    cfg = Config.load()
    if args.cmd == "providers-list":
        return cmd_providers_list(args, cfg)
    if args.cmd == "providers-show":
        return cmd_providers_show(args, cfg)
    if args.cmd == "init":
        return cmd_init(args, cfg)
    if args.cmd == "onboard":
        return cmd_onboard(args, cfg)
    if args.cmd == "reset-local":
        return cmd_reset_local(args, cfg)
    if args.cmd == "bootstrap":
        return cmd_bootstrap(args, cfg)
    if args.cmd == "accounts":
        return cmd_accounts(args, cfg)
    if args.cmd == "capabilities":
        return cmd_capabilities(args, cfg)
    if args.cmd == "transactions":
        return cmd_transactions(args, cfg)
    if args.cmd == "transfer":
        return cmd_transfer(args, cfg)
    if args.cmd == "transfer-submit":
        return cmd_transfer_submit(args, cfg)
    if args.cmd == "transfer-status":
        return cmd_transfer_status(args, cfg)
    if args.cmd == "keychain-setup":
        return cmd_keychain_setup(args, cfg)
    raise SystemExit("Unknown command")


if __name__ == "__main__":
    raise SystemExit(main())

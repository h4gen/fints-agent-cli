import argparse
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

import fints_agent_cli as fac


class DummyAccount:
    def __init__(self, iban: str):
        self.iban = iban


class DummyClient:
    def __init__(self, accounts=None):
        self.accounts = accounts or [DummyAccount("DE30120300001053830582")]
        self.init_tan_response = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_sepa_accounts(self):
        return self.accounts

    def deconstruct(self, including_private=True):
        return b"state"

    def pause_dialog(self):
        return b"dialog"

    def resume_dialog(self, _data):
        return self

    def send_tan(self, _resp, _tan):
        return SimpleNamespace(status="OK", responses=[])


def base_cfg() -> fac.Config:
    return fac.Config(
        user_id="hagenho",
        product_id="6151256F3D4F9975B877BD4A2",
        keychain_service="fints-agent-cli-pin",
        keychain_account="hagenho",
    )


def base_transfer_args(**overrides):
    data = {
        "product_id": None,
        "from_iban": None,
        "to_iban": "DE02100100109307118603",
        "to_bic": None,
        "to_name": "Max Mustermann",
        "amount": "12.34",
        "reason": "Testueberweisung",
        "sender_name": None,
        "instant": False,
        "dry_run": False,
        "auto": False,
        "auto_vop": False,
        "auto_poll": False,
        "poll_interval": 0.01,
        "poll_timeout": 3,
        "yes": True,
        "keychain_service": None,
        "keychain_account": None,
        "no_keychain": True,
    }
    data.update(overrides)
    return argparse.Namespace(**data)


def test_validate_iban_and_bic():
    assert fac.validate_iban("DE02100100109307118603")
    assert not fac.validate_iban("DE00INVALID")
    assert fac.validate_bic("DEUTDEFF")
    assert fac.validate_bic("DEUTDEFF500")
    assert not fac.validate_bic("BAD")


def test_validate_transfer_args_ok():
    args = base_transfer_args()
    amount = fac.validate_transfer_args(args)
    assert amount == Decimal("12.34")


def test_validate_transfer_args_rejects_invalid():
    args = base_transfer_args(amount="-1")
    with pytest.raises(SystemExit, match="Amount must be > 0"):
        fac.validate_transfer_args(args)

    args = base_transfer_args(to_iban="DE00BAD")
    with pytest.raises(SystemExit, match="Invalid recipient IBAN"):
        fac.validate_transfer_args(args)

    args = base_transfer_args(reason="x")
    with pytest.raises(SystemExit, match="Purpose is too short"):
        fac.validate_transfer_args(args)


def test_get_pin_uses_keychain(monkeypatch):
    cfg = base_cfg()
    args = argparse.Namespace(
        no_keychain=False, keychain_service=None, keychain_account=None
    )
    monkeypatch.setattr(fac, "keychain_get_pin", lambda *_: "1234")
    monkeypatch.setattr(fac.getpass, "getpass", lambda *_: "fallback")
    assert fac.get_pin(args, cfg) == "1234"


def test_get_pin_falls_back_to_prompt(monkeypatch):
    cfg = base_cfg()
    args = argparse.Namespace(
        no_keychain=False, keychain_service=None, keychain_account=None
    )
    monkeypatch.setattr(fac, "keychain_get_pin", lambda *_: None)
    monkeypatch.setattr(fac.getpass, "getpass", lambda *_: "prompt-pin")
    assert fac.get_pin(args, cfg) == "prompt-pin"


def test_get_pin_no_keychain_forces_prompt(monkeypatch):
    cfg = base_cfg()
    args = argparse.Namespace(
        no_keychain=True, keychain_service=None, keychain_account=None
    )
    monkeypatch.setattr(fac, "keychain_get_pin", lambda *_: "should-not-be-used")
    monkeypatch.setattr(fac.getpass, "getpass", lambda *_: "prompt-only")
    assert fac.get_pin(args, cfg) == "prompt-only"


def test_keychain_get_pin_success(monkeypatch):
    proc = SimpleNamespace(returncode=0, stdout="1234\n", stderr="")
    monkeypatch.setattr(fac.subprocess, "run", lambda *_, **__: proc)
    assert fac.keychain_get_pin("svc", "acc") == "1234"


def test_keychain_get_pin_not_found(monkeypatch):
    proc = SimpleNamespace(returncode=44, stdout="", stderr="not found")
    monkeypatch.setattr(fac.subprocess, "run", lambda *_, **__: proc)
    assert fac.keychain_get_pin("svc", "acc") is None


def test_keychain_store_pin_failure(monkeypatch):
    proc = SimpleNamespace(returncode=44, stdout="", stderr="boom")
    monkeypatch.setattr(fac.subprocess, "run", lambda *_, **__: proc)
    with pytest.raises(SystemExit, match="Failed to save to Keychain"):
        fac.keychain_store_pin("svc", "acc", "1234")


def test_resolve_keychain_precedence():
    cfg = base_cfg()
    args = argparse.Namespace(keychain_service="svc-cli", keychain_account="acc-cli")
    service, account = fac.resolve_keychain(args, cfg)
    assert service == "svc-cli"
    assert account == "acc-cli"


def test_cmd_keychain_setup_with_dummy_pin(monkeypatch, capsys):
    cfg = base_cfg()
    cfg.keychain_service = "old-service"
    cfg.keychain_account = "old-account"
    args = argparse.Namespace(
        user_id="hagenho",
        keychain_service="dummy-service",
        keychain_account="dummy-account",
    )
    monkeypatch.setattr(fac.getpass, "getpass", lambda *_: "0000")
    stored = {}

    def _store(service, account, pin):
        stored["service"] = service
        stored["account"] = account
        stored["pin"] = pin

    monkeypatch.setattr(fac, "keychain_store_pin", _store)
    monkeypatch.setattr(fac.Config, "save", lambda *_: None)

    rc = fac.cmd_keychain_setup(args, cfg)
    out = capsys.readouterr().out
    assert rc == 0
    assert stored == {"service": "dummy-service", "account": "dummy-account", "pin": "0000"}
    assert cfg.keychain_service == "dummy-service"
    assert cfg.keychain_account == "dummy-account"
    assert "Keychain setup OK." in out


def test_ensure_product_id_prefers_cli_over_env(monkeypatch):
    cfg = fac.Config(product_id=None)
    monkeypatch.setenv(fac.ENV_PRODUCT_ID, "FROM_ENV")
    fac.ensure_product_id(cfg, "FROM_CLI")
    assert cfg.product_id == "FROM_CLI"


def test_ensure_product_id_uses_default_when_missing(monkeypatch):
    cfg = fac.Config(product_id=None)
    monkeypatch.delenv(fac.ENV_PRODUCT_ID, raising=False)
    fac.ensure_product_id(cfg, None)
    assert cfg.product_id == fac.DEFAULT_PRODUCT_ID


def test_pick_account_with_multiple_requires_from_iban(capsys):
    accounts = [DummyAccount("DE11"), DummyAccount("DE22")]
    with pytest.raises(SystemExit):
        fac.pick_account(accounts, None)
    out = capsys.readouterr().out
    assert "--from-iban" in out


def test_print_transactions_tsv(capsys):
    rows = [
        {
            "date": "2026-02-16",
            "amount": "-3.43 EUR",
            "counterparty": "EDEKA",
            "counterparty_iban": "DE02100100109307118603",
            "purpose": "VISA Debitkartenumsatz",
        }
    ]
    fac.print_transactions(rows, "tsv", 120)
    out = capsys.readouterr().out
    assert "date\tamount\tcounterparty\tcounterparty_iban\tpurpose" in out
    assert "2026-02-16" in out
    assert "DE02100100109307118603" in out


def test_extract_counterparty_iban_prefers_recipient():
    data = {
        "recipient_iban": "DE02 1001 0010 9307 1186 03",
        "applicant_iban": "DE75512108001245126199",
    }
    iban = fac.extract_counterparty_iban(data, "")
    assert iban == "DE02100100109307118603"


def test_cmd_transfer_dry_run_no_submit(monkeypatch, capsys):
    cfg = base_cfg()
    args = base_transfer_args(dry_run=True, yes=False, auto=False)
    client = DummyClient()

    monkeypatch.setattr(fac, "get_pin", lambda *_: "1234")
    monkeypatch.setattr(fac, "build_client", lambda *_: client)
    monkeypatch.setattr(fac, "ensure_init_ok", lambda *_: None)
    monkeypatch.setattr(fac, "complete_tan", lambda _c, resp, **_: resp)
    monkeypatch.setattr(fac, "save_state", lambda *_: None)
    monkeypatch.setattr(fac.Config, "save", lambda *_: None)

    called = {"transfer": False}

    def _submit(*_args, **_kwargs):
        called["transfer"] = True
        return None

    monkeypatch.setattr(fac, "submit_transfer_request", _submit)

    rc = fac.cmd_transfer(args, cfg)
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN OK" in out
    assert called["transfer"] is False


def test_cmd_transfer_submit_creates_pending(monkeypatch, capsys):
    cfg = base_cfg()
    args = base_transfer_args(auto=True, yes=True)
    client = DummyClient()

    class DummyNeedTan:
        def __init__(self):
            self.decoupled = True

        def get_data(self):
            return b"retry"

    monkeypatch.setattr(fac, "NeedTANResponse", DummyNeedTan)
    monkeypatch.setattr(fac, "get_pin", lambda *_: "1234")
    monkeypatch.setattr(fac, "build_client", lambda *_: client)
    monkeypatch.setattr(fac, "ensure_init_ok", lambda *_: None)
    monkeypatch.setattr(fac, "complete_tan", lambda _c, resp, **_: resp)
    monkeypatch.setattr(fac, "complete_vop_only", lambda _c, resp, **_: resp)
    monkeypatch.setattr(fac, "submit_transfer_request", lambda *_: DummyNeedTan())
    monkeypatch.setattr(fac, "save_state", lambda *_: None)
    monkeypatch.setattr(fac.Config, "save", lambda *_: None)
    monkeypatch.setattr(fac.uuid, "uuid4", lambda: SimpleNamespace(hex="abc123def456"))
    monkeypatch.setattr(fac.time, "time", lambda: 1700000000.0)

    saved = {}

    def _save_pending(pid, payload):
        saved["id"] = pid
        saved["payload"] = payload

    monkeypatch.setattr(fac, "save_pending", _save_pending)

    rc = fac.cmd_transfer_submit(args, cfg)
    out = capsys.readouterr().out
    assert rc == 0
    assert saved["id"] == "abc123def4"
    assert saved["payload"]["retry_blob"] == b"retry"
    assert "Pending ID" in out


def test_cmd_transfer_status_wait_final_deletes_pending(monkeypatch, capsys):
    cfg = base_cfg()
    args = argparse.Namespace(
        id="pending1",
        wait=True,
        poll_interval=0.01,
        poll_timeout=1,
        product_id=None,
        keychain_service=None,
        keychain_account=None,
        no_keychain=True,
    )
    client = DummyClient()

    class DummyNeedRetry:
        @staticmethod
        def from_data(data):
            assert data == b"retry"
            return "retry-token"

    payload = {
        "retry_blob": b"retry",
        "dialog_data": b"dialog",
        "client_state": b"state",
    }
    final = SimpleNamespace(status="SUCCESS", responses=[SimpleNamespace(code="0020", text="OK")])

    monkeypatch.setattr(fac, "NeedRetryResponse", DummyNeedRetry)
    monkeypatch.setattr(fac, "load_pending", lambda _pid: payload)
    monkeypatch.setattr(fac, "get_pin", lambda *_: "1234")
    monkeypatch.setattr(fac, "build_client_with_state", lambda *_: client)
    monkeypatch.setattr(fac, "complete_tan", lambda _c, _r, **_: final)
    monkeypatch.setattr(fac, "save_state", lambda *_: None)
    monkeypatch.setattr(fac.Config, "save", lambda *_: None)

    deleted = {"id": None}
    monkeypatch.setattr(fac, "delete_pending", lambda pid: deleted.__setitem__("id", pid))

    rc = fac.cmd_transfer_status(args, cfg)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Final result" in out
    assert deleted["id"] == "pending1"


def test_import_aqbanking_bankinfo_parses_pintan(tmp_path):
    sample = """# header

bankId="50010517"
bic="INGDDEFFXXX"
bankName="ING-DiBa"
location="Frankfurt"
zipcode="00000"
city="Frankfurt"
services {
  element {
    type="HBCI"
    address="https%3A%2F%2Ffints.ing.de%2Ffints%2F"
    pversion=""
    mode="PINTAN"
    userFlags="0"
  }
}

bankId="10011001"
bic="NTSBDEB1XXX"
bankName="N26 Bank"
location="Berlin"
zipcode="10179"
city="Berlin"
services {
}
"""
    p = tmp_path / "banks.data"
    p.write_text(sample, encoding="utf-8")
    providers = fac.import_aqbanking_bankinfo(p)
    assert len(providers) == 1
    assert providers[0]["id"] == "de-50010517"
    assert providers[0]["fints_url"] == "https://fints.ing.de/fints/"


def test_resolve_provider_by_id_and_blz():
    providers = [
        {"id": "dkb", "name": "Deutsche Kreditbank", "blz": "12030000", "fints_url": "https://fints.dkb.de/fints"},
        {"id": "de-50010517", "name": "ING", "blz": "50010517", "fints_url": "https://fints.ing.de/fints/"},
    ]
    assert fac.resolve_provider("dkb", providers)["blz"] == "12030000"
    assert fac.resolve_provider("50010517", providers)["id"] == "de-50010517"


def test_cmd_init_applies_provider(monkeypatch, tmp_path, capsys):
    cfg = fac.Config()
    args = argparse.Namespace(
        provider="dkb",
        user_id="hagenho",
        customer_id=None,
        product_id="PID",
        keychain_service="svc",
        keychain_account="acc",
    )
    providers = [
        {
            "id": "dkb",
            "name": "DKB",
            "blz": "12030000",
            "fints_url": "https://fints.dkb.de/fints",
        }
    ]
    monkeypatch.setattr(fac, "load_providers", lambda: providers)
    monkeypatch.setattr(fac.Config, "save", lambda *_: None)

    rc = fac.cmd_init(args, cfg)
    out = capsys.readouterr().out
    assert rc == 0
    assert cfg.provider_id == "dkb"
    assert cfg.blz == "12030000"
    assert cfg.server == "https://fints.dkb.de/fints"
    assert cfg.user_id == "hagenho"
    assert cfg.product_id == "PID"
    assert "Config saved" in out
    assert json.loads(out.split("\n", 1)[1])["provider_id"] == "dkb"


def test_cmd_onboard_non_bootstrap(monkeypatch, capsys):
    cfg = fac.Config()
    args = argparse.Namespace(
        provider="dkb",
        user_id="hagenho",
        customer_id="",
        product_id="PID123",
        keychain_service="fints-agent-cli-pin",
        keychain_account="hagenho",
        refresh_providers=False,
        no_bootstrap=True,
    )
    providers = [
        {
            "id": "dkb",
            "name": "DKB",
            "blz": "12030000",
            "fints_url": "https://fints.dkb.de/fints",
        }
    ]
    monkeypatch.setattr(fac, "load_providers", lambda: providers)
    monkeypatch.setattr(fac, "_prompt_value", lambda _p, default=None, required=False: default or "")
    monkeypatch.setattr(fac.getpass, "getpass", lambda *_: "0000")
    stored = {}
    monkeypatch.setattr(
        fac,
        "keychain_store_pin",
        lambda service, account, pin: stored.update({"service": service, "account": account, "pin": pin}),
    )
    monkeypatch.setattr(fac.Config, "save", lambda *_: None)

    rc = fac.cmd_onboard(args, cfg)
    out = capsys.readouterr().out
    assert rc == 0
    assert cfg.provider_id == "dkb"
    assert cfg.user_id == "hagenho"
    assert cfg.product_id == "PID123"
    assert stored["service"] == "fints-agent-cli-pin"
    assert stored["account"] == "hagenho"
    assert "Onboarding complete (without bootstrap)." in out


def test_cmd_reset_local_yes(monkeypatch, tmp_path, capsys):
    cfg = fac.Config()
    cfg_path = tmp_path / "config.json"
    state_path = tmp_path / "client_state.bin"
    providers_path = tmp_path / "providers.json"
    pending_dir = tmp_path / "pending"
    pending_dir.mkdir()
    pending_file = pending_dir / "abc.pkl"

    cfg_path.write_text("{}", encoding="utf-8")
    state_path.write_bytes(b"x")
    providers_path.write_text("{}", encoding="utf-8")
    pending_file.write_bytes(b"x")

    monkeypatch.setattr(fac, "CFG_PATH", cfg_path)
    monkeypatch.setattr(fac, "STATE_PATH", state_path)
    monkeypatch.setattr(fac, "USER_PROVIDERS_PATH", providers_path)
    monkeypatch.setattr(fac, "PENDING_DIR", pending_dir)

    args = argparse.Namespace(yes=True)
    rc = fac.cmd_reset_local(args, cfg)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Local settings removed" in out
    assert not cfg_path.exists()
    assert not state_path.exists()
    assert not providers_path.exists()
    assert not pending_file.exists()

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.alerts.models import AlertEvent
from apps.audit.models import AuditRecord
from apps.binance_account_sync.models import (
    BinanceAccountSnapshot,
    BinanceBalanceSnapshot,
    BinancePositionMode,
    BinancePositionSnapshot,
    BinanceSymbolRuleSnapshot,
    BinanceSyncPurpose,
    BinanceSyncRun,
    BinanceSyncStatus,
)
from apps.binance_account_sync.selectors import load_trade_preparation_context
from apps.binance_account_sync.services.sync import (
    SyncRequest,
    create_running_run,
    refresh_for_ops_console,
    sync_for_trade_preparation,
)
from apps.binance_gateway.account_read import FakeBinanceAccountReadGateway
from apps.binance_gateway.public_market import FakeBinancePublicMarketGateway
from apps.binance_gateway.types import MARKET_TYPE_COIN_M, MARKET_TYPE_USDS_M
from apps.foundation.results import ResultStatus


pytestmark = pytest.mark.django_db


def enable_account_sync(settings, *, market_type: str = "USDS-M", symbols: list[str] | None = None) -> None:
    settings.ACTIVE_MARKET_TYPE = market_type
    settings.ACTIVE_ACCOUNT_DOMAIN = "default"
    settings.BINANCE_ACCOUNT_SYNC_ENABLED = True
    settings.BINANCE_ACCOUNT_SYNC_TTL_SECONDS = 1800
    settings.BINANCE_ACCOUNT_SYNC_SYMBOLS = symbols or ["BTCUSDT"]


def account_payload() -> dict[str, object]:
    return {
        "feeTier": 0,
        "canTrade": True,
        "canDeposit": True,
        "canWithdraw": True,
        "totalWalletBalance": "1000",
        "totalUnrealizedProfit": "1",
        "totalMarginBalance": "1001",
        "availableBalance": "900",
        "maxWithdrawAmount": "800",
        "asset": "USDT",
    }


def balances_payload(asset: str = "USDT") -> list[dict[str, object]]:
    return [
        {
            "asset": asset,
            "balance": "1000",
            "crossWalletBalance": "1000",
            "crossUnPnl": "1",
            "availableBalance": "900",
            "maxWithdrawAmount": "800",
            "marginAvailable": True,
            "updateTime": 1767225600000,
        }
    ]


def one_way_position(symbol: str = "BTCUSDT", *, leverage: str = "10", margin_asset: str = "USDT") -> list[dict[str, object]]:
    return [
        {
            "symbol": symbol,
            "positionSide": "BOTH",
            "positionAmt": "0.1",
            "entryPrice": "50000",
            "breakEvenPrice": "50000",
            "markPrice": "51000",
            "unRealizedProfit": "100",
            "liquidationPrice": "30000",
            "isolatedMargin": "0",
            "notional": "5100",
            "marginAsset": margin_asset,
            "isolated": False,
            "leverage": leverage,
            "updateTime": 1767225600000,
        }
    ]


def hedge_positions(symbol: str = "BTCUSDT") -> list[dict[str, object]]:
    return [
        {**one_way_position(symbol)[0], "positionSide": "LONG", "positionAmt": "0.1"},
        {**one_way_position(symbol)[0], "positionSide": "SHORT", "positionAmt": "0"},
    ]


def exchange_info_payload(
    symbol: str = "BTCUSDT",
    *,
    margin_asset: str = "USDT",
    settle_asset: str = "USDT",
    contract_size: str | None = None,
) -> dict[str, object]:
    info: dict[str, object] = {
        "symbol": symbol,
        "status": "TRADING",
        "baseAsset": "BTC",
        "quoteAsset": "USDT",
        "marginAsset": margin_asset,
        "settleAsset": settle_asset,
        "contractType": "PERPETUAL",
        "pricePrecision": 2,
        "quantityPrecision": 3,
        "orderTypes": ["MARKET"],
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.10", "minPrice": "0.10", "maxPrice": "1000000"},
            {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "1000"},
            {"filterType": "MIN_NOTIONAL", "notional": "5"},
        ],
    }
    if contract_size is not None:
        info["contractSize"] = contract_size
    return {"symbols": [info]}


def fake_account_gateway(
    *,
    positions: list[dict[str, object]] | None = None,
    balances: list[dict[str, object]] | None = None,
    fail_operation: str = "",
) -> FakeBinanceAccountReadGateway:
    return FakeBinanceAccountReadGateway(
        account_payload=account_payload(),
        balances_payload=balances or balances_payload(),
        positions_payload=positions or one_way_position(),
        fail_operation=fail_operation,
    )


def fake_market_gateway(payload: dict[str, object] | None = None, *, fail_operation: str = "") -> FakeBinancePublicMarketGateway:
    return FakeBinancePublicMarketGateway(
        server_time_utc=datetime(2026, 1, 1, tzinfo=UTC),
        exchange_info_payload=payload or exchange_info_payload(),
        fail_operation=fail_operation,
    )


def run_trade_sync(
    settings,
    *,
    key: str = "prep:2026-01-01T00:00:00Z",
    market_type: str = MARKET_TYPE_USDS_M,
    account_gateway: FakeBinanceAccountReadGateway | None = None,
    market_gateway: FakeBinancePublicMarketGateway | None = None,
):
    enable_account_sync(settings, market_type="USDS-M" if market_type == MARKET_TYPE_USDS_M else "COIN-M")
    return sync_for_trade_preparation(
        business_request_key=key,
        market_type=market_type,
        account_domain="default",
        symbols=["BTCUSDT"] if market_type == MARKET_TYPE_USDS_M else ["BTCUSD_PERP"],
        trace_id=f"trace-{key}",
        trigger_source="test",
        account_gateway=account_gateway or fake_account_gateway(),
        market_gateway=market_gateway or fake_market_gateway(),
    )


def test_trade_preparation_sync_writes_account_position_balance_and_rule_snapshots(settings) -> None:
    account_gateway = fake_account_gateway()
    market_gateway = fake_market_gateway()

    result = run_trade_sync(settings, account_gateway=account_gateway, market_gateway=market_gateway)

    assert result.status == ResultStatus.SUCCEEDED
    run = BinanceSyncRun.objects.get(id=result.data["binance_sync_run_id"])
    assert run.sync_purpose == BinanceSyncPurpose.TRADE_PREPARATION
    assert run.status == BinanceSyncStatus.SUCCEEDED
    assert run.position_mode == BinancePositionMode.ONE_WAY
    assert run.snapshot_set_hash
    assert run.as_of_utc is not None
    assert run.expires_at_utc is not None
    assert BinanceAccountSnapshot.objects.filter(sync_run=run).count() == 1
    assert BinanceBalanceSnapshot.objects.filter(sync_run=run, asset="USDT").count() == 1
    assert BinancePositionSnapshot.objects.filter(sync_run=run, symbol="BTCUSDT", normalized_position_side="BOTH").count() == 1
    assert BinanceSymbolRuleSnapshot.objects.filter(sync_run=run, symbol="BTCUSDT").count() == 1
    assert [call["operation"] for call in account_gateway.calls] == ["get_account", "get_balances", "get_positions"]
    assert [call["operation"] for call in market_gateway.calls] == ["get_symbol_exchange_info"]


def test_trade_preparation_sync_is_idempotent_by_business_request_key(settings) -> None:
    account_gateway = fake_account_gateway()
    market_gateway = fake_market_gateway()

    first = run_trade_sync(settings, key="prep:same", account_gateway=account_gateway, market_gateway=market_gateway)
    second = run_trade_sync(settings, key="prep:same", account_gateway=account_gateway, market_gateway=market_gateway)

    assert first.data["binance_sync_run_id"] == second.data["binance_sync_run_id"]
    assert BinanceSyncRun.objects.count() == 1
    assert len(account_gateway.calls) == 3
    assert len(market_gateway.calls) == 1


def test_running_sync_request_is_not_claimed_twice(settings) -> None:
    enable_account_sync(settings)
    request = SyncRequest(
        business_request_key="prep:running-race",
        sync_purpose=BinanceSyncPurpose.TRADE_PREPARATION,
        market_type=MARKET_TYPE_USDS_M,
        account_domain="default",
        symbols=("BTCUSDT",),
        trace_id="trace-running-race",
        trigger_source="test",
    )

    first, first_created = create_running_run(request)
    second, second_created = create_running_run(request)

    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    assert BinanceSyncRun.objects.count() == 1


def test_disabled_account_sync_creates_failed_run_and_alert_without_gateway_calls(settings) -> None:
    enable_account_sync(settings)
    settings.BINANCE_ACCOUNT_SYNC_ENABLED = False
    account_gateway = fake_account_gateway()
    market_gateway = fake_market_gateway()

    result = sync_for_trade_preparation(
        business_request_key="prep:disabled",
        market_type="USDS-M",
        account_domain="default",
        symbols=["BTCUSDT"],
        trace_id="trace-disabled",
        trigger_source="test",
        account_gateway=account_gateway,
        market_gateway=market_gateway,
    )

    run = BinanceSyncRun.objects.get(id=result.data["binance_sync_run_id"])
    assert result.status == ResultStatus.FAILED
    assert run.status == BinanceSyncStatus.FAILED
    assert run.error_code == "account_sync_disabled"
    assert account_gateway.calls == []
    assert market_gateway.calls == []
    assert AlertEvent.objects.filter(source_module="BinanceAccountSync", event_type="binance_account_sync_failed").exists()


def test_gateway_failure_does_not_fallback_to_previous_successful_sync(settings) -> None:
    first = run_trade_sync(settings, key="prep:success")
    assert first.status == ResultStatus.SUCCEEDED

    failing_gateway = fake_account_gateway(fail_operation="get_positions")
    failed = run_trade_sync(settings, key="prep:failed", account_gateway=failing_gateway)

    failed_run = BinanceSyncRun.objects.get(id=failed.data["binance_sync_run_id"])
    assert failed.status == ResultStatus.FAILED
    assert failed_run.status == BinanceSyncStatus.FAILED
    assert failed_run.error_code == "gateway_positions_failed"
    assert BinanceAccountSnapshot.objects.filter(sync_run=failed_run).count() == 0
    assert BinanceSyncRun.objects.count() == 2


def test_ops_display_sync_writes_audit_but_is_blocked_for_trading_context(settings) -> None:
    enable_account_sync(settings)

    result = refresh_for_ops_console(
        operator_id="operator-1",
        trace_id="trace-ops",
        account_gateway=fake_account_gateway(),
        market_gateway=fake_market_gateway(),
    )
    context = load_trade_preparation_context(
        sync_run_id=result.data["binance_sync_run_id"],
        symbol="BTCUSDT",
        trace_id="trace-ops-context",
        trigger_source="test",
    )

    assert result.status == ResultStatus.SUCCEEDED
    assert BinanceSyncRun.objects.get(id=result.data["binance_sync_run_id"]).sync_purpose == BinanceSyncPurpose.OPS_DISPLAY
    assert AuditRecord.objects.filter(operation_type="binance_account_sync_ops_refresh").exists()
    assert context.status == ResultStatus.BLOCKED
    assert context.reason_code == "binance_sync_run_not_trade_preparation"


def test_hedge_position_mode_sync_succeeds_but_trading_context_is_blocked(settings) -> None:
    result = run_trade_sync(settings, key="prep:hedge", account_gateway=fake_account_gateway(positions=hedge_positions()))

    context = load_trade_preparation_context(
        sync_run_id=result.data["binance_sync_run_id"],
        symbol="BTCUSDT",
        trace_id="trace-hedge-context",
        trigger_source="test",
    )

    assert result.status == ResultStatus.SUCCEEDED
    assert BinanceSyncRun.objects.get(id=result.data["binance_sync_run_id"]).position_mode == BinancePositionMode.HEDGE
    assert context.status == ResultStatus.BLOCKED
    assert context.reason_code == "position_mode_not_supported"


def test_invalid_observed_leverage_is_saved_as_null(settings) -> None:
    result = run_trade_sync(settings, key="prep:invalid-leverage", account_gateway=fake_account_gateway(positions=one_way_position(leverage="0")))

    position = BinancePositionSnapshot.objects.get(sync_run_id=result.data["binance_sync_run_id"], symbol="BTCUSDT")
    assert result.status == ResultStatus.SUCCEEDED
    assert position.observed_exchange_leverage is None


def test_coin_m_requires_valid_contract_size_for_trading_context(settings) -> None:
    result = run_trade_sync(
        settings,
        key="prep:coin-missing-contract-size",
        market_type=MARKET_TYPE_COIN_M,
        account_gateway=fake_account_gateway(
            positions=one_way_position("BTCUSD_PERP", margin_asset="BTC"),
            balances=balances_payload("BTC"),
        ),
        market_gateway=fake_market_gateway(exchange_info_payload("BTCUSD_PERP", margin_asset="BTC", settle_asset="BTC")),
    )

    context = load_trade_preparation_context(
        sync_run_id=result.data["binance_sync_run_id"],
        symbol="BTCUSD_PERP",
        trace_id="trace-coin-contract",
        trigger_source="test",
    )

    assert result.status == ResultStatus.SUCCEEDED
    assert context.status == ResultStatus.BLOCKED
    assert context.reason_code == "coin_m_contract_size_missing"


def test_trade_preparation_context_loads_required_fact_objects(settings) -> None:
    result = run_trade_sync(settings, key="prep:context")

    context = load_trade_preparation_context(
        sync_run_id=result.data["binance_sync_run_id"],
        symbol="BTCUSDT",
        trace_id="trace-context",
        trigger_source="test",
    )

    assert context.status == ResultStatus.SUCCEEDED
    assert context.data["context"].position_snapshot.position_amount == Decimal("0.1")
    assert context.data["asset"] == "USDT"

"""BinanceAccountSync 模块：读取账户同步事实并校验交易可消费上下文；只读数据库；不访问 Redis；不访问外部服务；不发送 Hermes；不调用大模型；不涉及交易执行；不允许真实交易。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import InvalidOperation
from typing import Any

from django.utils import timezone

from apps.binance_gateway.types import MARKET_TYPE_COIN_M
from apps.foundation.results import ResultStatus, ServiceResult

from .models import (
    BinanceAccountSnapshot,
    BinanceBalanceSnapshot,
    BinancePositionMode,
    BinancePositionSnapshot,
    BinanceSymbolRuleSnapshot,
    BinanceSyncPurpose,
    BinanceSyncRun,
    BinanceSyncStatus,
)
from .services.hashing import stable_hash


@dataclass(frozen=True)
class BinanceAccountTradingContext:
    sync_run: BinanceSyncRun
    account_snapshot: BinanceAccountSnapshot
    balance_snapshot: BinanceBalanceSnapshot
    position_snapshot: BinancePositionSnapshot
    symbol_rule_snapshot: BinanceSymbolRuleSnapshot


def get_sync_run(sync_run_id: int) -> BinanceSyncRun:
    return BinanceSyncRun.objects.get(id=sync_run_id)


def get_account_snapshot(sync_run_id: int) -> BinanceAccountSnapshot:
    return BinanceAccountSnapshot.objects.get(sync_run_id=sync_run_id)


def get_balance_snapshots(sync_run_id: int) -> list[BinanceBalanceSnapshot]:
    return list(BinanceBalanceSnapshot.objects.filter(sync_run_id=sync_run_id).order_by("asset"))


def get_balance_snapshot_for_asset(sync_run_id: int, asset: str) -> BinanceBalanceSnapshot:
    return BinanceBalanceSnapshot.objects.get(sync_run_id=sync_run_id, asset=asset.upper())


def get_position_snapshot(sync_run_id: int, symbol: str, position_side: str = "BOTH") -> BinancePositionSnapshot:
    return BinancePositionSnapshot.objects.get(
        sync_run_id=sync_run_id,
        symbol=symbol.upper(),
        normalized_position_side=position_side.upper(),
    )


def get_symbol_rule_snapshot(sync_run_id: int, symbol: str) -> BinanceSymbolRuleSnapshot:
    return BinanceSymbolRuleSnapshot.objects.get(sync_run_id=sync_run_id, symbol=symbol.upper())


def load_trade_preparation_context(
    *,
    sync_run_id: int,
    symbol: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    """加载 OrderPlan/PerformanceMetrics 可消费的自动交易账户边界。"""

    try:
        sync_run = get_sync_run(sync_run_id)
    except BinanceSyncRun.DoesNotExist:
        return _blocked("binance_sync_run_missing", "账户同步批次不存在", trace_id, trigger_source)

    basic_error = _validate_sync_run(sync_run)
    if basic_error:
        return _blocked(basic_error[0], basic_error[1], trace_id, trigger_source, sync_run=sync_run)

    normalized_symbol = symbol.upper()
    try:
        account_snapshot = get_account_snapshot(sync_run.id)
        symbol_rule_snapshot = get_symbol_rule_snapshot(sync_run.id, normalized_symbol)
        position_snapshot = get_position_snapshot(sync_run.id, normalized_symbol)
    except BinanceAccountSnapshot.DoesNotExist:
        return _blocked("account_snapshot_missing", "账户快照不存在", trace_id, trigger_source, sync_run=sync_run)
    except BinanceSymbolRuleSnapshot.DoesNotExist:
        return _blocked("symbol_rule_snapshot_missing", "交易规则快照不存在", trace_id, trigger_source, sync_run=sync_run)
    except BinancePositionSnapshot.DoesNotExist:
        return _blocked("position_snapshot_missing", "持仓快照不存在", trace_id, trigger_source, sync_run=sync_run)

    rule_error = _validate_symbol_rule(sync_run, symbol_rule_snapshot)
    if rule_error:
        return _blocked(rule_error[0], rule_error[1], trace_id, trigger_source, sync_run=sync_run)

    try:
        balance_snapshot = get_balance_snapshot_for_asset(sync_run.id, _required_asset(symbol_rule_snapshot))
    except BinanceBalanceSnapshot.DoesNotExist:
        return _blocked("balance_snapshot_missing", "目标保证金/结算资产余额快照不存在", trace_id, trigger_source, sync_run=sync_run)

    context = BinanceAccountTradingContext(
        sync_run=sync_run,
        account_snapshot=account_snapshot,
        balance_snapshot=balance_snapshot,
        position_snapshot=position_snapshot,
        symbol_rule_snapshot=symbol_rule_snapshot,
    )
    return ServiceResult(
        ResultStatus.SUCCEEDED,
        "binance_account_context_loaded",
        "账户同步上下文可供交易链路消费",
        trace_id,
        trigger_source,
        {
            "context": context,
            "binance_sync_run_id": sync_run.id,
            "account_snapshot_id": account_snapshot.id,
            "balance_snapshot_id": balance_snapshot.id,
            "position_snapshot_id": position_snapshot.id,
            "symbol_rule_snapshot_id": symbol_rule_snapshot.id,
            "symbol": normalized_symbol,
            "asset": balance_snapshot.asset,
        },
    )


def verify_trade_preparation_snapshot_set(
    *,
    sync_run_id: int,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    """依据已落库脱敏源载荷重新计算账户子快照与集合指纹。"""

    try:
        sync_run = get_sync_run(sync_run_id)
        account = get_account_snapshot(sync_run_id)
        balances = get_balance_snapshots(sync_run_id)
        positions = list(BinancePositionSnapshot.objects.filter(sync_run_id=sync_run_id).order_by("id"))
        rules = list(BinanceSymbolRuleSnapshot.objects.filter(sync_run_id=sync_run_id).order_by("id"))
    except (BinanceSyncRun.DoesNotExist, BinanceAccountSnapshot.DoesNotExist):
        return _blocked("snapshot_set_incomplete", "账户快照集合不完整", trace_id, trigger_source)

    from .services.sync import (
        SyncRequest,
        normalize_account,
        normalize_balance,
        normalize_position,
        normalize_symbol_rule,
        snapshot_hash,
    )

    request = SyncRequest(
        business_request_key=sync_run.business_request_key,
        sync_purpose=sync_run.sync_purpose,
        market_type=sync_run.market_type,
        account_domain=sync_run.account_domain,
        symbols=tuple(str(item).upper() for item in sync_run.requested_symbols),
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    try:
        account_draft = normalize_account(request, account.raw_payload, sync_run.position_mode, account.as_of_utc)
        balance_drafts = [normalize_balance(request, item.raw_payload) for item in balances]
        position_drafts = [normalize_position(request, item.raw_payload, sync_run.position_mode) for item in positions]
        as_of_utc = sync_run.as_of_utc or account.as_of_utc
        rule_drafts = [
            normalize_symbol_rule(request, item.symbol, item.raw_payload, as_of_utc)
            for item in rules
        ]
        account_hash = snapshot_hash("account", account_draft)
        balance_hashes = [snapshot_hash("balance", item) for item in balance_drafts]
        position_hashes = [snapshot_hash("position", item) for item in position_drafts]
        rule_hashes = [snapshot_hash("rule", item) for item in rule_drafts]
    except (TypeError, ValueError, InvalidOperation):
        return _blocked("snapshot_hash_rebuild_failed", "账户快照指纹无法重建", trace_id, trigger_source, sync_run=sync_run)

    if not _snapshot_matches_draft(account, account_draft) or account.snapshot_hash != account_hash:
        return _blocked("account_snapshot_hash_mismatch", "账户快照指纹不一致", trace_id, trigger_source, sync_run=sync_run)
    if (
        not _snapshot_collection_matches(balances, balance_drafts)
        or [item.snapshot_hash for item in balances] != balance_hashes
    ):
        return _blocked("balance_snapshot_hash_mismatch", "余额快照指纹不一致", trace_id, trigger_source, sync_run=sync_run)
    if (
        not _snapshot_collection_matches(positions, position_drafts)
        or [item.snapshot_hash for item in positions] != position_hashes
    ):
        return _blocked("position_snapshot_hash_mismatch", "持仓快照指纹不一致", trace_id, trigger_source, sync_run=sync_run)
    if (
        not _snapshot_collection_matches(rules, rule_drafts)
        or [item.snapshot_hash for item in rules] != rule_hashes
    ):
        return _blocked("symbol_rule_snapshot_hash_mismatch", "交易规则快照指纹不一致", trace_id, trigger_source, sync_run=sync_run)

    expected_set_hash = stable_hash(
        {
            "sync_purpose": sync_run.sync_purpose,
            "business_request_key": sync_run.business_request_key,
            "market_type": sync_run.market_type,
            "account_domain": sync_run.account_domain,
            "position_mode": sync_run.position_mode,
            "account": account_hash,
            "balances": sorted(balance_hashes),
            "positions": sorted(position_hashes),
            "rules": sorted(rule_hashes),
        }
    )
    if sync_run.snapshot_set_hash != expected_set_hash:
        return _blocked("snapshot_set_hash_mismatch", "账户快照集合指纹不一致", trace_id, trigger_source, sync_run=sync_run)
    return ServiceResult(
        ResultStatus.SUCCEEDED,
        "snapshot_set_hash_verified",
        "账户快照集合指纹已验证",
        trace_id,
        trigger_source,
        {"binance_sync_run_id": sync_run.id, "snapshot_set_hash": sync_run.snapshot_set_hash},
    )


def _snapshot_collection_matches(models: list[Any], drafts: list[dict[str, Any]]) -> bool:
    return len(models) == len(drafts) and all(
        _snapshot_matches_draft(model, draft)
        for model, draft in zip(models, drafts, strict=True)
    )


def _snapshot_matches_draft(model: Any, draft: dict[str, Any]) -> bool:
    for field_name, expected in draft.items():
        if field_name in {"raw_payload", "snapshot_hash"}:
            continue
        if getattr(model, field_name) != expected:
            return False
    return True


def _validate_sync_run(sync_run: BinanceSyncRun) -> tuple[str, str] | None:
    if sync_run.status != BinanceSyncStatus.SUCCEEDED:
        return "binance_sync_run_not_succeeded", "账户同步批次未成功"
    if sync_run.sync_purpose != BinanceSyncPurpose.TRADE_PREPARATION:
        return "binance_sync_run_not_trade_preparation", "后台展示快照不能供交易链路消费"
    if sync_run.position_mode != BinancePositionMode.ONE_WAY:
        return "position_mode_not_supported", "当前阶段只允许单向持仓模式进入交易链路"
    if not sync_run.snapshot_set_hash:
        return "snapshot_set_hash_missing", "账户快照集合缺少指纹"
    if sync_run.expires_at_utc and sync_run.expires_at_utc <= timezone.now():
        return "binance_sync_run_expired", "账户同步批次已过期"
    return None


def _validate_symbol_rule(sync_run: BinanceSyncRun, rule: BinanceSymbolRuleSnapshot) -> tuple[str, str] | None:
    if sync_run.market_type == MARKET_TYPE_COIN_M and (rule.contract_size is None or rule.contract_size <= 0):
        return "coin_m_contract_size_missing", "币本位交易上下文缺少有效合约面值"
    if not _required_asset(rule):
        return "required_asset_missing", "交易规则快照缺少保证金/结算资产"
    return None


def _required_asset(rule: BinanceSymbolRuleSnapshot) -> str:
    return str(rule.margin_asset or rule.settlement_asset or "").upper()


def _blocked(
    reason_code: str,
    message: str,
    trace_id: str,
    trigger_source: str,
    *,
    sync_run: BinanceSyncRun | None = None,
) -> ServiceResult:
    data: dict[str, Any] = {"binance_sync_run_id": sync_run.id if sync_run else None}
    if sync_run:
        data.update(
            {
                "sync_purpose": sync_run.sync_purpose,
                "status": sync_run.status,
                "market_type": sync_run.market_type,
                "account_domain": sync_run.account_domain,
            }
        )
    return ServiceResult(ResultStatus.BLOCKED, reason_code, message, trace_id, trigger_source, data)

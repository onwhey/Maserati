"use client";

import { useActionState, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Trash2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useFormStatus } from "react-dom";

import { EmptyState } from "@/components/ops/empty-state";
import { StatusBadge } from "@/components/ops/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

import { bulkUpdateStrategyWorkspaceItemsAction, deleteStrategyRoutePolicyAction } from "./actions";
import {
  WorkspaceComponentActionForm,
  WorkspaceRoutePolicyRadioForm,
  WorkspaceSingleChoiceComponentRadioForm
} from "./forms";
import { initialStrategyReleaseActionState } from "../strategy-releases/state";

type ComponentGroup = {
  componentType: string;
  componentCode: string;
  componentObjectId: string;
  renderKey: string;
  displayName: string;
  selected?: Record<string, unknown>;
  items: Record<string, unknown>[];
};

type AdoptionFilter = "all" | "adopted" | "not_adopted";
type BulkMode = "select" | "cancel" | "invert";
type BulkOperation = {
  action: "upsert" | "remove";
  component_type?: string;
  component_object_id?: number;
  item_id?: number;
  is_included?: boolean;
  reason: string;
};

function displayText(value: unknown, fallback = "-") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function versionText(component: Record<string, unknown>) {
  return displayText(component.version || component.algorithm_version, "无版本");
}

function humanizeStrategyText(value: unknown) {
  return displayText(value, "暂无说明")
    .replaceAll("bullish", "看多")
    .replaceAll("bearish", "看空")
    .replaceAll("neutral", "中性 / 不交易")
    .replaceAll("no_trade_strategy", "不交易策略")
    .replaceAll("StrategyDefinition", "策略定义");
}

function strategyCoreIdea(component: Record<string, unknown>) {
  const code = String(component.component_code ?? "");
  if (code === "long_trend_following") {
    return "处理上涨趋势延续或有效向上突破；确认多头优势后输出看多判断，本层不直接下单。";
  }
  if (code === "long_pullback_support") {
    return "处理大背景偏多中的回调或支撑侧机会；趋势未破坏且靠近支撑时倾向看多。";
  }
  if (code === "short_trend_following") {
    return "处理下跌趋势延续或有效向下跌破；确认空头优势后输出看空判断，本层不直接下单。";
  }
  if (code === "short_rebound_pressure") {
    return "处理大背景偏空中的反弹或压力侧机会；反弹未修复趋势且靠近压力时倾向看空。";
  }
  if (code.includes("top_reversal_unconfirmed_no_trade")) {
    return "处理多头高位结构受压但尚未确认反转的行情；不提前做空，也不继续追多，明确不交易。";
  }
  if (code.includes("bottom_reversal_unconfirmed_no_trade")) {
    return "处理空头低位结构受压但尚未确认反转的行情；不提前做多，也不继续追空，明确不交易。";
  }
  if (code.includes("neutral_range_no_trade")) {
    return "处理无方向震荡区间；没有明确趋势优势时不交易。";
  }
  if (code.includes("high_risk_environment_no_trade")) {
    return "处理高风险或信号失真环境；先保护资金，不主动交易。";
  }
  if (code.includes("unclear_environment_no_trade")) {
    return "处理市场环境不明确的阶段；事实不足以支持方向选择时不交易。";
  }
  return humanizeStrategyText(component.description);
}

function componentGroupKey(component: Record<string, unknown>) {
  return `${String(component.component_type)}:${String(component.component_code)}`;
}

function groupComponentsByCode(components: Record<string, unknown>[], layerSlug?: string) {
  if (layerSlug === "strategy-routing") {
    return components.map((component) => ({
      componentType: String(component.component_type ?? ""),
      componentCode: String(component.component_code ?? ""),
      componentObjectId: String(component.component_object_id ?? ""),
      renderKey: `${String(component.component_type ?? "")}:${String(component.component_object_id ?? "")}`,
      displayName: String(component.display_name ?? ""),
      selected: Boolean(component.workspace_is_selected_version) ? component : undefined,
      items: [component]
    }));
  }
  const grouped = new Map<string, Record<string, unknown>[]>();
  for (const component of components) {
    const key = componentGroupKey(component);
    grouped.set(key, [...(grouped.get(key) ?? []), component]);
  }
  return [...grouped.values()].map((items) => ({
    componentType: String(items[0]?.component_type ?? ""),
    componentCode: String(items[0]?.component_code ?? ""),
    componentObjectId: String(items[0]?.component_object_id ?? ""),
    renderKey: componentGroupKey(items[0] ?? {}),
    displayName: String(items.find((item) => item.display_name)?.display_name ?? ""),
    selected: items.find((item) => Boolean(item.workspace_is_selected_version)),
    items
  }));
}

function groupSearchText(group: ComponentGroup) {
  return [
    group.componentType,
    group.componentCode,
    group.componentObjectId,
    group.displayName,
    ...group.items.flatMap((item) => [
      item.version,
      item.description,
      item.algorithm_name,
      item.algorithm_version,
      item.status
    ])
  ]
    .map((item) => String(item ?? "").toLowerCase())
    .join(" ");
}

function filterGroups(groups: ComponentGroup[], query: string, adoptionFilter: AdoptionFilter) {
  const normalizedQuery = query.trim().toLowerCase();
  return groups.filter((group) => {
    const isAdopted = isGroupAdopted(group);
    if (adoptionFilter === "adopted" && !isAdopted) {
      return false;
    }
    if (adoptionFilter === "not_adopted" && isAdopted) {
      return false;
    }
    if (!normalizedQuery) {
      return true;
    }
    return groupSearchText(group).includes(normalizedQuery);
  });
}

function isGroupAdopted(group: ComponentGroup) {
  if (!group.selected) {
    return false;
  }
  if (group.componentType === "feature_definition" || group.componentType === "strategy_definition") {
    return true;
  }
  return Boolean(group.selected.workspace_is_included);
}

function latestAvailableVersion(group: ComponentGroup) {
  return [...group.items].sort((left, right) => {
    const leftId = Number(left.component_object_id ?? 0);
    const rightId = Number(right.component_object_id ?? 0);
    return leftId - rightId;
  })[group.items.length - 1];
}

function selectOperationForGroup(group: ComponentGroup): BulkOperation | null {
  const target = group.selected ?? latestAvailableVersion(group);
  if (!target) {
    return null;
  }
  return {
    action: "upsert",
    component_type: String(target.component_type ?? ""),
    component_object_id: Number(target.component_object_id ?? 0),
    is_included: group.componentType !== "feature_definition" && group.componentType !== "strategy_definition",
    reason: `批量采用 ${group.componentType}/${group.componentCode}`
  };
}

function cancelOperationForGroup(group: ComponentGroup): BulkOperation | null {
  if (!group.selected) {
    return null;
  }
  if (group.componentType === "feature_definition" || group.componentType === "strategy_definition") {
    return {
      action: "remove",
      item_id: Number(group.selected.workspace_item_id ?? 0),
      reason: `批量取消采用 ${group.componentType}/${group.componentCode}`
    };
  }
  return {
    action: "upsert",
    component_type: String(group.selected.component_type ?? ""),
    component_object_id: Number(group.selected.component_object_id ?? 0),
    is_included: false,
    reason: `批量取消纳入 ${group.componentType}/${group.componentCode}`
  };
}

function bulkOperations(groups: ComponentGroup[], mode: BulkMode) {
  return groups.flatMap((group) => {
    if (mode === "select") {
      const operation = selectOperationForGroup(group);
      return operation ? [operation] : [];
    }
    if (mode === "cancel") {
      const operation = cancelOperationForGroup(group);
      return operation ? [operation] : [];
    }
    const operation = isGroupAdopted(group) ? cancelOperationForGroup(group) : selectOperationForGroup(group);
    return operation ? [operation] : [];
  });
}

function ActionResult({ state }: { state: typeof initialStrategyReleaseActionState }) {
  if (!state.reason_code) {
    return null;
  }
  return <div className={state.ok ? "text-xs text-emerald-600" : "text-xs text-destructive"}>{state.message}</div>;
}

function BulkOperationForm({
  action,
  disabled,
  layerSlug,
  mode,
  operations,
  children
}: {
  action: (payload: FormData) => void;
  disabled: boolean;
  layerSlug: string;
  mode: BulkMode;
  operations: BulkOperation[];
  children: ReactNode;
}) {
  return (
    <form action={action}>
      <input type="hidden" name="layer_path" value={layerSlug} />
      <input type="hidden" name="bulk_mode" value={mode} />
      <input type="hidden" name={`operations_${mode}`} value={JSON.stringify(operations)} />
      <Button type="submit" variant="outline" disabled={disabled}>
        {children}
      </Button>
    </form>
  );
}

function WorkspaceState({ component }: { component: Record<string, unknown> }) {
  const componentType = String(component.component_type ?? "");
  if (component.workspace_is_selected_version) {
    const selectedDescription =
      componentType === "strategy_definition"
        ? "是否进入版本包由路由规则绑定决定"
        : component.workspace_inclusion_managed
          ? component.workspace_is_included
            ? "已纳入当前组合"
            : "未纳入当前组合"
          : "Feature 由原子依赖反推";
    return (
      <div className="space-y-1">
        <StatusBadge value="已选择" />
        <div className="text-xs text-muted-foreground">{selectedDescription}</div>
      </div>
    );
  }
  if (component.workspace_selected_component_object_id) {
    return (
      <div className="text-xs text-muted-foreground">
        已选择其他版本：{displayText(component.workspace_selected_version)}
      </div>
    );
  }
  return <div className="text-xs text-muted-foreground">未选择</div>;
}

function GroupHeader({
  group,
  isFeature
}: {
  group: ComponentGroup;
  isFeature: boolean;
}) {
  const isStrategy = group.componentType === "strategy_definition";
  const selectedVersion = group.selected ? versionText(group.selected) : "";
  const selectedIncluded = Boolean(group.selected?.workspace_is_included);
  const selectedTitle = isFeature ? "当前采用" : isStrategy ? "当前路由使用" : "当前版本";
  const title = isStrategy ? displayText(group.displayName, group.componentCode) : displayText(group.componentCode);
  const subtitle = isStrategy ? displayText(group.componentCode) : displayText(group.displayName, "暂无展示名称");
  return (
    <summary className="cursor-pointer px-4 py-3 transition-colors hover:bg-muted/30">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px] lg:items-center">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-foreground">{title}</span>
            <span className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              {group.items.length} 个版本
            </span>
          </div>
          <div className="truncate text-sm text-muted-foreground">{subtitle}</div>
          {!isStrategy ? <div className="text-xs text-muted-foreground">类型：{displayText(group.componentType)}</div> : null}
        </div>
        <div className="rounded-lg bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          {group.selected ? (
            <>
              <div>
                {selectedTitle}：<span className="font-medium text-foreground">{selectedVersion}</span>
              </div>
              {!isFeature && !isStrategy ? (
                <div>{selectedIncluded ? "已纳入当前组合" : "未纳入当前组合"}</div>
              ) : null}
              {isStrategy ? <div>当前路由正在使用这个策略版本</div> : null}
            </>
          ) : (
            <div>{isStrategy ? "当前路由未使用" : "未选择版本"}</div>
          )}
        </div>
      </div>
    </summary>
  );
}

function RoutePolicyCard({
  group,
  layerSlug
}: {
  group: ComponentGroup;
  layerSlug: string;
}) {
  const component = group.items[0] ?? {};
  return (
    <div className="rounded-xl border bg-card px-4 py-3">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_260px] lg:items-center">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-foreground">{displayText(group.displayName, group.componentCode)}</span>
            <span className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              {versionText(component)}
            </span>
            <StatusBadge value={component.status} />
          </div>
          <div className="text-xs text-muted-foreground">{displayText(group.componentCode)}</div>
          <div className="text-sm text-muted-foreground">{displayText(component.description, "暂无说明")}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          <WorkspaceRoutePolicyRadioForm component={component} layerPath={layerSlug} />
          <DeleteRoutePolicyButton component={component} />
        </div>
      </div>
    </div>
  );
}

const STRATEGY_ROW_TONES = [
  "bg-sky-50/65 dark:bg-sky-950/20",
  "bg-emerald-50/65 dark:bg-emerald-950/20",
  "bg-amber-50/65 dark:bg-amber-950/20",
  "bg-violet-50/65 dark:bg-violet-950/20",
  "bg-rose-50/65 dark:bg-rose-950/20",
  "bg-cyan-50/65 dark:bg-cyan-950/20"
];

function strategyRowTone(index: number) {
  return STRATEGY_ROW_TONES[index % STRATEGY_ROW_TONES.length];
}

function versionSortValue(component: Record<string, unknown>) {
  const version = versionText(component);
  const versionNumber = version.match(/\d+/)?.[0];
  if (versionNumber) {
    return Number(versionNumber);
  }
  return Number(component.component_object_id ?? 0);
}

function sortedStrategyVersions(group: ComponentGroup) {
  return [...group.items].sort((left, right) => {
    const versionDiff = versionSortValue(left) - versionSortValue(right);
    if (versionDiff !== 0) {
      return versionDiff;
    }
    return Number(left.component_object_id ?? 0) - Number(right.component_object_id ?? 0);
  });
}

function StrategyCompactTable({ groups }: { groups: ComponentGroup[] }) {
  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1260px] border-collapse text-sm text-foreground/85">
          <thead className="bg-muted/70 text-xs text-muted-foreground">
            <tr className="border-b">
              <th className="w-[340px] px-3 py-2 text-left font-medium">策略名称</th>
              <th className="w-[260px] px-3 py-2 text-left font-medium">策略代码</th>
              <th className="w-[80px] px-3 py-2 text-left font-medium">版本</th>
              <th className="px-3 py-2 text-left font-medium">核心思路</th>
              <th className="w-[150px] px-3 py-2 text-left font-medium">算法</th>
              <th className="w-[110px] px-3 py-2 text-left font-medium">路由使用</th>
            </tr>
          </thead>
          {groups.map((group, groupIndex) => {
            const versions = sortedStrategyVersions(group);
            const tone = strategyRowTone(groupIndex);
            const title = displayText(group.displayName, group.componentCode);
            const code = displayText(group.componentCode);

            return (
              <tbody key={group.renderKey} className={`${tone} border-b last:border-b-0`}>
                {versions.map((component, rowIndex) => (
                  <tr
                    key={`${String(component.component_type)}:${String(component.component_object_id ?? rowIndex)}`}
                    className="border-b border-border/60 last:border-b-0"
                  >
                    {rowIndex === 0 ? (
                      <td rowSpan={versions.length} className="whitespace-nowrap px-3 py-2 align-middle text-foreground">
                        <div className="font-medium text-foreground">{title}</div>
                      </td>
                    ) : null}
                    {rowIndex === 0 ? (
                      <td rowSpan={versions.length} className="px-3 py-2 align-middle">
                        <div className="max-w-[240px] truncate font-mono text-xs text-foreground/65" title={code}>
                          {code}
                        </div>
                      </td>
                    ) : null}
                    <td className="px-3 py-2 align-top">
                      <span className="rounded-md bg-background/80 px-2 py-0.5 text-xs text-foreground/70">
                        {versionText(component)}
                      </span>
                    </td>
                    <td className="px-3 py-2 align-top text-foreground/75">
                      <div className="line-clamp-2">{strategyCoreIdea(component)}</div>
                    </td>
                    <td className="px-3 py-2 align-top text-xs text-foreground/65">
                      <div className="truncate">{displayText(component.algorithm_name)}</div>
                    </td>
                    <td className="px-3 py-2 align-top text-xs">
                      {component.workspace_is_selected_version ? (
                        <span className="rounded-md bg-emerald-100 px-2 py-1 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300">
                          使用中
                        </span>
                      ) : (
                        <span className="rounded-md bg-background/80 px-2 py-1 text-muted-foreground">未使用</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            );
          })}
        </table>
      </div>
    </div>
  );
}

function componentStatusText(component: Record<string, unknown>) {
  const componentType = String(component.component_type ?? "");
  const isSelectedVersion = Boolean(component.workspace_is_selected_version);
  const isIncluded = Boolean(component.workspace_is_included);
  if (componentType === "feature_definition") {
    return isSelectedVersion ? "已选择" : "未选择";
  }
  return isSelectedVersion && isIncluded ? "已纳入" : "未纳入";
}

function componentSelectionColumnTitle(layerSlug: string) {
  if (layerSlug === "features") {
    return "选择状态";
  }
  return "纳入状态";
}

function componentNameColumnTitle(layerSlug: string) {
  if (layerSlug === "features") {
    return "特征名称";
  }
  if (layerSlug === "atomic-signals") {
    return "原子信号名称";
  }
  if (layerSlug === "domain-signals") {
    return "领域信号名称";
  }
  return "组件名称";
}

function componentCodeColumnTitle(layerSlug: string) {
  if (layerSlug === "features") {
    return "特征代码";
  }
  if (layerSlug === "atomic-signals") {
    return "原子信号代码";
  }
  if (layerSlug === "domain-signals") {
    return "领域代码";
  }
  return "组件代码";
}

function sortedComponentVersions(group: ComponentGroup) {
  return [...group.items].sort((left, right) => {
    const versionDiff = versionSortValue(left) - versionSortValue(right);
    if (versionDiff !== 0) {
      return versionDiff;
    }
    return Number(left.component_object_id ?? 0) - Number(right.component_object_id ?? 0);
  });
}

function MultiChoiceCompactTable({
  groups,
  layerSlug
}: {
  groups: ComponentGroup[];
  layerSlug: string;
}) {
  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1260px] border-collapse text-sm text-foreground/85">
          <thead className="bg-muted/70 text-xs text-muted-foreground">
            <tr className="border-b">
              <th className="w-[280px] px-3 py-2 text-left font-medium">{componentNameColumnTitle(layerSlug)}</th>
              <th className="w-[280px] px-3 py-2 text-left font-medium">{componentCodeColumnTitle(layerSlug)}</th>
              <th className="w-[90px] px-3 py-2 text-left font-medium">版本</th>
              <th className="px-3 py-2 text-left font-medium">说明</th>
              <th className="w-[170px] px-3 py-2 text-left font-medium">算法</th>
              <th className="w-[110px] px-3 py-2 text-left font-medium">{componentSelectionColumnTitle(layerSlug)}</th>
              <th className="w-[170px] px-3 py-2 text-right font-medium">操作</th>
            </tr>
          </thead>
          {groups.map((group, groupIndex) => {
            const versions = sortedComponentVersions(group);
            const tone = strategyRowTone(groupIndex);
            const title = displayText(group.displayName, group.componentCode);
            const code = displayText(group.componentCode);

            return (
              <tbody key={group.renderKey} className={`${tone} border-b last:border-b-0`}>
                {versions.map((component, rowIndex) => {
                  const algorithm = [
                    displayText(component.algorithm_name),
                    displayText(component.algorithm_version)
                  ]
                    .filter((value) => value !== "-")
                    .join(" / ");
                  const isSelected = componentStatusText(component).startsWith("已");

                  return (
                    <tr
                      key={`${String(component.component_type)}:${String(component.component_object_id ?? rowIndex)}`}
                      className="border-b border-border/60 last:border-b-0 align-middle"
                    >
                      {rowIndex === 0 ? (
                        <td rowSpan={versions.length} className="px-3 py-2 align-middle">
                          <div className="font-medium text-foreground">{title}</div>
                        </td>
                      ) : null}
                      {rowIndex === 0 ? (
                        <td rowSpan={versions.length} className="px-3 py-2 align-middle">
                          <div className="max-w-[260px] truncate font-mono text-xs text-foreground/65" title={code}>
                            {code}
                          </div>
                        </td>
                      ) : null}
                      <td className="px-3 py-2 align-middle">
                        <span className="rounded-md bg-background/80 px-2 py-0.5 text-xs text-foreground/70">
                          {versionText(component)}
                        </span>
                      </td>
                      <td className="px-3 py-2 align-middle text-foreground/75">
                        <div className="line-clamp-2">{displayText(component.description, "暂无说明")}</div>
                      </td>
                      <td className="px-3 py-2 align-middle text-xs text-foreground/65">
                        <div className="truncate" title={algorithm || "-"}>
                          {algorithm || "-"}
                        </div>
                      </td>
                      <td className="px-3 py-2 align-middle text-xs">
                        {isSelected ? (
                          <span className="rounded-md bg-emerald-100 px-2 py-1 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300">
                            {componentStatusText(component)}
                          </span>
                        ) : (
                          <span className="rounded-md bg-background/80 px-2 py-1 text-muted-foreground">
                            {componentStatusText(component)}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 align-middle text-right">
                        <WorkspaceComponentActionForm component={component} layerPath={layerSlug} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            );
          })}
        </table>
      </div>
    </div>
  );
}

function MarketRegimeCompactTable({
  groups,
  layerSlug
}: {
  groups: ComponentGroup[];
  layerSlug: string;
}) {
  const rows = groups.flatMap((group) =>
    [...group.items]
      .sort((left, right) => versionSortValue(left) - versionSortValue(right))
      .map((component, index) => ({ group, component, index }))
  );
  const selectedRow = [...rows]
    .reverse()
    .find(({ component }) => Boolean(component.workspace_is_selected_version) && Boolean(component.workspace_is_included));
  const selectedObjectId = selectedRow ? String(selectedRow.component.component_object_id ?? "") : "";

  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1180px] border-collapse text-sm text-foreground/85">
          <thead className="bg-muted/70 text-xs text-muted-foreground">
            <tr className="border-b">
              <th className="w-[260px] px-3 py-2 text-left font-medium">市场环境定义</th>
              <th className="w-[260px] px-3 py-2 text-left font-medium">定义代码</th>
              <th className="w-[90px] px-3 py-2 text-left font-medium">版本</th>
              <th className="px-3 py-2 text-left font-medium">说明</th>
              <th className="w-[170px] px-3 py-2 text-left font-medium">算法</th>
              <th className="w-[170px] px-3 py-2 text-left font-medium">当前组合</th>
              <th className="w-[170px] px-3 py-2 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map(({ group, component, index }) => {
              const code = displayText(component.component_code, group.componentCode);
              const isCurrent = selectedObjectId === String(component.component_object_id ?? "");
              const algorithm = [
                displayText(component.algorithm_name),
                displayText(component.algorithm_version)
              ]
                .filter((value) => value !== "-")
                .join(" / ");

              return (
                <tr
                  key={`${String(component.component_type)}:${String(component.component_object_id ?? index)}`}
                  className="align-middle"
                >
                  <td className="px-3 py-2">
                    <div className="font-medium text-foreground">
                      {displayText(component.display_name, group.displayName || group.componentCode)}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <div className="max-w-[240px] truncate font-mono text-xs text-foreground/65" title={code}>
                      {code}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <span className="rounded-md bg-background/80 px-2 py-0.5 text-xs text-foreground/70">
                      {versionText(component)}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-foreground/75">
                    <div className="line-clamp-2">{displayText(component.description, "暂无说明")}</div>
                  </td>
                  <td className="px-3 py-2 text-xs text-foreground/65">
                    <div className="truncate" title={algorithm || "-"}>
                      {algorithm || "-"}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    {isCurrent ? (
                      <StatusBadge value="当前已使用" />
                    ) : (
                      <span className="text-xs text-muted-foreground">未使用</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <WorkspaceSingleChoiceComponentRadioForm
                      checked={isCurrent}
                      checkedLabel="当前已使用"
                      component={component}
                      layerPath={layerSlug}
                      uncheckedLabel="使用此算法"
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DeleteRoutePolicyButton({ component }: { component: Record<string, unknown> }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [state, action] = useActionState(deleteStrategyRoutePolicyAction, initialStrategyReleaseActionState);
  const routePolicyId = Number(component.component_object_id ?? 0);
  const title = displayText(component.display_name, displayText(component.component_code));

  useEffect(() => {
    if (state.ok && state.reason_code) {
      setOpen(false);
      router.refresh();
    }
  }, [router, state.ok, state.reason_code]);

  return (
    <>
      <button
        type="button"
        disabled={!routePolicyId}
        onClick={() => setOpen(true)}
        className="inline-flex h-9 items-center gap-1 whitespace-nowrap rounded-md px-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:text-muted-foreground disabled:hover:bg-transparent dark:text-red-400 dark:hover:bg-red-950/30"
      >
        <Trash2 className="h-4 w-4" />
        删除
      </button>
      {!state.ok && state.reason_code ? (
        <div className="basis-full text-xs text-destructive lg:text-right">{state.message}</div>
      ) : null}

      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4" role="presentation">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={`delete-route-policy-title-${routePolicyId}`}
            className="w-full max-w-md rounded-xl border bg-background p-5 shadow-xl"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id={`delete-route-policy-title-${routePolicyId}`} className="text-base font-semibold">
                  确认删除策略路由方案
                </h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  将删除“{title}”及其下面的路由规则。已被版本包、回测或正式路由结果引用的方案不会被删除。
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label="关闭"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form action={action} className="mt-5 flex justify-end gap-2">
              <input type="hidden" name="route_policy_id" value={routePolicyId} />
              <input type="hidden" name="reason" value="后台删除策略路由方案" />
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="inline-flex h-9 items-center rounded-md border border-input bg-background px-3 text-sm font-medium hover:bg-muted"
              >
                取消
              </button>
              <DeleteRoutePolicySubmitButton />
            </form>
          </div>
        </div>
      ) : null}
    </>
  );
}

function DeleteRoutePolicySubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="inline-flex h-9 items-center rounded-md bg-red-600 px-3 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {pending ? "删除中..." : "确认删除"}
    </button>
  );
}

function ComponentVersionRows({
  group,
  layerSlug
}: {
  group: ComponentGroup;
  layerSlug: string;
}) {
  if (layerSlug === "strategies") {
    return (
      <div className="divide-y border-t">
        {group.items.map((component, index) => (
          <div
            key={`${String(component.component_type)}:${String(component.component_object_id ?? index)}`}
            className="grid gap-3 bg-background px-4 py-3 lg:grid-cols-[130px_minmax(0,1fr)_220px] lg:items-center"
          >
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                {versionText(component)}
              </span>
              <StatusBadge value={component.status} />
            </div>
            <div className="min-w-0 space-y-1">
              <div className="text-sm text-muted-foreground">{strategyCoreIdea(component)}</div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span>算法：{displayText(component.algorithm_name)}</span>
                <span>算法版本：{displayText(component.algorithm_version)}</span>
              </div>
            </div>
            <div className="rounded-lg bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
              {component.workspace_is_selected_version ? "当前路由使用此版本" : "当前路由未使用"}
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="divide-y border-t">
      {group.items.map((component, index) => (
        <div
          key={`${String(component.component_type)}:${String(component.component_object_id ?? index)}`}
          className="grid gap-3 bg-background px-4 py-3 lg:grid-cols-[130px_minmax(0,1fr)_220px_180px] lg:items-center"
        >
          <div className="flex items-center gap-2">
            <span className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              {versionText(component)}
            </span>
            <StatusBadge value={component.status} />
          </div>
          <div className="min-w-0 space-y-1">
            <div className="truncate text-sm text-muted-foreground">{displayText(component.description, "暂无说明")}</div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>算法：{displayText(component.algorithm_name)}</span>
              <span>算法版本：{displayText(component.algorithm_version)}</span>
            </div>
          </div>
          <div className="rounded-lg bg-muted/40 px-3 py-2">
            <WorkspaceState component={component} />
          </div>
          <div className="lg:text-right">
            <WorkspaceComponentActionForm component={component} layerPath={layerSlug} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ComponentGroupList({
  components,
  layerSlug
}: {
  components: Record<string, unknown>[];
  layerSlug: string;
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [adoptionFilter, setAdoptionFilter] = useState<AdoptionFilter>("all");
  const [bulkState, bulkAction, bulkPending] = useActionState(
    bulkUpdateStrategyWorkspaceItemsAction,
    initialStrategyReleaseActionState
  );
  const isStrategyRouteLayer = layerSlug === "strategy-routing";
  const isStrategyLayer = layerSlug === "strategies";
  const isMarketRegimeLayer = layerSlug === "market-regime";
  const isMultiChoiceCompactLayer =
    layerSlug === "features" || layerSlug === "atomic-signals" || layerSlug === "domain-signals";
  const isReadOnlyLayer = isStrategyRouteLayer || isStrategyLayer || isMarketRegimeLayer;
  const groups = useMemo(() => groupComponentsByCode(components, layerSlug), [components, layerSlug]);
  const filteredGroups = useMemo(() => filterGroups(groups, query, adoptionFilter), [groups, query, adoptionFilter]);
  const selectOperations = useMemo(() => bulkOperations(filteredGroups, "select"), [filteredGroups]);
  const cancelOperations = useMemo(() => bulkOperations(filteredGroups, "cancel"), [filteredGroups]);
  const invertOperations = useMemo(() => bulkOperations(filteredGroups, "invert"), [filteredGroups]);
  const isFeatureLayer = layerSlug === "features";

  useEffect(() => {
    if (bulkState.ok && bulkState.reason_code && bulkState.reason_code !== "strategy_workspace_bulk_noop") {
      router.refresh();
    }
  }, [bulkState.ok, bulkState.reason_code, router]);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_180px_auto]">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px]">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索代码、名称、算法或版本"
          />
          <Select value={adoptionFilter} onChange={(event) => setAdoptionFilter(event.target.value as AdoptionFilter)}>
            <option value="all">全部</option>
            <option value="adopted">{isStrategyLayer ? "当前路由使用" : "已采用"}</option>
            <option value="not_adopted">{isStrategyLayer ? "当前路由未使用" : "未采用"}</option>
          </Select>
        </div>
        {!isReadOnlyLayer ? (
          <div className="flex flex-wrap items-center gap-2 xl:justify-end">
            <BulkOperationForm
              action={bulkAction}
              disabled={bulkPending}
              layerSlug={layerSlug}
              mode="select"
              operations={selectOperations}
            >
              全选当前结果
            </BulkOperationForm>
            <BulkOperationForm
              action={bulkAction}
              disabled={bulkPending}
              layerSlug={layerSlug}
              mode="cancel"
              operations={cancelOperations}
            >
              取消当前结果
            </BulkOperationForm>
            <BulkOperationForm
              action={bulkAction}
              disabled={bulkPending}
              layerSlug={layerSlug}
              mode="invert"
              operations={invertOperations}
            >
              反选当前结果
            </BulkOperationForm>
          </div>
        ) : null}
      </div>
      <ActionResult state={bulkState} />

      <div className="text-xs text-muted-foreground">
        {isStrategyRouteLayer
          ? `共计 ${groups.length} 个路由方案，当前显示 ${filteredGroups.length} 个。`
          : isStrategyLayer
            ? `共计 ${groups.length} 个策略，当前显示 ${filteredGroups.length} 个。`
          : `共计 ${groups.length} 个组件，当前显示 ${filteredGroups.length} 个。`}
      </div>

      {filteredGroups.length ? (
        isStrategyLayer ? (
          <StrategyCompactTable groups={filteredGroups} />
        ) : isMarketRegimeLayer ? (
          <MarketRegimeCompactTable groups={filteredGroups} layerSlug={layerSlug} />
        ) : isMultiChoiceCompactLayer ? (
          <MultiChoiceCompactTable groups={filteredGroups} layerSlug={layerSlug} />
        ) : (
          <div className="space-y-3">
            {filteredGroups.map((group) => (
              isStrategyRouteLayer ? (
                <RoutePolicyCard key={group.renderKey} group={group} layerSlug={layerSlug} />
              ) : (
                <details
                  key={group.renderKey}
                  className="overflow-hidden rounded-xl border bg-card"
                >
                  <GroupHeader group={group} isFeature={isFeatureLayer} />
                  <ComponentVersionRows group={group} layerSlug={layerSlug} />
                </details>
              )
            ))}
          </div>
        )
      ) : (
        <EmptyState title="没有匹配的组件" description="可以换一个关键词，或切换采用状态筛选。" />
      )}
    </div>
  );
}

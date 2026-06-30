"use client";

import { useActionState, useMemo, useState } from "react";

import { EmptyState } from "@/components/ops/empty-state";
import { StatusBadge } from "@/components/ops/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

import { bulkUpdateStrategyWorkspaceItemsAction } from "./actions";
import { WorkspaceComponentActionForm } from "./forms";
import { initialStrategyReleaseActionState } from "../strategy-releases/state";

type ComponentGroup = {
  componentType: string;
  componentCode: string;
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

function componentGroupKey(component: Record<string, unknown>) {
  return `${String(component.component_type)}:${String(component.component_code)}`;
}

function groupComponentsByCode(components: Record<string, unknown>[]) {
  const grouped = new Map<string, Record<string, unknown>[]>();
  for (const component of components) {
    const key = componentGroupKey(component);
    grouped.set(key, [...(grouped.get(key) ?? []), component]);
  }
  return [...grouped.values()].map((items) => ({
    componentType: String(items[0]?.component_type ?? ""),
    componentCode: String(items[0]?.component_code ?? ""),
    displayName: String(items.find((item) => item.display_name)?.display_name ?? ""),
    selected: items.find((item) => Boolean(item.workspace_is_selected_version)),
    items
  }));
}

function groupSearchText(group: ComponentGroup) {
  return [
    group.componentType,
    group.componentCode,
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
  if (group.componentType === "feature_definition") {
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
    is_included: group.componentType !== "feature_definition",
    reason: `批量采用 ${group.componentType}/${group.componentCode}`
  };
}

function cancelOperationForGroup(group: ComponentGroup): BulkOperation | null {
  if (!group.selected) {
    return null;
  }
  if (group.componentType === "feature_definition") {
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

function WorkspaceState({ component }: { component: Record<string, unknown> }) {
  if (component.workspace_is_selected_version) {
    return (
      <div className="space-y-1">
        <StatusBadge value="已选择" />
        <div className="text-xs text-muted-foreground">
          {component.workspace_inclusion_managed
            ? component.workspace_is_included
              ? "已纳入当前组合"
              : "未纳入当前组合"
            : "Feature 由原子依赖反推"}
        </div>
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
  const selectedVersion = group.selected ? versionText(group.selected) : "";
  const selectedIncluded = Boolean(group.selected?.workspace_is_included);
  return (
    <summary className="cursor-pointer px-4 py-3 transition-colors hover:bg-muted/30">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px] lg:items-center">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-foreground">{displayText(group.componentCode)}</span>
            <span className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              {group.items.length} 个版本
            </span>
          </div>
          <div className="truncate text-sm text-muted-foreground">{displayText(group.displayName, "暂无展示名称")}</div>
          <div className="text-xs text-muted-foreground">类型：{displayText(group.componentType)}</div>
        </div>
        <div className="rounded-lg bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          {group.selected ? (
            <>
              <div>
                {isFeature ? "当前采用" : "当前版本"}：<span className="font-medium text-foreground">{selectedVersion}</span>
              </div>
              {!isFeature ? <div>{selectedIncluded ? "已纳入当前组合" : "未纳入当前组合"}</div> : null}
            </>
          ) : (
            <div>未选择版本</div>
          )}
        </div>
      </div>
    </summary>
  );
}

export function ComponentGroupList({
  components,
  layerSlug
}: {
  components: Record<string, unknown>[];
  layerSlug: string;
}) {
  const [query, setQuery] = useState("");
  const [adoptionFilter, setAdoptionFilter] = useState<AdoptionFilter>("all");
  const [bulkState, bulkAction, bulkPending] = useActionState(
    bulkUpdateStrategyWorkspaceItemsAction,
    initialStrategyReleaseActionState
  );
  const groups = useMemo(() => groupComponentsByCode(components), [components]);
  const filteredGroups = useMemo(() => filterGroups(groups, query, adoptionFilter), [groups, query, adoptionFilter]);
  const selectOperations = useMemo(() => bulkOperations(filteredGroups, "select"), [filteredGroups]);
  const cancelOperations = useMemo(() => bulkOperations(filteredGroups, "cancel"), [filteredGroups]);
  const invertOperations = useMemo(() => bulkOperations(filteredGroups, "invert"), [filteredGroups]);
  const isFeatureLayer = layerSlug === "features";

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
            <option value="adopted">已采用</option>
            <option value="not_adopted">未采用</option>
          </Select>
        </div>
        <form action={bulkAction} className="flex flex-wrap items-center gap-2 xl:justify-end">
          <input type="hidden" name="layer_path" value={layerSlug} />
          <input type="hidden" name="operations_select" value={JSON.stringify(selectOperations)} />
          <input type="hidden" name="operations_cancel" value={JSON.stringify(cancelOperations)} />
          <input type="hidden" name="operations_invert" value={JSON.stringify(invertOperations)} />
          <Button type="submit" name="bulk_mode" value="select" variant="outline" disabled={bulkPending}>
            全选当前结果
          </Button>
          <Button type="submit" name="bulk_mode" value="cancel" variant="outline" disabled={bulkPending}>
            取消当前结果
          </Button>
          <Button type="submit" name="bulk_mode" value="invert" variant="outline" disabled={bulkPending}>
            反选当前结果
          </Button>
        </form>
      </div>
      <ActionResult state={bulkState} />

      <div className="text-xs text-muted-foreground">
        共 {groups.length} 个组件，当前显示 {filteredGroups.length} 个。
      </div>

      {filteredGroups.length ? (
        <div className="space-y-3">
          {filteredGroups.map((group) => (
            <details
              key={`${group.componentType}:${group.componentCode}`}
              className="overflow-hidden rounded-xl border bg-card"
              open={Boolean(group.selected) || group.items.length <= 2}
            >
              <GroupHeader group={group} isFeature={isFeatureLayer} />
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
            </details>
          ))}
        </div>
      ) : (
        <EmptyState title="没有匹配的组件" description="可以换一个关键词，或切换采用状态筛选。" />
      )}
    </div>
  );
}

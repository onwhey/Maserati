import Link from "next/link";

import { ApiError } from "@/components/ops/api-error";
import { PageHeader } from "@/components/ops/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import type { Paginated } from "@/lib/api/types";
import { asRows } from "@/lib/ops-data";

import { GenerateReleaseFromWorkspaceForm } from "./forms";
import { strategyComponentLayers } from "./layers";

type LayerSummary = {
  totalCount: number;
  selectedCount: number;
};

export const dynamic = "force-dynamic";

function componentGroupKey(component: Record<string, unknown>) {
  if (String(component.component_type ?? "") === "strategy_route_policy") {
    return `${String(component.component_type)}:${String(component.component_object_id ?? "")}`;
  }
  return `${String(component.component_type)}:${String(component.component_code)}`;
}

function summarizeLayerComponents(components: Record<string, unknown>[]): LayerSummary {
  const groups = new Map<string, Record<string, unknown>[]>();
  for (const component of components) {
    const key = componentGroupKey(component);
    groups.set(key, [...(groups.get(key) ?? []), component]);
  }
  return {
    totalCount: groups.size,
    selectedCount: [...groups.values()].filter((items) => {
      const selected = items.find((item) => Boolean(item.workspace_is_selected_version));
      if (!selected) {
        return false;
      }
      const componentType = String(selected.component_type ?? "");
      if (componentType === "feature_definition" || componentType === "strategy_definition") {
        return true;
      }
      return Boolean(selected.workspace_is_included);
    }).length
  };
}

async function fetchLayerSummary(componentTypes: string[]) {
  const results = await Promise.all(
    componentTypes.map((componentType) =>
      opsFetch<Paginated<Record<string, unknown>>>(
        `/api/ops/strategy-workspace/components/?component_type=${encodeURIComponent(componentType)}`
      )
    )
  );
  const failed = results.find((result) => !result.ok);
  if (failed) {
    return { ok: false as const, failed, summary: { totalCount: 0, selectedCount: 0 } };
  }
  return {
    ok: true as const,
    failed: null,
    summary: summarizeLayerComponents(results.flatMap((result) => asRows(result.data?.items)))
  };
}

export default async function StrategyComponentsPage() {
  const layerSummaryResults = await Promise.all(
    strategyComponentLayers.map(async (layer) => ({
      layer,
      result: await fetchLayerSummary(layer.componentTypes)
    }))
  );
  const failedSummary = layerSummaryResults.find((item) => !item.result.ok);
  if (failedSummary && !failedSummary.result.ok) {
    return <ApiError reason={failedSummary.result.failed.reason_code} message={failedSummary.result.failed.message_zh} />;
  }

  return (
    <>
      <PageHeader
        title="策略组件"
        description="这里是策略分析组件管理入口；每个层级独立管理，不把特征、原子、领域和策略堆在一个页面。"
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {layerSummaryResults.map(({ layer, result }) => {
          const { totalCount, selectedCount } = result.summary;
          return (
            <Link key={layer.slug} href={`/strategy-components/${layer.slug}`} className="block">
              <Card className="h-full transition-colors hover:bg-muted/40">
                <CardHeader>
                  <CardTitle>{layer.title}</CardTitle>
                  <CardDescription>{layer.description}</CardDescription>
                </CardHeader>
                <CardContent className="text-sm text-muted-foreground">
                  <div>共计：{totalCount}</div>
                  <div>选择：{selectedCount}</div>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>

      <div className="mt-6 max-w-xl">
        <GenerateReleaseFromWorkspaceForm />
      </div>

      <div className="mt-6 text-sm text-muted-foreground">
        配置完成后，从本页生成草稿，再到{" "}
        <Link className="underline" href="/strategy-releases">
          策略发布
        </Link>{" "}
        页面完成预校验、冻结、验证证据、批准和启用。
      </div>
    </>
  );
}

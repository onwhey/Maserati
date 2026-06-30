import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiError } from "@/components/ops/api-error";
import { EmptyState } from "@/components/ops/empty-state";
import { PageHeader } from "@/components/ops/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import type { Paginated } from "@/lib/api/types";
import { asRows } from "@/lib/ops-data";

import { ComponentGroupList } from "../component-group-list";
import { getStrategyComponentLayer, strategyComponentLayers } from "../layers";

type PageProps = {
  params: Promise<{ layer: string }>;
};

async function fetchLayerComponents(componentTypes: string[]) {
  const results = await Promise.all(
    componentTypes.map((componentType) =>
      opsFetch<Paginated<Record<string, unknown>>>(
        `/api/ops/strategy-workspace/components/?component_type=${encodeURIComponent(componentType)}`
      )
    )
  );
  const failed = results.find((result) => !result.ok);
  if (failed) {
    return { ok: false as const, failed, rows: [] as Record<string, unknown>[] };
  }
  return {
    ok: true as const,
    failed: null,
    rows: results.flatMap((result) => asRows(result.data?.items))
  };
}

export function generateStaticParams() {
  return strategyComponentLayers.map((layer) => ({ layer: layer.slug }));
}

export default async function StrategyComponentLayerPage({ params }: PageProps) {
  const { layer: layerSlug } = await params;
  const layer = getStrategyComponentLayer(layerSlug);
  if (!layer) {
    notFound();
  }

  const componentsResult = await fetchLayerComponents(layer.componentTypes);
  if (!componentsResult.ok) {
    return <ApiError reason={componentsResult.failed.reason_code} message={componentsResult.failed.message_zh} />;
  }
  const components = componentsResult.rows;

  return (
    <>
      <div className="mb-4 flex items-center gap-3 text-sm text-muted-foreground">
        <Link className="underline" href="/strategy-components">
          返回策略组件
        </Link>
        <span>/</span>
        <span>{layer.title}</span>
      </div>

      <PageHeader title={layer.title} description={layer.description} />

      <Card>
        <CardHeader>
          <CardTitle>{layer.title}管理</CardTitle>
          <CardDescription>
            {layer.slug === "features"
              ? "本页只选择特征版本；是否进入发布包由已纳入原子信号的依赖自动决定。"
              : "本页选择组件版本，并决定是否纳入当前策略组合。"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {components.length ? (
            <ComponentGroupList components={components} layerSlug={layer.slug} />
          ) : (
            <EmptyState title={`暂无${layer.title}组件`} description="需要先通过 seed 或后台登记对应定义。" />
          )}
        </CardContent>
      </Card>
    </>
  );
}

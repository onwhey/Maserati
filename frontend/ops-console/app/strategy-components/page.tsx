import Link from "next/link";

import { ApiError } from "@/components/ops/api-error";
import { PageHeader } from "@/components/ops/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { opsFetch } from "@/lib/api/client";
import { asRows } from "@/lib/ops-data";

import { GenerateReleaseFromWorkspaceForm } from "./forms";
import { strategyComponentLayers } from "./layers";

function selectedCountForLayer(items: Record<string, unknown>[], componentTypes: string[]) {
  return items.filter((item) => componentTypes.includes(String(item.component_type ?? ""))).length;
}

function includedCountForLayer(items: Record<string, unknown>[], componentTypes: string[]) {
  return items.filter(
    (item) => componentTypes.includes(String(item.component_type ?? "")) && Boolean(item.is_included)
  ).length;
}

export default async function StrategyComponentsPage() {
  const workspaceResult = await opsFetch<Record<string, unknown>>("/api/ops/strategy-workspace/");

  if (!workspaceResult.ok) {
    return <ApiError reason={workspaceResult.reason_code} message={workspaceResult.message_zh} />;
  }

  const workspaceItems = asRows(workspaceResult.data.items);

  return (
    <>
      <PageHeader
        title="策略组件"
        description="这里是策略分析组件管理入口；每个层级独立管理，不把特征、原子、领域和策略堆在一个页面。"
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {strategyComponentLayers.map((layer) => {
          const selectedCount = selectedCountForLayer(workspaceItems, layer.componentTypes);
          const includedCount = includedCountForLayer(workspaceItems, layer.componentTypes);
          return (
            <Link key={layer.slug} href={`/strategy-components/${layer.slug}`} className="block">
              <Card className="h-full transition-colors hover:bg-muted/40">
                <CardHeader>
                  <CardTitle>{layer.title}</CardTitle>
                  <CardDescription>{layer.description}</CardDescription>
                </CardHeader>
                <CardContent className="text-sm text-muted-foreground">
                  <div>已选择：{selectedCount}</div>
                  <div>已纳入：{includedCount}</div>
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

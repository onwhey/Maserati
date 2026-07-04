"use client";

import { useActionState, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

import { createStrategyRoutePolicyVariantAction } from "./actions";
import { initialStrategyReleaseActionState } from "../strategy-releases/state";

export type StrategyOption = {
  id: number;
  strategy_code: string;
  strategy_version: string;
  display_name: string;
  description: string;
};

type RouteRuleOption = {
  id: number;
  rule_code: string;
  display_name: string;
  description: string;
  priority: number;
  match_conditions: Record<string, unknown>;
  selected_strategy_definition_id: number | null;
  selected_strategy_code: string;
  selected_strategy_version: string;
  selected_strategy_display_name: string;
};

export type RoutePolicyOption = {
  id: number;
  policy_code: string;
  policy_version: string;
  display_name: string;
  description: string;
  rules: RouteRuleOption[];
};

function text(value: unknown, fallback = "-") {
  const cleaned = String(value ?? "").trim();
  return cleaned || fallback;
}

function strategyLabel(strategy: StrategyOption) {
  const name = text(strategy.display_name, strategy.strategy_code);
  return `${name} / ${strategy.strategy_version}`;
}

function selectedStrategyText(rule: RouteRuleOption) {
  if (!rule.selected_strategy_definition_id) {
    return "未绑定策略";
  }
  return `${text(rule.selected_strategy_display_name, rule.selected_strategy_code)} / ${rule.selected_strategy_version}`;
}

function ActionResult({ state }: { state: typeof initialStrategyReleaseActionState }) {
  if (!state.reason_code) {
    return null;
  }
  return <div className={state.ok ? "text-sm text-emerald-600" : "text-sm text-destructive"}>{state.message}</div>;
}

function bindingsFromPolicy(policy: RoutePolicyOption | undefined) {
  return Object.fromEntries(
    (policy?.rules ?? []).map((rule) => [String(rule.id), Number(rule.selected_strategy_definition_id ?? 0)])
  );
}

export function StrategyRoutingBuilder({
  policies,
  strategies
}: {
  policies: RoutePolicyOption[];
  strategies: StrategyOption[];
}) {
  const [state, formAction, pending] = useActionState(
    createStrategyRoutePolicyVariantAction,
    initialStrategyReleaseActionState
  );
  const [sourcePolicyId, setSourcePolicyId] = useState<number>(policies[0]?.id ?? 0);
  const selectedPolicy = useMemo(
    () => policies.find((policy) => policy.id === sourcePolicyId) ?? policies[0],
    [policies, sourcePolicyId]
  );
  const [bindings, setBindings] = useState<Record<string, number>>(() => bindingsFromPolicy(selectedPolicy));

  function changeSourcePolicy(policyId: number) {
    const policy = policies.find((item) => item.id === policyId) ?? policies[0];
    setSourcePolicyId(policy?.id ?? 0);
    setBindings(bindingsFromPolicy(policy));
  }

  function setRuleStrategy(ruleId: number, strategyId: number) {
    setBindings((current) => ({ ...current, [String(ruleId)]: strategyId }));
  }

  if (!policies.length) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>策略路由方案</CardTitle>
          <CardDescription>暂无可复制的路由方案，需要先完成路由定义登记。</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>创建新的策略路由方案</CardTitle>
        <CardDescription>
          从已有方案复制一份，然后重新指定“每种市场环境交给哪个策略插件”。不会修改旧方案。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form action={formAction} className="space-y-5">
          <input type="hidden" name="confirm_write" value="on" />
          <input type="hidden" name="source_policy_id" value={selectedPolicy?.id ?? 0} />
          <input type="hidden" name="rule_strategy_bindings" value={JSON.stringify(bindings)} />

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="source_policy">源路由方案</Label>
              <Select
                id="source_policy"
                className="block w-full"
                value={String(selectedPolicy?.id ?? "")}
                onChange={(event) => changeSourcePolicy(Number(event.currentTarget.value))}
              >
                {policies.map((policy) => (
                  <option key={policy.id} value={policy.id}>
                    {text(policy.display_name, policy.policy_code)} / {policy.policy_version}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="display_name">新方案名称</Label>
              <Input id="display_name" name="display_name" placeholder="例如：【保守趋势】路由方案 v1" />
            </div>
            <div className="space-y-2 lg:col-span-2">
              <Label htmlFor="description">说明</Label>
              <Input id="description" name="description" placeholder="说明这套方案的交易性格和适用范围" />
            </div>
          </div>

          <div className="space-y-3">
            <div>
              <h3 className="font-medium">规则接线</h3>
              <p className="text-sm text-muted-foreground">
                左边是市场环境分支，右边选择这个分支要交给哪个策略处理。
              </p>
            </div>
            <div className="overflow-hidden rounded-xl border">
              {(selectedPolicy?.rules ?? []).map((rule) => (
                <div
                  key={rule.id}
                  className="grid gap-3 border-b px-4 py-3 last:border-b-0 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-center"
                >
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                        优先级 {rule.priority}
                      </span>
                      <span className="font-medium">{text(rule.display_name, rule.rule_code)}</span>
                    </div>
                    <div className="text-xs text-muted-foreground">{rule.rule_code}</div>
                    <div className="text-sm text-muted-foreground">{text(rule.description, "暂无说明")}</div>
                    <div className="text-xs text-muted-foreground">当前绑定：{selectedStrategyText(rule)}</div>
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor={`rule_${rule.id}`} className="text-xs">
                      绑定策略
                    </Label>
                    <Select
                      id={`rule_${rule.id}`}
                      className="block w-full"
                      value={String(bindings[String(rule.id)] ?? 0)}
                      onChange={(event) => setRuleStrategy(rule.id, Number(event.currentTarget.value))}
                    >
                      <option value="0">请选择策略</option>
                      {strategies.map((strategy) => (
                        <option key={strategy.id} value={strategy.id}>
                          {strategyLabel(strategy)}
                        </option>
                      ))}
                    </Select>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Button type="submit" disabled={pending}>
              {pending ? "创建中..." : "创建新路由方案"}
            </Button>
            <ActionResult state={state} />
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

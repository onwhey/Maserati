"use client";

import { useState } from "react";
import { Trash2, X } from "lucide-react";
import { useFormStatus } from "react-dom";

import { deleteStrategyBacktestRunAction } from "./actions";

type DeleteStrategyBacktestRunButtonProps = {
  runId: string;
  disabled: boolean;
};

export function DeleteStrategyBacktestRunButton({ runId, disabled }: DeleteStrategyBacktestRunButtonProps) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-1 text-sm font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:text-muted-foreground disabled:hover:bg-transparent dark:text-red-400 dark:hover:bg-red-950/30"
      >
        <Trash2 className="h-4 w-4" />
        删除
      </button>

      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4" role="presentation">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={`delete-backtest-title-${runId}`}
            className="w-full max-w-md rounded-xl border bg-background p-5 shadow-xl"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id={`delete-backtest-title-${runId}`} className="text-base font-semibold">
                  确认删除回测 #{runId}
                </h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  删除后会清理这次回测生成的周期结果、分析明细，以及对应的特征、原子信号、领域信号、市场环境、策略信号和目标仓位数据。
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

            <form action={deleteStrategyBacktestRunAction} className="mt-5 flex justify-end gap-2">
              <input type="hidden" name="run_id" value={runId} />
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="inline-flex h-9 items-center rounded-md border border-input bg-background px-3 text-sm font-medium hover:bg-muted"
              >
                取消
              </button>
              <DeleteSubmitButton />
            </form>
          </div>
        </div>
      ) : null}
    </>
  );
}

function DeleteSubmitButton() {
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

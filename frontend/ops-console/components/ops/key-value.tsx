import { displayValue } from "@/lib/utils";

export function KeyValueGrid({
  items
}: {
  items: Array<{ label: string; value: unknown }>;
}) {
  return (
    <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((item) => (
        <div key={item.label} className="rounded-lg border bg-card p-3 text-card-foreground">
          <dt className="text-xs text-muted-foreground">{item.label}</dt>
          <dd className="mt-1 break-words text-sm font-medium">{displayValue(item.value)}</dd>
        </div>
      ))}
    </dl>
  );
}

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

export function FilterBar({
  fields
}: {
  fields: Array<
    | { type: "input"; name: string; label: string; placeholder?: string; defaultValue?: string }
    | { type: "select"; name: string; label: string; defaultValue?: string; options: Array<{ label: string; value: string }> }
  >;
}) {
  return (
    <form className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border bg-card p-4 text-card-foreground">
      {fields.map((field) => (
        <label key={field.name} className="grid gap-1 text-xs text-muted-foreground">
          {field.label}
          {field.type === "input" ? (
            <Input name={field.name} placeholder={field.placeholder} defaultValue={field.defaultValue} />
          ) : (
            <Select name={field.name} defaultValue={field.defaultValue}>
              {field.options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          )}
        </label>
      ))}
      <Button type="submit">查询</Button>
    </form>
  );
}

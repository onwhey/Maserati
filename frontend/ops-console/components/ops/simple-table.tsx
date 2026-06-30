import type { ReactNode } from "react";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { displayValue } from "@/lib/utils";

export function SimpleTable<T extends Record<string, unknown>>({
  rows,
  columns
}: {
  rows: T[];
  columns: Array<{ key: keyof T | string; label: string; render?: (row: T) => ReactNode }>;
}) {
  return (
    <div className="overflow-x-auto rounded-xl border bg-card text-card-foreground">
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((column) => (
              <TableHead key={String(column.key)}>{column.label}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={String(row.id ?? index)}>
              {columns.map((column) => (
                <TableCell key={String(column.key)}>{column.render ? column.render(row) : displayValue(row[String(column.key)])}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

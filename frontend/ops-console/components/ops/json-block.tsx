export function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-[520px] overflow-auto rounded-lg bg-slate-950 p-4 text-xs leading-5 text-slate-100">
      {JSON.stringify(value ?? null, null, 2)}
    </pre>
  );
}

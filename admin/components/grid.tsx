"use client";
import { Empty } from "./ui";

/** Простая таблица результатов: любые колонки, горизонтальная прокрутка. */
export function Grid({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
  if (!rows.length) return <Empty>Нет строк</Empty>;
  return (
    <div className="scroll-thin overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line text-left">
            {columns.map((c) => <th key={c} className="whitespace-nowrap px-3 py-2 text-xs font-medium text-muted">{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line last:border-0 hover:bg-hover">
              {columns.map((c) => {
                const v = r[c];
                return (
                  <td key={c} className={"max-w-xs truncate px-3 py-2 " + (typeof v === "number" ? "text-right tabular-nums" : "")} title={String(v ?? "")}>
                    {v === null || v === undefined ? <span className="text-muted">null</span> : String(v)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

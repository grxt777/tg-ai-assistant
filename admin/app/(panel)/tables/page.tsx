"use client";
import { useEffect, useState } from "react";
import { act, api, useApi } from "@/lib/api";
import { Grid } from "@/components/grid";
import { Badge, Button, Card, ConfirmButton, Empty, ErrorNote, PageHeader, Textarea, cx } from "@/components/ui";

type Table = { name: string; schema: string; description: string; rows: number };
type Result = { columns?: string[]; rows?: Record<string, unknown>[]; truncated?: boolean; total?: number; rowcount?: number };
const PAGE = 50;

export default function TablesPage() {
  const list = useApi<{ tables: Table[] }>("tables");
  const [sel, setSel] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [rows, setRows] = useState<Result | null>(null);
  const [sql, setSql] = useState("");
  const [res, setRes] = useState<Result | null>(null);
  const [sqlErr, setSqlErr] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const tables = list.data?.tables || [];
  const current = tables.find((t) => t.name === sel);

  useEffect(() => { if (!sel && tables.length) setSel(tables[0].name); }, [tables, sel]);
  useEffect(() => {
    if (!sel) return;
    setRows(null);
    api<Result>(`tables/${sel}?limit=${PAGE}&offset=${page * PAGE}`).then(setRows).catch(() => setRows({ rows: [], columns: [] }));
  }, [sel, page]);

  const run = async () => {
    setRunning(true); setSqlErr(null); setRes(null);
    try { setRes(await api<Result>("sql", { body: { sql } })); list.reload(); }
    catch (e) { setSqlErr((e as Error).message); }
    setRunning(false);
  };

  const drop = async (name: string) => {
    if (await act(() => api(`tables/${name}`, { method: "DELETE" }), `Таблица ${name} удалена`)) { setSel(null); list.reload(); }
  };

  return (
    <>
      <PageHeader title="Таблицы" desc="Таблицы, которые ассистент сам завёл: расходы, привычки, задачи и т.д." />
      <ErrorNote error={list.error} />
      <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
        <Card title={`Все таблицы · ${tables.length}`}>
          {tables.length ? (
            <ul className="-mx-2 flex flex-col gap-0.5">
              {tables.map((t) => (
                <li key={t.name}>
                  <button onClick={() => { setSel(t.name); setPage(0); }}
                    className={cx("flex w-full items-center justify-between rounded-xl px-2 py-2 text-left text-sm", sel === t.name ? "bg-hover font-medium" : "hover:bg-hover")}>
                    <span className="truncate font-mono text-xs">{t.name}</span>
                    <span className="text-xs tabular-nums text-muted">{t.rows}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : <Empty>Таблиц пока нет. Скажи боту «запиши расход 50к на обед» — он заведёт.</Empty>}
        </Card>

        <div className="flex min-w-0 flex-col gap-4">
          {current && (
            <Card title={current.name} actions={<ConfirmButton onConfirm={() => drop(current.name)}>Удалить таблицу</ConfirmButton>}>
              {current.description && <p className="mb-2 text-sm text-muted">{current.description}</p>}
              <pre className="scroll-thin mb-4 overflow-x-auto rounded-2xl bg-hover p-2 font-mono text-[11px] text-muted">{current.schema}</pre>
              {rows ? <Grid columns={rows.columns || []} rows={rows.rows || []} /> : <Empty>Загрузка…</Empty>}
              {rows?.total !== undefined && rows.total > PAGE && (
                <div className="mt-3 flex items-center justify-between text-xs text-muted">
                  <span>{page * PAGE + 1}–{Math.min((page + 1) * PAGE, rows.total)} из {rows.total}</span>
                  <div className="flex gap-1">
                    <Button size="sm" disabled={!page} onClick={() => setPage(page - 1)}>← Новее</Button>
                    <Button size="sm" disabled={(page + 1) * PAGE >= rows.total} onClick={() => setPage(page + 1)}>Старее →</Button>
                  </div>
                </div>
              )}
            </Card>
          )}

          <Card title="SQL-консоль" actions={<Badge>только таблицы u_*</Badge>}>
            <Textarea rows={4} className="font-mono text-xs" value={sql} onChange={(e) => setSql(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(); }}
              placeholder={current ? `SELECT category, SUM(amount) FROM ${current.name} GROUP BY 1` : "SELECT …"} />
            <div className="mt-2 flex items-center gap-2">
              <Button variant="primary" onClick={run} disabled={running || !sql.trim()}>{running ? "Выполняю…" : "Выполнить"}</Button>
              <span className="text-xs text-muted">⌘/Ctrl + Enter</span>
            </div>
            {sqlErr && <div className="mt-3 rounded-2xl bg-bad/10 px-3 py-2 font-mono text-xs text-bad">{sqlErr}</div>}
            {res && (
              <div className="mt-3">
                {res.columns ? <>
                  <Grid columns={res.columns} rows={res.rows || []} />
                  {res.truncated && <div className="mt-2 text-xs text-muted">Показаны первые 1000 строк</div>}
                </> : <div className="text-sm text-ok">Готово. Затронуто строк: {res.rowcount}</div>}
              </div>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}

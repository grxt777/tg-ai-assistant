"use client";
import { useState } from "react";
import { fmtDate, useApi } from "@/lib/api";
import { Badge, Card, Empty, ErrorNote, PageHeader, Tabs } from "@/components/ui";

type Ev = { id: number; kind: string; name: string; data: string; ms: number | null; created_at: string };
const TONE: Record<string, "accent" | "neutral" | "bad"> = { llm: "accent", tool: "neutral", error: "bad" };
const LABEL: Record<string, string> = { llm: "модель", tool: "инструмент", error: "ошибка" };

export default function EventsPage() {
  const [kind, setKind] = useState<"" | "llm" | "tool" | "error">("");
  const [auto, setAuto] = useState(true);
  const { data, error } = useApi<{ events: Ev[] }>(`events?limit=300${kind ? `&kind=${kind}` : ""}`, auto ? 5000 : 0);
  const [open, setOpen] = useState<number | null>(null);

  return (
    <>
      <PageHeader title="Журнал" desc="Что ассистент делал: запросы к модели (с токенами и временем), вызовы инструментов, ошибки."
        actions={<label className="flex items-center gap-1.5 text-sm text-muted">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />обновлять каждые 5 с
        </label>} />
      <ErrorNote error={error} />
      <div className="mb-3">
        <Tabs value={kind} onChange={setKind} items={[["", "Все"], ["llm", "Модель"], ["tool", "Инструменты"], ["error", "Ошибки"]]} />
      </div>
      <Card>
        {data?.events.length ? (
          <ul className="font-mono text-xs">
            {data.events.map((e) => (
              <li key={e.id} className="border-b border-line last:border-0">
                <button onClick={() => setOpen(open === e.id ? null : e.id)} className="flex w-full items-center gap-3 py-2 text-left hover:bg-hover">
                  <span className="w-28 shrink-0 text-muted">{fmtDate(e.created_at)}</span>
                  <span className="w-24 shrink-0"><Badge tone={TONE[e.kind] || "neutral"}>{LABEL[e.kind] || e.kind}</Badge></span>
                  <span className="w-40 shrink-0 truncate">{e.name}</span>
                  <span className="min-w-0 flex-1 truncate text-muted">{e.data}</span>
                  <span className="w-16 shrink-0 text-right tabular-nums text-muted">{e.ms !== null ? `${(e.ms / 1000).toFixed(1)} с` : ""}</span>
                </button>
                {open === e.id && <pre className="mb-2 whitespace-pre-wrap break-all rounded-lg bg-hover p-3">{e.data}</pre>}
              </li>
            ))}
          </ul>
        ) : <Empty>Событий пока нет</Empty>}
      </Card>
    </>
  );
}

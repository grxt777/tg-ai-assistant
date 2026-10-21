"use client";
import Link from "next/link";
import { fmtBytes, fmtDate, fmtUptime, useApi } from "@/lib/api";
import { Badge, Card, Empty, ErrorNote, PageHeader, Stat } from "@/components/ui";

type Overview = {
  model: string; owner_id: number; timezone: string; uptime_sec: number; rss_mb: number | null; db_bytes: number;
  counts: Record<"memories" | "documents" | "chunks" | "tables" | "reminders" | "messages", number>;
  day: { llm_calls: number; tool_calls: number; errors: number; tokens: number };
  top_tools: { name: string; n: number }[];
  activity: { day: string; llm: number; tool: number; error: number }[];
  last_message_at: string | null;
};

function ActivityChart({ rows }: { rows: Overview["activity"] }) {
  const days = Array.from({ length: 14 }, (_, i) => {
    const d = new Date(Date.now() - (13 - i) * 864e5).toISOString().slice(0, 10);
    return rows.find((r) => r.day === d) || { day: d, llm: 0, tool: 0, error: 0 };
  });
  const max = Math.max(1, ...days.map((d) => d.llm + d.tool + d.error));
  return (
    <div>
      <div className="flex h-36 items-end gap-1.5">
        {days.map((d) => {
          const total = d.llm + d.tool + d.error;
          return (
            <div key={d.day} className="group relative flex h-full flex-1 flex-col justify-end"
              title={`${d.day}: запросов к модели ${d.llm}, инструментов ${d.tool}, ошибок ${d.error}`}>
              <div className="flex flex-col-reverse overflow-hidden rounded-[3px]" style={{ height: `${(total / max) * 100}%`, minHeight: total ? 3 : 0 }}>
                <div className="bg-accent" style={{ flex: d.llm }} />
                <div className="bg-accent/45" style={{ flex: d.tool }} />
                <div className="bg-bad" style={{ flex: d.error }} />
              </div>
              {!total && <div className="h-[2px] rounded bg-line" />}
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex justify-between text-[11px] text-muted">
        <span>{days[0].day.slice(5)}</span><span>сегодня</span>
      </div>
      <div className="mt-3 flex gap-4 text-xs text-muted">
        <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-sm bg-accent" />запросы к модели</span>
        <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-sm bg-accent/45" />инструменты</span>
        <span className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-sm bg-bad" />ошибки</span>
      </div>
    </div>
  );
}

export default function OverviewPage() {
  const { data, error } = useApi<Overview>("overview", 15000);
  const errors = useApi<{ events: any[] }>("events?kind=error&limit=5", 15000);
  const msgs = useApi<{ messages: any[] }>("messages?limit=6", 15000);
  const online = !!data && !error;

  return (
    <>
      <PageHeader title="Обзор" desc="Состояние ассистента, обновляется каждые 15 секунд"
        actions={<Badge tone={online ? "ok" : "bad"}>{online ? "● онлайн" : "● нет связи"}</Badge>} />
      <ErrorNote error={error} />
      {data && (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Модель" value={<span className="text-base">{data.model}</span>} hint={`Пояс ${data.timezone}`} />
            <Stat label="Работает без перезапуска" value={fmtUptime(data.uptime_sec)} hint={`Последнее сообщение: ${fmtDate(data.last_message_at)}`} />
            <Stat label="Память процесса" value={data.rss_mb ? `${data.rss_mb} МБ` : "—"} hint="из 512 МБ на сервере" />
            <Stat label="База данных" value={fmtBytes(data.db_bytes)} hint="диск 1 ГБ на Fly" />
          </div>

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Запросов к модели за сутки" value={data.day.llm_calls} />
            <Stat label="Вызовов инструментов" value={data.day.tool_calls} />
            <Stat label="Токенов за сутки" value={data.day.tokens.toLocaleString("ru-RU")} />
            <Stat label="Ошибок за сутки" value={data.day.errors} tone={data.day.errors ? "bad" : "ok"} />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card title="Активность за 14 дней" className="lg:col-span-2"><ActivityChart rows={data.activity} /></Card>
            <Card title="Что хранит ассистент">
              <ul className="flex flex-col gap-2 text-sm">
                {([
                  ["/memory", "Фактов в памяти", data.counts.memories],
                  ["/tables", "Своих таблиц", data.counts.tables],
                  ["/docs", "Документов", `${data.counts.documents} · ${data.counts.chunks} фрагм.`],
                  ["/reminders", "Активных напоминаний", data.counts.reminders],
                  ["/chat", "Сообщений в истории", data.counts.messages],
                ] as const).map(([href, label, v]) => (
                  <li key={href}>
                    <Link href={href} className="flex justify-between rounded-md px-2 py-1.5 hover:bg-hover">
                      <span className="text-muted">{label}</span><span className="font-medium tabular-nums">{v}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card title="Последние сообщения" className="lg:col-span-2" actions={<Link href="/chat" className="text-xs text-accent">Вся переписка →</Link>}>
              {msgs.data?.messages.length ? (
                <ul className="flex flex-col gap-2">
                  {msgs.data.messages.map((m) => (
                    <li key={m.id} className="flex gap-2 text-sm">
                      <Badge tone={m.role === "user" ? "accent" : "neutral"}>{m.role === "user" ? "Ты" : "Бот"}</Badge>
                      <span className="line-clamp-2 flex-1">{m.content}</span>
                      <span className="shrink-0 text-xs text-muted">{fmtDate(m.created_at)}</span>
                    </li>
                  ))}
                </ul>
              ) : <Empty>Пока пусто</Empty>}
            </Card>
            <Card title="Частые инструменты">
              {data.top_tools.length ? (
                <ul className="flex flex-col gap-2">
                  {data.top_tools.map((t) => (
                    <li key={t.name} className="text-sm">
                      <div className="flex justify-between"><span className="font-mono text-xs">{t.name}</span><span className="tabular-nums text-muted">{t.n}</span></div>
                      <div className="mt-1 h-1.5 rounded bg-hover"><div className="h-full rounded bg-accent" style={{ width: `${(t.n / data.top_tools[0].n) * 100}%` }} /></div>
                    </li>
                  ))}
                </ul>
              ) : <Empty>Ещё не вызывались</Empty>}
            </Card>
          </div>

          <Card title="Последние ошибки" actions={<Link href="/events" className="text-xs text-accent">Журнал →</Link>}>
            {errors.data?.events.length ? (
              <ul className="flex flex-col gap-2">
                {errors.data.events.map((e) => (
                  <li key={e.id} className="flex gap-3 text-sm">
                    <span className="shrink-0 text-xs text-muted">{fmtDate(e.created_at)}</span>
                    <span className="font-mono text-xs text-bad">{e.name}</span>
                    <span className="line-clamp-2 flex-1 text-xs text-muted">{e.data}</span>
                  </li>
                ))}
              </ul>
            ) : <Empty>Ошибок нет 👌</Empty>}
          </Card>
        </div>
      )}
    </>
  );
}

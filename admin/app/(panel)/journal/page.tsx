"use client";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { act, api, useApi } from "@/lib/api";
import { haptic } from "@/lib/tg";
import { Badge, Button, Card, ConfirmButton, Empty, ErrorNote, Input, PageHeader, Tabs, cx } from "@/components/ui";

type Param = { key: string; label: string; description?: string; active?: number };
type Avg = Record<string, number | null>;
type Point = { date: string; score: number | null; scores: Record<string, number>; income: number; expense: number };
type Month = { month: string; income: number; expense: number; score: number | null; logged: number };
type Period = { income: number; expense: number; net: number; avg: Avg; logged: number };
type Stats = Period & {
  days: number; from: string; to: string; params: Param[];
  prev: Period; streak: number;
  expense_by_category: { category: string; amount: number }[];
  income_by_category: { category: string; amount: number }[];
  event_categories: { category: string; n: number }[];
  best_days: { date: string; score: number; summary: string }[];
  worst_days: { date: string; score: number; summary: string }[];
  series: Point[]; by_month: Month[];
};
type DayRow = { date: string; summary: string; score: number | null; income: number; expense: number; entries: number };
type Day = {
  date: string; summary: string; verdict: string; score: number | null; scores: Record<string, number>; params: Param[];
  entries: { id: number; kind: "event" | "note"; category: string; text: string }[];
  transactions: { id: number; type: "income" | "expense"; amount: number; category: string; note: string }[];
  income: number; expense: number;
};

const RANGES: [string, string][] = [["7", "Неделя"], ["30", "Месяц"], ["365", "Год"]];

// ---------- форматирование ----------
const parse = (d: string) => { const [y, m, dd] = d.split("-").map(Number); return new Date(y, m - 1, dd || 1); };
const fmtDay = (d: string, o: Intl.DateTimeFormatOptions = { weekday: "short", day: "numeric", month: "short" }) => parse(d).toLocaleDateString("ru-RU", o);
const fmtMonth = (m: string) => parse(m).toLocaleDateString("ru-RU", { month: "short" }).replace(".", "");
const sum = (n: number) => Math.round(n).toLocaleString("ru-RU");
function short(n: number) {
  const a = Math.abs(n), s = n < 0 ? "−" : "";
  if (a >= 1e6) return `${s}${(a / 1e6).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млн`;
  if (a >= 1e3) return `${s}${Math.round(a / 1e3).toLocaleString("ru-RU")} тыс`;
  return `${s}${Math.round(a)}`;
}
const scoreTone = (v: number | null) => v == null ? "neutral" : v >= 7 ? "ok" : v >= 5 ? "warn" : "bad";

/** Изменение к прошлому периоду: стрелка + подпись, цвет — хорошо это или плохо. */
function Delta({ cur, prev, money, lowerIsBetter }: { cur: number | null; prev: number | null; money?: boolean; lowerIsBetter?: boolean }) {
  if (cur == null || prev == null || (money && !prev)) return <span>нет данных для сравнения</span>;
  const diff = cur - prev;
  if (Math.abs(diff) < (money ? 1 : 0.05)) return <span>как в прошлый период</span>;
  const good = lowerIsBetter ? diff < 0 : diff > 0;
  const text = money ? `${Math.round((diff / prev) * 100)}%` : diff.toFixed(1);
  return <span className={good ? "text-ok" : "text-bad"}>{diff > 0 ? "↑ +" : "↓ "}{text.replace("-", "−")} к прошлому</span>;
}

// ---------- графики ----------
type BarItem = { key: string; label: string; values: (number | null)[]; title: ReactNode };

/** Столбики с подписью выбранного значения сверху (наведение или тап). */
function Bars({ items, colors, max, labelEvery = 1, empty }: { items: BarItem[]; colors: string[]; max: number; labelEvery?: number; empty?: string }) {
  const [sel, setSel] = useState<number | null>(null);
  const has = items.some((i) => i.values.some((v) => v));
  const shown = sel ?? items.length - 1;
  if (!has) return <Empty>{empty || "Пока нет данных за этот период"}</Empty>;
  return (
    <div>
      <div className="mb-2 min-h-5 text-xs text-muted">{items[shown]?.title}</div>
      <div className="flex h-36 items-end gap-[2px] border-b border-line" onPointerLeave={() => setSel(null)}>
        {items.map((it, i) => (
          <button key={it.key} type="button" aria-label={it.label}
            className={cx("flex h-full flex-1 items-end justify-center gap-[2px] rounded-t-md", sel === i && "bg-hover")}
            onPointerEnter={(e) => e.pointerType === "mouse" && setSel(i)}
            onClick={() => { haptic.select(); setSel(i); }}>
            {it.values.map((v, j) => (
              <div key={j} className="w-full max-w-6 rounded-t-[4px]"
                style={{ height: `${((v || 0) / max) * 100}%`, minHeight: v ? 2 : 0, background: colors[j] }} />
            ))}
          </button>
        ))}
      </div>
      <div className="mt-1.5 flex gap-[2px] text-[10px] text-muted">
        {items.map((it, i) => (
          <span key={it.key} className="flex-1 overflow-visible whitespace-nowrap text-center">
            {i % labelEvery === 0 || i === items.length - 1 ? it.label : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

function Legend({ items }: { items: [string, string][] }) {
  return (
    <div className="flex gap-3 text-xs text-muted">
      {items.map(([c, l]) => <span key={l} className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-sm" style={{ background: c }} />{l}</span>)}
    </div>
  );
}

/** Календарь: недели — колонки, дни — строки, цвет — итоговая оценка дня. */
function Calendar({ series, onOpen }: { series: Point[]; onOpen: (d: string) => void }) {
  const pad = (parse(series[0].date).getDay() + 6) % 7; // с понедельника
  const cells: (Point | null)[] = [...Array(pad).fill(null), ...series];
  const weeks = Math.ceil(cells.length / 7);
  return (
    <div>
      <div className="scroll-thin overflow-x-auto pb-1" ref={(el) => { if (el) el.scrollLeft = el.scrollWidth; }}>
        <div className="grid w-max grid-flow-col gap-[3px]" style={{ gridTemplateRows: "repeat(7, 14px)", gridTemplateColumns: `repeat(${weeks}, 14px)` }}>
          {cells.map((p, i) => p ? (
            <button key={p.date} type="button" onClick={() => onOpen(p.date)}
              title={`${fmtDay(p.date)}: ${p.score != null ? `оценка ${p.score}/10` : "без оценки"}`}
              className="rounded-[3px] transition hover:ring-2 hover:ring-accent/50"
              style={{ background: p.score != null ? `color-mix(in srgb, var(--accent) ${20 + p.score * 8}%, transparent)` : "var(--hover)" }} />
          ) : <i key={`p${i}`} />)}
        </div>
      </div>
      <div className="mt-2 flex items-center gap-1.5 text-[11px] text-muted">
        <span>оценка 1</span>
        {[2, 5, 8, 10].map((s) => <i key={s} className="h-2.5 w-2.5 rounded-[3px]" style={{ background: `color-mix(in srgb, var(--accent) ${20 + s * 8}%, transparent)` }} />)}
        <span>10</span>
        <i className="ml-2 h-2.5 w-2.5 rounded-[3px] bg-hover" /><span>нет записи</span>
      </div>
    </div>
  );
}

function HBars({ rows, total }: { rows: { label: string; value: number; text: string }[]; total: number }) {
  return (
    <ul className="flex flex-col gap-2.5">
      {rows.map((r) => (
        <li key={r.label} className="text-sm">
          <div className="flex justify-between gap-2"><span className="truncate">{r.label}</span><span className="shrink-0 tabular-nums text-muted">{r.text}</span></div>
          <div className="mt-1 h-1.5 rounded bg-hover"><div className="h-full rounded bg-accent" style={{ width: `${(r.value / total) * 100}%` }} /></div>
        </li>
      ))}
    </ul>
  );
}

// ---------- день целиком ----------
function DaySheet({ date, onClose, onChange }: { date: string; onClose: () => void; onChange: () => void }) {
  const { data, error, reload } = useApi<Day>(`journal/days/${date}`);
  const del = async (kind: string, id: number | string) => {
    if (await act(() => api(`journal/${kind}/${id}`, { method: "DELETE" }), "Удалено")) { reload(); onChange(); }
  };
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  const events = data?.entries.filter((e) => e.kind === "event") || [];
  const notes = data?.entries.filter((e) => e.kind === "note") || [];
  const empty = data && !data.summary && !data.entries.length && !data.transactions.length && data.score == null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center md:items-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div className="sheet-in glass-strong scroll-thin relative max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-t-[28px] p-5 md:rounded-[28px]"
        style={{ paddingBottom: "calc(var(--safe-bottom) + 20px)" }} onClick={(e) => e.stopPropagation()}>
        <div className="relative flex items-start justify-between gap-3">
          <div>
            <div className="text-xl font-bold first-letter:uppercase">{fmtDay(date, { weekday: "long", day: "numeric", month: "long" })}</div>
            <div className="text-xs text-muted">{parse(date).getFullYear()}</div>
          </div>
          <Button size="sm" onClick={onClose}>Закрыть</Button>
        </div>
        <ErrorNote error={error} />
        {empty && <Empty>За этот день ничего не записано</Empty>}
        {data && !empty && (
          <div className="relative mt-4 flex flex-col gap-5">
            {data.summary && <p className="text-[15px] leading-relaxed">{data.summary}</p>}
            {data.verdict && (
              <div className="rounded-2xl bg-accent/10 px-3.5 py-3 text-sm leading-relaxed">
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-accent">Оценка ассистента</div>
                {data.verdict}
              </div>
            )}

            {(data.score != null || Object.keys(data.scores).length > 0) && (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {[{ key: "score", label: "Итог дня", value: data.score },
                  ...data.params.filter((p) => data.scores[p.key] != null).map((p) => ({ ...p, value: data.scores[p.key] }))].map((p) => (
                  <div key={p.key} className={cx("rounded-2xl bg-hover px-3 py-2", p.key === "score" && "col-span-2 sm:col-span-1")}>
                    <div className="text-[11px] text-muted">{p.label}</div>
                    <div className="text-lg font-semibold tabular-nums">{p.value ?? "—"}<span className="text-xs font-normal text-muted">/10</span></div>
                  </div>
                ))}
              </div>
            )}

            {([["События", events], ["Заметки", notes]] as const).map(([title, list]) => list.length > 0 && (
              <section key={title}>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
                <ul className="flex flex-col gap-1.5">
                  {list.map((e) => (
                    <li key={e.id} className="flex items-start gap-2 text-sm">
                      <Badge>{e.category}</Badge>
                      <span className="flex-1">{e.text}</span>
                      <ConfirmButton onConfirm={() => del("entry", e.id)}>×</ConfirmButton>
                    </li>
                  ))}
                </ul>
              </section>
            ))}

            {data.transactions.length > 0 && (
              <section>
                <h3 className="mb-2 flex justify-between text-xs font-semibold uppercase tracking-wide text-muted">
                  <span>Деньги</span>
                  <span className="normal-case tracking-normal">+{sum(data.income)} / −{sum(data.expense)} сум</span>
                </h3>
                <ul className="flex flex-col gap-1.5">
                  {data.transactions.map((t) => (
                    <li key={t.id} className="flex items-center gap-2 text-sm">
                      <i className="h-2 w-2 shrink-0 rounded-sm" style={{ background: t.type === "income" ? "var(--inc)" : "var(--exp)" }} />
                      <span className="min-w-0 flex-1 truncate">{t.category}{t.note && <span className="text-muted"> · {t.note}</span>}</span>
                      <span className="shrink-0 font-medium tabular-nums">{t.type === "income" ? "+" : "−"}{sum(t.amount)}</span>
                      <ConfirmButton onConfirm={() => del("transaction", t.id)}>×</ConfirmButton>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <div className="flex justify-end"><ConfirmButton onConfirm={async () => { await del("day", date); onClose(); }}>Удалить день</ConfirmButton></div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------- лента дней ----------
function History({ onOpen, version }: { onOpen: (d: string) => void; version: number }) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<DayRow[]>([]);
  const [more, setMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const LIMIT = 30;

  const load = async (before?: string) => {
    try {
      const p = new URLSearchParams({ limit: String(LIMIT) });
      if (before) p.set("before", before);
      if (query) p.set("q", query);
      const d = await api<{ days: DayRow[] }>(`journal/days?${p}`);
      setRows((r) => (before ? [...r, ...d.days] : d.days));
      setMore(d.days.length === LIMIT);
      setError(null);
    } catch (e) { setError((e as Error).message); }
  };
  useEffect(() => { load(); }, [query, version]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const t = setTimeout(() => setQuery(q.trim()), 350); return () => clearTimeout(t); }, [q]);

  return (
    <Card title="История">
      <Input placeholder="Поиск по записям, тратам, заметкам" value={q} onChange={(e) => setQ(e.target.value)} className="mb-3" />
      <ErrorNote error={error} />
      {rows.length ? (
        <ul>
          {rows.map((d) => (
            <li key={d.date}>
              <button type="button" onClick={() => { haptic.tap("light"); onOpen(d.date); }}
                className="flex w-full items-start gap-3 rounded-2xl px-2 py-3 text-left transition hover:bg-hover active:scale-[0.99]">
                <div className="w-12 shrink-0 text-center">
                  <div className="text-xl font-semibold leading-none tabular-nums">{parse(d.date).getDate()}</div>
                  <div className="mt-1 text-[11px] text-muted">{fmtDay(d.date, { month: "short" }).replace(".", "")} · {fmtDay(d.date, { weekday: "short" })}</div>
                </div>
                <div className="min-w-0 flex-1">
                  <div className="line-clamp-2 text-sm">{d.summary || <span className="text-muted">{d.entries ? `${d.entries} записей` : "только деньги"}</span>}</div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                    {d.score != null && <Badge tone={scoreTone(d.score)}>итог {d.score}/10</Badge>}
                    {d.income > 0 && <span className="tabular-nums">+{short(d.income)}</span>}
                    {d.expense > 0 && <span className="tabular-nums">−{short(d.expense)}</span>}
                  </div>
                </div>
              </button>
            </li>
          ))}
        </ul>
      ) : <Empty>{query ? "Ничего не нашлось" : "Записей пока нет. Вечером расскажи боту, как прошёл день."}</Empty>}
      {more && <div className="mt-2 flex justify-center"><Button size="sm" onClick={() => load(rows[rows.length - 1].date)}>Показать ещё</Button></div>}
    </Card>
  );
}

// ---------- страница ----------
export default function JournalPage() {
  const [range, setRange] = useState("7");
  const { data: s, error, reload } = useApi<Stats>(`journal/stats?days=${range}`, 60000);
  const [open, setOpen] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const year = range === "365";

  const scoreItems = useMemo<BarItem[]>(() => !s ? [] : year
    ? s.by_month.map((m) => ({ key: m.month, label: fmtMonth(m.month), values: [m.score],
        title: <>{parse(m.month).toLocaleDateString("ru-RU", { month: "long", year: "numeric" })}: средняя оценка <b className="text-fg">{m.score ?? "—"}</b> · записано дней {m.logged}</> }))
    : s.series.map((p) => ({ key: p.date, label: range === "7" ? fmtDay(p.date, { weekday: "short" }) : String(parse(p.date).getDate()), values: [p.score],
        title: <>{fmtDay(p.date)}: итог <b className="text-fg">{p.score ?? "—"}</b>{s.params.filter((x) => p.scores[x.key] != null).slice(0, 3).map((x) => <span key={x.key}> · {x.label.toLowerCase()} {p.scores[x.key]}</span>)}</> })), [s, year, range]);

  const moneyItems = useMemo<BarItem[]>(() => !s ? [] : (year ? s.by_month.map((m) => ({ ...m, key: m.month, label: fmtMonth(m.month) }))
    : s.series.map((p) => ({ ...p, key: p.date, label: range === "7" ? fmtDay(p.date, { weekday: "short" }) : String(parse(p.date).getDate()) })))
    .map((p) => ({ key: p.key, label: p.label, values: [p.income, p.expense],
      title: <>{year ? parse(p.key).toLocaleDateString("ru-RU", { month: "long" }) : fmtDay(p.key)}: доход <b className="text-fg">{sum(p.income)}</b> · расход <b className="text-fg">{sum(p.expense)}</b> сум</> })), [s, year, range]);

  const moneyMax = Math.max(1, ...moneyItems.flatMap((i) => i.values.map((v) => v || 0)));
  const changed = () => { reload(); setVersion((v) => v + 1); };

  return (
    <>
      <PageHeader title="Дневник" desc="Пиши боту вечером, как прошёл день — всё появится здесь"
        actions={<Tabs value={range} onChange={setRange} items={RANGES} />} />
      <ErrorNote error={error} />
      {s && (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile label="Средняя оценка дня" value={s.avg.score != null ? <>{s.avg.score}<span className="text-sm text-muted">/10</span></> : "—"}
              hint={<Delta cur={s.avg.score} prev={s.prev.avg.score} />} />
            <StatTile label="Доход" value={short(s.income)} hint={<Delta cur={s.income} prev={s.prev.income} money />} />
            <StatTile label="Расход" value={short(s.expense)} hint={<Delta cur={s.expense} prev={s.prev.expense} money lowerIsBetter />} />
            <StatTile label="Доход − расход" value={<span className={s.net < 0 ? "text-bad" : ""}>{s.net > 0 ? "+" : ""}{short(s.net)}</span>}
              hint={`записано ${s.logged} из ${s.days} дн. · серия ${s.streak}`} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title={year ? "Оценка дня по месяцам" : "Оценка дня"}>
              <Bars items={scoreItems} colors={["var(--accent)"]} max={10} labelEvery={range === "30" ? 5 : 1} empty="Оценок за этот период пока нет" />
            </Card>
            <Card title="Деньги, сум" actions={<Legend items={[["var(--inc)", "доход"], ["var(--exp)", "расход"]]} />}>
              <Bars items={moneyItems} colors={["var(--inc)", "var(--exp)"]} max={moneyMax} labelEvery={range === "30" ? 5 : 1} empty="Доходов и расходов за этот период нет" />
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card title="Параметры дня">
              <ul className="flex flex-col gap-3">
                {s.params.map(({ key: k, label }) => (
                  <li key={k} className="text-sm">
                    <div className="flex items-baseline justify-between gap-2">
                      <span>{label}</span>
                      <span className="font-semibold tabular-nums">{s.avg[k] ?? "—"}<span className="text-xs font-normal text-muted">/10</span></span>
                    </div>
                    <div className="mt-1 h-1.5 rounded bg-hover"><div className="h-full rounded bg-accent" style={{ width: `${(s.avg[k] || 0) * 10}%` }} /></div>
                    <div className="mt-0.5 text-[11px] text-muted"><Delta cur={s.avg[k]} prev={s.prev.avg[k]} /></div>
                  </li>
                ))}
              </ul>
            </Card>
            <Card title="Куда уходят деньги">
              {s.expense_by_category.length ? (
                <HBars total={s.expense_by_category[0].amount}
                  rows={s.expense_by_category.slice(0, 8).map((c) => ({ label: c.category, value: c.amount,
                    text: `${short(c.amount)} · ${Math.round((c.amount / s.expense) * 100)}%` }))} />
              ) : <Empty>Расходов нет</Empty>}
              {s.income_by_category.length > 0 && (
                <p className="mt-4 text-xs text-muted">Доход: {s.income_by_category.map((c) => `${c.category} ${short(c.amount)}`).join(" · ")}</p>
              )}
            </Card>
            <Card title="Лучшие и худшие дни">
              {s.best_days.length ? (
                <div className="flex flex-col gap-3">
                  {([["Лучшие", s.best_days], ["Тяжёлые", s.worst_days.filter((w) => !s.best_days.some((b) => b.date === w.date))]] as const)
                    .map(([title, list]) => list.length > 0 && (
                      <div key={title}>
                        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{title}</div>
                        {list.map((d) => (
                          <button key={d.date} type="button" onClick={() => setOpen(d.date)} className="flex w-full items-start gap-2 rounded-xl px-1.5 py-1.5 text-left text-sm hover:bg-hover">
                            <Badge tone={scoreTone(d.score)}>{d.score}</Badge>
                            <span className="w-14 shrink-0 text-xs text-muted">{fmtDay(d.date, { day: "numeric", month: "short" })}</span>
                            <span className="line-clamp-1 flex-1">{d.summary}</span>
                          </button>
                        ))}
                      </div>
                    ))}
                  {s.event_categories.length > 0 && (
                    <p className="text-xs text-muted">Чем был занят: {s.event_categories.map((c) => `${c.category} ${c.n}`).join(" · ")}</p>
                  )}
                </div>
              ) : <Empty>Появятся, когда будут оценки</Empty>}
            </Card>
          </div>

          {range !== "7" && <Card title="Календарь"><Calendar series={s.series} onOpen={setOpen} /></Card>}

          <History onOpen={setOpen} version={version} />
          <Criteria onChange={reload} />
        </div>
      )}
      {open && <DaySheet date={open} onClose={() => setOpen(null)} onChange={changed} />}
    </>
  );
}

function StatTile({ label, value, hint }: { label: string; value: ReactNode; hint: ReactNode }) {
  return (
    <div className="glass rounded-[22px] p-4">
      <div className="relative text-xs text-muted">{label}</div>
      <div className="relative mt-1 truncate text-2xl font-semibold tabular-nums">{value}</div>
      <div className="relative mt-1 text-[11px] leading-snug text-muted">{hint}</div>
    </div>
  );
}

/** Критерии оценки: бот добавляет их сам (с согласия), здесь можно выключить ненужные. */
function Criteria({ onChange }: { onChange: () => void }) {
  const { data, reload } = useApi<{ params: Param[] }>("journal/params");
  const toggle = async (p: Param) => {
    if (await act(() => api(`journal/params/${p.key}`, { method: "PUT", body: { active: !p.active } }), p.active ? "Критерий выключен" : "Критерий включён")) {
      reload(); onChange();
    }
  };
  return (
    <Card title="Критерии оценки">
      <p className="relative mb-3 text-xs text-muted">Ассистент оценивает день по ним сам. Новый критерий — просто попроси в чате: «оценивай ещё сон».</p>
      <ul className="relative">
        {data?.params.map((p) => (
          <li key={p.key} className="flex items-start gap-3 border-b border-line py-2.5 last:border-0">
            <div className={cx("min-w-0 flex-1", !p.active && "opacity-50")}>
              <div className="text-sm font-medium">{p.label}</div>
              <div className="text-xs text-muted">{p.description}</div>
            </div>
            <input type="checkbox" aria-label={p.label} className="mt-1 h-5 w-5 shrink-0 accent-[var(--accent)]" checked={!!p.active} onChange={() => toggle(p)} />
          </li>
        ))}
      </ul>
    </Card>
  );
}

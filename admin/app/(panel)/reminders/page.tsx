"use client";
import { useState } from "react";
import { act, api, useApi } from "@/lib/api";
import { Badge, Button, Card, ConfirmButton, Empty, ErrorNote, Input, PageHeader, Select, Tabs } from "@/components/ui";

type Rem = { id: number; due_local: string; text: string; repeat: string; kind: string; done: number };
const REPEAT: Record<string, string> = { none: "один раз", daily: "каждый день", weekly: "каждую неделю" };

export default function RemindersPage() {
  const [tab, setTab] = useState<"active" | "done">("active");
  const { data, error, reload } = useApi<{ reminders: Rem[] }>(`reminders${tab === "done" ? "?done=1" : ""}`, 30000);
  const [when, setWhen] = useState("");
  const [text, setText] = useState("");
  const [repeat, setRepeat] = useState("none");
  const [kind, setKind] = useState("notify");

  const add = async () => {
    const r = await act(() => api("reminders", { body: { when: when.replace("T", " "), text, repeat, kind } }), "Напоминание создано");
    if (r) { setText(""); setWhen(""); reload(); }
  };

  return (
    <>
      <PageHeader title="Напоминания" desc="Время — в твоём часовом поясе. «Задача» — ассистент сам её выполнит и пришлёт результат." />
      <ErrorNote error={error} />
      <Card title="Новое напоминание" className="mb-4">
        <div className="grid gap-2 md:grid-cols-[1fr_200px_160px_150px_auto]">
          <Input placeholder={kind === "task" ? "Что сделать: «составь план на день»" : "Текст напоминания"} value={text} onChange={(e) => setText(e.target.value)} />
          <Input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
          <Select value={repeat} onChange={(e) => setRepeat(e.target.value)}>
            {Object.entries(REPEAT).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </Select>
          <Select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="notify">Напомнить</option>
            <option value="task">Задача для ИИ</option>
          </Select>
          <Button variant="primary" onClick={add} disabled={!text.trim() || !when}>Создать</Button>
        </div>
      </Card>

      <div className="mb-3"><Tabs value={tab} onChange={setTab} items={[["active", "Активные"], ["done", "Выполненные и отменённые"]]} /></div>
      <Card>
        {data?.reminders.length ? (
          <ul>
            {data.reminders.map((r) => (
              <li key={r.id} className="flex items-center gap-3 border-b border-line py-3 last:border-0">
                <div className="w-36 shrink-0 font-mono text-xs tabular-nums">{r.due_local}</div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm">{r.text}</div>
                  <div className="mt-1 flex gap-1.5">
                    <Badge tone={r.kind === "task" ? "accent" : "neutral"}>{r.kind === "task" ? "задача для ИИ" : "напоминание"}</Badge>
                    <Badge>{REPEAT[r.repeat] || r.repeat}</Badge>
                  </div>
                </div>
                {tab === "active" && <ConfirmButton onConfirm={() => act(() => api(`reminders/${r.id}`, { method: "DELETE" }), "Отменено").then(reload)}>Отменить</ConfirmButton>}
              </li>
            ))}
          </ul>
        ) : <Empty>{tab === "active" ? "Активных напоминаний нет" : "Пусто"}</Empty>}
      </Card>
    </>
  );
}

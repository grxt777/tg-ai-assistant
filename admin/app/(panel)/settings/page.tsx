"use client";
import { useEffect, useState } from "react";
import { act, api, useApi } from "@/lib/api";
import { Button, Card, ErrorNote, Input, PageHeader, Select, Textarea } from "@/components/ui";

type S = { model: string; temperature: string; history_limit: string; instructions: string; fallback: string; journal_time: string };

export default function SettingsPage() {
  const { data, error, reload } = useApi<{ values: S; defaults: S; fallback_chain: string[] }>("settings");
  const models = useApi<{ models: string[] }>("models");
  const [v, setV] = useState<S | null>(null);
  useEffect(() => { if (data) setV(data.values); }, [data]);
  if (!v || !data) return <><PageHeader title="Настройки" /><ErrorNote error={error} /></>;

  const d = data.defaults;
  const set = (k: keyof S) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  const save = async () => { if (await act(() => api("settings", { method: "PUT", body: v }), "Сохранено — действует со следующего сообщения")) reload(); };
  const temp = Number(v.temperature || d.temperature);

  return (
    <>
      <PageHeader title="Настройки" desc="Меняются на лету, без перезапуска бота. Пустое поле — значение по умолчанию."
        actions={<Button variant="primary" onClick={save}>Сохранить</Button>} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Модель">
          <Select value={v.model} onChange={set("model")}>
            <option value="">По умолчанию ({d.model})</option>
            {(models.data?.models || []).map((m) => <option key={m} value={m}>{m}</option>)}
          </Select>
          <p className="mt-2 text-xs text-muted">flash — быстрая и бесплатная. pro — умнее, но лимиты бесплатного тарифа намного меньше. lite — самые высокие лимиты.</p>
        </Card>
        <Card title="Запасные модели">
          <label className="relative flex items-center justify-between gap-3">
            <span className="text-sm">Переключаться, когда дневной лимит модели закончился</span>
            <input type="checkbox" className="h-5 w-5 accent-[var(--accent)]" checked={(v.fallback || d.fallback) !== "0"}
              onChange={(e) => setV({ ...v, fallback: e.target.checked ? "1" : "0" })} />
          </label>
          <p className="relative mt-2 text-xs text-muted">У каждой модели свой бесплатный лимит в сутки. Порядок: {data.fallback_chain.join(" → ")}.</p>
        </Card>
        <Card title={`Креативность (temperature): ${temp.toFixed(1)}`}>
          <input type="range" min={0} max={1.5} step={0.1} value={temp} onChange={set("temperature")} className="w-full accent-[var(--accent)]" />
          <div className="mt-1 flex justify-between text-xs text-muted"><span>точнее</span><span>по умолчанию {d.temperature}</span><span>креативнее</span></div>
        </Card>
        <Card title="Сколько сообщений диалога помнить">
          <Input type="number" min={2} max={200} placeholder={`по умолчанию ${d.history_limit}`} value={v.history_limit} onChange={set("history_limit")} />
          <p className="mt-2 text-xs text-muted">Больше — лучше держит нить разговора, но тратит больше токенов. Долговременная память от этого не зависит.</p>
        </Card>
        <Card title="Вечерний вопрос для дневника">
          <div className="flex gap-2">
            <Input type="time" value={v.journal_time === "off" ? "" : v.journal_time || d.journal_time}
              onChange={(e) => setV({ ...v, journal_time: e.target.value })} disabled={v.journal_time === "off"} />
            <Button onClick={() => setV({ ...v, journal_time: v.journal_time === "off" ? "" : "off" })}>
              {v.journal_time === "off" ? "Включить" : "Выключить"}
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted">В это время бот спросит, как прошёл день, — если ты ещё не рассказал сам.</p>
        </Card>
        <Card title="Дополнительные указания ассистенту" className="lg:col-span-2">
          <Textarea rows={6} value={v.instructions} onChange={set("instructions")}
            placeholder={"Например:\n— Отвечай коротко, максимум 5 предложений.\n— Обращайся ко мне на «ты».\n— Суммы пиши в сумах."} />
          <p className="mt-2 text-xs text-muted">Добавляется к системному промпту при каждом сообщении.</p>
        </Card>
      </div>
    </>
  );
}

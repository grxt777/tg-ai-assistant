"use client";
import { useEffect, useState } from "react";
import { act, api, fmtDate, useApi } from "@/lib/api";
import { Badge, Button, Card, ConfirmButton, Empty, ErrorNote, Input, PageHeader, Select, Textarea, cx } from "@/components/ui";

const CATS: [string, string][] = [
  ["profile", "Профиль"], ["preference", "Предпочтения"], ["person", "Люди"],
  ["goal", "Цели"], ["event", "События"], ["note", "Заметки"],
];
const catLabel = (c: string) => CATS.find(([k]) => k === c)?.[1] || c;

type Mem = { id: number; category: string; content: string; created_at?: string; updated_at?: string; score?: number };

function Row({ m, onChanged }: { m: Mem; onChanged: () => void }) {
  const [edit, setEdit] = useState(false);
  const [content, setContent] = useState(m.content);
  const [cat, setCat] = useState(m.category);
  const save = async () => {
    if (await act(() => api(`memories/${m.id}`, { method: "PATCH", body: { content, category: cat } }), "Сохранено")) {
      setEdit(false);
      onChanged();
    }
  };
  return (
    <li className="group border-b border-line py-3 last:border-0">
      {edit ? (
        <div className="flex flex-col gap-2">
          <Textarea rows={3} value={content} onChange={(e) => setContent(e.target.value)} />
          <div className="flex gap-2">
            <Select value={cat} onChange={(e) => setCat(e.target.value)} className="w-44">
              {CATS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </Select>
            <Button variant="primary" onClick={save}>Сохранить</Button>
            <Button onClick={() => { setEdit(false); setContent(m.content); setCat(m.category); }}>Отмена</Button>
          </div>
        </div>
      ) : (
        <div className="flex items-start gap-3">
          <span className="w-10 shrink-0 pt-0.5 font-mono text-xs text-muted">#{m.id}</span>
          <div className="min-w-0 flex-1">
            <div className="text-sm">{m.content}</div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
              <Badge tone={m.category === "profile" ? "accent" : "neutral"}>{catLabel(m.category)}</Badge>
              {m.score !== undefined && <Badge tone="ok">совпадение {Math.round(m.score * 100)}%</Badge>}
              {m.updated_at && <span>обновлено {fmtDate(m.updated_at)}</span>}
            </div>
          </div>
          <div className="flex shrink-0 gap-1 opacity-100 transition md:opacity-0 md:group-hover:opacity-100">
            <Button size="sm" onClick={() => setEdit(true)}>Изменить</Button>
            <ConfirmButton onConfirm={() => act(() => api(`memories/${m.id}`, { method: "DELETE" }), "Удалено").then(onChanged)} />
          </div>
        </div>
      )}
    </li>
  );
}

export default function MemoryPage() {
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [cat, setCat] = useState("");
  const [semantic, setSemantic] = useState(false);
  const [adding, setAdding] = useState(false);
  const [newText, setNewText] = useState("");
  const [newCat, setNewCat] = useState("note");

  useEffect(() => { const t = setTimeout(() => setDq(q), 350); return () => clearTimeout(t); }, [q]);
  const params = new URLSearchParams();
  if (dq) params.set("q", dq);
  if (cat && !(semantic && dq)) params.set("category", cat);
  if (semantic && dq) params.set("semantic", "1");
  const { data, error, loading, reload } = useApi<{ memories: Mem[] }>(`memories?${params}`);
  const all = useApi<{ memories: Mem[] }>("memories");
  const counts = Object.fromEntries(CATS.map(([k]) => [k, all.data?.memories.filter((m) => m.category === k).length || 0]));
  const refresh = () => { reload(); all.reload(); };

  const add = async () => {
    if (await act(() => api("memories", { body: { content: newText, category: newCat } }), "Добавлено")) {
      setNewText(""); setAdding(false); refresh();
    }
  };

  return (
    <>
      <PageHeader title="Память" desc="Факты, которые ассистент знает о тебе. Профиль всегда у него перед глазами."
        actions={<Button variant="primary" onClick={() => setAdding((v) => !v)}>+ Добавить факт</Button>} />
      <ErrorNote error={error} />

      {adding && (
        <Card className="mb-4">
          <div className="flex flex-col gap-2">
            <Textarea rows={2} autoFocus placeholder="Например: Умид учится в Inha, 3 курс" value={newText} onChange={(e) => setNewText(e.target.value)} />
            <div className="flex gap-2">
              <Select value={newCat} onChange={(e) => setNewCat(e.target.value)} className="w-44">
                {CATS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </Select>
              <Button variant="primary" onClick={add} disabled={!newText.trim()}>Сохранить</Button>
            </div>
          </div>
        </Card>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input placeholder={semantic ? "Поиск по смыслу: «где я учусь?»" : "Поиск по тексту"} value={q} onChange={(e) => setQ(e.target.value)} className="w-72" />
        <label className="flex items-center gap-1.5 text-sm text-muted">
          <input type="checkbox" checked={semantic} onChange={(e) => setSemantic(e.target.checked)} />по смыслу
        </label>
        <div className="ml-auto flex flex-wrap gap-1">
          <button onClick={() => setCat("")} className={cx("rounded-full border px-3 py-1 text-xs", !cat ? "border-accent text-accent" : "border-line text-muted")}>
            Все {all.data?.memories.length ?? ""}
          </button>
          {CATS.map(([k, l]) => (
            <button key={k} onClick={() => setCat(cat === k ? "" : k)}
              className={cx("rounded-full border px-3 py-1 text-xs", cat === k ? "border-accent text-accent" : "border-line text-muted")}>
              {l} {counts[k] || 0}
            </button>
          ))}
        </div>
      </div>

      <Card>
        {loading && !data ? <Empty>Загрузка…</Empty> : data?.memories.length ? (
          <ul>{data.memories.map((m) => <Row key={m.id} m={m} onChanged={refresh} />)}</ul>
        ) : <Empty>{dq ? "Ничего не найдено" : "Память пока пуста — ассистент заполнит её сам по ходу общения"}</Empty>}
      </Card>
    </>
  );
}

"use client";
import { useRef, useState } from "react";
import { act, api, fmtDate, useApi } from "@/lib/api";
import { Button, Card, ConfirmButton, Empty, ErrorNote, PageHeader } from "@/components/ui";

type Doc = { id: number; title: string; created_at: string; chunks: number; chars: number };

function DocRow({ d, onDeleted }: { d: Doc; onDeleted: () => void }) {
  const [open, setOpen] = useState(false);
  const [chunks, setChunks] = useState<{ idx: number; content: string }[] | null>(null);
  const toggle = async () => {
    setOpen(!open);
    if (!chunks) setChunks((await act(() => api<{ chunks: any[] }>(`documents/${d.id}`)))?.chunks || []);
  };
  return (
    <li className="border-b border-line py-3 last:border-0">
      <div className="flex items-center gap-3">
        <button onClick={toggle} className="min-w-0 flex-1 text-left">
          <div className="truncate text-sm font-medium">{open ? "▾" : "▸"} {d.title}</div>
          <div className="mt-0.5 text-xs text-muted">{d.chunks} фрагм. · {d.chars.toLocaleString("ru-RU")} символов · {fmtDate(d.created_at)}</div>
        </button>
        <ConfirmButton onConfirm={() => act(() => api(`documents/${d.id}`, { method: "DELETE" }), "Документ удалён").then(onDeleted)} />
      </div>
      {open && (
        <div className="mt-3 flex max-h-96 flex-col gap-2 overflow-y-auto scroll-thin">
          {chunks === null ? <Empty>Загрузка…</Empty> : chunks.map((c) => (
            <div key={c.idx} className="rounded-lg bg-hover p-3 text-xs">
              <div className="mb-1 font-mono text-muted">фрагмент {c.idx + 1}</div>
              <div className="whitespace-pre-wrap">{c.content}</div>
            </div>
          ))}
        </div>
      )}
    </li>
  );
}

export default function DocsPage() {
  const { data, error, reload } = useApi<{ documents: Doc[] }>("documents");
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    for (const f of Array.from(files)) {
      if (f.size > 4 * 1024 * 1024) { act(async () => { throw new Error(`${f.name}: больше 4 МБ — отправь его боту в Telegram`); }); continue; }
      const form = new FormData();
      form.append("file", f);
      await act(() => api<{ chunks: number }>("documents", { form }), `«${f.name}» добавлен`);
    }
    setBusy(false);
    if (input.current) input.current.value = "";
    reload();
  };

  return (
    <>
      <PageHeader title="Документы" desc="База знаний: ассистент ищет по этим файлам, когда отвечает."
        actions={<>
          <input ref={input} type="file" multiple accept=".txt,.md,.pdf,.csv,.json,.py,.html" hidden onChange={(e) => upload(e.target.files)} />
          <Button variant="primary" onClick={() => input.current?.click()} disabled={busy}>{busy ? "Загружаю…" : "+ Загрузить файл"}</Button>
        </>} />
      <ErrorNote error={error} />
      <Card>
        {data?.documents.length ? <ul>{data.documents.map((d) => <DocRow key={d.id} d={d} onDeleted={reload} />)}</ul>
          : <Empty>Документов нет. Загрузи .txt, .md, .pdf или .csv — здесь или через бота.</Empty>}
      </Card>
    </>
  );
}

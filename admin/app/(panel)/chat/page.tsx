"use client";
import { useEffect, useRef, useState } from "react";
import { act, api, fmtDate } from "@/lib/api";
import { Button, ConfirmButton, Empty, ErrorNote, Input, PageHeader, Tabs, Textarea, cx } from "@/components/ui";

type Msg = { id: number; role: "user" | "model"; content: string; created_at: string; pending?: boolean };

export default function ChatPage() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [hasMore, setHasMore] = useState(true);
  const [text, setText] = useState("");
  const [mode, setMode] = useState<"agent" | "send">("agent");
  const [mirror, setMirror] = useState(true);
  const [busy, setBusy] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  const load = async (before?: number) => {
    try {
      const params = new URLSearchParams({ limit: "60" });
      if (before) params.set("before", String(before));
      if (q) params.set("q", q);
      const d = await api<{ messages: Msg[] }>(`messages?${params}`);
      setHasMore(d.messages.length === 60);
      setMsgs((old) => (before ? [...d.messages, ...old] : d.messages));
      setError(null);
      if (!before) setTimeout(() => bottom.current?.scrollIntoView(), 50);
    } catch (e) { setError((e as Error).message); }
  };

  useEffect(() => {
    const t = setTimeout(() => load(), q ? 300 : 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const submit = async () => {
    const t = text.trim();
    if (!t || busy) return;
    setBusy(true);
    if (mode === "send") {
      if (await act(() => api("send", { body: { text: t } }), "Отправлено в Telegram")) setText("");
      setBusy(false);
      return;
    }
    const now = new Date().toISOString().slice(0, 19).replace("T", " ");
    setMsgs((m) => [...m, { id: -1, role: "user", content: t, created_at: now }, { id: -2, role: "model", content: "Думает…", created_at: now, pending: true }]);
    setText("");
    setTimeout(() => bottom.current?.scrollIntoView({ behavior: "smooth" }), 50);
    const r = await act(() => api<{ reply: string }>("chat", { body: { text: t, mirror } }));
    if (!r) setText(t);
    await load();
    setBusy(false);
  };

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col md:h-[calc(100vh-4rem)]">
      <PageHeader title="Переписка" desc="История диалога с ассистентом. Отсюда можно и написать ему."
        actions={<>
          <Input placeholder="Поиск по сообщениям" value={q} onChange={(e) => setQ(e.target.value)} className="w-56" />
          <ConfirmButton size="md" onConfirm={() => act(() => api("reset", { body: {} }), "Контекст диалога сброшен")}>Сбросить контекст</ConfirmButton>
        </>} />
      <ErrorNote error={error} />

      <div className="scroll-thin flex-1 overflow-y-auto rounded-xl border border-line bg-panel p-4">
        {hasMore && msgs.length > 0 && (
          <div className="mb-4 text-center"><Button size="sm" onClick={() => load(msgs[0].id)}>Загрузить раньше</Button></div>
        )}
        {!msgs.length && <Empty>{q ? "Ничего не найдено" : "Сообщений пока нет"}</Empty>}
        <div className="flex flex-col gap-3">
          {msgs.map((m, i) => (
            <div key={`${m.id}-${i}`} className={cx("flex", m.role === "user" ? "justify-end" : "justify-start")}>
              <div className={cx("max-w-[85%] rounded-2xl px-3.5 py-2 text-sm",
                m.role === "user" ? "rounded-br-md bg-accent text-white" : "rounded-bl-md bg-hover",
                m.pending && "animate-pulse text-muted")}>
                <div className="whitespace-pre-wrap break-words">{m.content}</div>
                <div className={cx("mt-1 text-right text-[10px]", m.role === "user" ? "text-white/70" : "text-muted")}>{fmtDate(m.created_at)}</div>
              </div>
            </div>
          ))}
        </div>
        <div ref={bottom} />
      </div>

      <div className="mt-3 rounded-xl border border-line bg-panel p-3">
        <div className="mb-2 flex flex-wrap items-center gap-3">
          <Tabs value={mode} onChange={setMode} items={[["agent", "Спросить ассистента"], ["send", "Написать от имени бота"]]} />
          {mode === "agent" && (
            <label className="flex items-center gap-1.5 text-xs text-muted">
              <input type="checkbox" checked={mirror} onChange={(e) => setMirror(e.target.checked)} />
              продублировать ответ в Telegram
            </label>
          )}
        </div>
        <div className="flex gap-2">
          <Textarea rows={2} value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
            placeholder={mode === "agent" ? "Сообщение ассистенту (Enter — отправить)" : "Это сообщение придёт тебе в Telegram от бота"} />
          <Button variant="primary" onClick={submit} disabled={busy || !text.trim()} className="h-auto">{busy ? "…" : "Отправить"}</Button>
        </div>
      </div>
    </div>
  );
}

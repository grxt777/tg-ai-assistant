"use client";
import { useEffect, useState } from "react";
import { act, api, fmtDate } from "@/lib/api";
import { Button, ConfirmButton, Empty, ErrorNote, Input, PageHeader, Tabs, cx } from "@/components/ui";
import { haptic } from "@/lib/tg";

type Msg = { id: number; role: "user" | "model"; content: string; created_at: string; pending?: boolean };

const toBottom = (smooth = false) =>
  setTimeout(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: smooth ? "smooth" : "auto" }), 60);

export default function ChatPage() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [search, setSearch] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [text, setText] = useState("");
  const [mode, setMode] = useState<"agent" | "send">("agent");
  const [mirror, setMirror] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = async (before?: number) => {
    try {
      const params = new URLSearchParams({ limit: "60" });
      if (before) params.set("before", String(before));
      if (q) params.set("q", q);
      const d = await api<{ messages: Msg[] }>(`messages?${params}`);
      setHasMore(d.messages.length === 60);
      setMsgs((old) => (before ? [...d.messages, ...old] : d.messages));
      setError(null);
      if (!before) toBottom();
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
    haptic.tap();
    if (mode === "send") {
      if (await act(() => api("send", { body: { text: t } }), "Отправлено в Telegram")) setText("");
      setBusy(false);
      return;
    }
    const now = new Date().toISOString().slice(0, 19).replace("T", " ");
    setMsgs((m) => [...m, { id: -1, role: "user", content: t, created_at: now }, { id: -2, role: "model", content: "Думает…", created_at: now, pending: true }]);
    setText("");
    toBottom(true);
    const r = await act(() => api<{ reply: string }>("chat", { body: { text: t, mirror } }));
    if (!r) setText(t);
    await load();
    setBusy(false);
  };

  return (
    <>
      <PageHeader title="Чат" desc="Диалог с ассистентом. Отсюда можно и написать ему."
        actions={<>
          <Button size="sm" onClick={() => setSearch((s) => !s)}>{search ? "Скрыть поиск" : "Поиск"}</Button>
          <ConfirmButton onConfirm={() => act(() => api("reset", { body: {} }), "Контекст диалога сброшен")}>Сбросить контекст</ConfirmButton>
        </>} />
      {search && <Input autoFocus placeholder="Поиск по сообщениям" value={q} onChange={(e) => setQ(e.target.value)} className="mb-4" />}
      <ErrorNote error={error} />

      {hasMore && msgs.length > 0 && (
        <div className="mb-4 text-center"><Button size="sm" onClick={() => load(msgs[0].id)}>Загрузить раньше</Button></div>
      )}
      {!msgs.length && <Empty>{q ? "Ничего не найдено" : "Сообщений пока нет"}</Empty>}

      <div className="flex flex-col gap-2 pb-4">
        {msgs.map((m, i) => {
          const user = m.role === "user";
          return (
            <div key={`${m.id}-${i}`} className={cx("flex", user ? "justify-end" : "justify-start")}>
              <div className={cx("max-w-[85%] rounded-[22px] px-4 py-2.5 text-[15px] leading-snug md:max-w-[70%]",
                user ? "rounded-br-md bg-accent text-white shadow-lg shadow-accent/25" : "glass rounded-bl-md",
                m.pending && "animate-pulse text-muted")}>
                <div className="relative whitespace-pre-wrap break-words">{m.content}</div>
                <div className={cx("relative mt-1 text-right text-[10px]", user ? "text-white/70" : "text-muted")}>{fmtDate(m.created_at)}</div>
              </div>
            </div>
          );
        })}
      </div>

      {/* поле ввода прилипает к низу; на мобилке — над нижней панелью */}
      <div className="composer sticky z-20 -mx-1 pb-1">
        <div className="glass-strong rounded-[26px] p-2">
          <div className="relative mb-2 flex flex-wrap items-center gap-2 px-1">
            <Tabs value={mode} onChange={setMode} items={[["agent", "Ассистенту"], ["send", "От имени бота"]]} />
            {mode === "agent" && (
              <label className="flex items-center gap-1.5 text-xs text-muted">
                <input type="checkbox" checked={mirror} onChange={(e) => setMirror(e.target.checked)} className="accent-[var(--accent)]" />
                копия в Telegram
              </label>
            )}
          </div>
          <div className="relative flex items-end gap-2">
            <textarea rows={1} value={text} onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !("ontouchstart" in window)) { e.preventDefault(); submit(); } }}
              placeholder={mode === "agent" ? "Сообщение ассистенту" : "Придёт тебе в Telegram от бота"}
              className="max-h-40 min-h-11 flex-1 resize-none rounded-[20px] bg-hover px-4 py-2.5 text-base outline-none placeholder:text-muted md:text-sm"
              style={{ fieldSizing: "content" } as React.CSSProperties} />
            <button onClick={submit} disabled={busy || !text.trim()} aria-label="Отправить"
              className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-accent text-white shadow-lg shadow-accent/30 transition active:scale-90 disabled:opacity-40">
              {busy ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                : <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round"><path d="M12 19V5M5 12l7-7 7 7" /></svg>}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

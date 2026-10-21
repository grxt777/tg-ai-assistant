"use client";
import { useEffect, useState } from "react";
import { Backdrop } from "@/components/shell";
import { Button, Input } from "@/components/ui";
import { haptic, initTelegram, tg } from "@/lib/tg";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [inTg, setInTg] = useState(false);

  // внутри Telegram входим автоматически — по подписанным данным мини-аппа
  useEffect(() => {
    const w = tg();
    if (!w) return;
    setInTg(true);
    initTelegram();
    setBusy(true);
    fetch("/api/login/tg", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ initData: w.initData }) })
      .then(async (r) => {
        if (r.ok) { haptic.ok(); window.location.replace("/"); return; }
        setError((await r.json().catch(() => ({}))).error || "Не удалось войти через Telegram");
        haptic.bad();
        setBusy(false);
      })
      .catch(() => { setError("Нет связи с сервером"); setBusy(false); });
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    const res = await fetch("/api/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ password }) });
    if (res.ok) window.location.href = "/";
    else {
      setError((await res.json().catch(() => ({}))).error || "Ошибка входа");
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen place-items-center px-5">
      <Backdrop />
      <div className="sheet-in glass-strong w-full max-w-sm rounded-[32px] p-7">
        <div className="relative mb-6 flex flex-col items-center text-center">
          <div className="mb-3 grid h-16 w-16 place-items-center rounded-[22px] bg-gradient-to-br from-accent to-fuchsia-500 text-2xl font-bold text-white shadow-xl shadow-accent/40">A</div>
          <div className="text-xl font-bold">Ассистент</div>
          <div className="mt-1 text-sm text-muted">{inTg ? "Входим через Telegram…" : "Панель управления — только для владельца"}</div>
        </div>
        {inTg && busy ? (
          <div className="relative flex justify-center py-2"><div className="h-7 w-7 animate-spin rounded-full border-2 border-accent border-t-transparent" /></div>
        ) : (
          <form onSubmit={submit} className="relative">
            <Input type="password" autoFocus={!inTg} placeholder="Пароль" value={password} onChange={(e) => setPassword(e.target.value)} />
            <Button variant="primary" className="mt-3 w-full" disabled={busy || !password}>{busy ? "Проверяю…" : "Войти"}</Button>
          </form>
        )}
        {error && <div className="relative mt-3 text-center text-sm text-bad">{error}</div>}
      </div>
    </div>
  );
}

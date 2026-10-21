"use client";
import { useState } from "react";
import { Button, Input } from "@/components/ui";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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
    <div className="grid min-h-screen place-items-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-line bg-panel p-6">
        <div className="mb-5 flex items-center gap-2">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-accent font-bold text-white">A</div>
          <div>
            <div className="font-semibold">Админка ассистента</div>
            <div className="text-xs text-muted">Вход только для владельца</div>
          </div>
        </div>
        <Input type="password" autoFocus placeholder="Пароль" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <div className="mt-2 text-sm text-bad">{error}</div>}
        <Button variant="primary" className="mt-4 w-full" disabled={busy || !password}>{busy ? "Проверяю…" : "Войти"}</Button>
      </form>
    </div>
  );
}

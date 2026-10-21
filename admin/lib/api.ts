"use client";
import { useCallback, useEffect, useRef, useState } from "react";
export { act } from "@/components/ui";

export class ApiError extends Error {}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const res = await fetch(`/api/bot/${path}`, {
    method: opts.method || (opts.body || opts.form ? "POST" : "GET"),
    headers: opts.body !== undefined ? { "content-type": "application/json" } : undefined,
    body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
    cache: "no-store",
  });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new ApiError("Сессия истекла");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data?.error) throw new ApiError(data?.error || `HTTP ${res.status}`);
  return data as T;
}

/** Загрузка данных с автообновлением. refreshMs=0 — без автообновления. */
export function useApi<T = any>(path: string | null, refreshMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);

  const reload = useCallback(async () => {
    if (!path) return;
    const my = ++seq.current;
    try {
      const d = await api<T>(path);
      if (my === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (my === seq.current) setError((e as Error).message);
    } finally {
      if (my === seq.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    setLoading(true);
    reload();
    if (!refreshMs) return;
    const t = setInterval(() => document.visibilityState === "visible" && reload(), refreshMs);
    return () => clearInterval(t);
  }, [reload, refreshMs]);

  return { data, error, loading, reload, setData };
}

export function fmtDate(utc?: string | null) {
  if (!utc) return "—";
  const d = new Date(utc.replace(" ", "T") + (utc.endsWith("Z") ? "" : "Z"));
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function fmtBytes(n: number) {
  if (n < 1024) return `${n} Б`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} КБ`;
  return `${(n / 1024 ** 2).toFixed(1)} МБ`;
}

export function fmtUptime(s: number) {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d} д ${h} ч` : h ? `${h} ч ${m} мин` : `${m} мин`;
}

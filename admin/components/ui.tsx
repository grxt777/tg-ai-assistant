"use client";
import { useEffect, useState, type ReactNode, type ButtonHTMLAttributes, type InputHTMLAttributes, type TextareaHTMLAttributes, type SelectHTMLAttributes } from "react";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

export function PageHeader({ title, desc, actions }: { title: string; desc?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {desc && <p className="mt-1 text-sm text-muted">{desc}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ children, className, title, actions }: { children: ReactNode; className?: string; title?: string; actions?: ReactNode }) {
  return (
    <section className={cx("rounded-xl border border-line bg-panel", className)}>
      {(title || actions) && (
        <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-3">
          <h2 className="text-sm font-medium">{title}</h2>
          {actions}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "ok" | "bad" }) {
  return (
    <div className="rounded-xl border border-line bg-panel p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className={cx("mt-1 text-2xl font-semibold tabular-nums", tone === "bad" && "text-bad", tone === "ok" && "text-ok")}>{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger"; size?: "sm" | "md" };
export function Button({ variant = "ghost", size = "md", className, ...p }: BtnProps) {
  return (
    <button
      {...p}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-7 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
        variant === "primary" && "bg-accent text-white hover:opacity-90",
        variant === "ghost" && "border border-line bg-panel hover:bg-hover",
        variant === "danger" && "border border-line bg-panel text-bad hover:bg-bad/10",
        className,
      )}
    />
  );
}

const field = "w-full rounded-lg border border-line bg-bg px-3 text-sm outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20";
export const Input = ({ className, ...p }: InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={cx(field, "h-9", className)} />;
export const Textarea = ({ className, ...p }: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={cx(field, "py-2", className)} />;
export const Select = ({ className, ...p }: SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={cx(field, "h-9", className)} />;

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "ok" | "bad" | "accent" | "warn" }) {
  const tones = {
    neutral: "bg-hover text-muted",
    ok: "bg-ok/15 text-ok",
    bad: "bg-bad/15 text-bad",
    warn: "bg-warn/15 text-warn",
    accent: "bg-accent/15 text-accent",
  };
  return <span className={cx("inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-medium", tones[tone])}>{children}</span>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-10 text-center text-sm text-muted">{children}</div>;
}

export function ErrorNote({ error }: { error?: string | null }) {
  if (!error) return null;
  return <div className="mb-4 rounded-lg border border-bad/30 bg-bad/10 px-3 py-2 text-sm text-bad">{error}</div>;
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: [T, string][] }) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-panel p-0.5">
      {items.map(([v, label]) => (
        <button key={v} onClick={() => onChange(v)}
          className={cx("rounded-md px-3 py-1 text-sm transition", value === v ? "bg-hover font-medium" : "text-muted hover:text-fg")}>
          {label}
        </button>
      ))}
    </div>
  );
}

// ---- тосты ----
type Toast = { id: number; text: string; bad?: boolean };
let push: ((t: Omit<Toast, "id">) => void) | null = null;
export const toast = (text: string, bad = false) => push?.({ text, bad });

export function Toaster() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => {
    push = (t) => {
      const id = Date.now() + Math.random();
      setItems((x) => [...x, { ...t, id }]);
      setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 3500);
    };
    return () => { push = null; };
  }, []);
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {items.map((t) => (
        <div key={t.id} className={cx("rounded-lg border px-3 py-2 text-sm shadow-lg", t.bad ? "border-bad/30 bg-panel text-bad" : "border-line bg-panel")}>
          {t.text}
        </div>
      ))}
    </div>
  );
}

/** Обёртка для действий: ловит ошибку и показывает тост. */
export async function act<T>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> {
  try {
    const r = await fn();
    if (ok) toast(ok);
    return r;
  } catch (e) {
    toast((e as Error).message, true);
  }
}

/** Кнопка удаления с подтверждением вторым кликом (без системных диалогов). */
export function ConfirmButton({ onConfirm, children = "Удалить", size = "sm" }: { onConfirm: () => void; children?: ReactNode; size?: "sm" | "md" }) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(t);
  }, [armed]);
  return (
    <Button variant="danger" size={size} onClick={() => (armed ? (setArmed(false), onConfirm()) : setArmed(true))}>
      {armed ? "Точно?" : children}
    </Button>
  );
}

"use client";
import { haptic } from "@/lib/tg";
import { useEffect, useState, type ReactNode, type ButtonHTMLAttributes, type InputHTMLAttributes, type TextareaHTMLAttributes, type SelectHTMLAttributes } from "react";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

export function PageHeader({ title, desc, actions }: { title: string; desc?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3 md:mb-6">
      <div>
        <h1 className="text-[32px] font-bold leading-tight tracking-tight md:text-3xl">{title}</h1>
        {desc && <p className="mt-1 text-sm text-muted">{desc}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ children, className, title, actions }: { children: ReactNode; className?: string; title?: string; actions?: ReactNode }) {
  return (
    <section className={cx("glass rounded-[24px]", className)}>
      {(title || actions) && (
        <div className="relative flex items-center justify-between gap-2 px-4 pb-1 pt-4">
          <h2 className="text-[15px] font-semibold">{title}</h2>
          {actions}
        </div>
      )}
      <div className="relative p-4">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "ok" | "bad" }) {
  return (
    <div className="glass rounded-[22px] p-4">
      <div className="relative text-xs text-muted">{label}</div>
      <div className={cx("relative mt-1 truncate text-2xl font-semibold tabular-nums", tone === "bad" && "text-bad", tone === "ok" && "text-ok")}>{value}</div>
      {hint && <div className="relative mt-1 truncate text-xs text-muted">{hint}</div>}
    </div>
  );
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger"; size?: "sm" | "md" };
export function Button({ variant = "ghost", size = "md", className, ...p }: BtnProps) {
  return (
    <button
      {...p}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-full font-medium transition active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-xs" : "h-10 px-4 text-sm",
        variant === "primary" && "bg-accent text-white shadow-lg shadow-accent/30 hover:brightness-110",
        variant === "ghost" && "bg-hover hover:bg-line",
        variant === "danger" && "bg-bad/10 text-bad hover:bg-bad/15",
        className,
      )}
    />
  );
}

// 16px на мобилке — чтобы iOS не зумил страницу при фокусе
const field = "w-full rounded-2xl border border-line bg-hover px-3.5 text-base outline-none transition placeholder:text-muted focus:border-accent focus:bg-panel focus:ring-4 focus:ring-accent/15 md:text-sm";
export const Input = ({ className, ...p }: InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={cx(field, "h-11 md:h-10", className)} />;
export const Textarea = ({ className, ...p }: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={cx(field, "py-2.5", className)} />;
export const Select = ({ className, ...p }: SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={cx(field, "h-11 md:h-10", className)} />;

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "ok" | "bad" | "accent" | "warn" }) {
  const tones = {
    neutral: "bg-hover text-muted",
    ok: "bg-ok/15 text-ok",
    bad: "bg-bad/15 text-bad",
    warn: "bg-warn/15 text-warn",
    accent: "bg-accent/15 text-accent",
  };
  return <span className={cx("inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium", tones[tone])}>{children}</span>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-10 text-center text-sm text-muted">{children}</div>;
}

export function ErrorNote({ error }: { error?: string | null }) {
  if (!error) return null;
  return <div className="mb-4 rounded-2xl bg-bad/10 px-4 py-3 text-sm text-bad">{error}</div>;
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: [T, string][] }) {
  return (
    <div className="glass scroll-thin inline-flex max-w-full overflow-x-auto rounded-full p-1">
      {items.map(([v, label]) => (
        <button key={v} onClick={() => { haptic.select(); onChange(v); }}
          className={cx("relative whitespace-nowrap rounded-full px-3.5 py-1.5 text-sm transition",
            value === v ? "bg-accent font-medium text-white shadow-md shadow-accent/30" : "text-muted hover:text-fg")}>
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
    <div className="pointer-events-none fixed inset-x-4 z-50 mx-auto flex max-w-sm flex-col items-center gap-2 md:inset-x-auto md:right-6 md:items-end"
      style={{ top: "calc(var(--safe-top) + 12px)" }}>
      {items.map((t) => (
        <div key={t.id} className={cx("sheet-in glass-strong rounded-full px-4 py-2.5 text-sm font-medium", t.bad && "text-bad")}>
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
    if (ok) { toast(ok); haptic.ok(); }
    return r;
  } catch (e) {
    toast((e as Error).message, true);
    haptic.bad();
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
    <Button variant="danger" size={size} onClick={() => { haptic.tap(armed ? "medium" : "light"); if (armed) { setArmed(false); onConfirm(); } else setArmed(true); }}>
      {armed ? "Точно?" : children}
    </Button>
  );
}

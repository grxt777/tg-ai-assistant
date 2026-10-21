"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { cx } from "./ui";

const NAV: [string, string, string][] = [
  ["/", "Обзор", "M3 12l9-9 9 9M5 10v10h14V10"],
  ["/chat", "Переписка", "M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-6.4A8 8 0 1 1 21 12z"],
  ["/memory", "Память", "M12 3a6 6 0 0 0-6 6c0 2.4 1.4 3.6 2 5h8c.6-1.4 2-2.6 2-5a6 6 0 0 0-6-6zM9 18h6M10 21h4"],
  ["/tables", "Таблицы", "M3 5h18v14H3zM3 10h18M9 5v14"],
  ["/docs", "Документы", "M7 3h7l5 5v13H7zM14 3v5h5"],
  ["/reminders", "Напоминания", "M12 8v4l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z"],
  ["/events", "Журнал", "M4 6h16M4 12h16M4 18h10"],
  ["/settings", "Настройки", "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"],
];

export function Icon({ d, className }: { d: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className={cx("h-4 w-4 shrink-0", className)}>
      <path d={d} />
    </svg>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<string>("auto");
  useEffect(() => {
    try { setTheme(localStorage.getItem("theme") || "auto"); } catch {}
  }, []);
  const next = () => {
    const t = theme === "auto" ? "dark" : theme === "dark" ? "light" : "auto";
    setTheme(t);
    try { t === "auto" ? localStorage.removeItem("theme") : localStorage.setItem("theme", t); } catch {}
    if (t === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = t;
  };
  return (
    <button onClick={next} className="w-full rounded-lg px-3 py-2 text-left text-sm text-muted hover:bg-hover hover:text-fg">
      Тема: {theme === "auto" ? "как в системе" : theme === "dark" ? "тёмная" : "светлая"}
    </button>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [path]);

  const logout = async () => {
    await fetch("/api/logout", { method: "POST" });
    window.location.href = "/login";
  };

  const nav = (
    <nav className="flex h-full flex-col gap-1 p-3">
      <div className="mb-4 flex items-center gap-2 px-3 pt-2">
        <div className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-sm font-bold text-white">A</div>
        <div className="text-sm font-semibold">Ассистент</div>
      </div>
      {NAV.map(([href, label, d]) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link key={href} href={href}
            className={cx("flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition",
              active ? "bg-hover font-medium text-fg" : "text-muted hover:bg-hover hover:text-fg")}>
            <Icon d={d} />{label}
          </Link>
        );
      })}
      <div className="mt-auto flex flex-col gap-1 border-t border-line pt-3">
        <ThemeToggle />
        <button onClick={logout} className="rounded-lg px-3 py-2 text-left text-sm text-muted hover:bg-hover hover:text-fg">Выйти</button>
      </div>
    </nav>
  );

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 border-r border-line bg-panel md:block">{nav}</aside>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setOpen(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <aside className="absolute left-0 top-0 h-full w-60 border-r border-line bg-panel" onClick={(e) => e.stopPropagation()}>{nav}</aside>
        </div>
      )}
      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-panel/90 px-4 py-3 backdrop-blur md:hidden">
          <button onClick={() => setOpen(true)} aria-label="Меню" className="rounded-lg p-1.5 hover:bg-hover">
            <Icon d="M4 6h16M4 12h16M4 18h16" className="h-5 w-5" />
          </button>
          <span className="text-sm font-semibold">Ассистент</span>
        </header>
        <main className="mx-auto w-full max-w-6xl px-4 py-6 md:px-8 md:py-8">{children}</main>
      </div>
    </div>
  );
}

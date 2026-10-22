"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { haptic, initTelegram, isTelegram } from "@/lib/tg";
import { cx } from "./ui";

const I = {
  home: "M3 11.5 12 4l9 7.5M5.5 9.5V20h13V9.5",
  chat: "M20 11.5a7.5 7.5 0 0 1-10.9 6.7L4 19.5l1.4-4.6A7.5 7.5 0 1 1 20 11.5z",
  memory: "M12 3.5a5.5 5.5 0 0 0-3.2 10c.6.5 1.2 1.3 1.2 2.2v.8h4v-.8c0-.9.6-1.7 1.2-2.2A5.5 5.5 0 0 0 12 3.5zM10 20h4",
  journal: "M6 3.5h11.5v17H6a1.5 1.5 0 0 1-1.5-1.5V5A1.5 1.5 0 0 1 6 3.5zM9 8h5.5M9 11.5h5.5M8 3.5v17",
  bell: "M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15zM10 20.5a2 2 0 0 0 4 0",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  tables: "M4 5h16v14H4zM4 10h16M10 5v14",
  docs: "M7 3.5h7l4.5 4.5v12.5H7zM14 3.5V8h4.5",
  events: "M4 6h16M4 12h16M4 18h10",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM4 12h2M18 12h2M12 4v2M12 18v2M6.3 6.3l1.4 1.4M16.3 16.3l1.4 1.4M6.3 17.7l1.4-1.4M16.3 7.7l1.4-1.4",
  moon: "M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z",
  logout: "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10",
};

export function Icon({ d, className, strokeWidth = 1.9 }: { d: string; className?: string; strokeWidth?: number }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={cx("h-5 w-5 shrink-0", className)}>
      <path d={d} />
    </svg>
  );
}

const TABS = [
  { href: "/", label: "Обзор", icon: I.home },
  { href: "/chat", label: "Чат", icon: I.chat },
  { href: "/journal", label: "Дневник", icon: I.journal },
  { href: "/reminders", label: "Время", icon: I.bell },
  { href: "#more", label: "Ещё", icon: I.more },
];
const MORE = [
  { href: "/memory", label: "Память", icon: I.memory },
  { href: "/tables", label: "Таблицы", icon: I.tables },
  { href: "/docs", label: "Документы", icon: I.docs },
  { href: "/events", label: "Логи", icon: I.events },
  { href: "/settings", label: "Настройки", icon: I.settings },
];
const SIDEBAR = [...TABS.slice(0, 2), TABS[2], { ...TABS[3], label: "Напоминания" }, ...MORE];

function tabIndex(path: string) {
  if (MORE.some((m) => path.startsWith(m.href))) return 4;
  const i = TABS.findIndex((t) => (t.href === "/" ? path === "/" : path.startsWith(t.href)));
  return i < 0 ? 0 : i;
}

// ---------- тема ----------
function useTheme() {
  const [theme, setTheme] = useState("auto");
  useEffect(() => { try { setTheme(localStorage.getItem("theme") || "auto"); } catch {} }, []);
  const cycle = () => {
    const t = theme === "auto" ? "dark" : theme === "dark" ? "light" : "auto";
    setTheme(t);
    try { t === "auto" ? localStorage.removeItem("theme") : localStorage.setItem("theme", t); } catch {}
    if (t === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = t;
  };
  const label = theme === "auto" ? "Авто" : theme === "dark" ? "Тёмная" : "Светлая";
  return { cycle, label };
}

async function logout() {
  await fetch("/api/logout", { method: "POST" });
  window.location.href = "/login";
}

// ---------- нижняя панель с линзой ----------
const PAD = 6; // внутренний отступ панели

function TabBar({ active, onSelect, hidden }: { active: number; onSelect: (i: number) => void; hidden: boolean }) {
  const bar = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  const [x, setX] = useState<number | null>(null); // центр линзы во время перетаскивания
  const [stretch, setStretch] = useState(1);
  const drag = useRef({ id: -1, startX: 0, moved: false, lastX: 0, lastT: 0, idx: active });

  useLayoutEffect(() => {
    const el = bar.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const itemW = Math.max(1, (w - PAD * 2) / TABS.length);
  const center = (i: number) => PAD + itemW * i + itemW / 2;
  const nearest = (px: number) => Math.max(0, Math.min(TABS.length - 1, Math.floor((px - PAD) / itemW)));
  const clamp = (px: number) => Math.max(center(0) - itemW * 0.15, Math.min(center(TABS.length - 1) + itemW * 0.15, px));
  const localX = (e: React.PointerEvent) => e.clientX - (bar.current?.getBoundingClientRect().left || 0);

  const dragging = x !== null;
  const lensX = dragging ? x : center(active);

  const down = (e: React.PointerEvent) => {
    const lx = localX(e);
    drag.current = { id: e.pointerId, startX: lx, moved: false, lastX: lx, lastT: performance.now(), idx: active };
    bar.current?.setPointerCapture(e.pointerId);
  };

  const move = (e: React.PointerEvent) => {
    const d = drag.current;
    if (d.id !== e.pointerId) return;
    const lx = localX(e);
    if (!d.moved && Math.abs(lx - d.startX) < 6) return;
    d.moved = true;
    const now = performance.now();
    const v = (lx - d.lastX) / Math.max(1, now - d.lastT); // px/ms
    d.lastX = lx; d.lastT = now;
    setStretch(1 + Math.min(Math.abs(v) * 0.12, 0.32));
    setX(clamp(lx));
    const idx = nearest(lx);
    if (idx !== d.idx) { d.idx = idx; haptic.select(); }
  };

  const up = (e: React.PointerEvent) => {
    const d = drag.current;
    if (d.id !== e.pointerId) return;
    d.id = -1;
    const idx = nearest(d.moved ? (x ?? d.startX) : d.startX);
    setX(null);
    setStretch(1);
    if (!d.moved) haptic.tap("light");
    onSelect(idx);
  };

  const lensW = itemW - 2;
  return (
    <div
      className={cx("fixed inset-x-0 z-40 mx-auto max-w-md px-4 transition-all duration-300 md:hidden",
        hidden ? "pointer-events-none translate-y-6 opacity-0" : "opacity-100")}
      style={{ bottom: "calc(var(--safe-bottom) + 10px)" }}
    >
      <div
        ref={bar}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={up}
        className="glass-strong relative h-[66px] touch-none select-none rounded-full"
        role="tablist"
      >
        {w > 0 && (
          <div
            className="lens absolute top-[5px] h-[56px] rounded-full"
            style={{
              width: lensW,
              transform: `translateX(${lensX - lensW / 2}px) scale(${dragging ? 1.12 * stretch : 1}, ${dragging ? 1.12 / Math.sqrt(stretch) : 1})`,
              transition: dragging
                ? "transform 90ms cubic-bezier(.2,.8,.2,1)"
                : "transform 560ms cubic-bezier(.34,1.56,.64,1)",
            }}
          />
        )}
        <div className="relative flex h-full px-[6px]">
          {TABS.map((t, i) => {
            const dist = Math.abs(lensX - center(i));
            const under = dist < itemW / 2;
            const mag = dragging ? 1 + 0.3 * Math.max(0, 1 - dist / itemW) : 1;
            return (
              <div key={t.href} role="tab" aria-selected={i === active}
                className={cx("flex flex-1 flex-col items-center justify-center gap-0.5 transition-colors duration-200",
                  under ? "text-accent" : "text-muted")}>
                <div style={{ transform: `scale(${mag})`, transition: dragging ? "transform 80ms" : "transform 400ms cubic-bezier(.34,1.56,.64,1)" }}
                  className="flex flex-col items-center gap-0.5">
                  <Icon d={t.icon} className="h-[22px] w-[22px]" strokeWidth={under ? 2.2 : 1.9} />
                  <span className={cx("text-[10px] leading-none", under ? "font-semibold" : "font-medium")}>{t.label}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function MoreSheet({ open, onClose, path }: { open: boolean; onClose: () => void; path: string }) {
  const theme = useTheme();
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-30 md:hidden" onClick={onClose}>
      <div className="absolute inset-0 bg-black/20" />
      <div className="sheet-in glass-strong absolute inset-x-4 z-10 mx-auto max-w-md rounded-[28px] p-3"
        style={{ bottom: "calc(var(--safe-bottom) + 88px)" }} onClick={(e) => e.stopPropagation()}>
        <div className="grid grid-cols-2 gap-2">
          {MORE.map((m) => (
            <Link key={m.href} href={m.href} onClick={() => haptic.tap()}
              className={cx("flex items-center gap-3 rounded-2xl px-4 py-3.5 text-sm font-medium transition active:scale-95",
                path.startsWith(m.href) ? "bg-accent text-white" : "bg-hover")}>
              <Icon d={m.icon} />{m.label}
            </Link>
          ))}
        </div>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <button onClick={() => { haptic.select(); theme.cycle(); }} className="flex items-center gap-3 rounded-2xl bg-hover px-4 py-3 text-sm active:scale-95">
            <Icon d={I.moon} />Тема: {theme.label}
          </button>
          {!isTelegram() && (
            <button onClick={logout} className="flex items-center gap-3 rounded-2xl bg-hover px-4 py-3 text-sm text-bad active:scale-95">
              <Icon d={I.logout} />Выйти
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Sidebar({ path }: { path: string }) {
  const theme = useTheme();
  return (
    <aside className="sticky top-0 hidden h-screen w-64 shrink-0 p-3 md:block">
      <nav className="glass flex h-full flex-col gap-1 rounded-[28px] p-3">
        <div className="mb-4 flex items-center gap-2.5 px-3 pt-2">
          <div className="grid h-9 w-9 place-items-center rounded-2xl bg-gradient-to-br from-accent to-fuchsia-500 text-sm font-bold text-white shadow-lg shadow-accent/30">A</div>
          <div>
            <div className="text-sm font-semibold">Ассистент</div>
            <div className="text-[11px] text-muted">панель управления</div>
          </div>
        </div>
        {SIDEBAR.map((n) => {
          const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
          return (
            <Link key={n.href} href={n.href}
              className={cx("flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm transition",
                active ? "bg-accent text-white shadow-lg shadow-accent/25" : "text-muted hover:bg-hover hover:text-fg")}>
              <Icon d={n.icon} className="h-[18px] w-[18px]" />{n.label}
            </Link>
          );
        })}
        <div className="mt-auto flex flex-col gap-1 pt-3">
          <button onClick={theme.cycle} className="flex items-center gap-3 rounded-2xl px-3 py-2.5 text-left text-sm text-muted hover:bg-hover hover:text-fg">
            <Icon d={I.moon} className="h-[18px] w-[18px]" />Тема: {theme.label}
          </button>
          <button onClick={logout} className="flex items-center gap-3 rounded-2xl px-3 py-2.5 text-left text-sm text-muted hover:bg-hover hover:text-fg">
            <Icon d={I.logout} className="h-[18px] w-[18px]" />Выйти
          </button>
        </div>
      </nav>
    </aside>
  );
}

export function Backdrop() {
  return <div className="backdrop" aria-hidden><i /><i /><i /><i /></div>;
}

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [sheet, setSheet] = useState(false);
  const [typing, setTyping] = useState(false);
  const [pending, setPending] = useState<number | null>(null);

  useEffect(() => { initTelegram(); }, []);
  useEffect(() => { setSheet(false); setPending(null); }, [path]);
  useEffect(() => { document.documentElement.dataset.typing = typing ? "1" : ""; }, [typing]);

  // прячем панель, когда открыта клавиатура
  useEffect(() => {
    const isField = (el: EventTarget | null) => el instanceof HTMLElement && el.matches("input:not([type=checkbox]):not([type=range]), textarea, select");
    const onIn = (e: FocusEvent) => isField(e.target) && setTyping(true);
    const onOut = () => setTimeout(() => setTyping(isField(document.activeElement)), 50);
    document.addEventListener("focusin", onIn);
    document.addEventListener("focusout", onOut);
    return () => { document.removeEventListener("focusin", onIn); document.removeEventListener("focusout", onOut); };
  }, []);

  const select = useCallback((i: number) => {
    const t = TABS[i];
    if (t.href === "#more") { setSheet((s) => !s); setPending(null); return; }
    setSheet(false);
    setPending(i);
    if (t.href !== path) router.push(t.href);
  }, [path, router]);

  const active = sheet ? 4 : pending ?? tabIndex(path);

  return (
    <div className="flex min-h-screen">
      <Backdrop />
      <Sidebar path={path} />
      <div className="min-w-0 flex-1">
        <main key={path} className="page-in mx-auto w-full max-w-6xl px-4 md:px-8 md:py-8"
          style={{ paddingTop: "calc(var(--safe-top) + 20px)", paddingBottom: "calc(var(--safe-bottom) + 110px)" }}>
          {children}
        </main>
      </div>
      <div className="edge-top" aria-hidden />
      <div className="edge-bottom" aria-hidden />
      <MoreSheet open={sheet} onClose={() => setSheet(false)} path={path} />
      <TabBar active={active} onSelect={select} hidden={typing} />
    </div>
  );
}

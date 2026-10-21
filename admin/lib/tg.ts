"use client";
// Тонкая обёртка над Telegram WebApp SDK. Вне Telegram всё молча ничего не делает.

type TgWebApp = {
  initData: string;
  version: string;
  platform: string;
  colorScheme: "light" | "dark";
  isVersionAtLeast(v: string): boolean;
  ready(): void;
  expand(): void;
  requestFullscreen?: () => void;
  disableVerticalSwipes?: () => void;
  setHeaderColor?: (c: string) => void;
  setBackgroundColor?: (c: string) => void;
  setBottomBarColor?: (c: string) => void;
  onEvent(e: string, cb: () => void): void;
  HapticFeedback?: {
    selectionChanged(): void;
    impactOccurred(s: "light" | "medium" | "heavy" | "rigid" | "soft"): void;
    notificationOccurred(t: "error" | "success" | "warning"): void;
  };
  BackButton?: { show(): void; hide(): void; onClick(cb: () => void): void; offClick(cb: () => void): void };
};

export function tg(): TgWebApp | null {
  if (typeof window === "undefined") return null;
  const w = (window as unknown as { Telegram?: { WebApp?: TgWebApp } }).Telegram?.WebApp;
  return w && w.initData ? w : null;
}

export const isTelegram = () => !!tg();

export const haptic = {
  select: () => tg()?.HapticFeedback?.selectionChanged(),
  tap: (s: "light" | "medium" | "soft" = "light") => tg()?.HapticFeedback?.impactOccurred(s),
  ok: () => tg()?.HapticFeedback?.notificationOccurred("success"),
  bad: () => tg()?.HapticFeedback?.notificationOccurred("error"),
};

/** Разворачивает мини-апп, синхронизирует тему с Telegram. */
export function initTelegram() {
  const w = tg();
  if (!w) return;
  document.documentElement.dataset.tg = "1";
  const apply = () => {
    document.documentElement.dataset.theme = w.colorScheme;
    const bg = w.colorScheme === "dark" ? "#07070c" : "#eef0f7";
    try { w.setHeaderColor?.(bg); w.setBackgroundColor?.(bg); w.setBottomBarColor?.(bg); } catch {}
  };
  w.ready();
  w.expand();
  apply();
  w.onEvent("themeChanged", apply);
  if (w.isVersionAtLeast("7.7")) w.disableVerticalSwipes?.();
  // на телефонах — во весь экран, как настоящее приложение
  if (w.isVersionAtLeast("8.0") && ["ios", "android"].includes(w.platform)) {
    try { w.requestFullscreen?.(); } catch {}
  }
}

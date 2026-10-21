// Вход из Telegram Mini App: подпись initData проверяет бот (у него токен), здесь только выдаём сессию.
import { setSessionCookie } from "@/lib/cookie";

export async function POST(req: Request) {
  const { initData } = await req.json().catch(() => ({ initData: "" }));
  if (!initData) return Response.json({ error: "нет данных Telegram" }, { status: 400 });
  const base = (process.env.BOT_API_URL || "").replace(/\/$/, "");
  try {
    const res = await fetch(`${base}/api/tg-verify`, {
      method: "POST", cache: "no-store",
      headers: { Authorization: `Bearer ${process.env.ADMIN_API_TOKEN}`, "content-type": "application/json" },
      body: JSON.stringify({ initData }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) return Response.json({ error: data.error || "вход не удался" }, { status: 403 });
    await setSessionCookie();
    return Response.json({ ok: true, user: data.user });
  } catch (e) {
    return Response.json({ error: `Бот недоступен: ${(e as Error).message}` }, { status: 502 });
  }
}

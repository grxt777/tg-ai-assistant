// Прокси к API бота на Fly: токен живёт только на сервере, в браузер не попадает.
import type { NextRequest } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";

export const maxDuration = 120; // ответ ассистента может идти долго

async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  if (!(await verifySession(req.cookies.get(SESSION_COOKIE)?.value))) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const { path } = await ctx.params;
  const base = (process.env.BOT_API_URL || "").replace(/\/$/, "");
  const url = `${base}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers: Record<string, string> = { Authorization: `Bearer ${process.env.ADMIN_API_TOKEN}` };
  const ct = req.headers.get("content-type");
  if (ct) headers["content-type"] = ct;
  const hasBody = !["GET", "HEAD"].includes(req.method);
  try {
    const res = await fetch(url, {
      method: req.method, headers, cache: "no-store",
      body: hasBody ? await req.arrayBuffer() : undefined,
    });
    return new Response(res.body, {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") || "application/json" },
    });
  } catch (e) {
    return Response.json({ error: `Бот недоступен: ${(e as Error).message}` }, { status: 502 });
  }
}

export { forward as GET, forward as POST, forward as PUT, forward as PATCH, forward as DELETE };

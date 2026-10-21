import { cookies } from "next/headers";
import { SESSION_COOKIE, checkPassword, createSession } from "@/lib/auth";

export async function POST(req: Request) {
  const { password } = await req.json().catch(() => ({ password: "" }));
  if (!checkPassword(String(password || ""))) {
    await new Promise((r) => setTimeout(r, 800)); // притормаживаем перебор
    return Response.json({ error: "Неверный пароль" }, { status: 401 });
  }
  const s = await createSession();
  (await cookies()).set(SESSION_COOKIE, s.value, {
    httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/", maxAge: s.maxAge,
  });
  return Response.json({ ok: true });
}

import { checkPassword } from "@/lib/auth";
import { setSessionCookie } from "@/lib/cookie";

export async function POST(req: Request) {
  const { password } = await req.json().catch(() => ({ password: "" }));
  if (!checkPassword(String(password || ""))) {
    await new Promise((r) => setTimeout(r, 800)); // притормаживаем перебор
    return Response.json({ error: "Неверный пароль" }, { status: 401 });
  }
  await setSessionCookie();
  return Response.json({ ok: true });
}

import { cookies } from "next/headers";
import { SESSION_COOKIE, createSession } from "./auth";

/** Ставит cookie сессии. SameSite=None + Partitioned — чтобы работало и внутри Telegram Web (iframe). */
export async function setSessionCookie() {
  const s = await createSession();
  const prod = process.env.NODE_ENV === "production";
  (await cookies()).set(SESSION_COOKIE, s.value, {
    httpOnly: true, path: "/", maxAge: s.maxAge,
    ...(prod ? { secure: true, sameSite: "none" as const, partitioned: true } : { sameSite: "lax" as const }),
  });
}

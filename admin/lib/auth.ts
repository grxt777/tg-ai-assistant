// Сессия: "<expires>.<hmac>" в httpOnly-cookie. Web Crypto — работает и в proxy, и в route handlers.
export const SESSION_COOKIE = "admin_session";
const DAYS = 30;

async function sign(value: string) {
  const secret = process.env.SESSION_SECRET || "";
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value));
  return Buffer.from(sig).toString("base64url");
}

function safeEqual(a: string, b: string) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function createSession() {
  const exp = String(Date.now() + DAYS * 864e5);
  return { value: `${exp}.${await sign(exp)}`, maxAge: DAYS * 86400 };
}

export async function verifySession(value?: string) {
  if (!value || !process.env.SESSION_SECRET) return false;
  const [exp, sig] = value.split(".");
  if (!exp || !sig || Number(exp) < Date.now()) return false;
  return safeEqual(sig, await sign(exp));
}

export function checkPassword(input: string) {
  const real = process.env.ADMIN_PASSWORD || "";
  return real.length > 0 && safeEqual(input, real);
}

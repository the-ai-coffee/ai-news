// Accès privé par authentification HTTP Basic (Vercel Routing Middleware, sans dépendance).
// Variables d'environnement Vercel : SITE_PASSWORD (obligatoire), SITE_USER (défaut : "lecteur").
// Sans SITE_PASSWORD, le site reste fermé (fail closed).

export const config = { matcher: "/(.*)" };

const REALM = 'Basic realm="Le Releve", charset="UTF-8"';

function safeEqual(a, b) {
  const enc = new TextEncoder();
  const x = enc.encode(a);
  const y = enc.encode(b);
  let diff = x.length ^ y.length;
  const len = Math.max(x.length, y.length);
  for (let i = 0; i < len; i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

function decodeBasic(header) {
  if (!header || !header.startsWith("Basic ")) return null;
  try {
    const bytes = Uint8Array.from(atob(header.slice(6).trim()), (c) => c.charCodeAt(0));
    const decoded = new TextDecoder().decode(bytes);
    const sep = decoded.indexOf(":");
    return sep < 0 ? null : { user: decoded.slice(0, sep), pass: decoded.slice(sep + 1) };
  } catch {
    return null;
  }
}

export default function middleware(request) {
  const password = process.env.SITE_PASSWORD;
  if (!password) {
    return new Response("Site non configuré.", { status: 503 });
  }
  const expectedUser = process.env.SITE_USER || "lecteur";
  const creds = decodeBasic(request.headers.get("authorization"));
  if (creds !== null) {
    // Les deux comparaisons sont toujours évaluées (temps constant).
    const userOk = safeEqual(creds.user, expectedUser);
    const passOk = safeEqual(creds.pass, password);
    if (userOk && passOk) return; // la requête continue vers le fichier statique
  }
  return new Response("Authentification requise.", {
    status: 401,
    headers: { "WWW-Authenticate": REALM, "Cache-Control": "no-store" },
  });
}

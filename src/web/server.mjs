import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { resolve, extname } from "node:path";
import { pathToFileURL } from "node:url";

export function publicConfig(env) {
  const config = { tenantId: env.INNEXQ_WEB_TENANT_ID, clientId: env.INNEXQ_WEB_CLIENT_ID, apiOrigin: env.INNEXQ_WEB_API_ORIGIN, apiScope: env.INNEXQ_WEB_API_SCOPE };
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const api = new URL(config.apiOrigin);
  if (!uuid.test(config.tenantId) || !uuid.test(config.clientId) || api.protocol !== "https:" || api.origin !== config.apiOrigin || !api.hostname.endsWith(".azurecontainerapps.io") || !/^api:\/\/[0-9a-fA-F-]{36}\/(Runs\.Read|Certificates\.Request)$/.test(config.apiScope)) throw new Error("Invalid web configuration");
  return config;
}

export function appServer(config, root = resolve(import.meta.dirname, "dist")) {
  const mime = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml" };
  return createServer(async (req, res) => {
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Referrer-Policy", "no-referrer");
    res.setHeader("Strict-Transport-Security", "max-age=31536000");
    res.setHeader("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
    res.setHeader("Content-Security-Policy", `default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' ${config.apiOrigin} https://login.microsoftonline.com; frame-src 'self' https://login.microsoftonline.com; frame-ancestors 'self'; base-uri 'none'; form-action 'none'; object-src 'none'`);
    if (!["GET", "HEAD"].includes(req.method)) { res.writeHead(405, { Allow: "GET, HEAD" }); res.end(); return; }
    const path = new URL(req.url, "http://localhost").pathname;
    if (path !== "/redirect.html") res.setHeader("Cross-Origin-Opener-Policy", "same-origin");
    if (path === "/config.json" || path === "/health/live") {
      res.setHeader("Content-Type", "application/json");
      res.end(req.method === "HEAD" ? undefined : JSON.stringify(path === "/config.json" ? config : { status: "ok" })); return;
    }
    const file = path === "/" ? "index.html" : path === "/redirect.html" ? "redirect.html" : /^\/assets\/[A-Za-z0-9_.-]+$/.test(path) ? path.slice(1) : null;
    if (!file) { res.writeHead(404); res.end(); return; }
    try {
      const body = await readFile(resolve(root, file));
      res.setHeader("Content-Type", mime[extname(file)] || "application/octet-stream");
      res.end(req.method === "HEAD" ? undefined : body);
    } catch { res.writeHead(404); res.end(); }
  });
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const config = publicConfig(process.env);
  appServer(config).listen(Number(process.env.PORT || 8080), "0.0.0.0", () => console.log("InnexQ static web server ready"));
}

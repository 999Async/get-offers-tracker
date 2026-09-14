import type { Plugin } from "vite";

// Development only. The hosted worker never includes this local-account adapter.
export function localCodex(): Plugin {
  return {
    name: "getoffers-local-codex",
    apply: "serve",
    configureServer(server) {
      if (process.env.GETOFFERS_LOCAL_CODEX !== "1") return;
      const token = process.env.AGENT_ASSISTANT_TOKEN;
      if (!token || token.length < 32) throw new Error("Local assistant token missing");
      const assistantPort = Number(process.env.GETOFFERS_LOCAL_ASSISTANT_PORT || 8780);
      if (!Number.isInteger(assistantPort) || assistantPort < 1024 || assistantPort > 65535) throw new Error("Invalid local assistant port");
      const assistantOrigin = `http://127.0.0.1:${assistantPort}`;
      const endpoint = `${assistantOrigin}/assistant/local`;
      const call = async (body: object, target = endpoint) => {
        const response = await fetch(target, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(body), signal: AbortSignal.timeout(30000) });
        const value = await response.json() as Record<string, unknown>;
        return { response, value };
      };
      server.middlewares.use(async (req, res, next) => {
        // Never accept identity claimed by a browser on the local development server.
        for (const name of Object.keys(req.headers)) if (name.startsWith("oai-authenticated-")) delete req.headers[name];
        req.rawHeaders = req.rawHeaders.flatMap((value, index, headers) => index % 2 === 0 && !value.toLowerCase().startsWith("oai-authenticated-") ? [value, headers[index + 1]] : []);
        if (!["127.0.0.1", "::1", "::ffff:127.0.0.1"].includes(req.socket.remoteAddress || "")) { res.writeHead(403); res.end(); return; }
        const address = server.httpServer?.address();
        const port = typeof address === "object" && address ? address.port : server.config.server.port;
        const allowedHosts = [`localhost:${port}`, `127.0.0.1:${port}`, `[::1]:${port}`];
        if (!allowedHosts.includes(req.headers.host || "")) { res.writeHead(403); res.end(); return; }
        const origin = `http://${req.headers.host}`;
        if (req.method !== "GET" && req.method !== "HEAD" && req.headers.origin !== origin) { res.writeHead(403); res.end(); return; }
        const session = (req.headers.cookie || "").split(";").map(p => p.trim()).find(p => p.startsWith("getoffers_local="))?.slice(16) || "";
        const route = req.url?.split("?")[0];
        const json = (status: number, body: unknown) => { res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" }); res.end(JSON.stringify(body)); };
        try {
          if (route === "/api/developer-observability") {
            if (process.env.GETOFFERS_LOCAL_DEVELOPER !== "1") { json(404, { error: "NOT_FOUND" }); return; }
            if (req.method !== "GET") { json(405, { error: "METHOD_NOT_ALLOWED" }); return; }
            if (!session) { json(403, { error: "DEVELOPER_ACCESS_DENIED" }); return; }
            const params = new URL(req.url || "", origin).searchParams;
            if ([...params.keys()].some(key => !["action", "id", "baseline", "challenger"].includes(key)) || params.size > 4 || (req.url?.length || 0) > 1000) { json(400, { error: "INVALID_REQUEST" }); return; }
            const { response, value } = await call({ ...Object.fromEntries(params), session }, `${assistantOrigin}/assistant/observability`);
            json(response.status, value); return;
          }
          if (route === "/api/local-assistant") {
            if (req.method === "GET") {
              const { response, value } = await call({ action: "status", session });
              json(response.ok ? 200 : 503, value); return;
            }
            if (req.method !== "POST") { json(405, { error: "METHOD_NOT_ALLOWED" }); return; }
            let raw = "";
            for await (const chunk of req) { raw += chunk; if (Buffer.byteLength(raw) > 1024) { json(413, { error: "REQUEST_TOO_LARGE" }); return; } }
            const body = JSON.parse(raw) as { action?: string; model?: string };
            if (!body || !["connect", "disconnect", "model"].includes(body.action || "") || Object.keys(body).some(k => !["action", "model"].includes(k))) { json(400, { error: "INVALID_REQUEST" }); return; }
            const { response, value } = await call({ action: body.action, model: body.model, session });
            if (response.ok && body.action === "connect" && typeof value.session === "string") {
              res.setHeader("Set-Cookie", `getoffers_local=${value.session}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800`);
              delete value.session;
            }
            if (body.action === "disconnect") res.setHeader("Set-Cookie", "getoffers_local=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0");
            json(response.status, value); return;
          }
          if (session) {
            const { response, value } = await call({ action: "session", session });
            if (response.ok && typeof value.userId === "string" && typeof value.email === "string") {
              req.headers["oai-authenticated-user-id"] = value.userId;
              req.headers["oai-authenticated-user-email"] = value.email;
              req.rawHeaders.push("oai-authenticated-user-id", value.userId, "oai-authenticated-user-email", value.email);
            }
          }
          next();
        } catch {
          if (route === "/api/local-assistant" || route === "/api/developer-observability") json(503, { error: "LOCAL_SERVICE_UNAVAILABLE" });
          else next(); // Authentication stays absent; protected routes fail closed.
        }
      });
    },
  };
}

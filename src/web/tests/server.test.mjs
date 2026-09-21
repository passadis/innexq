import { test } from "node:test";
import assert from "node:assert/strict";
import { appServer, publicConfig } from "../server.mjs";
const env = { INNEXQ_WEB_TENANT_ID: "35de4c50-7dcd-4871-8685-61789c017da2", INNEXQ_WEB_CLIENT_ID: "11111111-1111-4111-8111-111111111111", INNEXQ_WEB_API_ORIGIN: "https://api.example.azurecontainerapps.io", INNEXQ_WEB_API_SCOPE: "api://11111111-1111-4111-8111-111111111111/Runs.Read", SECRET: "never-export-this" };
test("public configuration is explicit and contains no arbitrary environment values", () => {
  assert.equal(Object.keys(publicConfig(env)).length, 4);
  assert.throws(() => publicConfig({ ...env, INNEXQ_WEB_API_ORIGIN: "https://evil.example" }));
  const customer = { ...env, INNEXQ_WEB_API_SCOPE: env.INNEXQ_WEB_API_SCOPE.replace('Runs.Read', 'Certificates.Request') };
  assert.equal(Object.keys(publicConfig(customer)).length, 4);
  assert.equal(publicConfig(customer).apiScope, customer.INNEXQ_WEB_API_SCOPE);
  for (const scope of ['Runs.Write', 'runs.read', 'certificates.request', 'Certificates.Request Runs.Read', 'https://graph.microsoft.com/Mail.Send']) {
    assert.throws(() => publicConfig({ ...env, INNEXQ_WEB_API_SCOPE: `api://11111111-1111-4111-8111-111111111111/${scope}` }));
  }
});
for (const scope of ['Runs.Read', 'Certificates.Request']) test(`${scope} server exposes static shell only, no proxy, writes, tokens or directory traversal`, async () => {
  const server = appServer(publicConfig({ ...env, INNEXQ_WEB_API_SCOPE: env.INNEXQ_WEB_API_SCOPE.replace('Runs.Read', scope) }));
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  try {
    const config = await fetch(origin + "/config.json");
    assert.equal(config.headers.get("cache-control"), "no-store");
    const settings = await config.json();
    assert.equal(JSON.stringify(settings).includes(env.SECRET), false);
    assert.equal(settings.apiScope.endsWith(`/${scope}`), true);
    for (const path of ["/api/runs", "/api/customer/catalog", "/api/operations/certificates", "/server.mjs", "/.env", "/assets/%2e%2e/server.mjs"]) assert.equal((await fetch(origin + path)).status, 404);
    assert.equal((await fetch(origin + "/", { method: "POST" })).status, 405);
    const shell = await fetch(origin + "/");
    assert.equal(shell.status, 200);
    assert.equal(shell.headers.get("cross-origin-opener-policy"), "same-origin");
    const bridge = await fetch(origin + "/redirect.html");
    assert.equal(bridge.status, 200);
    assert.equal(bridge.headers.get("cross-origin-opener-policy"), null);
    assert.match(bridge.headers.get("content-security-policy"), /script-src 'self'/);
  } finally { await new Promise(resolve => server.close(resolve)); }
});

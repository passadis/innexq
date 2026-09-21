import { afterEach, expect, test, vi } from "vitest";
import { createRunApi, validateConfig } from "./api";
const config = { tenantId: "35de4c50-7dcd-4871-8685-61789c017da2", clientId: "11111111-1111-4111-8111-111111111111", apiOrigin: "https://api.example.azurecontainerapps.io", apiScope: "api://11111111-1111-4111-8111-111111111111/Runs.Read" };
afterEach(() => vi.unstubAllGlobals());
test("read client only sends GET to the configured API, with no cookie or redirect forwarding", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
  vi.stubGlobal("fetch", fetcher);
  await createRunApi(config, async () => "test-only").listRuns();
  expect(fetcher).toHaveBeenCalledWith(config.apiOrigin + "/api/runs", expect.objectContaining({ method: "GET", cache: "no-store", credentials: "omit", redirect: "error" }));
});
test("invalid run IDs cannot redirect a bearer token", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  expect(() => createRunApi(config, async () => "test-only").getRun("../detect")).toThrow("Invalid Run");
  expect(fetcher).not.toHaveBeenCalled();
});
test("invalid deployment config fails closed", () => {
  for (const apiOrigin of ["http://api.example.azurecontainerapps.io", "https://evil.test", "https://api.example.azurecontainerapps.io/path", "https://user:password@api.example.azurecontainerapps.io"]) expect(() => validateConfig({ ...config, apiOrigin })).toThrow(); // pragma: allowlist secret -- synthetic rejected URL
  expect(() => validateConfig({ ...config, apiScope: "https://graph.microsoft.com/Mail.Send" })).toThrow();
});
test("server error payloads are never shown to the user", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({ secret: "private error" }) })); // pragma: allowlist secret -- synthetic response fixture
  await expect(createRunApi(config, async () => "test-only").listRuns()).rejects.toThrow("Run service is unavailable");
});
test("aborted selection never sends a token after slow token acquisition", async () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const controller = new AbortController(); controller.abort();
  await expect(createRunApi(config, async () => "test-only").listRuns(controller.signal)).rejects.toThrow("Aborted");
  expect(fetcher).not.toHaveBeenCalled();
});

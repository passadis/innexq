import type { RunRecord, RunEvent } from "./contracts";

export interface WebConfig { tenantId: string; clientId: string; apiOrigin: string; apiScope: string }
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function validateConfig(value: WebConfig): WebConfig {
  const origin = new URL(value.apiOrigin);
  if (!uuid.test(value.tenantId) || !uuid.test(value.clientId) || origin.protocol !== "https:" ||
      !origin.hostname.endsWith(".azurecontainerapps.io") || origin.origin !== value.apiOrigin ||
      !/^api:\/\/[0-9a-f-]{36}\/Runs\.Read$/i.test(value.apiScope)) {
    throw new Error("InnexQ sign-in configuration is unavailable.");
  }
  return value;
}

export function createRunApi(config: WebConfig, getToken: () => Promise<string>) {
  validateConfig(config);
  async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
    const token = await getToken();
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const response = await fetch(config.apiOrigin + path, {
      method: "GET", headers: { Authorization: `Bearer ${token}` }, signal,
      cache: "no-store", credentials: "omit", redirect: "error",
    });
    if (!response.ok) {
      if (response.status === 401) throw new Error("Your session expired. Sign out and sign in again.");
      if (response.status === 403) throw new Error("This account is not authorized to view these Runs.");
      if (response.status === 404) throw new Error("This Run is no longer available to this account.");
      throw new Error("The Run service is unavailable. Refresh to try again.");
    }
    return response.json() as Promise<T>;
  }
  const runPath = (id: string) => {
    if (!uuid.test(id)) throw new Error("Invalid Run identifier.");
    return `/api/runs/${id}`;
  };
  return {
    listRuns: (signal?: AbortSignal) => get<RunRecord[]>("/api/runs", signal),
    getRun: (id: string, signal?: AbortSignal) => get<RunRecord>(runPath(id), signal),
    getEvents: (id: string, signal?: AbortSignal) => get<RunEvent[]>(runPath(id) + "/events", signal),
  };
}

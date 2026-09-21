export interface CustomerConfig {
  tenantId: string;
  clientId: string;
  apiOrigin: string;
  apiScope: string;
}

export interface CustomerCatalog {
  customer_name: string;
  equipment: { equipment_id: string; name: string; serial_number: string }[];
  presets: { equipment_id: string; prompt: string }[];
}

export interface CustomerRequestInput { request_id: string; equipment_id: string; prompt: string }
export interface CustomerRequestStatus {
  request_id: string;
  status: 'release_ready' | 'operations_required';
  message: string;
  /** Optional only for compatibility during an API-first rolling deployment. */
  case_status?: 'not_required' | 'open' | 'acknowledged' | 'closed_without_release';
  updated_at?: string;
}

export interface CustomerMessageInput {
  message_id: string;
  prompt: string;
  equipment_id: string | null;
  parent_message_id: string | null;
}
export interface CustomerMessage {
  message_id: string;
  intent: 'certificate_request' | 'service_status' | 'certificate_status' | 'service_request' | 'general' | 'clarify';
  equipment_id: string | null;
  kind: 'answer' | 'clarification' | 'confirmation_required' | 'unsupported';
  message: string;
  as_of: string | null;
  citations: { document_id: string; document_version: string; page: number; label: string; value: string }[];
  can_confirm: boolean;
}

export interface CustomerApi {
  catalog(signal?: AbortSignal): Promise<CustomerCatalog>;
  request(input: CustomerRequestInput, signal?: AbortSignal): Promise<CustomerRequestStatus>;
  message(input: CustomerMessageInput, signal?: AbortSignal): Promise<CustomerMessage>;
  confirm(id: string, signal?: AbortSignal): Promise<CustomerRequestStatus>;
  status(id: string, signal?: AbortSignal): Promise<CustomerRequestStatus>;
  pdf(id: string, signal?: AbortSignal): Promise<Blob>;
}

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const unavailable = () => new Error('The certificate service is unavailable. Please try again.');
const isObject = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
const isText = (value: unknown, max = 200): value is string => typeof value === 'string' && value.trim().length > 0 && value.length <= max;
const equipmentPattern = /^DEMO-[A-Z0-9-]+$/;

export function customerMessageResponse(value: unknown, id: string): CustomerMessage {
  if (!isObject(value) || value.message_id !== id || !uuid.test(id) ||
      !['certificate_request', 'service_status', 'certificate_status', 'service_request', 'general', 'clarify'].includes(String(value.intent)) ||
      !['answer', 'clarification', 'confirmation_required', 'unsupported'].includes(String(value.kind)) ||
      !(value.equipment_id === null || (isText(value.equipment_id) && equipmentPattern.test(value.equipment_id))) ||
      !isText(value.message, 2000) || typeof value.can_confirm !== 'boolean' ||
      !(value.as_of === null || (typeof value.as_of === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value.as_of) && Number.isFinite(Date.parse(value.as_of)))) ||
      !Array.isArray(value.citations) || value.citations.length > 30) throw unavailable();
  const confirmable = value.intent === 'certificate_request' && value.kind === 'confirmation_required' && value.equipment_id !== null;
  if (value.can_confirm !== confirmable || (value.kind === 'confirmation_required' && !confirmable)) throw unavailable();
  const citations = value.citations.map(item => {
    if (!isObject(item) || !isText(item.document_id) || !isText(item.document_version) ||
        !Number.isSafeInteger(item.page) || (item.page as number) < 1 || !isText(item.label) || !isText(item.value, 1000)) throw unavailable();
    return { document_id: item.document_id, document_version: item.document_version, page: item.page as number, label: item.label, value: item.value };
  });
  return { message_id: id, intent: value.intent as CustomerMessage['intent'], equipment_id: value.equipment_id,
    kind: value.kind as CustomerMessage['kind'], message: value.message, as_of: value.as_of, citations, can_confirm: value.can_confirm };
}

export function validateCustomerConfig(value: CustomerConfig): CustomerConfig {
  const origin = new URL(value.apiOrigin);
  if (!uuid.test(value.tenantId) || !uuid.test(value.clientId) || origin.protocol !== 'https:' ||
      !origin.hostname.endsWith('.azurecontainerapps.io') || origin.origin !== value.apiOrigin ||
      !/^api:\/\/[0-9a-f-]{36}\/Certificates\.Request$/i.test(value.apiScope)) {
    throw new Error('InnexQ customer sign-in configuration is unavailable.');
  }
  return value;
}

function catalogResponse(value: unknown): CustomerCatalog {
  if (!isObject(value) || !isText(value.customer_name) || !Array.isArray(value.equipment) ||
      value.equipment.length > 10 || !Array.isArray(value.presets) || value.presets.length > 10) throw unavailable();
  const equipment = value.equipment.map(item => {
    if (!isObject(item) || !isText(item.equipment_id) || !isText(item.name) || !isText(item.serial_number)) throw unavailable();
    return { equipment_id: item.equipment_id, name: item.name, serial_number: item.serial_number };
  });
  const ids = new Set(equipment.map(item => item.equipment_id));
  if (ids.size !== equipment.length) throw unavailable();
  const presets = value.presets.map(item => {
    if (!isObject(item) || !isText(item.equipment_id) || !ids.has(item.equipment_id) || !isText(item.prompt, 2000)) throw unavailable();
    return { equipment_id: item.equipment_id, prompt: item.prompt };
  });
  return { customer_name: value.customer_name, equipment, presets };
}

export function statusResponse(value: unknown, id: string): CustomerRequestStatus {
  if (!isObject(value) || value.request_id !== id ||
      (value.status !== 'release_ready' && value.status !== 'operations_required') || !isText(value.message, 1000)) throw unavailable();
  // Only the public contract is retained. Internal evidence and Operations reasons never enter UI state.
  const result: CustomerRequestStatus = { request_id: id, status: value.status, message: value.message };
  if (value.case_status !== undefined || value.updated_at !== undefined) {
    if (!['not_required', 'open', 'acknowledged', 'closed_without_release'].includes(String(value.case_status)) ||
        typeof value.updated_at !== 'string' || !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value.updated_at) ||
        !Number.isFinite(Date.parse(value.updated_at)) ||
        ((value.status === 'release_ready') !== (value.case_status === 'not_required'))) throw unavailable();
    result.case_status = value.case_status as CustomerRequestStatus['case_status'];
    result.updated_at = value.updated_at;
  }
  return result;
}

export function createCustomerApi(config: CustomerConfig, getToken: () => Promise<string>): CustomerApi {
  validateCustomerConfig(config);
  const requestPath = (id: string) => {
    if (!uuid.test(id)) throw new Error('Invalid request identifier.');
    return `/api/customer/requests/${id}`;
  };
  async function send(path: string, signal?: AbortSignal, input?: object) {
    const token = await getToken();
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const response = await fetch(config.apiOrigin + path, {
      method: input ? 'POST' : 'GET',
      headers: { Authorization: `Bearer ${token}`, ...(input ? { 'Content-Type': 'application/json' } : {}) },
      ...(input ? { body: JSON.stringify(input) } : {}),
      signal, cache: 'no-store', credentials: 'omit', redirect: 'error',
    });
    if (!response.ok) {
      if (response.status === 401) throw new Error('Your session expired. Sign out and sign in again.');
      if (response.status === 403 || response.status === 404) throw new Error('This request is not available to this account.');
      throw unavailable();
    }
    return response;
  }
  return {
    catalog: async signal => catalogResponse(await (await send('/api/customer/catalog', signal)).json()),
    request: async (input, signal) => {
      requestPath(input.request_id);
      if (!isText(input.equipment_id) || !isText(input.prompt, 2000)) throw new Error('Choose equipment and enter your request.');
      // Never forward caller-added customer IDs, actor IDs, or authorization fields.
      const body = { request_id: input.request_id, equipment_id: input.equipment_id, prompt: input.prompt };
      return statusResponse(await (await send('/api/customer/requests', signal, body)).json(), input.request_id);
    },
    message: async (input, signal) => {
      if (!uuid.test(input.message_id) || !isText(input.prompt, 1000) ||
          !(input.equipment_id === null || (isText(input.equipment_id) && equipmentPattern.test(input.equipment_id))) ||
          !(input.parent_message_id === null || uuid.test(input.parent_message_id))) throw new Error('Enter a message and choose valid equipment if needed.');
      const body = { message_id: input.message_id, prompt: input.prompt, equipment_id: input.equipment_id, parent_message_id: input.parent_message_id };
      return customerMessageResponse(await (await send('/api/customer/messages', signal, body)).json(), input.message_id);
    },
    confirm: async (id, signal) => {
      requestPath(id);
      return statusResponse(await (await send(`/api/customer/messages/${id}/confirm`, signal, {})).json(), id);
    },
    status: async (id, signal) => statusResponse(await (await send(requestPath(id), signal)).json(), id),
    pdf: async (id, signal) => {
      const response = await send(requestPath(id) + '/pdf', signal);
      if (response.headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== 'application/pdf') throw unavailable();
      const blob = await response.blob();
      if (blob.size === 0 || blob.size > 20 * 1024 * 1024) throw unavailable();
      return blob;
    },
  };
}

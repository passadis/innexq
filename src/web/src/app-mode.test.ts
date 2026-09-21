import { describe, expect, it } from 'vitest';
import { isCustomerPortal, validateAppConfig } from './app-mode';
import { createRunApi } from './api';
import { createCustomerApi } from './customer-api';
import { createOperationsApi } from './operations-api';

const config = { tenantId: '35de4c50-7dcd-4871-8685-61789c017da2', clientId: '11111111-1111-4111-8111-111111111111', apiOrigin: 'https://api.example.azurecontainerapps.io', apiScope: 'api://11111111-1111-4111-8111-111111111111/Runs.Read' };
describe('separate web experiences', () => {
  it('selects the experience only from an explicitly allowed configured scope', () => {
    expect(validateAppConfig(config)).toEqual(config);
    expect(isCustomerPortal(config)).toBe(false);
    expect(isCustomerPortal({ ...config, apiScope: config.apiScope.replace('Runs.Read', 'Certificates.Request') })).toBe(true);
  });
  it('rejects combined, differently cased and unrelated scopes', () => {
    for (const scope of ['Runs.Read Certificates.Request', 'runs.read', 'certificates.request', 'Mail.Send', 'Runs.Write']) {
      expect(() => validateAppConfig({ ...config, apiScope: config.apiScope.replace('Runs.Read', scope) })).toThrow();
    }
  });
  it('does not allow a customer configuration to create either employee API client', () => {
    const customer = { ...config, apiScope: config.apiScope.replace('Runs.Read', 'Certificates.Request') };
    expect(() => createRunApi(customer, async () => 'test-only')).toThrow();
    expect(() => createOperationsApi(customer, async () => 'test-only')).toThrow();
    expect(() => createCustomerApi(config, async () => 'test-only')).toThrow();
  });
});

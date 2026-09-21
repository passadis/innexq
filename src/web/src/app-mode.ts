import { validateConfig, type WebConfig } from './api';
import { validateCustomerConfig } from './customer-api';

export function validateAppConfig(config: WebConfig): WebConfig {
  if (/^api:\/\/[0-9a-fA-F-]{36}\/Certificates\.Request$/.test(config.apiScope)) return validateCustomerConfig(config);
  if (/^api:\/\/[0-9a-fA-F-]{36}\/Runs\.Read$/.test(config.apiScope)) return validateConfig(config);
  throw new Error('InnexQ sign-in configuration is unavailable.');
}

export function isCustomerPortal(config: WebConfig): boolean {
  validateAppConfig(config);
  return config.apiScope.endsWith('/Certificates.Request');
}

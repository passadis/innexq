import { expect, test } from 'vitest';
import { parseDecisionLink } from './decision-link';
const valid = '?run=11111111-1111-4111-8111-111111111111&version=1&hash=' + 'a'.repeat(64);
test('decision links are strict and cannot omit, duplicate or redirect their identity', () => {
  expect(parseDecisionLink('')).toBeNull();
  expect(parseDecisionLink(valid)).toMatchObject({ version: 1 });
  for (const query of ['?run=../other', valid + '&run=other', valid.replace('version=1', 'version=0'), valid.replace('version=1', 'version=9007199254740992'), valid.replace('hash=', 'missing=')]) {
    expect(parseDecisionLink(query)).toEqual({ invalid: true });
  }
});

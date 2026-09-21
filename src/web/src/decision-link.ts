export type DecisionLink = { run: string; version: number; hash: string } | { invalid: true } | null;

export function parseDecisionLink(search: string): DecisionLink {
  const params = new URLSearchParams(search);
  if (!['run', 'version', 'hash'].some(key => params.has(key))) return null;
  if (['run', 'version', 'hash'].some(key => params.getAll(key).length !== 1)) return { invalid: true };
  const run = params.get('run')!;
  const version = params.get('version')!;
  const hash = params.get('hash')!;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(run) ||
      !/^[1-9][0-9]*$/.test(version) || !Number.isSafeInteger(Number(version)) ||
      !/^[0-9a-f]{64}$/.test(hash)) return { invalid: true };
  return { run, version: Number(version), hash };
}

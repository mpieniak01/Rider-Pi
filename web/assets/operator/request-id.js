// Request correlation uses browser cryptography; failure never dispatches a mutation.
export function requestId(prefix = 'rider') {
  const crypto = globalThis.crypto;
  if (typeof crypto?.randomUUID === 'function') return prefix + '-' + crypto.randomUUID();
  if (typeof crypto?.getRandomValues !== 'function') throw new Error('secure_randomness_unavailable');
  const bytes = new Uint8Array(16); crypto.getRandomValues(bytes);
  return prefix + '-' + Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
}

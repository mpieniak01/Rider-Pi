// Compatibility while the catalog v2 operator panel replaces the old controls.
export const legacyContractMessage = 'Wymagany panel operatora v2 / Operator panel v2 required';

export function legacyBlocked(button) {
  return button.dataset.contractV2Required === 'true';
}

export function blockLegacyButton(button) {
  button.dataset.contractV2Required = 'true';
  button.disabled = true;
  button.title = legacyContractMessage;
}

export function legacyResourceState(data) {
  if (data?.error) return { css: 'is-err', state: 'unknown', error: data.error };
  if (data?.state === 'free' && data.free === true) return { css: 'is-ok', state: 'free' };
  if (data?.state === 'busy' && data.free === false) return { css: 'is-warn', state: 'busy' };
  return { css: 'is-off', state: data?.state === 'unavailable' ? 'unavailable' : 'unknown' };
}

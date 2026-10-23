/** Translation data is optional: a failed catalogue must not disable manual control. */
export async function loadProfileMessages() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2000);
  try {
    const response = await fetch(new URL('./navigation-profile-messages.json', import.meta.url), {
      signal: controller.signal, cache: 'no-cache',
    });
    if (!response.ok) return {};
    const messages = await response.json();
    if (!messages || Array.isArray(messages) || typeof messages !== 'object') return {};
    if (Object.values(messages).some(values => !Array.isArray(values)
      || values.length !== 3 || values.some(value => typeof value !== 'string'))) return {};
    return messages;
  } catch {
    return {};
  } finally {
    clearTimeout(timeout);
  }
}
export const profileMessages = await loadProfileMessages();
export function profileText(key, values = {}) {
  const locale = document.documentElement.lang;
  const index = locale.startsWith('en') ? 1 : locale.startsWith('de') ? 2 : 0;
  let value = profileMessages[key]?.[index] || key;
  for (const [name, replacement] of Object.entries(values)) value = value.replaceAll('{'+name+'}', String(replacement));
  return value;
}

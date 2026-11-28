/**
 * Leaves the application for another address: the API's Google sign-in start, or Google itself.
 * It is a function of its own so that tests can see where the application would have gone.
 */
export function goTo(address: string): void {
  window.location.assign(address);
}

/** True for an https address. An address the API hands over is followed only when it is one. */
export function isSecureAddress(address: string): boolean {
  return URL.canParse(address) && new URL(address).protocol === 'https:';
}

// The address a person just registered with, or tried to sign in with before confirming it.
// It is handed to the verification and sign-in screens in memory and never put in the address bar.
let pending: string | null = null;

export const pendingEmail = {
  get: (): string | null => pending,
  set(value: string | null): void {
    pending = value;
  },
};

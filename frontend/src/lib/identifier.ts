const identifier = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** True for an identifier as the API issues them. Nothing else from an address is sent to the API as one. */
export const isIdentifier = (value: unknown): value is string => typeof value === 'string' && identifier.test(value);

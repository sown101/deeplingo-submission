// Return-location safety for auth redirects.
//
// Sign-in/onboarding redirect targets come from router state. Defense in
// depth: only INTERNAL application routes may be restored — never an
// absolute URL, a scheme-relative host ("//evil.example"), a
// backslash-scheme trick ("/\evil.example"), or a javascript: payload.

export function safeInternalLocation(value: unknown): string | null {
  if (typeof value !== "string") return null;
  if (value.length === 0 || value.length > 512) return null;
  if (!value.startsWith("/")) return null;
  if (value.startsWith("//") || value.startsWith("/\\")) return null;
  if (value.includes("://")) return null;
  if (value.includes("\\")) return null;
  // Reject control characters that could split or confuse parsers.
  if (/[\u0000-\u001f\u007f]/.test(value)) return null;
  return value;
}

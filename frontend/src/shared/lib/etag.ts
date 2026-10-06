// `ETag: "sha256:<hex>"` (ADR-028 C4/C5), the legacy `"<hex>"` form and weak (`W/`) variants.
const DIGEST_ETAG = /^(?:W\/)?"(?:sha256:)?([0-9a-fA-F]{64})"$/;

/**
 * The SHA-256 carried by an ETag, lower-cased; null when absent or opaque (for example a
 * proxy-generated validator). An ETag is only a pre-check: the SHA-256 of the received
 * body stays the authoritative integrity check.
 */
export function etagSha256(etag: string | null | undefined): string | null {
  const match = etag?.trim().match(DIGEST_ETAG);
  return match?.[1] ? match[1].toLowerCase() : null;
}

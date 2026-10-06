const CHUNK_ERROR = /ChunkLoadError|Loading (?:CSS )?chunk .*failed|Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i;

/** Browser errors for a route bundle that could not be fetched (network blip or a newer deploy). */
export function isChunkLoadError(error: unknown): boolean {
  return error instanceof Error && CHUNK_ERROR.test(`${error.name}: ${error.message}`);
}

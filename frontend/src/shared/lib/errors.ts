export class ApiClientError extends Error {
  public readonly code: string;
  public readonly status?: number;

  constructor(message: string, code: string, status?: number) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.status = status;
  }
}

export function toErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Unexpected error";
}

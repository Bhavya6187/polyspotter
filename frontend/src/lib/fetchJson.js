// Server-side JSON fetch that only treats an HTTP 404 as "not found".
//
// Pages call notFound() when this returns null. Any other failure (5xx,
// network error, bad JSON) throws, so Next renders the error boundary (and
// ISR keeps serving the last good page) instead of a cacheable soft/hard 404
// for a transient backend outage.

export class ApiError extends Error {
  constructor(status, url) {
    super(`API error: ${status} for ${url}`);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function fetchJsonOr404(url, init) {
  const res = await fetch(url, init);
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiError(res.status, String(url));
  return res.json();
}

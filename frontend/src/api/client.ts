const API_ROOT = '/api'

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(`${API_ROOT}${path}`, { ...options, headers })
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const body = await response.json()
      message = body.detail || message
    } catch { /* response is not JSON */ }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export type JsonMethod = 'POST' | 'PUT' | 'PATCH'

export const jsonBody = (
  value: unknown,
  method: JsonMethod = 'POST',
): Pick<RequestInit, 'body' | 'method'> => ({
  method,
  body: JSON.stringify(value),
})

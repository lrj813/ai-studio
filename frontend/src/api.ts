const BASE = '/api'

async function handle(res: Response): Promise<any> {
  if (!res.ok) {
    let msg = `请求失败 (${res.status})`
    try {
      const b = await res.json()
      if (b?.error?.message) msg = b.error.message
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
  if (res.status === 204) return null
  return res.json()
}

export const http = {
  get: (p: string) => fetch(`${BASE}${p}`).then(handle),
  post: (p: string, body?: unknown) =>
    fetch(`${BASE}${p}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then(handle),
  patch: (p: string, body: unknown) =>
    fetch(`${BASE}${p}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(handle),
  put: (p: string, body: unknown) =>
    fetch(`${BASE}${p}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(handle),
  del: (p: string) => fetch(`${BASE}${p}`, { method: 'DELETE' }).then(handle),
  upload: (p: string, form: FormData) =>
    fetch(`${BASE}${p}`, { method: 'POST', body: form }).then(handle),
}

export function assetUrl(id: string, thumb = false): string {
  return `${BASE}/assets/${id}/${thumb ? 'thumb' : 'file'}`
}

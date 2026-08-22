function getCookie(name) {
  const cookies = document.cookie ? document.cookie.split(';') : []
  for (const cookie of cookies) {
    const [key, ...parts] = cookie.trim().split('=')
    if (key === name) return decodeURIComponent(parts.join('='))
  }
  return ''
}

export async function ensureCsrf() {
  await fetch('/api/auth/csrf/', { credentials: 'include' })
}

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {})
  const isForm = options.body instanceof FormData
  if (options.body && !isForm && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (!['GET', 'HEAD', 'OPTIONS'].includes((options.method || 'GET').toUpperCase())) {
    if (!getCookie('csrftoken')) await ensureCsrf()
    headers.set('X-CSRFToken', getCookie('csrftoken'))
  }
  const response = await fetch(`/api/${path.replace(/^\//, '')}`, {
    credentials: 'include',
    ...options,
    headers,
  })
  if (response.status === 204) return null
  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json') ? await response.json() : await response.blob()
  if (!response.ok) {
    const error = new Error(payload?.detail || '请求失败')
    error.status = response.status
    error.payload = payload
    throw error
  }
  return payload
}

export function listItems(payload) {
  return Array.isArray(payload) ? payload : payload?.results || []
}


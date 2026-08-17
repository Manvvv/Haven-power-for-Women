/**
 * Haven Secure API Client
 * Automatically attaches Authorization Bearer tokens (Clerk JWT or Authority Session Token)
 * to all backend API requests.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export function getAuthorityToken(): string | null {
  if (typeof window === 'undefined') return null;
  return sessionStorage.getItem('haven_authority_token');
}

export function setAuthorityToken(token: string) {
  if (typeof window !== 'undefined') {
    sessionStorage.setItem('haven_authority_token', token);
  }
}

export function clearAuthorityToken() {
  if (typeof window !== 'undefined') {
    sessionStorage.removeItem('haven_authority_token');
  }
}

export async function getAuthHeaders(customToken?: string): Promise<Record<string, string>> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };

  // 1. If explicit token is provided, use it
  if (customToken) {
    headers['Authorization'] = `Bearer ${customToken}`;
    return headers;
  }

  // 2. Check for Authority Token in session
  const authorityToken = getAuthorityToken();
  if (authorityToken) {
    headers['Authorization'] = `Bearer ${authorityToken}`;
    return headers;
  }

  // 3. Check for Clerk session token if in browser
  if (typeof window !== 'undefined' && (window as any).Clerk?.session) {
    try {
      const token = await (window as any).Clerk.session.getToken();
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
    } catch {
      // Non-blocking fallback
    }
  }

  return headers;
}

export async function secureFetch(
  endpoint: string,
  options: RequestInit = {},
  customToken?: string
): Promise<Response> {
  const authHeaders = await getAuthHeaders(customToken);
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;

  // If body is FormData, don't set Content-Type header so browser sets boundary
  if (options.body instanceof FormData) {
    delete authHeaders['Content-Type'];
  }

  const mergedHeaders = {
    ...authHeaders,
    ...(options.headers as Record<string, string> || {}),
  };

  return fetch(url, {
    ...options,
    headers: mergedHeaders,
  });
}

export default secureFetch;

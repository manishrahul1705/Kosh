import axios, { AxiosError } from 'axios'
import { getAccessToken, signOut } from '@/lib/auth'

export const apiClient = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
  timeout: 60000,
})

apiClient.interceptors.request.use(async (config) => {
  const token = await getAccessToken()
  if (token) config.headers.set('Authorization', `Bearer ${token}`)
  return config
})

apiClient.interceptors.response.use(
  (res) => res,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      signOut()
      if (window.location.pathname !== '/login') window.location.assign('/login')
    }
    return Promise.reject(error)
  }
)

export type ApiError = {
  message: string
  status?: number
  detail?: unknown
}

export function toApiError(err: unknown): ApiError {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    const msg =
      typeof detail === 'string'
        ? detail
        : err.response?.statusText ?? err.message
    return { message: msg, status: err.response?.status, detail }
  }
  return { message: String(err) }
}

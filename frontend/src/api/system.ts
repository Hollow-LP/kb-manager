import { request } from './http'

export interface HealthResult {
  status: 'ok' | 'degraded'
  checks: Record<string, string>
}

export const getHealth = () => request<HealthResult>({ url: '/health' })

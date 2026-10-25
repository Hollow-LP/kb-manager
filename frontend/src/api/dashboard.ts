import { request } from './http'

export interface DashboardMetrics {
  days: number
  total_visits: number
  unique_visitors: number
  total_units: number
  total_tokens: number
  avg_response_ms: number
  faq_hits: number
  gap_questions: number
  faq_hit_rate: number
}

export interface QuestionRank {
  question: string
  ask_count: number
  variant_count: number
  avg_tokens: number
}

export interface UnitRank {
  unit_id: number
  unit_code: string
  title: string
  category: string | null
  hit_count: number
  recalled_count: number
  denied_count: number
}

export interface TrendPoint {
  bucket: string
  visits: number
  uv: number
  tokens: number
  avg_response_ms: number
  faq_hits: number
}

export interface TokenPoint {
  bucket: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  visits: number
}

export interface ResponseTimeStats {
  labels: string[]
  counts: number[]
  p50: number
  p95: number
  avg: number
  samples: number
}

export interface DashboardOverview {
  metrics: DashboardMetrics
  questions: QuestionRank[]
  units: UnitRank[]
  trend: TrendPoint[]
  tokens: TokenPoint[]
  response_time: ResponseTimeStats
  scope_days: number
}

export type Granularity = 'day' | 'week'

export const apiOverview = (days: number, granularity: Granularity) =>
  request<DashboardOverview>({ url: '/dashboard/overview', params: { days, granularity } })
export const apiMetrics = (days: number) =>
  request<DashboardMetrics>({ url: '/dashboard/metrics', params: { days } })
export const apiQuestionRanking = (days: number, top = 10) =>
  request<QuestionRank[]>({ url: '/dashboard/rankings/questions', params: { days, top } })
export const apiUnitRanking = (days: number, top = 10) =>
  request<UnitRank[]>({ url: '/dashboard/rankings/units', params: { days, top } })
export const apiTrend = (days: number, granularity: Granularity) =>
  request<TrendPoint[]>({ url: '/dashboard/stats/trend', params: { days, granularity } })
export const apiTokenStats = (days: number, granularity: Granularity) =>
  request<TokenPoint[]>({ url: '/dashboard/stats/tokens', params: { days, granularity } })
export const apiResponseTime = (days: number) =>
  request<ResponseTimeStats>({ url: '/dashboard/stats/response-time', params: { days } })

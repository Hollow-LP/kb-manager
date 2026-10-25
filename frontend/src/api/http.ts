import axios from 'axios'
import { ElMessage } from 'element-plus'

/** 与后端 app/core/exceptions.py 的错误结构一致 */
export interface ApiError {
  code: string
  message: string
  detail?: unknown
}

export const TOKEN_KEY = 'kb_access_token'

const http = axios.create({ baseURL: '/api', timeout: 30000 })

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (res) => res.data,
  (error) => {
    const status = error.response?.status
    const body = error.response?.data as ApiError | undefined
    if (status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      if (!location.pathname.startsWith('/login')) {
        location.href = `/login?redirect=${encodeURIComponent(location.pathname + location.search)}`
      }
    } else if (!error.config?.silent) {
      ElMessage.error(body?.message || '请求失败，请稍后重试')
    }
    return Promise.reject(body ?? error)
  },
)

/** 统一请求方法：返回值即后端 JSON 体 */
export const request = <T = unknown>(config: Parameters<typeof http.request>[0]) =>
  http.request<unknown, T>(config)

export default http

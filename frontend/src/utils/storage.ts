import { API_BASE } from '@/api/client'
const prefix = `smartvision:${API_BASE}:`
export function readLocal(key: string) { try { return localStorage.getItem(prefix + key) } catch { return null } }
export function writeLocal(key: string, value: string | null) {
  try { if (value === null) localStorage.removeItem(prefix + key); else localStorage.setItem(prefix + key, value) } catch { /* 隐私模式仍可使用 */ }
}

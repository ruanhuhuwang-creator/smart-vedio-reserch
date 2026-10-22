export function time(seconds: number, fraction = false) {
  const safe = Math.max(0, Number.isFinite(seconds) ? seconds : 0)
  const value = fraction ? Math.round(safe * 10) / 10 : Math.floor(safe)
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor(value / 60) % 60
  const secs = fraction ? (value % 60).toFixed(1).padStart(4, '0') : String(Math.floor(value % 60)).padStart(2, '0')
  return `${hours ? `${hours}:` : ''}${String(minutes).padStart(2, '0')}:${secs}`
}
export const bytes = (value: number) => `${(value / 1024 / 1024).toFixed(1)} MB`
export const statusLabel: Record<string, string> = { not_analyzed: '待分析', queued: '排队中', running: '分析中', completed: '已建立索引', succeeded: '分析成功', failed: '分析失败', cancelled: '已停止' }
export const categories = [
  { key: 'person', name: '行人', color: '#46d9b6' }, { key: 'car', name: '汽车', color: '#65a7ff' },
  { key: 'bicycle', name: '自行车', color: '#b79aff' }, { key: 'motorcycle', name: '摩托车', color: '#f3bc69' },
  { key: 'bus', name: '公交车', color: '#ff829d' }, { key: 'truck', name: '卡车', color: '#91d6f1' },
]
export const categoryName = (key: string) => categories.find(c => c.key === key)?.name || key
export const categoryColor = (key: string) => categories.find(c => c.key === key)?.color || '#adb9cb'

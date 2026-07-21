export const statusLabels: Record<string, string> = {
  imported: '待生成', image1_queued: '图一排队', image1_running: '图一生成中',
  image1_review: '待选图一', image1_selected: '图一已选', image2_ready: '可生成图二',
  image2_queued: '图二排队', image2_running: '图二生成中', image2_review: '待选图二',
  completed: '已完成', failed: '失败', paused: '已暂停', interrupted: '已中断',
}

export function statusLabel(value: string): string {
  return statusLabels[value] || value
}

export function statusTone(value: string): 'good' | 'warn' | 'bad' | 'neutral' {
  if (value === 'completed') return 'good'
  if (value.includes('review') || value === 'image2_ready') return 'warn'
  if (value === 'failed' || value === 'interrupted') return 'bad'
  return 'neutral'
}


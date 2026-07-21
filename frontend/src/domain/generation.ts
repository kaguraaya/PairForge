import type { ModelInfo } from '../api/types'

export function candidateLimits(model: ModelInfo | undefined) {
  return {
    image1: Math.max(1, model?.max_text_outputs ?? 1),
    image2: Math.max(1, model?.max_edit_outputs ?? 1),
  }
}

export function candidateDefaults(model: ModelInfo | undefined) {
  const limits = candidateLimits(model)
  return {
    image1: Math.min(2, limits.image1),
    image2: 1,
  }
}

export interface SizePreset {
  ratio: string
  label: string
  value: string
  recommendation?: string
}

const SEEDREAM_5_LITE_SIZE_PRESETS: SizePreset[] = [
  { ratio: '1:1', label: '方图', value: '2048x2048', recommendation: '官方 2K' },
  { ratio: '4:3', label: '横图', value: '2304x1728', recommendation: '官方 2K' },
  { ratio: '3:4', label: '竖图', value: '1728x2304', recommendation: '官方 2K' },
  { ratio: '16:9', label: '宽屏', value: '2560x1440', recommendation: '官方 2K' },
  { ratio: '9:16', label: '竖屏', value: '1440x2560', recommendation: '官方 2K' },
]

const SEEDREAM_LEGACY_SIZE_PRESETS: SizePreset[] = [
  { ratio: '1:1', label: '方图', value: '2048x2048' },
  { ratio: '4:3', label: '横图', value: '2048x1536' },
  { ratio: '3:4', label: '竖图', value: '1536x2048' },
  { ratio: '16:9', label: '宽屏', value: '2048x1152' },
  { ratio: '9:16', label: '竖屏', value: '1152x2048' },
]

const ALIBABA_SIZE_PRESETS: SizePreset[] = [
  { ratio: '1:1', label: '方图', value: '2048*2048' },
  { ratio: '4:3', label: '横图', value: '2368*1728' },
  { ratio: '3:4', label: '竖图', value: '1728*2368' },
  { ratio: '16:9', label: '宽屏', value: '2688*1536' },
  { ratio: '9:16', label: '竖屏', value: '1536*2688' },
]

export function sizePresets(model: Pick<ModelInfo, 'provider' | 'model'> | undefined): SizePreset[] {
  if (!model) return []
  if (model.provider === 'volcengine' && model.model === 'doubao-seedream-5-0-lite-260128') {
    return SEEDREAM_5_LITE_SIZE_PRESETS
  }
  if (model.provider === 'volcengine') return SEEDREAM_LEGACY_SIZE_PRESETS
  if (model.provider === 'alibaba') return ALIBABA_SIZE_PRESETS
  return []
}

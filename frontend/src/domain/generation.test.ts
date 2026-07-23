import { describe, expect, it } from 'vitest'
import type { ModelInfo } from '../api/types'
import { candidateDefaults, candidateLimits, sizePresets } from './generation'

const model = (image1: number, image2: number): ModelInfo => ({
  provider: 'test', model: 'test', display_name: 'Test',
  max_text_outputs: image1, max_edit_outputs: image2,
  default_size: '1K', multiple_output_semantics: 'exact',
  unit_price_cny: '0', price_checked_on: 'test', support_level: 'testing',
})

describe('candidate controls', () => {
  it('uses independent model limits for image one and image two', () => {
    expect(candidateLimits(model(6, 4))).toEqual({ image1: 6, image2: 4 })
  })

  it('defaults to two image-one candidates and one image-two candidate when enabled', () => {
    expect(candidateDefaults(model(6, 4))).toEqual({ image1: 2, image2: 1 })
    expect(candidateDefaults(model(1, 1))).toEqual({ image1: 1, image2: 1 })
  })
})

describe('model size presets', () => {
  it('uses the provider-specific dimension separator and includes common ratios', () => {
    const seedream = sizePresets({ provider: 'volcengine', model: 'doubao-seedream-5-0-lite-260128' })
    const seedream45 = sizePresets({ provider: 'volcengine', model: 'doubao-seedream-4-5-251128' })
    const qwen = sizePresets({ provider: 'alibaba', model: 'qwen-image-2.0' })

    expect(seedream.find(item => item.ratio === '1:1')?.value).toBe('2048x2048')
    expect(seedream.find(item => item.ratio === '4:3')?.value).toBe('2304x1728')
    expect(seedream.find(item => item.ratio === '4:3')?.recommendation).toBe('官方 2K')
    expect(seedream.find(item => item.ratio === '16:9')?.value).toBe('2848x1600')
    expect(seedream.find(item => item.ratio === '21:9')?.value).toBe('3136x1344')
    expect(seedream.every(item => {
      const [width, height] = item.value.split('x').map(Number)
      return width * height >= 2560 * 1440
    })).toBe(true)
    expect(seedream45).toEqual(seedream)
    expect(seedream45.find(item => item.ratio === '4:3')?.value).toBe('2304x1728')
    expect(seedream45.find(item => item.ratio === '9:16')?.value).toBe('1600x2848')
    expect(qwen.find(item => item.ratio === '16:9')?.value).toBe('2688*1536')
    expect(sizePresets({ provider: 'custom', model: 'custom' })).toEqual([])
  })
})

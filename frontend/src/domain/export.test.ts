import { describe, expect, it } from 'vitest'
import { isExportPending } from './export'

describe('isExportPending', () => {
  it('detects first exports and changed selections but ignores unchanged pairs', () => {
    const firstExport = {
      state: 'completed', selected_image1_id: 'a1', selected_image2_id: 'a2',
      last_exported_image1_id: null, last_exported_image2_id: null,
    }
    expect(isExportPending(firstExport)).toBe(true)
    expect(isExportPending({
      ...firstExport, last_exported_image1_id: 'a1', last_exported_image2_id: 'a2',
    })).toBe(false)
    expect(isExportPending({
      ...firstExport, last_exported_image1_id: 'a1', last_exported_image2_id: 'old-a2',
    })).toBe(true)
    expect(isExportPending({ ...firstExport, state: 'image2_ready' })).toBe(false)
  })
})

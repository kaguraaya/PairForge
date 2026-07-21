import { describe, expect, it } from 'vitest'
import { statusLabel, statusTone } from './status'

describe('question status', () => {
  it('maps workflow states to clear Chinese labels', () => {
    expect(statusLabel('image1_review')).toBe('待选图一')
    expect(statusTone('completed')).toBe('good')
    expect(statusTone('failed')).toBe('bad')
  })
})


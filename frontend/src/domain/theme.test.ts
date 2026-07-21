import { describe, expect, it } from 'vitest'

import { initialTheme, normalizeTheme, oppositeTheme } from './theme'

describe('theme preference', () => {
  it('restores an explicit saved theme before consulting the operating system', () => {
    expect(initialTheme('light', true)).toBe('light')
    expect(initialTheme('dark', false)).toBe('dark')
  })

  it('falls back to the operating-system preference and toggles predictably', () => {
    expect(initialTheme(null, true)).toBe('dark')
    expect(initialTheme('unknown', false)).toBe('light')
    expect(normalizeTheme('unknown')).toBeNull()
    expect(oppositeTheme('dark')).toBe('light')
    expect(oppositeTheme('light')).toBe('dark')
  })
})

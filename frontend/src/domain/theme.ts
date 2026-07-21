export type ColorTheme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'double-image-workbench-theme'

export function normalizeTheme(value: string | null): ColorTheme | null {
  return value === 'light' || value === 'dark' ? value : null
}

export function initialTheme(stored: string | null, prefersDark: boolean): ColorTheme {
  return normalizeTheme(stored) || (prefersDark ? 'dark' : 'light')
}

export function oppositeTheme(theme: ColorTheme): ColorTheme {
  return theme === 'dark' ? 'light' : 'dark'
}

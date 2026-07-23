import { describe, expect, it } from 'vitest'
import { jsonBody } from './client'

describe('JSON request helper', () => {
  it('uses POST by default and allows an explicit PUT method', () => {
    expect(jsonBody({ id: 'profile' })).toEqual({
      method: 'POST',
      body: '{"id":"profile"}',
    })
    expect(jsonBody({ profile_id: 'profile' }, 'PUT')).toEqual({
      method: 'PUT',
      body: '{"profile_id":"profile"}',
    })
  })
})

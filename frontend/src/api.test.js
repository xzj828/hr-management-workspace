import { describe, expect, it } from 'vitest'
import { listItems } from './api'

describe('listItems', () => {
  it('supports DRF paginated payloads', () => {
    expect(listItems({ count: 2, results: [{ id: 1 }, { id: 2 }] })).toHaveLength(2)
  })

  it('keeps plain arrays unchanged', () => {
    const items = [{ id: 1 }]
    expect(listItems(items)).toBe(items)
  })
})

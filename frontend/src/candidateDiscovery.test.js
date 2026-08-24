import { describe, expect, it } from 'vitest'
import { discoveryPayload, discoverySyncMessage } from './candidateDiscovery'

describe('candidate discovery helpers', () => {
  it('normalizes API payload identifiers', () => {
    const payload = discoveryPayload({ accountId: '3', jobId: '8', mode: 'search', keyword: ' Vue ' })
    expect(payload).toMatchObject({ boss_account: 3, job: 8, mode: 'search', keyword: 'Vue' })
    expect(payload.request_id).toBeTruthy()
  })

  it('summarizes discovery sync', () => {
    expect(discoverySyncMessage({ sync: { created: 2, updated: 3, total: 5 } })).toBe('新增 2 · 更新 3 · 共 5 位候选人')
  })
})

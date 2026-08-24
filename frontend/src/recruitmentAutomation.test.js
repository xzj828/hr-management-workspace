import { describe, expect, test } from 'vitest'

import { availableActions, loginStatusLabel } from './recruitmentAutomation'


describe('recruitment automation policy', () => {
  test('requires human handling for token failures', () => {
    expect(loginStatusLabel('token_invalid')).toBe('登录二维码已失效，请重新打开登录浏览器')
  })

  test('exposes read-only sync but never direct outbound actions', () => {
    expect(availableActions({ active: true, has_active_task: false })).toEqual([
      'open_login', 'check_status', 'sync_positions', 'sync_conversations',
    ])
  })

  test('disables actions while an account task is active', () => {
    expect(availableActions({ active: true, has_active_task: true })).toEqual([])
    expect(availableActions({ active: false, has_active_task: false })).toEqual([])
  })
})

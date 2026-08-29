import { describe, expect, test } from 'vitest'

import { availableActions, loginStatusLabel, taskStatusLabels } from './recruitmentAutomation'


describe('recruitment automation policy', () => {
  test('requires human handling for token failures', () => {
    expect(loginStatusLabel('token_invalid')).toBe('登录二维码已失效，请重新打开登录浏览器')
  })

  test('exposes read-only sync but never direct outbound actions', () => {
    expect(availableActions({ active: true, has_active_task: false })).toEqual([
      'check_status', 'open_login', 'sync_positions', 'sync_conversations',
    ])
  })

  test('keeps independent status checks available while an account task is active', () => {
    expect(availableActions({ active: true, has_active_task: true })).toEqual(['check_status'])
    expect(availableActions({ active: false, has_active_task: false })).toEqual([])
  })

  test('uses a readable label while a task is cancelling', () => {
    expect(taskStatusLabels.cancel_requested).toBe('正在取消')
  })
})

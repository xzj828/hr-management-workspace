import { describe, expect, it } from 'vitest'
import { apiErrorMessage, listItems } from './api'

describe('apiErrorMessage', () => {
  it('reads DRF list errors instead of hiding them behind a generic message', () => {
    expect(apiErrorMessage(['该 BOSS 账号今日自动化用量已达上限']))
      .toBe('该 BOSS 账号今日自动化用量已达上限')
  })

  it('flattens field errors and removes duplicate messages', () => {
    expect(apiErrorMessage({
      config: ['目标数量无效'],
      workflow_version: ['目标数量无效', '自定义流程未启用'],
    })).toBe('目标数量无效；自定义流程未启用')
  })

  it('prefers detail and keeps a fallback for non-JSON failures', () => {
    expect(apiErrorMessage({ detail: '登录已失效', ignored: '不应显示' })).toBe('登录已失效')
    expect(apiErrorMessage(new Blob())).toBe('请求失败')
  })
})

describe('listItems', () => {
  it('supports DRF paginated payloads', () => {
    expect(listItems({ count: 2, results: [{ id: 1 }, { id: 2 }] })).toHaveLength(2)
  })

  it('keeps plain arrays unchanged', () => {
    const items = [{ id: 1 }]
    expect(listItems(items)).toBe(items)
  })
})

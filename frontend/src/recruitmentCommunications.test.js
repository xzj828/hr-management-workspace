import { describe, expect, it } from 'vitest'
import { communicationPayload, defaultMessage, interviewMessage } from './recruitmentCommunications'

describe('recruitment communications', () => {
  it('builds editable simple message defaults', () => {
    expect(defaultMessage('greet', 'Vue 前端工程师')).toContain('Vue 前端工程师')
    expect(defaultMessage('request_resume')).toContain('PDF 简历')
  })

  it('builds a structured interview snapshot', () => {
    const invitation = {
      interview_at: '2026-08-28T10:00', mode: 'online', location: '腾讯会议 123',
      contact_name: 'HR 小周', note: '请提前五分钟进入',
    }
    expect(interviewMessage(invitation)).toContain('2026/08/28')
    expect(interviewMessage(invitation)).toContain('腾讯会议 123')
  })

  it('creates API payload from selected applications', () => {
    const payload = communicationPayload({
      accountId: 7, applicationIds: [11, 12], action: 'greet', message: '你好', requestId: 'r-1',
    })
    expect(payload).toEqual({
      boss_account: 7, application_ids: [11, 12], action: 'greet', message: '你好',
      request_id: 'r-1', invitation: {},
    })
  })
})


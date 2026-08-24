export const communicationActions = [
  { key: 'greet', label: '打招呼' },
  { key: 'request_resume', label: '索要简历' },
  { key: 'send_interview', label: '面试邀约' },
]

export function defaultMessage(action, jobTitle = '') {
  if (action === 'request_resume') return '你好，方便发送一份最新版 PDF 简历吗？谢谢。'
  if (action === 'send_interview') return ''
  return `你好，我们正在招聘${jobTitle || '相关岗位'}，你的经历与岗位比较匹配，想和你进一步沟通。`
}

export function interviewMessage(invitation) {
  const value = invitation.interview_at ? new Date(invitation.interview_at) : null
  const date = value && !Number.isNaN(value.getTime())
    ? `${value.getFullYear()}/${String(value.getMonth() + 1).padStart(2, '0')}/${String(value.getDate()).padStart(2, '0')} ${String(value.getHours()).padStart(2, '0')}:${String(value.getMinutes()).padStart(2, '0')}`
    : '待确认'
  const mode = invitation.mode === 'offline' ? '线下面试' : '线上面试'
  const note = invitation.note ? `；备注：${invitation.note}` : ''
  return `你好，邀请你于 ${date} 参加${mode}。地点/链接：${invitation.location}；联系人：${invitation.contact_name}${note}`
}

export function communicationPayload({ accountId, applicationIds, action, message, requestId, invitation = {} }) {
  return {
    boss_account: Number(accountId),
    application_ids: applicationIds.map(Number),
    action,
    message: String(message || '').trim(),
    request_id: requestId,
    invitation: action === 'send_interview' ? invitation : {},
  }
}

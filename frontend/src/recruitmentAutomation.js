const LOGIN_STATUS_LABELS = {
  unknown: '尚未检查',
  browser_stopped: '隔离浏览器未启动',
  waiting_login: '等待人工登录',
  waiting_human: '等待人工处理',
  ready: '已登录，可执行只读同步',
  token_invalid: '登录二维码已失效，请重新打开登录浏览器',
  risk_control: '需要在隔离浏览器中完成人工验证',
  error: '状态检查异常',
}

export const actionLabels = {
  open_login: '打开登录浏览器',
  check_status: '检查状态',
  sync_positions: '同步职位',
}

export const taskStatusLabels = {
  pending: '等待执行',
  leased: 'Worker 已领取',
  running: '正在执行',
  waiting_human: '等待人工处理',
  succeeded: '已完成',
  failed: '执行失败',
  cancelled: '已取消',
}

export function loginStatusLabel(status) {
  return LOGIN_STATUS_LABELS[status] || LOGIN_STATUS_LABELS.unknown
}

export function availableActions(account) {
  if (!account?.active || account.has_active_task) return []
  return ['open_login', 'check_status', 'sync_positions']
}

export function accountDisplayStatus(account) {
  return account?.verification_status || account?.login_status || 'unknown'
}

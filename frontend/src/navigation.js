export const modules = [
  { id: 'recruitment', label: '招聘管理', routeName: 'recruitment-dashboard' },
  { id: 'attendance', label: '考勤管理', routeName: 'attendance-dashboard' },
]

const navigation = {
  recruitment: [
    { name: 'recruitment-dashboard', label: '招聘看板', icon: '⌁' },
    { name: 'recruitment-jobs', label: '职位管理', icon: '▣' },
    { name: 'recruitment-candidates', label: '候选人', icon: '◎' },
    { name: 'recruitment-pipeline', label: '招聘流程', icon: '◇' },
    { name: 'recruitment-automation', label: '自动化任务', icon: '⇄' },
    { name: 'recruitment-resumes', label: '简历中心', icon: '▤' },
  ],
  attendance: [
    { name: 'attendance-dashboard', label: '考勤看板', icon: '⌁' },
    { name: 'employees', label: '人员管理', icon: '◎' },
    { name: 'imports', label: '导入中心', icon: '⇧' },
    { name: 'results', label: '核算结果', icon: '✓' },
    { name: 'suspicions', label: '异常审核', icon: '!' },
    { name: 'settings', label: '规则与标签', icon: '⚙' },
  ],
}

const storagePrefix = 'ximing-hr:last-route:'

function moduleDefinition(moduleId) {
  return modules.find((module) => module.id === moduleId)
}

export function moduleDestination(moduleId) {
  const module = moduleDefinition(moduleId) || modules.find((item) => item.id === 'attendance')
  return sessionStorage.getItem(`${storagePrefix}${module.id}`) || module.routeName
}

export function rememberModuleRoute(route) {
  const moduleId = moduleForRoute(route)
  const allowedNames = navigationForModule(moduleId).map((item) => item.name)
  if (allowedNames.includes(route.name)) {
    sessionStorage.setItem(`${storagePrefix}${moduleId}`, route.name)
  }
}

export function resetRememberedModuleRoutes() {
  modules.forEach((module) => sessionStorage.removeItem(`${storagePrefix}${module.id}`))
}

export function moduleForRoute(route) {
  return route.meta?.module || 'attendance'
}

export function navigationForModule(moduleId) {
  return navigation[moduleId] || navigation.attendance
}

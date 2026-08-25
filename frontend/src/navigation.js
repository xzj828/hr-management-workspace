export const modules = [
  { id: 'recruitment', label: '招聘管理', routeName: 'recruitment-workbench', icon: 'briefcase' },
  { id: 'attendance', label: '考勤管理', routeName: 'attendance-dashboard', icon: 'calendar-check' },
]

const navigation = {
  recruitment: [
    { name: 'recruitment-workbench', label: '招聘作业台', icon: 'briefcase', scope: 'job' },
    { name: 'recruitment-results', label: '结果中心', icon: 'dashboard', scope: 'job' },
    { name: 'recruitment-admin', label: '管理后台', icon: 'sliders', scope: 'global' },
  ],
  attendance: [
    { name: 'attendance-dashboard', label: '考勤看板', icon: 'dashboard' },
    { name: 'employees', label: '人员管理', icon: 'users' },
    { name: 'imports', label: '导入中心', icon: 'upload' },
    { name: 'results', label: '核算结果', icon: 'calculator-check' },
    { name: 'suspicions', label: '异常审核', icon: 'alert-circle' },
    { name: 'settings', label: '规则与标签', icon: 'sliders' },
  ],
}

const storagePrefix = 'ximing-hr:last-route:'

function moduleDefinition(moduleId) {
  return modules.find((module) => module.id === moduleId)
}

export function moduleDestination(moduleId) {
  const module = moduleDefinition(moduleId) || modules.find((item) => item.id === 'attendance')
  const remembered = sessionStorage.getItem(`${storagePrefix}${module.id}`)
  const allowedNames = navigationForModule(module.id).map((item) => item.name)
  return allowedNames.includes(remembered) ? remembered : module.routeName
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

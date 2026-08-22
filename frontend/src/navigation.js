export const modules = [
  { id: 'recruitment', label: '招聘管理', routeName: 'recruitment-dashboard', icon: 'briefcase' },
  { id: 'attendance', label: '考勤管理', routeName: 'attendance-dashboard', icon: 'calendar-check' },
]

const navigation = {
  recruitment: [
    { name: 'recruitment-dashboard', label: '招聘看板', icon: 'dashboard' },
    { name: 'recruitment-jobs', label: '职位管理', icon: 'briefcase' },
    { name: 'recruitment-candidates', label: '候选人', icon: 'user' },
    { name: 'recruitment-pipeline', label: '招聘流程', icon: 'workflow' },
    { name: 'recruitment-automation', label: '自动化任务', icon: 'refresh' },
    { name: 'recruitment-resumes', label: '简历中心', icon: 'document' },
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

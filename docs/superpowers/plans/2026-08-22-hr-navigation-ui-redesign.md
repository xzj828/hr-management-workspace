# HR Navigation UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the two HR business modules into the existing left sidebar and render each module's six page links as a restrained, single-line top navigation in the content workspace.

**Architecture:** Keep `frontend/src/navigation.js` as the only navigation data source and add small helpers for remembering the last route visited inside each module. Keep `AppLayout.vue` responsible for composition, extract the account dropdown into a focused component, and preserve all existing route names and URLs. The redesign is desktop-first; narrow desktop windows retain the left rail while the top navigation scrolls horizontally.

**Tech Stack:** Vue 3 Composition API, Vue Router 4, Pinia 3, Vitest, Vue Test Utils, Vite, Django staticfiles/WhiteNoise.

---

## File map

- `frontend/src/navigation.js` — module definitions, per-module page links, and current-session last-route helpers.
- `frontend/src/navigation.test.js` — pure tests for module/page mappings and last-route behavior.
- `frontend/src/components/UserAccountMenu.vue` — avatar/name trigger and compact account dropdown.
- `frontend/src/components/UserAccountMenu.test.js` — dropdown visibility, accessibility state, and emitted actions.
- `frontend/src/components/AppLayout.vue` — left module rail, contextual top navigation, Copilot entry, and page outlet.
- `frontend/src/components/AppLayout.test.js` — verifies navigation is rendered in the correct regions.
- `frontend/src/styles.css` — desktop visual hierarchy, horizontal overflow, dropdown styles, and removal of the mobile bottom rail.
- `frontend/index.html` — update the browser title from attendance-only branding to the HR platform.

### Task 1: Add module destination memory to the navigation source

**Files:**
- Modify: `frontend/src/navigation.js`
- Modify: `frontend/src/navigation.test.js`

- [ ] **Step 1: Write failing navigation-state tests**

Append these imports and tests to `frontend/src/navigation.test.js`:

```javascript
import {
  moduleDestination,
  rememberModuleRoute,
  resetRememberedModuleRoutes,
} from './navigation'

describe('module destinations', () => {
  it('starts each module on its dashboard', () => {
    resetRememberedModuleRoutes()
    expect(moduleDestination('recruitment')).toBe('recruitment-dashboard')
    expect(moduleDestination('attendance')).toBe('attendance-dashboard')
  })

  it('returns to the last page visited in each module', () => {
    resetRememberedModuleRoutes()
    rememberModuleRoute({ name: 'recruitment-candidates', meta: { module: 'recruitment' } })
    rememberModuleRoute({ name: 'employees', meta: { module: 'attendance' } })

    expect(moduleDestination('recruitment')).toBe('recruitment-candidates')
    expect(moduleDestination('attendance')).toBe('employees')
  })

  it('ignores route names that do not belong to the declared module', () => {
    resetRememberedModuleRoutes()
    rememberModuleRoute({ name: 'employees', meta: { module: 'recruitment' } })
    expect(moduleDestination('recruitment')).toBe('recruitment-dashboard')
  })
})
```

- [ ] **Step 2: Run the focused test and verify RED**

Run from `frontend`:

```powershell
npm test -- src/navigation.test.js
```

Expected: FAIL because `moduleDestination`, `rememberModuleRoute`, and `resetRememberedModuleRoutes` are not exported.

- [ ] **Step 3: Implement the minimal route-memory helpers**

Add this after the `navigation` object in `frontend/src/navigation.js`:

```javascript
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
```

Use `sessionStorage`, not `localStorage`, so destinations survive a refresh in the same browser tab but do not become a permanent user preference.

- [ ] **Step 4: Run the navigation tests and verify GREEN**

```powershell
npm test -- src/navigation.test.js
```

Expected: all navigation tests pass.

- [ ] **Step 5: Commit navigation state**

```powershell
git add frontend/src/navigation.js frontend/src/navigation.test.js
git commit -m "feat: remember hr module destinations"
```

### Task 2: Create the compact account dropdown

**Files:**
- Create: `frontend/src/components/UserAccountMenu.vue`
- Create: `frontend/src/components/UserAccountMenu.test.js`

- [ ] **Step 1: Write the failing component tests**

Create `frontend/src/components/UserAccountMenu.test.js`:

```javascript
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import UserAccountMenu from './UserAccountMenu.vue'

const user = {
  username: 'hr-user',
  first_name: '小王',
  role_label: 'HR',
}

describe('UserAccountMenu', () => {
  it('keeps account actions hidden until the user trigger is opened', async () => {
    const wrapper = mount(UserAccountMenu, { props: { user } })
    const trigger = wrapper.get('[data-testid="account-trigger"]')

    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)

    await trigger.trigger('click')

    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('[role="menu"]').text()).toContain('HR')
  })

  it('emits model settings and logout actions', async () => {
    const wrapper = mount(UserAccountMenu, { props: { user } })
    await wrapper.get('[data-testid="account-trigger"]').trigger('click')
    await wrapper.get('[data-testid="model-settings"]').trigger('click')
    expect(wrapper.emitted('model-settings')).toHaveLength(1)

    await wrapper.get('[data-testid="account-trigger"]').trigger('click')
    await wrapper.get('[data-testid="logout"]').trigger('click')
    expect(wrapper.emitted('logout')).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
npm test -- src/components/UserAccountMenu.test.js
```

Expected: FAIL because `UserAccountMenu.vue` does not exist.

- [ ] **Step 3: Implement the account dropdown**

Create `frontend/src/components/UserAccountMenu.vue`:

```vue
<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'

const props = defineProps({
  user: { type: Object, default: null },
})
const emit = defineEmits(['logout', 'model-settings'])
const open = ref(false)
const displayName = computed(() => props.user?.first_name || props.user?.username || '用户')
const initial = computed(() => displayName.value.slice(0, 1).toUpperCase())

function close() {
  open.value = false
}

function onDocumentClick(event) {
  if (!event.target.closest('.account-menu')) close()
}

function onKeydown(event) {
  if (event.key === 'Escape') close()
}

document.addEventListener('click', onDocumentClick)
document.addEventListener('keydown', onKeydown)
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onKeydown)
})

function choose(action) {
  close()
  emit(action)
}
</script>

<template>
  <div class="account-menu">
    <button
      class="account-menu__trigger"
      data-testid="account-trigger"
      type="button"
      :aria-expanded="String(open)"
      aria-haspopup="menu"
      @click.stop="open = !open"
    >
      <span class="avatar">{{ initial }}</span>
      <span class="account-menu__name">{{ displayName }}</span>
      <span class="account-menu__chevron" aria-hidden="true">⌄</span>
    </button>
    <div v-if="open" class="account-menu__panel" role="menu">
      <div class="account-menu__identity">
        <strong>{{ displayName }}</strong>
        <span>{{ user?.role_label || '普通用户' }}</span>
      </div>
      <button data-testid="model-settings" role="menuitem" type="button" @click="choose('model-settings')">模型配置</button>
      <button data-testid="logout" role="menuitem" type="button" @click="choose('logout')">退出登录</button>
    </div>
  </div>
</template>
```

- [ ] **Step 4: Run the focused test and verify GREEN**

```powershell
npm test -- src/components/UserAccountMenu.test.js
```

Expected: both account-menu tests pass.

- [ ] **Step 5: Commit the account menu**

```powershell
git add frontend/src/components/UserAccountMenu.vue frontend/src/components/UserAccountMenu.test.js
git commit -m "feat: add compact hr account menu"
```

### Task 3: Move modules left and page links to the top bar

**Files:**
- Create: `frontend/src/components/AppLayout.test.js`
- Modify: `frontend/src/components/AppLayout.vue`

- [ ] **Step 1: Write a failing layout hierarchy test**

Create `frontend/src/components/AppLayout.test.js`:

```javascript
import { reactive } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'

const route = reactive({
  name: 'recruitment-dashboard',
  meta: { module: 'recruitment', title: '招聘看板' },
})

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRoute: () => route,
    useRouter: () => ({ push: vi.fn() }),
  }
})

import AppLayout from './AppLayout.vue'

describe('AppLayout navigation hierarchy', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('renders two modules in the sidebar and recruitment pages in the top bar', () => {
    const wrapper = mount(AppLayout, {
      global: {
        stubs: {
          RouterLink: { props: ['to'], template: '<a><slot /></a>' },
          RouterView: true,
          RecruitmentCopilotDrawer: true,
        },
      },
    })

    expect(wrapper.findAll('.module-nav .nav-item').map((item) => item.text())).toEqual([
      '招聘管理',
      '考勤管理',
    ])
    expect(wrapper.findAll('.top-navigation__link').map((item) => item.text())).toEqual([
      '招聘看板',
      '职位管理',
      '候选人',
      '招聘流程',
      '自动化任务',
      '简历中心',
    ])
    expect(wrapper.find('.module-switcher').exists()).toBe(false)
    expect(wrapper.find('.topbar h1').exists()).toBe(false)
  })
})
```

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
npm test -- src/components/AppLayout.test.js
```

Expected: FAIL because the current sidebar renders six page links and the top bar renders `.module-switcher`.

- [ ] **Step 3: Replace `AppLayout.vue` with the approved hierarchy**

Use this complete component in `frontend/src/components/AppLayout.vue`:

```vue
<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  modules,
  moduleDestination,
  moduleForRoute,
  navigationForModule,
  rememberModuleRoute,
} from '@/navigation'
import RecruitmentCopilotDrawer from '@/components/RecruitmentCopilotDrawer.vue'
import UserAccountMenu from '@/components/UserAccountMenu.vue'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const collapsed = ref(false)
const copilotOpen = ref(false)

const currentModule = computed(() => moduleForRoute(route))
const topNavigation = computed(() => navigationForModule(currentModule.value))

watch(
  () => route.name,
  () => rememberModuleRoute(route),
  { immediate: true },
)

function moduleRoute(moduleId) {
  return { name: moduleDestination(moduleId) }
}

async function signOut() {
  await auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="shell" :class="{ 'shell--collapsed': collapsed }">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand__mark">XM</div>
        <div class="brand__text"><strong>西鸣人事</strong><span>People OS</span></div>
      </div>
      <nav class="module-nav" aria-label="业务模块">
        <router-link
          v-for="module in modules"
          :key="module.id"
          :to="moduleRoute(module.id)"
          class="nav-item"
          :class="{ 'nav-item--active': currentModule === module.id }"
        >
          <span class="nav-item__icon">{{ module.id === 'recruitment' ? '◇' : '⌁' }}</span>
          <span class="nav-item__label">{{ module.label }}</span>
        </router-link>
      </nav>
      <div class="sidebar__foot">
        <div class="system-state"><i></i><span>本地服务运行中</span></div>
        <button class="collapse-button" type="button" @click="collapsed = !collapsed">{{ collapsed ? '›' : '‹ 收起导航' }}</button>
      </div>
    </aside>

    <main class="workspace">
      <header class="topbar">
        <nav class="top-navigation" :aria-label="`${currentModule === 'recruitment' ? '招聘' : '考勤'}功能`">
          <router-link
            v-for="item in topNavigation"
            :key="item.name"
            :to="{ name: item.name }"
            class="top-navigation__link"
          >{{ item.label }}</router-link>
        </nav>
        <div class="topbar__actions">
          <button v-if="currentModule === 'recruitment'" class="copilot-entry" type="button" @click="copilotOpen = true">
            <span aria-hidden="true">✦</span> Copilot
          </button>
          <UserAccountMenu :user="auth.user" @model-settings="copilotOpen = true" @logout="signOut" />
        </div>
      </header>
      <section class="page-container"><router-view /></section>
    </main>
    <RecruitmentCopilotDrawer v-if="copilotOpen" @close="copilotOpen = false" />
  </div>
</template>
```

- [ ] **Step 4: Run the focused layout and navigation tests**

```powershell
npm test -- src/components/AppLayout.test.js src/navigation.test.js
```

Expected: layout hierarchy and route-memory tests pass.

- [ ] **Step 5: Commit the layout hierarchy**

```powershell
git add frontend/src/components/AppLayout.vue frontend/src/components/AppLayout.test.js
git commit -m "feat: invert hr navigation hierarchy"
```

### Task 4: Apply the desktop-first visual system

**Files:**
- Modify: `frontend/src/styles.css`
- Modify: `frontend/index.html`

- [ ] **Step 1: Replace the old module-switcher and topbar styles**

Remove `.module-switcher` rules. Replace the existing `.topbar`, `.topbar__actions`, `.user-chip`, and related mobile topbar rules with:

```css
.topbar {
  position: sticky;
  top: 0;
  z-index: 15;
  height: 64px;
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  gap: 22px;
  padding: 0 28px;
  background: rgba(255,255,255,.94);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(14px);
}
.top-navigation { min-width: 0; display: flex; align-items: stretch; gap: 26px; overflow-x: auto; scrollbar-width: none; }
.top-navigation::-webkit-scrollbar { display: none; }
.top-navigation__link { position: relative; min-width: max-content; display: inline-flex; align-items: center; color: #425066; font-size: 13px; font-weight: 600; white-space: nowrap; }
.top-navigation__link:hover { color: var(--ink); }
.top-navigation__link.router-link-exact-active { color: var(--teal-dark); }
.top-navigation__link.router-link-exact-active::after { content: ''; position: absolute; left: 0; right: 0; bottom: 0; height: 2px; background: var(--teal); }
.topbar__actions { flex: 0 0 auto; display: flex; align-items: center; gap: 14px; background: #fff; }
.copilot-entry { display: inline-flex; align-items: center; gap: 6px; padding: 7px 2px; color: var(--muted); background: transparent; border: 0; font-size: 12px; font-weight: 700; }
.copilot-entry:hover { color: var(--teal-dark); }
.module-nav { display: flex; flex-direction: column; gap: 6px; }
.nav-item--active { color: #ecfdfb; background: rgba(15,159,143,.16); }
.nav-item--active::before { content: ''; position: absolute; left: -14px; width: 3px; height: 24px; border-radius: 0 3px 3px 0; background: #25c2b0; }
```

- [ ] **Step 2: Add account-menu styles**

Append:

```css
.account-menu { position: relative; }
.account-menu__trigger { min-height: 40px; display: flex; align-items: center; gap: 9px; padding: 0; color: var(--ink); background: transparent; border: 0; }
.account-menu__name { max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; font-weight: 700; }
.account-menu__chevron { color: #94a3b8; font-size: 12px; }
.account-menu__panel { position: absolute; right: 0; top: calc(100% + 8px); width: 190px; overflow: hidden; padding: 6px; background: #fff; border: 1px solid var(--line); border-radius: 11px; box-shadow: 0 16px 42px rgba(15,23,42,.14); }
.account-menu__identity { display: flex; flex-direction: column; padding: 10px 11px; border-bottom: 1px solid var(--line); }
.account-menu__identity strong { color: var(--ink); font-size: 12px; }
.account-menu__identity span { margin-top: 3px; color: var(--muted); font-size: 10px; }
.account-menu__panel button { width: 100%; min-height: 36px; display: flex; align-items: center; padding: 0 11px; color: var(--slate); background: transparent; border: 0; border-radius: 7px; font-size: 11px; text-align: left; }
.account-menu__panel button:hover, .account-menu__panel button:focus-visible { color: var(--ink); background: #f3f6f8; outline: none; }
```

- [ ] **Step 3: Remove the mobile bottom-navigation transformation**

In the existing `@media (max-width: 680px)` block, delete rules that change `.shell` to `display: block`, move `.sidebar` to the bottom, hide `.brand`, and turn `.nav-list` into a horizontal row. Keep the desktop grid at narrow widths and add:

```css
@media (max-width: 900px) {
  .shell { grid-template-columns: 76px minmax(0,1fr); }
  .topbar { padding: 0 18px; gap: 14px; }
  .top-navigation { gap: 20px; }
  .account-menu__name, .account-menu__chevron { display: none; }
  .page-container { padding: 22px 20px 34px; }
}
```

The left rail must remain on the left at every supported width.

- [ ] **Step 4: Update the browser title**

Change `frontend/index.html`:

```html
<title>西鸣人事管理系统</title>
```

- [ ] **Step 5: Run the full frontend test suite and production build**

```powershell
npm test
npm run build
```

Expected: all Vitest tests pass and Vite writes the production bundle to `backend/frontend_dist`.

- [ ] **Step 6: Commit the visual redesign**

```powershell
git add frontend/src/styles.css frontend/index.html
git commit -m "style: refine hr desktop navigation"
```

### Task 5: Deploy and verify the redesigned shell

**Files:**
- Verify: `backend/frontend_dist/`
- Verify: `backend/staticfiles/`
- Verify: Git working tree

- [ ] **Step 1: Run backend regression tests**

From the repository root:

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py test accounts attendance recruitment --verbosity 1
```

Expected: all existing Django tests pass.

- [ ] **Step 2: Collect the freshly built static assets**

The order is mandatory: `npm run build` must finish before this command.

```powershell
$env:DJANGO_DEBUG='0'
.\.venv\Scripts\python.exe .\backend\manage.py collectstatic --noinput
```

Expected: new hashed JS and CSS assets are copied or post-processed into `backend/staticfiles`.

- [ ] **Step 3: Restart only the project Waitress process on port 8000**

Resolve the listener and confirm its command line belongs to this repository before stopping it:

```powershell
$expectedPython = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction Stop | Select-Object -First 1
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
if ($process.CommandLine -notlike "*$expectedPython*waitress*") { throw 'Port 8000 is not owned by this HR project' }
$parentId = $process.ParentProcessId
Stop-Process -Id $listener.OwningProcess
if ($parentId -and (Get-Process -Id $parentId -ErrorAction SilentlyContinue)) { Stop-Process -Id $parentId }
Start-Sleep -Milliseconds 500
$env:DJANGO_DEBUG='0'
$python = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
$backend = (Resolve-Path -LiteralPath '.\backend').Path
Start-Process -FilePath $python -ArgumentList @('-m','waitress','--listen=0.0.0.0:8000','--threads=8','config.wsgi:application') -WorkingDirectory $backend -WindowStyle Hidden
```

Expected: a new listener appears on port 8000.

- [ ] **Step 4: Verify HTML, JS, and CSS responses**

```powershell
$page = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/login' -UseBasicParsing -TimeoutSec 5
$scriptPath = [regex]::Match($page.Content, 'src="([^"]+\.js)"').Groups[1].Value
$stylePath = [regex]::Match($page.Content, 'href="([^"]+\.css)"').Groups[1].Value
$script = Invoke-WebRequest -Uri "http://127.0.0.1:8000$scriptPath" -UseBasicParsing -TimeoutSec 5
$style = Invoke-WebRequest -Uri "http://127.0.0.1:8000$stylePath" -UseBasicParsing -TimeoutSec 5
$page.StatusCode
$script.Headers['Content-Type']
$style.Headers['Content-Type']
```

Expected: status `200`, JavaScript content type, and CSS content type. Neither asset may return `text/html`.

- [ ] **Step 5: Perform browser acceptance checks**

Open `http://127.0.0.1:8000/`, log in, and verify:

```text
Left rail: 西鸣人事 brand, 招聘管理, 考勤管理, service status, collapse control
Recruitment top nav: 招聘看板, 职位管理, 候选人, 招聘流程, 自动化任务, 简历中心
Attendance top nav: 考勤看板, 人员管理, 导入中心, 核算结果, 异常审核, 规则与标签
Top bar: no page title, no module pills, one-line page links, compact Copilot, compact account menu
Content: page title remains inside each page body
Narrow desktop: left rail stays left and top links scroll without wrapping
```

Expected: no blank page, no overlapping navigation, and no JavaScript page errors.

- [ ] **Step 6: Verify repository cleanliness and record final commits**

```powershell
git status --short
git log --oneline -6
```

Expected: no uncommitted source changes; static build outputs remain ignored.

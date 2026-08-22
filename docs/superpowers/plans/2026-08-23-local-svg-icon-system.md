# Local SVG Icon System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace character-based icons with a cohesive, locally bundled linear SVG icon system across recruitment and attendance without changing the current information architecture.

**Architecture:** A single `AppIcon` Vue component renders sanitized path data from a local semantic registry. Navigation and page components consume stable icon names, while CSS controls size and state through `currentColor`; no browser-time request is made to Iconfont or any CDN.

**Tech Stack:** Vue 3, Vite, Vitest, Vue Test Utils, local SVG path data sourced from Iconfont, Django/WhiteNoise static delivery

---

## File Structure

- Create `frontend/src/icons/source/*.svg`: sanitized Iconfont source SVGs named by business semantics.
- Create `frontend/scripts/build-icons.mjs`: deterministic converter from local SVGs to the JavaScript path registry.
- Create `frontend/src/icons/iconPaths.js`: generated local icon registry with semantic names, view boxes, and path data.
- Create `frontend/src/components/AppIcon.vue`: the only SVG rendering component; handles size, title, and decorative accessibility.
- Create `frontend/src/components/AppIcon.test.js`: registry/rendering/current-color/accessibility tests.
- Modify `frontend/src/navigation.js`: replace character glyph values with semantic icon names and add module icons.
- Modify `frontend/src/navigation.test.js`: assert the navigation-to-icon contract.
- Modify `frontend/src/components/AppLayout.vue`: render module, top-navigation, collapse, and Copilot icons.
- Modify `frontend/src/components/AppLayout.test.js`: verify icon rendering and active navigation behavior.
- Modify `frontend/src/components/ModalPanel.vue`, `RecruitmentDetailDrawer.vue`, and `UserAccountMenu.vue`: replace close and chevron characters.
- Modify `frontend/src/views/ImportsView.vue`, `DashboardView.vue`, `SettingsView.vue`, and `SuspicionsView.vue`: replace attendance symbols and add meaningful state icons.
- Modify `frontend/src/views/recruitment/RecruitmentAutomationView.vue` and `RecruitmentResumesView.vue`: replace more/preview/download symbols and add restrained action icons.
- Modify `frontend/src/styles.css`: normalize icon dimensions, alignment, color inheritance, and hover/active transitions.
- Create `frontend/src/icons/SOURCES.md`: record Iconfont search term, item URL or asset identifier, retrieval date, and semantic name for every vendored icon.
- Modify `frontend/package.json`: expose the deterministic `icons:build` command.

### Task 1: Build the Local Icon Registry and Renderer

**Files:**
- Create: `frontend/src/icons/iconPaths.js`
- Create: `frontend/src/icons/source/*.svg`
- Create: `frontend/scripts/build-icons.mjs`
- Create: `frontend/src/icons/SOURCES.md`
- Create: `frontend/src/components/AppIcon.vue`
- Create: `frontend/src/components/AppIcon.test.js`
- Modify: `frontend/package.json`

- [ ] **Step 1: Select and sanitize one coherent Iconfont line family**

From Iconfont, download SVG versions for these exact semantic names:

```text
dashboard, briefcase, user, users, workflow, refresh,
document, calendar-check, upload, calculator-check, alert-circle,
sliders, search, filter, download, plus, close, more-horizontal,
eye, chevron-down, chevron-left, chevron-right, arrow-right,
clock, check-circle, shield, sparkles
```

For every SVG, preserve its `viewBox` and path geometry, remove width/height/style/class attributes, remove hard-coded color because the component supplies `currentColor`, and remove metadata, scripts and transforms that are not required for rendering. Record one table row per icon in `frontend/src/icons/SOURCES.md` with the columns `Semantic name`, `Iconfont source`, `Search term`, and `Retrieved`; the source cell must contain the real item URL or asset identifier and the date must be `2026-08-23`.

Do not retain any asset whose author/license metadata does not permit use in this project; select another Iconfont item instead.

- [ ] **Step 2: Write the failing component tests**

Create `frontend/src/components/AppIcon.test.js`:

```js
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppIcon from './AppIcon.vue'

describe('AppIcon', () => {
  it('renders a registered icon using currentColor', () => {
    const wrapper = mount(AppIcon, { props: { name: 'briefcase', size: 20 } })
    expect(wrapper.get('svg').attributes('width')).toBe('20')
    expect(wrapper.get('svg').attributes('height')).toBe('20')
    expect(wrapper.get('svg').attributes('style')).toContain('color: inherit')
    expect(wrapper.findAll('path, line, rect, circle, polyline').length).toBeGreaterThan(0)
  })

  it('hides decorative icons from assistive technology', () => {
    const wrapper = mount(AppIcon, { props: { name: 'dashboard' } })
    expect(wrapper.get('svg').attributes('aria-hidden')).toBe('true')
  })

  it('exposes a title for meaningful standalone icons', () => {
    const wrapper = mount(AppIcon, { props: { name: 'alert-circle', label: '异常提醒' } })
    expect(wrapper.get('svg').attributes('role')).toBe('img')
    expect(wrapper.get('title').text()).toBe('异常提醒')
  })

  it('does not silently render an unknown name', () => {
    expect(() => mount(AppIcon, { props: { name: 'not-real' } })).toThrow(/Unknown icon/)
  })
})
```

- [ ] **Step 3: Run the focused test and verify failure**

Run:

```powershell
cd frontend
npx vitest run src/components/AppIcon.test.js
```

Expected: FAIL because `AppIcon.vue` does not exist.

- [ ] **Step 4: Implement deterministic registry generation**

Create `frontend/scripts/build-icons.mjs`:

```js
import { readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const sourceDir = resolve(root, 'src/icons/source')
const outputFile = resolve(root, 'src/icons/iconPaths.js')
const expectedNames = [
  'alert-circle', 'arrow-right', 'briefcase', 'calculator-check',
  'calendar-check', 'check-circle', 'chevron-down', 'chevron-left',
  'chevron-right', 'clock', 'close', 'dashboard', 'document', 'download',
  'eye', 'filter', 'more-horizontal', 'plus', 'refresh', 'search', 'shield',
  'sliders', 'sparkles', 'upload', 'user', 'users', 'workflow',
]

const files = readdirSync(sourceDir).filter((name) => name.endsWith('.svg')).sort()
const actualNames = files.map((name) => name.replace(/\.svg$/, ''))
if (JSON.stringify(actualNames) !== JSON.stringify(expectedNames)) {
  throw new Error(`Icon set mismatch: ${actualNames.join(', ')}`)
}

const registry = Object.fromEntries(files.map((filename) => {
  const source = readFileSync(resolve(sourceDir, filename), 'utf8')
  if (/<script\b|on\w+=|<foreignObject\b/i.test(source)) {
    throw new Error(`Unsafe SVG content: ${filename}`)
  }
  const viewBox = source.match(/viewBox=["']([^"']+)["']/i)?.[1]
  const paths = [...source.matchAll(/<path\b[^>]*\bd=["']([^"']+)["'][^>]*>/gi)].map((match) => match[1])
  if (!viewBox || !paths.length) throw new Error(`Invalid path-only SVG: ${filename}`)
  return [filename.replace(/\.svg$/, ''), { viewBox, paths }]
}))

writeFileSync(
  outputFile,
  `export const iconPaths = Object.freeze(${JSON.stringify(registry, null, 2)})\n`,
  'utf8',
)
```

Add this script to `frontend/package.json`:

```json
"icons:build": "node scripts/build-icons.mjs"
```

Run `npm run icons:build`, inspect `frontend/src/icons/iconPaths.js`, and verify it contains all 27 keys with real path arrays.

- [ ] **Step 5: Implement the renderer**

Create `frontend/src/components/AppIcon.vue`:

```vue
<script setup>
import { computed } from 'vue'
import { iconPaths } from '@/icons/iconPaths'

const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 20 },
  label: { type: String, default: '' },
})

const icon = computed(() => {
  const definition = iconPaths[props.name]
  if (!definition) throw new Error(`Unknown icon: ${props.name}`)
  return definition
})
</script>

<template>
  <svg
    class="app-icon"
    :viewBox="icon.viewBox"
    :width="size"
    :height="size"
    style="color: inherit"
    fill="currentColor"
    :role="label ? 'img' : undefined"
    :aria-hidden="label ? undefined : 'true'"
    focusable="false"
  >
    <title v-if="label">{{ label }}</title>
    <path v-for="path in icon.paths" :key="path" :d="path" />
  </svg>
</template>
```

- [ ] **Step 6: Run the focused test and commit**

Run `npx vitest run src/components/AppIcon.test.js` from `frontend`.

Expected: 4 tests PASS.

Commit:

```powershell
git add frontend/scripts/build-icons.mjs frontend/src/icons frontend/src/components/AppIcon.vue frontend/src/components/AppIcon.test.js frontend/package.json
git commit -m "feat: add local svg icon system"
```

### Task 2: Replace Module and Top Navigation Glyphs

**Files:**
- Modify: `frontend/src/navigation.js:1-21`
- Modify: `frontend/src/navigation.test.js`
- Modify: `frontend/src/components/AppLayout.vue:1-85`
- Modify: `frontend/src/components/AppLayout.test.js`
- Modify: `frontend/src/styles.css:47-66`

- [ ] **Step 1: Extend failing navigation tests**

Assert these exact mappings:

```js
expect(modules.map(({ id, icon }) => [id, icon])).toEqual([
  ['recruitment', 'briefcase'],
  ['attendance', 'calendar-check'],
])
expect(navigationForModule('recruitment').map((item) => item.icon)).toEqual([
  'dashboard', 'briefcase', 'user', 'workflow', 'refresh', 'document',
])
expect(navigationForModule('attendance').map((item) => item.icon)).toEqual([
  'dashboard', 'users', 'upload', 'calculator-check', 'alert-circle', 'sliders',
])
```

Update `AppLayout.test.js` to assert that the active module and all top links contain `.app-icon`, and that the active top link inherits the active text color.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```powershell
npx vitest run src/navigation.test.js src/components/AppLayout.test.js
```

Expected: FAIL because navigation still contains character glyphs and top links do not render icons.

- [ ] **Step 3: Implement semantic navigation icons**

Add `icon` to module definitions and replace every navigation character with the exact names from Step 1. Import `AppIcon` in `AppLayout.vue` and render:

```vue
<AppIcon class="nav-item__icon" :name="module.icon" :size="20" />
<AppIcon :name="item.icon" :size="18" />
<AppIcon name="sparkles" :size="17" />
<AppIcon :name="collapsed ? 'chevron-right' : 'chevron-left'" :size="18" />
```

Keep the existing module and route labels visible. The collapse button text remains `收起导航` when expanded and is visually hidden when collapsed.

- [ ] **Step 4: Normalize navigation CSS**

Change `.nav-item__icon` from text-specific typography to flex alignment, add a `6px` gap inside `.top-navigation__link`, change its hover color to `var(--teal-dark)`, and add:

```css
.app-icon { display: inline-block; flex: 0 0 auto; vertical-align: -0.15em; }
.top-navigation__link { transition: color 150ms ease; }
.top-navigation__link:hover,
.top-navigation__link.router-link-exact-active { color: var(--teal-dark); }
```

- [ ] **Step 5: Run focused tests and commit**

Expected: navigation and AppLayout tests PASS.

```powershell
git add frontend/src/navigation.js frontend/src/navigation.test.js frontend/src/components/AppLayout.vue frontend/src/components/AppLayout.test.js frontend/src/styles.css
git commit -m "feat: align navigation with svg icons"
```

### Task 3: Replace Shared Control Glyphs

**Files:**
- Modify: `frontend/src/components/ModalPanel.vue`
- Modify: `frontend/src/components/RecruitmentDetailDrawer.vue`
- Modify: `frontend/src/components/UserAccountMenu.vue`
- Modify: `frontend/src/components/UserAccountMenu.test.js`
- Modify: `frontend/src/styles.css:95,382`

- [ ] **Step 1: Write failing shared-control assertions**

Extend existing component tests to require a `close` icon inside both close buttons and a `chevron-down` icon inside the account trigger. Assert that every icon-only close button has `aria-label="关闭"`.

- [ ] **Step 2: Verify tests fail**

Run:

```powershell
npx vitest run src/components/UserAccountMenu.test.js src/components/AppIcon.test.js
```

Expected: FAIL because the chevron is still a character.

- [ ] **Step 3: Replace the shared glyphs**

Import `AppIcon` and render the following exact markup patterns:

```vue
<button class="icon-button" type="button" aria-label="关闭" @click="$emit('close')">
  <AppIcon name="close" :size="18" />
</button>
```

```vue
<AppIcon class="account-menu__chevron" name="chevron-down" :size="15" />
```

Remove font-size declarations that existed only to size `×` or `⌄`; preserve the existing 34px click target.

- [ ] **Step 4: Run tests and commit**

Expected: focused tests PASS.

```powershell
git add frontend/src/components/ModalPanel.vue frontend/src/components/RecruitmentDetailDrawer.vue frontend/src/components/UserAccountMenu.vue frontend/src/components/UserAccountMenu.test.js frontend/src/styles.css
git commit -m "feat: replace shared control glyphs"
```

### Task 4: Apply Semantic Icons to Attendance Pages

**Files:**
- Modify: `frontend/src/views/ImportsView.vue`
- Modify: `frontend/src/views/DashboardView.vue`
- Modify: `frontend/src/views/SettingsView.vue`
- Modify: `frontend/src/views/SuspicionsView.vue`
- Create: `frontend/src/views/AttendanceIcons.test.js`
- Modify: `frontend/src/styles.css:253-322,497-498`

- [ ] **Step 1: Write the failing page-level test**

Create `AttendanceIcons.test.js` using shallow mounts with API and ECharts stubs. Assert these pairs:

```js
[
  ['ImportsView', 'upload'],
  ['DashboardView', 'clock'],
  ['DashboardView', 'upload'],
  ['SettingsView', 'sliders'],
  ['SettingsView', 'shield'],
  ['SuspicionsView', 'alert-circle'],
  ['SuspicionsView', 'arrow-right'],
  ['SuspicionsView', 'check-circle'],
]
```

Also assert rendered text does not contain `⇧`, `◷`, `⌘`, or standalone `✓` icon characters.

- [ ] **Step 2: Run the new test and verify failure**

Run `npx vitest run src/views/AttendanceIcons.test.js`.

Expected: FAIL because the pages still render character glyphs.

- [ ] **Step 3: Replace attendance symbols with `AppIcon`**

Use `upload` in the import drop zone, `clock` and `upload` in dashboard empty states, `sliders` for policy cards, `shield` for the role/tag notice, `alert-circle` in the review explainer, `arrow-right` in the review timeline, and `check-circle` in the completed empty state.

Policy mode labels (`标准`, `弹性`, `免考勤`, `轮班`) remain as text beside or below the shared sliders icon; do not encode those words inside the SVG.

- [ ] **Step 4: Update state-icon CSS**

Remove text-glyph font sizing and use `.app-icon` sizing instead. Preserve colored background containers. Under the existing narrow-screen rule rotate only the arrow icon wrapper:

```css
@media (max-width: 760px) {
  .review-card__timeline > .timeline-arrow { transform: rotate(90deg); text-align: center; }
}
```

- [ ] **Step 5: Run tests and commit**

Run the new test plus all existing attendance-related tests. Expected: PASS.

```powershell
git add frontend/src/views/ImportsView.vue frontend/src/views/DashboardView.vue frontend/src/views/SettingsView.vue frontend/src/views/SuspicionsView.vue frontend/src/views/AttendanceIcons.test.js frontend/src/styles.css
git commit -m "feat: add semantic attendance icons"
```

### Task 5: Apply Restrained Icons to Recruitment Actions

**Files:**
- Modify: `frontend/src/views/recruitment/RecruitmentAutomationView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentAutomationView.test.js`
- Modify: `frontend/src/views/recruitment/RecruitmentResumesView.vue`
- Modify: `frontend/src/views/recruitment/RecruitmentResumesView.test.js`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add failing recruitment assertions**

Require `more-horizontal` in the account action button, `eye` in the preview button, and `download` in the PDF link. Keep existing text visible for preview and download; the more button remains icon-only and retains `aria-label="账号操作"`.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```powershell
npx vitest run src/views/recruitment/RecruitmentAutomationView.test.js src/views/recruitment/RecruitmentResumesView.test.js
```

Expected: FAIL because the SVG icons are absent.

- [ ] **Step 3: Implement the recruitment action icons**

Render:

```vue
<AppIcon name="more-horizontal" :size="19" />
```

inside the account menu trigger, and:

```vue
<AppIcon name="eye" :size="16" /> <span>预览</span>
<AppIcon name="download" :size="16" /> <span>下载 PDF</span>
```

inside the resume actions. Add a shared `.button-with-icon` inline-flex utility with a 6px gap; do not add icons to every table text action.

- [ ] **Step 4: Run tests and commit**

Expected: both recruitment test files PASS.

```powershell
git add frontend/src/views/recruitment/RecruitmentAutomationView.vue frontend/src/views/recruitment/RecruitmentAutomationView.test.js frontend/src/views/recruitment/RecruitmentResumesView.vue frontend/src/views/recruitment/RecruitmentResumesView.test.js frontend/src/styles.css
git commit -m "feat: refine recruitment action icons"
```

### Task 6: Full Verification, Static Publishing, and Browser Acceptance

**Files:**
- Modify only if a verification failure identifies a root cause in an already touched file.

- [ ] **Step 1: Scan for remaining icon characters**

Run:

```powershell
rg -n "⌁|▣|◎|◇|⇄|▤|⇧|⚙|⌘|◷|✦|•••|>×<" frontend/src -g "*.vue" -g "*.js"
```

Expected: no icon-role character matches. Textual multiplication signs or punctuation are allowed only when they are content rather than controls.

- [ ] **Step 2: Run the complete frontend suite**

Run from `frontend`:

```powershell
npm test
npm run build
```

Expected: all Vitest tests PASS and Vite build exits 0. The existing ECharts chunk-size warning is non-blocking.

- [ ] **Step 3: Publish the new hashed static assets**

Run from `backend`:

```powershell
..\.venv\Scripts\python.exe manage.py collectstatic --noinput
```

Expected: the newly built JS and CSS asset hashes appear under `backend/staticfiles/assets`.

- [ ] **Step 4: Restart only this workspace's web and worker processes**

Resolve the listener on port 8000 and verify its command line belongs to `C:\Users\35059\OneDrive\Desktop\hr\hr` before stopping it. Restart with `scripts/start-local.ps1` using a hidden PowerShell process, then wait until `/api/auth/csrf/` returns HTTP 200.

- [ ] **Step 5: Run Edge acceptance checks**

Using headless Playwright with the installed Edge channel:

- Open `/login` and verify `#app` has rendered content.
- Log in with the existing local test/admin account only if credentials are already available in the current environment; otherwise verify the authenticated pages through the user's existing browser session.
- Inspect recruitment and attendance navigation, modal close buttons, import empty state, review state, automation account menu, and resume actions.
- Assert all SVG requests succeed, no page error occurs, and no console error is introduced by `AppIcon`.
- Confirm hover and active navigation colors resolve to the existing teal CSS color.

- [ ] **Step 6: Check the worktree and commit any verification-only fix**

Run:

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors and no uncommitted source changes. If verification required a focused fix, rerun the affected test and full suite, then commit it with a message describing that root cause.

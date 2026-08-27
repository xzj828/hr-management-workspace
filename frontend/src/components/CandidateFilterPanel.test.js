import { mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import CandidateFilterPanel from './CandidateFilterPanel.vue'
import { defaultCandidateFilters } from '@/recruitmentCandidateFilters'

const wrappers = []

function mountPanel() {
  const wrapper = mount({
    components: { CandidateFilterPanel },
    setup() {
      const filters = ref(defaultCandidateFilters())
      return { filters }
    },
    template: '<CandidateFilterPanel v-model="filters" />',
  }, { attachTo: document.body })
  wrappers.push(wrapper)
  return wrapper
}

function floatingForm() {
  return document.body.querySelector('[data-test="candidate-filter-form"]')
}

async function clickFloating(selector) {
  floatingForm().querySelector(selector).click()
  await nextTick()
}

afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
})

describe('CandidateFilterPanel', () => {
  it('starts collapsed with unlimited filters and exposes every requested filter row', async () => {
    const wrapper = mountPanel()

    expect(wrapper.get('[data-test="candidate-filter-trigger"]').attributes('aria-expanded')).toBe('false')
    expect(wrapper.text()).toContain('不限条件')
    await wrapper.get('[data-test="candidate-filter-trigger"]').trigger('click')

    const form = floatingForm()
    expect(form.textContent).toContain('年龄')
    expect(form.textContent).toContain('活跃度')
    expect(form.textContent).toContain('近期没有看过')
    expect(form.textContent).toContain('是否与同事交换简历')
    expect(form.textContent).toContain('牛人关键词')
    expect(form.textContent).toContain('院校')
    expect(form.textContent).toContain('专业')
    expect(form.textContent).toContain('跳槽频率')
    expect(form.textContent).toContain('求职状态')
    expect(form.textContent).toContain('学历要求')
    expect(form.parentElement).toBe(document.body)
    expect(getComputedStyle(form).position).toBe('fixed')
    expect(Number(getComputedStyle(form).zIndex)).toBeGreaterThan(200)
  })

  it('selects single, multiple and age filters, then clears the white-gold form', async () => {
    const wrapper = mountPanel()
    await wrapper.get('[data-test="candidate-filter-trigger"]').trigger('click')
    await clickFloating('[data-test="filter-gender-female"]')
    await clickFloating('[data-test="filter-keyword-data_analysis"]')
    await clickFloating('[data-test="filter-keyword-new_media"]')
    await clickFloating('[data-test="filter-age-enable"]')

    const ageMin = floatingForm().querySelector('[data-test="filter-age-min"]')
    ageMin.value = '24'
    ageMin.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()

    expect(floatingForm().querySelector('[data-test="filter-gender-female"]').classList).toContain('is-selected')
    expect(floatingForm().querySelector('[data-test="filter-keyword-data_analysis"]').getAttribute('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-test="candidate-filter-trigger"]').text()).toContain('已选 3 项')

    await clickFloating('[data-test="candidate-filter-clear"]')
    expect(floatingForm().querySelector('[data-test="filter-gender-any"]').classList).toContain('is-selected')
    expect(wrapper.get('[data-test="candidate-filter-trigger"]').text()).toContain('不限条件')
  })

  it('closes the top-layer panel with Escape and restores focus to the trigger', async () => {
    const wrapper = mountPanel()
    const trigger = wrapper.get('[data-test="candidate-filter-trigger"]')
    await trigger.trigger('click')

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await nextTick()

    expect(floatingForm()).toBeNull()
    expect(document.activeElement).toBe(trigger.element)
  })
})

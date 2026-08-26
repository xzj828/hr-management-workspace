import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import { describe, expect, it } from 'vitest'
import CandidateFilterPanel from './CandidateFilterPanel.vue'
import { defaultCandidateFilters } from '@/recruitmentCandidateFilters'

function mountPanel() {
  return mount({
    components: { CandidateFilterPanel },
    setup() {
      const filters = ref(defaultCandidateFilters())
      return { filters }
    },
    template: '<CandidateFilterPanel v-model="filters" />',
  })
}

describe('CandidateFilterPanel', () => {
  it('starts collapsed with unlimited filters and exposes every requested filter row', async () => {
    const wrapper = mountPanel()

    expect(wrapper.get('[data-test="candidate-filter-trigger"]').attributes('aria-expanded')).toBe('false')
    expect(wrapper.text()).toContain('不限条件')
    await wrapper.get('[data-test="candidate-filter-trigger"]').trigger('click')

    expect(wrapper.get('[data-test="candidate-filter-form"]').text()).toContain('年龄')
    expect(wrapper.text()).toContain('活跃度')
    expect(wrapper.text()).toContain('近期没有看过')
    expect(wrapper.text()).toContain('是否与同事交换简历')
    expect(wrapper.text()).toContain('牛人关键词')
    expect(wrapper.text()).toContain('院校')
    expect(wrapper.text()).toContain('专业')
    expect(wrapper.text()).toContain('跳槽频率')
    expect(wrapper.text()).toContain('求职状态')
    expect(wrapper.text()).toContain('学历要求')
  })

  it('selects single, multiple and age filters, then clears the white-gold form', async () => {
    const wrapper = mountPanel()
    await wrapper.get('[data-test="candidate-filter-trigger"]').trigger('click')
    await wrapper.get('[data-test="filter-gender-female"]').trigger('click')
    await wrapper.get('[data-test="filter-keyword-data_analysis"]').trigger('click')
    await wrapper.get('[data-test="filter-keyword-new_media"]').trigger('click')
    await wrapper.get('[data-test="filter-age-enable"]').trigger('click')
    await wrapper.get('[data-test="filter-age-min"]').setValue('24')

    expect(wrapper.get('[data-test="filter-gender-female"]').classes()).toContain('is-selected')
    expect(wrapper.get('[data-test="filter-keyword-data_analysis"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-test="candidate-filter-trigger"]').text()).toContain('已选 3 项')

    await wrapper.get('[data-test="candidate-filter-clear"]').trigger('click')
    expect(wrapper.get('[data-test="filter-gender-any"]').classes()).toContain('is-selected')
    expect(wrapper.get('[data-test="candidate-filter-trigger"]').text()).toContain('不限条件')
  })
})

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CandidateDiscoveryCard from './CandidateDiscoveryCard.vue'

const candidate = { id: 'd1', display_name: '林晓', current_title: '前端工程师', city: '北京', source_label: '推荐候选人', advantage: 'Vue 工程化', tags: ['Vue'], job_title: '高级前端', identity_quality: 'fingerprint', imported_candidate: null }

describe('CandidateDiscoveryCard', () => {
  it('emits selection without opening the card', async () => {
    const wrapper = mount(CandidateDiscoveryCard, { props: { candidate } })
    await wrapper.get('[data-test="discovery-check-d1"]').setValue(true)
    expect(wrapper.emitted('toggle')?.[0]).toEqual(['d1'])
    expect(wrapper.emitted('open')).toBeUndefined()
  })

  it('marks imported candidates as unavailable', () => {
    const wrapper = mount(CandidateDiscoveryCard, { props: { candidate: { ...candidate, imported_candidate: 9 } } })
    expect(wrapper.text()).toContain('已入库')
    expect(wrapper.get('input').attributes('disabled')).toBeDefined()
  })
})

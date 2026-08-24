import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AutomationBatchPanel from './AutomationBatchPanel.vue'

describe('AutomationBatchPanel', () => {
  it('shows independent candidate progress and failures', () => {
    const wrapper = mount(AutomationBatchPanel, { props: { batch: {
      id: 'b1', action: 'request_resume', status: 'partial', total_items: 2, succeeded_items: 1, failed_items: 1,
      account_name: '主账号', steps: [
        { id: 1, candidate_name: '林然', status: 'succeeded', error_message: '' },
        { id: 2, candidate_name: '周青', status: 'failed', error_message: '会话身份不唯一' },
      ],
    } } })
    expect(wrapper.text()).toContain('1 / 2')
    expect(wrapper.text()).toContain('林然')
    expect(wrapper.text()).toContain('会话身份不唯一')
  })
})


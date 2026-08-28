import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ResumeDocumentViewer from './ResumeDocumentViewer.vue'

const pdfResume = {
  candidate_name: '周晓宁', original_name: 'zhou-xiaoning.pdf', content_type: 'application/pdf',
  preview_url: '/api/resumes/1/file/', download_url: '/api/resumes/1/file/?download=1', file_available: true,
}

describe('ResumeDocumentViewer', () => {
  afterEach(() => { document.body.innerHTML = ''; document.body.style.overflow = '' })

  it('shows a scrollable PDF card with zoom, download and close controls', async () => {
    const wrapper = mount(ResumeDocumentViewer, { attachTo: document.body, props: { resume: pdfResume, candidateName: '周晓宁' } })
    expect(wrapper.get('[role="dialog"]').attributes('aria-modal')).toBe('true')
    expect(wrapper.get('[data-test="resume-scroll-viewport"]').exists()).toBe(true)
    expect(wrapper.get('iframe').attributes('src')).toContain('zoom=100')
    expect(wrapper.get('a[aria-label="下载原始简历"]').attributes('href')).toBe(pdfResume.download_url)
    await wrapper.get('[data-test="resume-zoom-in"]').trigger('click')
    expect(wrapper.get('iframe').attributes('src')).toContain('zoom=125')
    await wrapper.get('[data-test="resume-zoom-reset"]').trigger('click')
    expect(wrapper.get('iframe').attributes('src')).toContain('zoom=100')
    await wrapper.get('button[aria-label="关闭原始简历"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })

  it('renders every image MIME type and constrains zoom between 50 and 200 percent', async () => {
    const wrapper = mount(ResumeDocumentViewer, { props: { resume: { ...pdfResume, original_name: 'resume.jpg', content_type: 'image/jpeg', preview_url: '/resume.jpg' } } })
    const image = wrapper.get('img')
    expect(image.attributes('src')).toBe('/resume.jpg')
    for (let index = 0; index < 6; index += 1) await wrapper.get('[data-test="resume-zoom-in"]').trigger('click')
    expect(image.attributes('style')).toContain('width: 200%')
    expect(wrapper.get('[data-test="resume-zoom-in"]').attributes()).toHaveProperty('disabled')
    for (let index = 0; index < 8; index += 1) await wrapper.get('[data-test="resume-zoom-out"]').trigger('click')
    expect(image.attributes('style')).toContain('width: 50%')
    expect(wrapper.get('[data-test="resume-zoom-out"]').attributes()).toHaveProperty('disabled')
  })
})

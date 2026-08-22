import { describe, expect, it } from 'vitest'

import { formatFileSize, formatRecruitmentDate, stageColumns } from './recruitment'


describe('recruitment helpers', () => {
  it('uses the approved pipeline stages', () => {
    expect(stageColumns.map((item) => item.key)).toEqual([
      'new',
      'to_screen',
      'communicating',
      'interviewing',
      'to_offer',
      'hired',
      'rejected',
    ])
  })

  it('formats file sizes for resume rows', () => {
    expect(formatFileSize(0)).toBe('0 B')
    expect(formatFileSize(1536)).toBe('1.5 KB')
  })

  it('uses a dash for an empty recruitment date', () => {
    expect(formatRecruitmentDate('')).toBe('—')
  })
})

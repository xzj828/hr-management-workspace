export const CANDIDATE_FILTER_GROUPS = Object.freeze([
  Object.freeze({
    key: 'activity',
    label: '活跃度',
    options: Object.freeze([
      ['any', '不限'],
      ['just_active', '刚刚活跃'],
      ['today', '今日活跃'],
      ['within_3_days', '3 日内活跃'],
      ['this_week', '本周活跃'],
      ['this_month', '本月活跃'],
    ]),
  }),
  Object.freeze({ key: 'gender', label: '性别', options: Object.freeze([['any', '不限'], ['male', '男'], ['female', '女']]) }),
  Object.freeze({ key: 'unseen_period', label: '近期没有看过', options: Object.freeze([['any', '不限'], ['within_14_days', '近 14 天没有']]) }),
  Object.freeze({ key: 'colleague_resume_period', label: '是否与同事交换简历', options: Object.freeze([['any', '不限'], ['within_30_days', '近一个月没有']]) }),
  Object.freeze({
    key: 'school',
    label: '院校',
    options: Object.freeze([
      ['any', '不限'], ['985', '985'], ['211', '211'], ['double_first_class', '双一流院校'],
      ['overseas', '留学'], ['famous_global', '国内外名校'], ['public_undergraduate', '公办本科'],
    ]),
  }),
  Object.freeze({
    key: 'major',
    label: '专业',
    options: Object.freeze([
      ['any', '不限'], ['journalism', '新闻传播学类'], ['e_commerce', '电子商务类'],
      ['business_admin', '工商管理类'], ['public_admin', '公共管理类'], ['management_science', '管理科学与工程类'],
    ]),
  }),
  Object.freeze({
    key: 'job_stability',
    label: '跳槽频率',
    options: Object.freeze([['any', '不限'], ['fewer_than_3_in_5_years', '5 年少于 3 份'], ['average_over_1_year', '平均每份工作大于 1 年']]),
  }),
  Object.freeze({
    key: 'job_status',
    label: '求职状态',
    options: Object.freeze([
      ['any', '不限'], ['left_immediately', '离职 · 随时到岗'], ['employed_not_considering', '在职 · 暂不考虑'],
      ['employed_open', '在职 · 考虑机会'], ['employed_within_month', '在职 · 月内到岗'],
    ]),
  }),
  Object.freeze({
    key: 'education',
    label: '学历要求',
    options: Object.freeze([
      ['any', '不限'], ['junior_or_below', '初中及以下'], ['technical', '中专 / 中技'], ['high_school', '高中'],
      ['associate', '大专'], ['bachelor', '本科'], ['master', '硕士'], ['doctorate', '博士'],
    ]),
  }),
])

export const TALENT_KEYWORD_OPTIONS = Object.freeze([
  ['data_analysis', '数据分析'], ['business_negotiation', '商务谈判'], ['office_software', '办公软件'],
  ['kol', 'KOL'], ['new_media', '新媒体'], ['creator_resources', '达人资源'],
  ['business_cooperation', '商务合作'], ['social_media', '社交媒体'], ['media_buying', '媒介投放'],
])

export const DEFAULT_CANDIDATE_FILTERS = Object.freeze({
  age_min: null,
  age_max: null,
  activity: 'any',
  gender: 'any',
  unseen_period: 'any',
  colleague_resume_period: 'any',
  talent_keywords: Object.freeze([]),
  school: 'any',
  major: 'any',
  job_stability: 'any',
  job_status: 'any',
  education: 'any',
})

const optionLabels = new Map([
  ...CANDIDATE_FILTER_GROUPS.flatMap((group) => group.options.map(([value, label]) => [`${group.key}:${value}`, label])),
  ...TALENT_KEYWORD_OPTIONS.map(([value, label]) => [`talent_keywords:${value}`, label]),
])

export function defaultCandidateFilters() {
  return { ...DEFAULT_CANDIDATE_FILTERS, talent_keywords: [] }
}

export function normalizeCandidateFilters(value) {
  const input = value && typeof value === 'object' && !Array.isArray(value) ? value : {}
  const normalized = defaultCandidateFilters()
  const ageMin = Number(input.age_min)
  const ageMax = Number(input.age_max)
  if (Number.isInteger(ageMin) && Number.isInteger(ageMax) && ageMin >= 18 && ageMax <= 60 && ageMin <= ageMax) {
    normalized.age_min = ageMin
    normalized.age_max = ageMax
  }
  for (const group of CANDIDATE_FILTER_GROUPS) {
    const allowed = new Set(group.options.map(([option]) => option))
    normalized[group.key] = allowed.has(input[group.key]) ? input[group.key] : 'any'
  }
  const allowedKeywords = new Set(TALENT_KEYWORD_OPTIONS.map(([option]) => option))
  normalized.talent_keywords = [...new Set(Array.isArray(input.talent_keywords) ? input.talent_keywords : [])]
    .filter((option) => allowedKeywords.has(option))
    .slice(0, TALENT_KEYWORD_OPTIONS.length)
  return normalized
}

export function candidateFilterCount(value) {
  const filters = normalizeCandidateFilters(value)
  return Number(filters.age_min !== null)
    + CANDIDATE_FILTER_GROUPS.filter((group) => filters[group.key] !== 'any').length
    + Number(filters.talent_keywords.length > 0)
}

export function candidateFilterSummary(value, limit = 3) {
  const filters = normalizeCandidateFilters(value)
  const labels = []
  if (filters.age_min !== null) labels.push(`${filters.age_min}–${filters.age_max} 岁`)
  for (const group of CANDIDATE_FILTER_GROUPS) {
    if (filters[group.key] !== 'any') labels.push(optionLabels.get(`${group.key}:${filters[group.key]}`))
  }
  if (filters.talent_keywords.length) {
    const keywordLabels = filters.talent_keywords.map((option) => optionLabels.get(`talent_keywords:${option}`))
    labels.push(`关键词：${keywordLabels.join('、')}`)
  }
  if (!labels.length) return '不限条件'
  const visible = labels.slice(0, limit)
  return `${visible.join(' · ')}${labels.length > limit ? ` · 另 ${labels.length - limit} 项` : ''}`
}

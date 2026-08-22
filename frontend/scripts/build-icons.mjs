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


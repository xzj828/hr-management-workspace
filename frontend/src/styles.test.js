import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const stylesheet = readFileSync(resolve(process.cwd(), 'src/styles.css'), 'utf8')

describe('top navigation layout', () => {
  it('fills the available topbar width and uses the teal hover state', () => {
    expect(stylesheet).toMatch(/\.top-navigation\s*\{[^}]*flex:\s*1 1 auto;[^}]*justify-content:\s*space-between;/s)
    expect(stylesheet).toMatch(/\.top-navigation__link:hover\s*\{[^}]*color:\s*var\(--teal-dark\);[^}]*\}/s)
  })
})

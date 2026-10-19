import { describe, expect, it } from 'vitest'
import ts from 'typescript'
import fs from 'node:fs'
import path from 'node:path'

const banned = /\b(mock|synthetic|demo|fixtures?|fake|dummy|samples?|test\s+data)\b/i

describe('Business UI wording', () => {
  it('keeps user-facing text neutral and retains sandbox disclosure', () => {
    const root = path.resolve('src')
    const failures: string[] = []
    function scan(folder: string) {
      for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
        if (entry.name === 'test' || /\.(?:test|spec)\./.test(entry.name)) continue
        const file = path.join(folder, entry.name)
        if (entry.isDirectory()) { scan(file); continue }
        if (!/\.tsx?$/.test(file)) continue
        const source = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true)
        function walk(node: ts.Node) {
          // Identifiers, comments, backend paths and protocol field names are
          // not displayed copy. Inspect prose literals and JSX text/attributes.
          if (ts.isJsxText(node) || ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
            const value = node.text
            const internal = value.startsWith('/') || (ts.isStringLiteral(node) &&
              (ts.isImportDeclaration(node.parent) || ts.isLiteralTypeNode(node.parent)))
            if (!internal && banned.test(value)) failures.push(`${path.relative(root, file)}: ${value.trim()}`)
          }
          ts.forEachChild(node, walk)
        }
        walk(source)
      }
    }
    scan(root)
    expect(failures).toEqual([])
    expect(fs.readFileSync(path.join(root, 'components/ui/SandboxBanner.tsx'), 'utf8')).toContain('no real money moves')
  })
})

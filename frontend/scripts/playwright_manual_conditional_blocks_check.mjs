import { chromium, request } from '@playwright/test'

const API_BASE = process.env.API_BASE ?? 'http://127.0.0.1:8080/api/'
const WEB_BASE = process.env.WEB_BASE ?? 'http://127.0.0.1:5176'
const HEADED = process.argv.includes('--headed') || process.env.HEADED === '1'

async function expectOk(resp, label) {
  if (resp.ok()) return
  const text = await resp.text()
  throw new Error(`${label} failed: ${resp.status()} ${text}`)
}

async function selectTextInPreview(page, text) {
  await page.evaluate((needle) => {
    const host = document.querySelector('.docx-preview-mount')
    if (!host) throw new Error('preview host not found')
    const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT)
    let target = null
    while (walker.nextNode()) {
      const node = walker.currentNode
      if (!node?.textContent) continue
      const idx = node.textContent.indexOf(needle)
      if (idx >= 0) {
        target = { node, idx }
        break
      }
    }
    if (!target) throw new Error(`text not found in preview: ${needle}`)
    const range = document.createRange()
    range.setStart(target.node, target.idx)
    range.setEnd(target.node, target.idx + needle.length)
    const sel = window.getSelection()
    sel?.removeAllRanges()
    sel?.addRange(range)
    host.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
  }, text)
}

async function main() {
  const api = await request.newContext({ baseURL: API_BASE })
  const boot = await api.post('templates/bootstrap-empty', { data: { name: 'Playwright conditional blocks check' } })
  await expectOk(boot, 'bootstrap-empty')
  const { templateId, versionId } = await boot.json()

  const docx = await api.post(`templates/${templateId}/versions/${versionId}/editor-text`, {
    data: { text: 'Для физ лица\nДля юр лица\nИмя: {{name}}' },
  })
  await expectOk(docx, 'put editor-text')
  const publish = await api.post(`templates/${templateId}/versions/${versionId}/publish`)
  await expectOk(publish, 'publish')

  const browser = await chromium.launch({ headless: !HEADED, slowMo: HEADED ? 300 : 0 })
  const page = await browser.newPage()
  await page.goto(`${WEB_BASE}/documents/${templateId}/edit`, { waitUntil: 'networkidle' })
  await page.waitForSelector('.docx-preview-mount', { timeout: 20000 })

  await selectTextInPreview(page, 'Для физ лица')
  await page.locator('.conditional-block-editor select').first().selectOption('customer_type')
  await page.locator('.conditional-block-editor input[type="text"]').first().fill('phys')
  await page.locator('.conditional-block-editor select').nth(1).selectOption('if')
  await page.getByRole('button', { name: 'Создать условный блок из выделения' }).click()
  await page.waitForFunction(() => document.body.textContent?.includes('Условный блок создан.') ?? false, { timeout: 15000 })

  await selectTextInPreview(page, 'Для юр лица')
  await page.locator('.conditional-block-editor select').first().selectOption('customer_type')
  await page.locator('.conditional-block-editor input[type="text"]').first().fill('phys')
  await page.locator('.conditional-block-editor select').nth(1).selectOption('else')
  await page.getByRole('button', { name: 'Создать условный блок из выделения' }).click()
  await page.waitForFunction(() => (document.body.textContent || '').includes('Условный блок создан.'), { timeout: 15000 })

  await browser.close()

  const republish = await api.post(`templates/${templateId}/versions/${versionId}/publish`)
  await expectOk(republish, 'republish')

  const physRender = await api.post(`templates/${templateId}/versions/${versionId}/render-sync`, {
    data: { customer_type: 'phys', name: 'Иван' },
  })
  await expectOk(physRender, 'render-sync phys')
  const physBody = Buffer.from(await physRender.body()).toString('binary')

  const jurRender = await api.post(`templates/${templateId}/versions/${versionId}/render-sync`, {
    data: { customer_type: 'jur', name: 'ООО Астра' },
  })
  await expectOk(jurRender, 'render-sync jur')
  const jurBody = Buffer.from(await jurRender.body()).toString('binary')

  console.log(
    JSON.stringify({
      ok: true,
      templateId,
      versionId,
      physHasPhysText: physBody.includes('Для физ лица'),
      physHasJurText: physBody.includes('Для юр лица'),
      jurHasPhysText: jurBody.includes('Для физ лица'),
      jurHasJurText: jurBody.includes('Для юр лица'),
    }),
  )
  await api.dispose()
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})

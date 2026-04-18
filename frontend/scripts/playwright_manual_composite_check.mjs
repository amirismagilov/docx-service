import { chromium, request } from '@playwright/test'
import { Document, Packer, Paragraph, TextRun, UnderlineType } from 'docx'

const API_BASE = process.env.API_BASE ?? 'http://127.0.0.1:8080/api/'
const WEB_BASE = process.env.WEB_BASE ?? 'http://127.0.0.1:5176'
const HEADED = process.argv.includes('--headed') || process.env.HEADED === '1'
const SLOW_MO_MS = Number(process.env.SLOW_MO_MS ?? (HEADED ? '1000' : '0'))
const KEEP_OPEN_MS = Number(process.env.KEEP_OPEN_MS ?? (HEADED ? '5000' : '0'))
const STEP_PAUSE_MS = Number(process.env.STEP_PAUSE_MS ?? (HEADED ? '1200' : '0'))

async function expectOk(resp, label) {
  if (resp.ok()) return
  const text = await resp.text()
  throw new Error(`${label} failed: ${resp.status()} ${text}`)
}

async function buildLargeFormattedDocxBuffer() {
  const paragraphs = []
  const firstWord = 'FIRSTWORD'
  for (let i = 1; i <= 50; i += 1) {
    const lead = i === 1 ? firstWord : `W${String(i).padStart(2, '0')}`
    paragraphs.push(
      new Paragraph({
        children: [
          new TextRun({
            text: `${lead} `,
            bold: i % 2 === 0,
            italics: i % 3 === 0,
          }),
          new TextRun({
            text: `line-${String(i).padStart(2, '0')} `,
            underline: i % 4 === 0 ? { type: UnderlineType.SINGLE } : undefined,
          }),
          new TextRun({
            text: 'formatted-tail',
            bold: i % 5 === 0,
            italics: i % 5 === 0,
          }),
        ],
      }),
    )
  }
  const doc = new Document({
    sections: [{ children: paragraphs }],
  })
  return {
    firstWord,
    buffer: await Packer.toBuffer(doc),
  }
}

async function main() {
  const api = await request.newContext({ baseURL: API_BASE })
  const bootstrap = await api.post('templates/bootstrap-empty', { data: { name: 'Playwright composite check' } })
  await expectOk(bootstrap, 'bootstrap-empty')
  const bootData = await bootstrap.json()
  const templateId = bootData.templateId
  const versionId = bootData.versionId

  const { firstWord, buffer: docxBuffer } = await buildLargeFormattedDocxBuffer()

  const upload = await api.post(`templates/${templateId}/versions/${versionId}/upload-docx`, {
    multipart: {
      file: {
        name: 'large_formatted.docx',
        mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        buffer: docxBuffer,
      },
    },
  })
  await expectOk(upload, 'upload-docx')

  const applyComposite = await api.post(`templates/${templateId}/versions/${versionId}/apply-tag`, {
    data: {
      findText: firstWord,
      replacementTemplate: '{{field_1}}\\n{{field_2}}',
      replaceAll: false,
      occurrenceIndex: 0,
    },
  })
  await expectOk(applyComposite, 'apply composite')

  const browser = await chromium.launch({ headless: !HEADED, slowMo: SLOW_MO_MS })
  const page = await browser.newPage()
  await page.goto(`${WEB_BASE}/documents/${templateId}/edit`, { waitUntil: 'networkidle' })
  if (STEP_PAUSE_MS > 0) await page.waitForTimeout(STEP_PAUSE_MS)

  await page.waitForSelector('.preview-tag-list-row .preview-tag-edit-btn', { timeout: 20000 })
  if (STEP_PAUSE_MS > 0) await page.waitForTimeout(STEP_PAUSE_MS)
  await page.locator('.preview-tag-list-row .preview-tag-edit-btn').first().click()
  if (STEP_PAUSE_MS > 0) await page.waitForTimeout(STEP_PAUSE_MS)

  const composer = page.locator('textarea.composite-template-textarea')
  await composer.waitFor({ state: 'visible', timeout: 10000 })
  if (STEP_PAUSE_MS > 0) await page.waitForTimeout(STEP_PAUSE_MS)
  await composer.fill('{{field_1}} {{field_2}}')
  if (STEP_PAUSE_MS > 0) await page.waitForTimeout(STEP_PAUSE_MS)

  await page.getByRole('button', { name: 'Вставить тег' }).click()
  if (STEP_PAUSE_MS > 0) await page.waitForTimeout(STEP_PAUSE_MS)
  await page.waitForFunction(() => document.body.textContent?.includes('Составная вставка применена в DOCX.') ?? false, {
    timeout: 20000,
  })
  if (STEP_PAUSE_MS > 0) await page.waitForTimeout(STEP_PAUSE_MS)

  await page.locator('.preview-tag-list-row .preview-tag-edit-btn').first().click()
  if (STEP_PAUSE_MS > 0) await page.waitForTimeout(STEP_PAUSE_MS)
  await composer.waitFor({ state: 'visible', timeout: 10000 })
  const composerValue = await composer.inputValue()
  if (composerValue !== '{{field_1}} {{field_2}}') {
    throw new Error(`unexpected composer value: "${composerValue}"`)
  }

  const editorAfter = await api.get(`templates/${templateId}/versions/${versionId}/editor-text`)
  await expectOk(editorAfter, 'get editor-text after edit')
  const editorPayload = await editorAfter.json()
  const editorText = String(editorPayload.text ?? '')
  const firstLine = editorText.split('\n', 1)[0] ?? ''
  if (firstLine.includes('{{field_1}}\n{{field_2}}') || !firstLine.includes('{{field_1}} {{field_2}}')) {
    throw new Error(`first line still has wrong composite layout: "${firstLine}"`)
  }

  if (KEEP_OPEN_MS > 0) {
    await page.waitForTimeout(KEEP_OPEN_MS)
  }

  await browser.close()
  await api.dispose()

  console.log(
    JSON.stringify({
      ok: true,
      templateId,
      versionId,
      composerValue,
      editorText,
      firstLine,
      lineBreakRemoved: true,
    }),
  )
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})

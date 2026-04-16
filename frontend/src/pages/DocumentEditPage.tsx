import { DragEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { renderAsync } from 'docx-preview'
import { API_BASE } from '../api'
import {
  emptyForm,
  fieldsToSchemaJson,
  mergeFormValues,
  sanitizeFieldId,
  schemaJsonToFields,
} from '../schema'
import type { FieldDef, TemplateDetail } from '../types'

type TabId = 'design' | 'fields' | 'document'

type FieldRow = FieldDef & { clientKey: string }
type PreviewTagAnchor = {
  key: string
  tagId: string
  label: string
  occurrence: number
}
type ComposerMode = 'template' | 'builder'
const PARA_BREAK_MARKER = '[[PARA_BREAK]]'

function newClientKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `k_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`
}

function rowsFromSchema(schemaJson: string): FieldRow[] {
  return schemaJsonToFields(schemaJson).map((f) => ({
    ...f,
    clientKey: newClientKey(),
  }))
}

function pickVersionId(d: TemplateDetail, preferred: string | null | undefined): string | null {
  const vers = d.versions ?? []
  if (preferred && vers.some((x) => x.id === preferred)) return preferred
  if (!vers.length) return null
  return [...vers].sort((a, b) => b.version - a.version)[0].id
}


function parseLoadErrorText(raw: string): string {
  try {
    const j = JSON.parse(raw) as { detail?: unknown }
    if (typeof j.detail === 'string') return j.detail
    if (Array.isArray(j.detail)) return j.detail.map((x: { msg?: string }) => x.msg ?? '').filter(Boolean).join('; ')
  } catch {
    /* not JSON */
  }
  return raw || 'Неизвестная ошибка'
}

function collectPreviewTagAnchors(root: HTMLDivElement, fields: FieldDef[]): {
  anchors: PreviewTagAnchor[]
  elementsByKey: Record<string, HTMLElement>
} {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const counts = new Map<string, number>()
  const anchors: PreviewTagAnchor[] = []
  const elementsByKey: Record<string, HTMLElement> = {}
  const regex = /\{\{([a-zA-Z0-9_]+)\}\}/g

  while (walker.nextNode()) {
    const node = walker.currentNode
    const text = node.textContent ?? ''
    if (!text.includes('{{')) continue
    const parent = node.parentElement
    if (!parent) continue

    for (const match of text.matchAll(regex)) {
      const tagId = match[1]
      const occurrence = (counts.get(tagId) ?? 0) + 1
      counts.set(tagId, occurrence)
      const label = fields.find((f) => f.id === tagId)?.label ?? tagId
      const key = `${tagId}::${occurrence}`
      anchors.push({ key, tagId, label, occurrence })
      elementsByKey[key] = parent
      parent.classList.add('preview-tag-anchor-target')
    }
  }

  return { anchors, elementsByKey }
}

export default function DocumentEditPage() {
  const { templateId } = useParams<{ templateId: string }>()
  const [tab, setTab] = useState<TabId>('design')
  const [message, setMessage] = useState('')
  const [detail, setDetail] = useState<TemplateDetail | null>(null)
  const [versionId, setVersionId] = useState<string | null>(null)
  const [fieldRows, setFieldRows] = useState<FieldRow[]>([])
  const [formValues, setFormValues] = useState<Record<string, string>>({})
  const [tagTargetId, setTagTargetId] = useState('')
  const [selectedDocxText, setSelectedDocxText] = useState('')
  const [selectedOccurrenceIndex, setSelectedOccurrenceIndex] = useState<number | null>(null)
  const [previewTagAnchors, setPreviewTagAnchors] = useState<PreviewTagAnchor[]>([])
  const [composerMode, setComposerMode] = useState<ComposerMode>('builder')
  const [replacementTemplate, setReplacementTemplate] = useState('')
  const [showAdvancedComposer, setShowAdvancedComposer] = useState(false)
  const [published, setPublished] = useState(false)
  /** Локально: поля формы не сохранены в схему. */
  const [schemaDraftDirty, setSchemaDraftDirty] = useState(false)
  const [isDragOverDocx, setIsDragOverDocx] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [loading, setLoading] = useState(true)

  const previewRef = useRef<HTMLDivElement>(null)
  const previewTagElementsRef = useRef<Record<string, HTMLElement>>({})

  const tid = templateId ?? ''
  const fields: FieldDef[] = useMemo(() => fieldRows.map(({ clientKey: _c, ...f }) => f), [fieldRows])

  const refreshPreview = useCallback(async (t: string, v: string) => {
    const el = previewRef.current
    if (!el) return
    const r = await fetch(`${API_BASE}/templates/${t}/versions/${v}/docx-file`)
    if (!r.ok) {
      el.innerHTML = '<p class="preview-fallback">Нет данных для предпросмотра</p>'
      return
    }
    const blob = await r.blob()
    el.innerHTML = ''
    try {
      await renderAsync(blob, el, undefined, {
        className: 'docx-preview-root',
        inWrapper: true,
      })
      const collected = collectPreviewTagAnchors(el, fields)
      previewTagElementsRef.current = collected.elementsByKey
      setPreviewTagAnchors(collected.anchors)
    } catch {
      el.innerHTML =
        '<p class="preview-fallback">Не удалось отрисовать DOCX в браузере. Сохраните шаблон и скачайте результат.</p>'
      previewTagElementsRef.current = {}
      setPreviewTagAnchors([])
    }
  }, [fields])

  const refreshTemplateDetailFromApi = useCallback(async () => {
    if (!tid || !versionId) return
    const r = await fetch(`${API_BASE}/templates/${tid}`)
    if (!r.ok) return
    const d = (await r.json()) as TemplateDetail
    setDetail(d)
    const ver = d.versions?.find((x) => x.id === versionId)
    setPublished(ver?.status === 1)
  }, [tid, versionId])

  useEffect(() => {
    if (!tid) {
      setLoading(false)
      return
    }

    let cancelled = false
    setLoading(true)
    setLoadError('')
    setMessage('')
    setDetail(null)
    setVersionId(null)
    setPublished(false)
    setSchemaDraftDirty(false)
    setTagTargetId('')
    setSelectedDocxText('')
    setSelectedOccurrenceIndex(null)
    setPreviewTagAnchors([])
    setShowAdvancedComposer(false)
    setFieldRows([])
    setFormValues({})
    setTab('design')

    void (async () => {
      try {
        const r = await fetch(`${API_BASE}/templates/${tid}`)
        const raw = await r.text()
        if (cancelled) return
        if (!r.ok) {
          setLoadError(parseLoadErrorText(raw))
          setLoading(false)
          return
        }
        const d = JSON.parse(raw) as TemplateDetail
        if (!d.versions || !Array.isArray(d.versions)) {
          setLoadError('Некорректный ответ API: нет списка версий')
          setLoading(false)
          return
        }
        const vid = pickVersionId(d, d.currentVersionId ?? null)
        if (!vid) {
          setLoadError('У шаблона нет версий. Создайте документ заново.')
          setLoading(false)
          return
        }
        const rows = rowsFromSchema(d.schemaJson ?? '{}')
        const ver = d.versions.find((x) => x.id === vid)
        if (cancelled) return
        setDetail(d)
        setFieldRows(rows)
        setFormValues(emptyForm(rows))
        setVersionId(vid)
        setPublished(ver?.status === 1)
      } catch (e) {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [tid])

  const hasUnpublishedChanges = schemaDraftDirty
  const effectivePublished = published && !hasUnpublishedChanges

  useEffect(() => {
    if (!fields.length) {
      setTagTargetId('')
      return
    }
    setTagTargetId((prev) => (prev && fields.some((f) => f.id === prev) ? prev : fields[0].id))
  }, [fields])

  const patchFieldRow = (clientKey: string, patch: Partial<FieldDef>) => {
    setSchemaDraftDirty(true)
    setFieldRows((prev) => {
      const cur = prev.find((r) => r.clientKey === clientKey)
      if (!cur) return prev
      const merged: FieldDef = {
        id: patch.id ?? cur.id,
        label: patch.label ?? cur.label,
      }
      if (cur.id !== merged.id) {
        queueMicrotask(() => {
          setFormValues((fv) => {
            const copy = { ...fv }
            copy[merged.id] = copy[cur.id] ?? ''
            delete copy[cur.id]
            return copy
          })
        })
      }
      return prev.map((r) => (r.clientKey === clientKey ? { ...merged, clientKey } : r))
    })
  }

  const addFieldRow = () => {
    setSchemaDraftDirty(true)
    setFieldRows((prev) => {
      let n = prev.length + 1
      let id = `field_${n}`
      while (prev.some((r) => r.id === id)) {
        n += 1
        id = `field_${n}`
      }
      const rowId = id
      queueMicrotask(() => {
        setFormValues((fv) => ({ ...fv, [rowId]: '' }))
      })
      return [...prev, { clientKey: newClientKey(), id, label: 'Новое поле' }]
    })
  }

  const removeFieldRow = (clientKey: string) => {
    setSchemaDraftDirty(true)
    setFieldRows((prev) => {
      const row = prev.find((r) => r.clientKey === clientKey)
      if (row) {
        queueMicrotask(() => {
          setFormValues((fv) => {
            const copy = { ...fv }
            delete copy[row.id]
            return copy
          })
        })
      }
      return prev.filter((r) => r.clientKey !== clientKey)
    })
  }

  const saveSchema = async () => {
    if (!tid) return
    const defs: FieldDef[] = fieldRows.map((r) => ({
      id: r.id.trim(),
      label: (r.label.trim() || r.id.trim()) || 'Поле',
    }))
    const ids = defs.map((d) => d.id)
    if (ids.some((id) => !id)) {
      setMessage('Укажите идентификатор у каждого поля.')
      return
    }
    if (new Set(ids).size !== ids.length) {
      setMessage('Идентификаторы полей не должны повторяться.')
      return
    }
    const normalized = defs.map((d) => ({ ...d, id: sanitizeFieldId(d.id) }))
    const nids = normalized.map((d) => d.id)
    if (new Set(nids).size !== nids.length) {
      setMessage('После нормализации id полей совпали — задайте разные идентификаторы.')
      return
    }
    setMessage('')
    const schemaJson = fieldsToSchemaJson(normalized)
    const r = await fetch(`${API_BASE}/templates/${tid}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schemaJson }),
    })
    const raw = await r.text()
    if (!r.ok) {
      setMessage(`Схема не сохранена: ${parseLoadErrorText(raw)}`)
      return
    }
    const d = JSON.parse(raw) as TemplateDetail
    setDetail(d)
    // После изменения schema считаем публикацию недействительной до явной републикации
    setPublished(false)
    setFormValues((fv) => mergeFormValues(fv, normalized))
    setFieldRows(normalized.map((f) => ({ ...f, clientKey: newClientKey() })))
    setSchemaDraftDirty(false)
    setMessage('Схема полей сохранена.')
  }

  useEffect(() => {
    if (!tid || !versionId || tab !== 'design') return
    const t = requestAnimationFrame(() => {
      void refreshPreview(tid, versionId)
    })
    return () => cancelAnimationFrame(t)
  }, [tid, versionId, tab, refreshPreview])

  const onVersionChange = async (newVid: string) => {
    if (!detail) return
    setVersionId(newVid)
    const ver = (detail.versions ?? []).find((x) => x.id === newVid)
    setPublished(ver?.status === 1)
    if (tab === 'design') await refreshPreview(detail.id, newVid)
  }

  const insertFieldTag = (fieldId: string) => {
    setMessage(`Тег {{${fieldId}}} используйте в DOCX-шаблоне и затем загрузите файл заново.`)
  }

  const appendToReplacementTemplate = (chunk: string) => {
    setReplacementTemplate((prev) => prev + chunk)
  }

  const removeLastTemplateChunk = () => {
    setReplacementTemplate((prev) => {
      if (!prev) return prev
      if (prev.endsWith(PARA_BREAK_MARKER)) return prev.slice(0, -PARA_BREAK_MARKER.length)
      const tagMatch = prev.match(/\{\{[a-zA-Z0-9_]+\}\}$/)
      if (tagMatch) return prev.slice(0, -tagMatch[0].length)
      return prev.slice(0, -1)
    })
  }

  const uploadDocxFile = async (file: File) => {
    if (!tid || !versionId) return
    const isDocx =
      file.name.toLowerCase().endsWith('.docx') ||
      file.type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    if (!isDocx) {
      setMessage('Можно загрузить только файл .docx')
      return
    }
    const fd = new FormData()
    fd.append('file', file)
    const r = await fetch(`${API_BASE}/templates/${tid}/versions/${versionId}/upload-docx`, {
      method: 'POST',
      body: fd,
    })
    if (!r.ok) {
      setMessage('Ошибка загрузки файла')
      return
    }
    setPublished(false)
    setMessage(`Загружен файл: ${file.name}.`)
    if (tab === 'design') await refreshPreview(tid, versionId)
  }

  const onUploadDocx = async (e: FormEvent<HTMLInputElement>) => {
    const file = e.currentTarget.files?.[0]
    e.currentTarget.value = ''
    if (!file) return
    await uploadDocxFile(file)
  }

  const onDocxDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOverDocx(true)
  }

  const onDocxDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOverDocx(false)
  }

  const onDocxDrop = async (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOverDocx(false)
    const file = e.dataTransfer.files?.[0]
    if (!file) return
    await uploadDocxFile(file)
  }

  const captureSelectionFromPreview = () => {
    const host = previewRef.current
    if (!host) return
    const sel = window.getSelection()
    if (!sel || sel.rangeCount === 0) return
    const range = sel.getRangeAt(0)
    if (!host.contains(range.commonAncestorContainer)) return
    const selected = sel.toString().trim()
    if (!selected) return

    const pre = range.cloneRange()
    pre.selectNodeContents(host)
    pre.setEnd(range.startContainer, range.startOffset)
    const beforeText = pre.toString()

    let count = 0
    let pos = 0
    while (true) {
      const i = beforeText.indexOf(selected, pos)
      if (i < 0) break
      count += 1
      pos = i + selected.length
    }
    setSelectedDocxText(selected)
    setSelectedOccurrenceIndex(count)
  }

  const applyTagInDocx = async () => {
    if (!tid || !versionId || !isBinaryDocxMode) return
    if (!selectedDocxText.trim()) {
      setMessage('Сначала выделите фрагмент текста в предпросмотре документа.')
      return
    }
    if (!tagTargetId.trim()) {
      setMessage('Выберите тег для вставки.')
      return
    }
    const template = replacementTemplate.trim() || `{{${tagTargetId}}}`
    if (selectedOccurrenceIndex === null || selectedOccurrenceIndex < 0) {
      setMessage('Не удалось определить позицию выделения. Выделите текст в предпросмотре ещё раз.')
      return
    }
    const r = await fetch(`${API_BASE}/templates/${tid}/versions/${versionId}/apply-tag`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        findText: selectedDocxText,
        tagId: tagTargetId,
        replacementTemplate: template,
        replaceAll: false,
        occurrenceIndex: selectedOccurrenceIndex,
      }),
    })
    const raw = await r.text()
    if (!r.ok) {
      setMessage(parseLoadErrorText(raw))
      return
    }
    setPublished(false)
    setMessage('Составная вставка применена в DOCX.')
    setSelectedDocxText('')
    setSelectedOccurrenceIndex(null)
    if (tab === 'design') await refreshPreview(tid, versionId)
  }

  const scrollToPreviewTag = (key: string) => {
    const target = previewTagElementsRef.current[key]
    if (!target) {
      setMessage('Не удалось найти тег в предпросмотре. Обновите шаблон или откройте вкладку заново.')
      return
    }
    target.scrollIntoView({ behavior: 'smooth', block: 'center' })
    target.classList.remove('preview-tag-anchor-active')
    requestAnimationFrame(() => {
      target.classList.add('preview-tag-anchor-active')
      window.setTimeout(() => target.classList.remove('preview-tag-anchor-active'), 1800)
    })
  }

  const publishTemplate = async () => {
    if (!tid || !versionId) return
    const r = await fetch(`${API_BASE}/templates/${tid}/versions/${versionId}/publish`, { method: 'POST' })
    if (!r.ok) {
      setMessage('Не удалось опубликовать')
      return
    }
    setPublished(true)
    setMessage('Версия опубликована.')
    const r2 = await fetch(`${API_BASE}/templates/${tid}`)
    if (r2.ok) {
      const d = (await r2.json()) as TemplateDetail
      setDetail(d)
      const ver = (d.versions ?? []).find((x) => x.id === versionId)
      setPublished(ver?.status === 1)
    }
  }

  const generateDocument = async () => {
    if (!tid || !versionId) return
    const r = await fetch(`${API_BASE}/templates/${tid}/versions/${versionId}/render-sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(formValues),
    })
    if (!r.ok) {
      const raw = await r.text()
      setMessage(parseLoadErrorText(raw))
      return
    }
    const blob = await r.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${detail?.name?.replace(/\s+/g, '_') ?? 'document'}.docx`
    a.click()
    URL.revokeObjectURL(url)
    setMessage('Документ скачан.')
  }

  if (!tid) {
    return (
      <main className="page">
        <p>Не указан документ.</p>
        <Link to="/">К списку</Link>
      </main>
    )
  }

  if (loadError) {
    return (
      <main className="page">
        <p className="message message-warn">Не удалось загрузить документ: {loadError}</p>
        <p className="hint">Если вы перезапускали сервер API, список в памяти очищен — создайте документ снова.</p>
        <Link to="/">К списку</Link>
      </main>
    )
  }

  if (loading || !detail || !versionId) {
    return (
      <main className="page">
        <p className="hint">Загрузка…</p>
        <Link to="/">К списку</Link>
      </main>
    )
  }

  const versionsSorted = [...(detail.versions ?? [])].sort((a, b) => b.version - a.version)
  const currentVersion = (detail.versions ?? []).find((v) => v.id === versionId)
  const isBinaryDocxMode = Boolean(currentVersion?.sourceFileName)

  return (
    <main className="page">
      <header className="app-header">
        <div className="breadcrumb">
          <Link to="/">Документы</Link>
          <span className="breadcrumb-sep">/</span>
          <span>{detail.name}</span>
        </div>
        <h1>Редактирование: {detail.name}</h1>
        <p className="lead">
          Шаблон: поля, загрузка .docx, текст и предпросмотр. Документ: заполнение и скачивание.
        </p>
        <div className="row row-spread">
          <nav className="tabs" aria-label="Разделы">
            <button type="button" className={tab === 'design' ? 'tab tab-active' : 'tab'} onClick={() => setTab('design')}>
              Шаблон
            </button>
            <button type="button" className={tab === 'fields' ? 'tab tab-active' : 'tab'} onClick={() => setTab('fields')}>
              Поля
            </button>
            <button type="button" className={tab === 'document' ? 'tab tab-active' : 'tab'} onClick={() => setTab('document')}>
              Документ
            </button>
          </nav>
          {versionsSorted.length > 1 && (
            <label className="version-select-label">
              Версия
              <select
                className="version-select"
                value={versionId}
                onChange={(e) => void onVersionChange(e.target.value)}
              >
                {versionsSorted.map((v) => (
                  <option key={v.id} value={v.id}>
                    v{v.version} {v.status === 1 ? '(опублик.)' : '(черновик)'}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </header>

      {tab === 'design' && (
        <>
          {(schemaDraftDirty || !published || isBinaryDocxMode) && (
            <section className="card publication-notice">
              <p className="message message-warn publication-notice-text">
                {schemaDraftDirty && (
                  <span>
                    Поля формы или теги <code>{'{{…}}'}</code> изменены — нажмите «Сохранить схему полей».
                    {published
                      ? ' После сохранения все опубликованные версии этого шаблона будут сняты с публикации.'
                      : ' Затем снова опубликуйте версию.'}{' '}
                  </span>
                )}
                {!published && !schemaDraftDirty && (
                  <span>
                    Есть неопубликованные изменения на сервере: текущая версия в статусе черновика. Опубликуйте её, чтобы
                    формировать документ на вкладке «Документ».
                  </span>
                )}
                {isBinaryDocxMode && (
                  <span>
                    Вы в режиме Word-шаблона. Чтобы сохранить форматирование, используйте вставку тегов в предпросмотре (выделить текст → Вставить тег) или загрузите обновлённый DOCX. Текстовое сохранение отключено.
                  </span>
                )}
              </p>
            </section>
          )}

          <section className="card">
            <h2>Загрузка шаблона Word</h2>
            <div
              className={isDragOverDocx ? 'docx-dropzone docx-dropzone-active' : 'docx-dropzone'}
              onDragOver={onDocxDragOver}
              onDragEnter={onDocxDragOver}
              onDragLeave={onDocxDragLeave}
              onDrop={(e) => void onDocxDrop(e)}
            >
              <label className="file-label">
                Загрузить .docx
                <input
                  type="file"
                  accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  onChange={onUploadDocx}
                />
              </label>
              <p className="hint">Или перетащите файл .docx в эту область.</p>
            </div>
            <p className="hint">
              Плейсхолдеры в Word — одним фрагментом, например <code>{'{{price_amount}}'}</code>.
            </p>
          </section>

          <section className="card">
            <h2>Предпросмотр шаблона</h2>
            <p className="hint">
              Редактор шаблона временно отключён. Используйте загрузку готового DOCX и предпросмотр ниже.
            </p>
            {isBinaryDocxMode && (
              <>
                <div className="preview-tag-toolbar">
                  <label className="preview-tag-toolbar-text">
                    Выделенный текст
                    <input value={selectedDocxText} readOnly placeholder="Выделите фрагмент в документе" />
                  </label>
                  <label>
                    Тег
                    <select value={tagTargetId} onChange={(e) => setTagTargetId(e.target.value)}>
                      {fields.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.label} ({f.id})
                        </option>
                      ))}
                    </select>
                  </label>
                  <button type="button" onClick={() => void applyTagInDocx()} disabled={!fields.length || !selectedDocxText.trim()}>
                    Вставить тег
                  </button>
                  <button type="button" className="btn-secondary" onClick={() => setShowAdvancedComposer((v) => !v)}>
                    {showAdvancedComposer ? 'Короткая форма' : 'Полная форма'}
                  </button>
                  <span className="hint">
                    {selectedOccurrenceIndex === null ? 'Выделите текст в предпросмотре.' : `Позиция: ${selectedOccurrenceIndex + 1}-е вхождение.`}
                  </span>
                </div>
                {showAdvancedComposer && (
                  <div className="preview-tag-composer">
                    <div className="row">
                      <button
                        type="button"
                        className={composerMode === 'builder' ? 'tab tab-active' : 'tab'}
                        onClick={() => setComposerMode('builder')}
                      >
                        Конструктор
                      </button>
                      <button
                        type="button"
                        className={composerMode === 'template' ? 'tab tab-active' : 'tab'}
                        onClick={() => setComposerMode('template')}
                      >
                        Шаблон
                      </button>
                    </div>
                    {composerMode === 'builder' ? (
                      <div className="preview-tag-composer-builder">
                        <div className="row">
                          <button type="button" className="btn-secondary" onClick={() => appendToReplacementTemplate(`{{${tagTargetId}}}`)} disabled={!tagTargetId}>
                            Добавить тег
                          </button>
                          <button type="button" className="btn-secondary" onClick={() => appendToReplacementTemplate(' ')}>
                            Пробел
                          </button>
                          <button type="button" className="btn-secondary" onClick={() => appendToReplacementTemplate('/')}>
                            Слэш
                          </button>
                          <button type="button" className="btn-secondary" onClick={() => appendToReplacementTemplate('-')}>
                            Тире
                          </button>
                          <button type="button" className="btn-secondary" onClick={() => appendToReplacementTemplate('\n')}>
                            Перенос строки
                          </button>
                          <button type="button" className="btn-secondary" onClick={() => appendToReplacementTemplate(PARA_BREAK_MARKER)}>
                            Новый абзац
                          </button>
                          <button type="button" className="btn-secondary" onClick={removeLastTemplateChunk}>
                            Удалить последний
                          </button>
                          <button type="button" className="btn-secondary" onClick={() => setReplacementTemplate('')}>
                            Очистить
                          </button>
                        </div>
                      </div>
                    ) : null}
                    <label>
                      Шаблон вставки
                      <textarea
                        className="composite-template-textarea"
                        value={replacementTemplate}
                        onChange={(e) => setReplacementTemplate(e.target.value)}
                        placeholder={'{{buyer_name}} / {{buyer_inn}}\\n{{buyer_address}}'}
                        spellCheck={false}
                      />
                    </label>
                    <p className="hint">
                      <code>{'\\n'}</code> = перенос строки внутри абзаца. <code>{PARA_BREAK_MARKER}</code> = новый абзац.
                    </p>
                  </div>
                )}
                <div className="preview-tag-list">
                  <div className="preview-tag-list-header">
                    <h3>Добавленные теги</h3>
                    <span className="hint">
                      {previewTagAnchors.length > 0 ? `${previewTagAnchors.length} шт.` : 'Пока не найдены'}
                    </span>
                  </div>
                  {previewTagAnchors.length > 0 ? (
                    <div className="preview-tag-list-items">
                      {previewTagAnchors.map((anchor) => (
                        <button
                          key={anchor.key}
                          type="button"
                          className="preview-tag-list-item"
                          onClick={() => scrollToPreviewTag(anchor.key)}
                        >
                          <span>{anchor.label}</span>
                          <code>{`{{${anchor.tagId}}}`}</code>
                          <span className="hint">#{anchor.occurrence}</span>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p className="hint">После вставки тегов здесь появится список переходов по документу.</p>
                  )}
                </div>
              </>
            )}
            <div ref={previewRef} className="docx-preview-mount" onMouseUp={captureSelectionFromPreview} />
          </section>

          <section className="card">
            <h2>Публикация</h2>
            <div className="row">
              <button type="button" onClick={() => void publishTemplate()} disabled={effectivePublished}>
                {effectivePublished ? 'Эта версия опубликована' : hasUnpublishedChanges ? 'Опубликовать версию снова' : 'Опубликовать версию'}
              </button>
              <span className="hint">Без публикации нельзя сформировать файл на вкладке «Документ».</span>
            </div>
          </section>
        </>
      )}

      {tab === 'fields' && (
        <section className="card">
          <h2>Поля формы</h2>
          <p className="hint">
            Идентификатор используется в шаблоне как <code>{'{{id}}'}</code>. После изменений нажмите «Сохранить схему».
          </p>
          <div className="field-editor-actions-top">
            <button type="button" className="btn-secondary" onClick={addFieldRow}>
              Добавить поле
            </button>
            <button type="button" onClick={() => void saveSchema()}>
              Сохранить схему полей
            </button>
          </div>
          {fieldRows.length === 0 ? (
            <p className="hint">Пока нет полей — добавьте строку или откройте готовый шаблон.</p>
          ) : (
            <div className="field-editor">
                {fieldRows.map((row) => (
                <div key={row.clientKey} className="field-editor-row">
                  <label>
                    Идентификатор
                    <input
                      value={row.id}
                      onChange={(e) => patchFieldRow(row.clientKey, { id: e.target.value })}
                      onBlur={() => {
                        const s = sanitizeFieldId(row.id)
                        if (s !== row.id) patchFieldRow(row.clientKey, { id: s })
                      }}
                      spellCheck={false}
                      autoComplete="off"
                    />
                  </label>
                  <label>
                    Подпись в форме
                    <input
                      value={row.label}
                      onChange={(e) => patchFieldRow(row.clientKey, { label: e.target.value })}
                      autoComplete="off"
                    />
                  </label>
                  <div className="field-editor-row-btns">
                      <button type="button" className="btn-secondary" onClick={() => insertFieldTag(row.id)} disabled={isBinaryDocxMode}>
                      Вставить {'{{' + row.id + '}}'}
                    </button>
                  </div>
                  <div className="field-editor-row-btns">
                    <button type="button" className="btn-text btn-danger" onClick={() => removeFieldRow(row.clientKey)}>
                      Удалить
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
            {isBinaryDocxMode && (
              <p className="hint">Для загруженного DOCX вставляйте теги в самом файле Word и загружайте его заново.</p>
            )}
        </section>
      )}

      {tab === 'document' && (
        <section className="card">
          <h2>Заполнение и генерация</h2>
          {fields.length === 0 ? (
            <p className="hint">Нет полей. На вкладке «Шаблон» добавьте поля и сохраните схему.</p>
          ) : (
            <>
              {!effectivePublished && <p className="message message-warn">Сначала опубликуйте версию на вкладке «Шаблон».</p>}
              <form
                className="form-grid"
                onSubmit={(e) => {
                  e.preventDefault()
                  void generateDocument()
                }}
              >
                {fields.map((f) => (
                  <label key={f.id}>
                    {f.label}
                    <input
                      value={formValues[f.id] ?? ''}
                      onChange={(e) => setFormValues((prev) => ({ ...prev, [f.id]: e.target.value }))}
                      autoComplete="off"
                    />
                  </label>
                ))}
                <div className="row">
                  <button type="submit" disabled={!effectivePublished}>
                    Сформировать и скачать .docx
                  </button>
                </div>
              </form>
            </>
          )}
        </section>
      )}

      {message && <p className="message">{message}</p>}
    </main>
  )
}

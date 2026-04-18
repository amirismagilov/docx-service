import {
  DragEvent,
  FormEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
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
import type { FieldDef, TagSlot, TemplateDetail } from '../types'

type TabId = 'design' | 'fields' | 'document'

type FieldRow = FieldDef & { clientKey: string }
type PreviewTagAnchor = {
  key: string
  tagIds: string[]
  label: string
  occurrence: number
  /** Точный фрагмент в предпросмотре (для findText в API) */
  rawText: string
  /** Значение для textarea «Шаблон вставки»: переносы как два символа \\n, табы как \\t */
  composerTemplate: string
  /** 0-based индекс вхождения findText в документе (как occurrenceIndex в apply-tag) */
  occurrenceIndex: number
  isComposite: boolean
  /** Смещение начала в innerText (сопоставление со слотами) */
  anchorStartAt: number
  /** Серверный слот — для редактирования/удаления с восстановлением исходного текста */
  tagSlotId?: string
  /** Точный currentTemplate слота (может отличаться от rawText из-за переносов/пробелов в DOCX) */
  slotCurrentTemplate?: string
  /** Индекс вхождения в DOCX из слота (не путать с occurrenceIndex предпросмотра) */
  slotOccurrenceIndex?: number
}
const PARA_BREAK_MARKER = '[[PARA_BREAK]]'

/** Текст из DOM/Word → поле «Шаблон вставки» (переносы как \\n, табы как \\t). */
function docPlainTextToComposerTemplate(s: string): string {
  return s.replace(/\r\n/g, '\n').replace(/\n/g, '\\n').replace(/\t/g, '\\t')
}

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

function filterFieldsByTagQuery(fields: FieldDef[], query: string): FieldDef[] {
  const q = query.trim().toLowerCase()
  if (!q) return fields
  return fields.filter(
    (f) =>
      f.id.toLowerCase().includes(q) ||
      f.label.toLowerCase().includes(q) ||
      `${f.label} (${f.id})`.toLowerCase().includes(q),
  )
}

/** Те же переносы строк, что в DOCX логическом тексте и в слотах API (для findText / сопоставления). */
function normalizeTagFindText(s: string): string {
  let t = s.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
  // NBSP и др. Unicode-пробелы в превью (не только ASCII), см. norm_tag_fragment на сервере.
  t = t.replace(/\n[^\S\r\n]+(?=\{\{)/g, '\n')
  return t
}

/** Для сопоставления со слотами: игнорируем пробелы вокруг переводов строк. */
function normalizeSlotComparableText(s: string): string {
  return normalizeTagFindText(s).replace(/[^\S\r\n]*\n[^\S\r\n]*/g, '\n').trim()
}

function textOffsetFromRootTo(root: HTMLElement, textNode: Text, offsetInNode: number): number {
  const r = document.createRange()
  r.setStart(root, 0)
  r.setEnd(textNode, offsetInNode)
  return normalizeTagFindText(r.toString()).length
}

/** 0-based индекс вхождения needle, которое начинается с позиции needleStartAt в fullText. */
function occurrenceIndexAt(fullText: string, needle: string, needleStartAt: number): number {
  if (!needle) return 0
  if (fullText.slice(needleStartAt, needleStartAt + needle.length) === needle) {
    let count = 0
    let pos = 0
    for (;;) {
      const i = fullText.indexOf(needle, pos)
      if (i < 0 || i >= needleStartAt) break
      count += 1
      pos = i + needle.length
    }
    return count
  }
  let count = 0
  let pos = 0
  while (pos <= fullText.length) {
    const i = fullText.indexOf(needle, pos)
    if (i < 0) break
    if (i === needleStartAt) return count
    count += 1
    pos = i + needle.length
  }
  return 0
}

function normalizeBetweenPlaceholders(between: string): string {
  return between
    .replace(/\u200b/g, '')
    .replace(/\ufeff/g, '')
    .replace(/\r\n/g, '\n')
    .replace(/\\n/g, '\n')
    .replace(/\\t/g, '\t')
    .replace(/\\r/g, '\r')
    .replace(/\u2028/g, '\n')
    .replace(/\u2029/g, '\n')
}

/**
 * Между двумя {{…}} в одной составной вставке: пробелы, переносы, разделители шаблона,
 * литералы \n / \t (как в поле вставки). Без «живого» текста (букв/цифр вне escape-последовательностей).
 */
function isBetweenCompositeTemplateFragments(between: string): boolean {
  if (between.length > 240) return false
  const normalized = normalizeBetweenPlaceholders(between)
  if (/^\s*$/.test(normalized)) return true
  if (/[\p{L}\p{N}]/u.test(normalized)) return false
  return /^[\s\u00a0/\\\-–—·|·,;:+&]+$/u.test(normalized)
}

/** Склеивать ли два подряд {{…}} в один составной пункт списка. */
function canMergeCompositePair(prev: FlatTagMatch, next: FlatTagMatch, between: string): boolean {
  if (isBetweenCompositeTemplateFragments(between)) return true
  const normalized = normalizeBetweenPlaceholders(between)
  if (!/^\s*$/.test(normalized)) return false
  return hasBrBetweenFlatMatches(prev, next) || hasStructuralLineGapBetween(prev, next)
}

type FlatTagMatch = {
  tagId: string
  node: Text
  start: number
  len: number
}

function textBetweenMatches(prev: FlatTagMatch, next: FlatTagMatch): string {
  const r = document.createRange()
  r.setStart(prev.node, prev.start + prev.len)
  r.setEnd(next.node, next.start)
  return r.toString()
}

/** Между двумя совпадениями в DOM есть &lt;br&gt; (Range.toString() часто даёт пустую строку). */
function hasBrBetweenFlatMatches(prev: FlatTagMatch, next: FlatTagMatch): boolean {
  const r = document.createRange()
  r.setStart(prev.node, prev.start + prev.len)
  r.setEnd(next.node, next.start)
  return r.cloneContents().querySelectorAll('br').length > 0
}

const PREVIEW_BLOCK_SEL =
  'p,div,li,td,th,section,article,h1,h2,h3,h4,h5,h6,header,footer,table,tr'

/**
 * Реальный разрыв между плейсхолдерами: &lt;br&gt;, другой блок в диапазоне, разные блочные предки.
 * Не используем getBoundingClientRect — docx-preview часто кладёт соседние {{}} в разные inline-обёртки
 * и визуально «на двух строках» даже после склейки в одном абзаце Word.
 */
function hasStructuralLineGapBetween(prev: FlatTagMatch, next: FlatTagMatch): boolean {
  if (hasBrBetweenFlatMatches(prev, next)) return true
  try {
    const n1 = prev.node.parentElement
    const n2 = next.node.parentElement
    if (!n1 || !n2) return false
    if (n1 === n2) return false

    const r = document.createRange()
    r.setStart(prev.node, prev.start + prev.len)
    r.setEnd(next.node, next.start)
    const frag = r.cloneContents()
    if (frag.querySelectorAll('br').length > 0) return true
    if (frag.querySelector(PREVIEW_BLOCK_SEL)) return true

    const b1 = n1.closest(PREVIEW_BLOCK_SEL)
    const b2 = n2.closest(PREVIEW_BLOCK_SEL)
    if (b1 && b2 && b1 !== b2) return true

    return false
  } catch {
    return false
  }
}

function compositeSeparatorForPair(
  prev: FlatTagMatch,
  next: FlatTagMatch,
  between: string,
  forComposer: boolean,
): string {
  const wsOnly = /^\s*$/.test(normalizeBetweenPlaceholders(between))
  const lineBreak = hasBrBetweenFlatMatches(prev, next) || hasStructuralLineGapBetween(prev, next)
  if (lineBreak && wsOnly) {
    return forComposer ? '\\n' : '\n'
  }
  if (between.length > 0) {
    const n = between.replace(/\r\n/g, '\n')
    return forComposer ? n.replace(/\n/g, '\\n').replace(/\t/g, '\\t') : n
  }
  if (lineBreak) {
    return forComposer ? '\\n' : '\n'
  }
  return ''
}

/** Логическая строка составного тега с реальным \\n там, где в Word/DOM мягкий перенос. */
function buildCanonicalCompositeRawText(flat: FlatTagMatch[], i: number, j: number, tagIds: string[]): string {
  let s = `{{${tagIds[0]}}}`
  for (let k = i; k < j; k++) {
    const between = textBetweenMatches(flat[k], flat[k + 1])
    const sep = compositeSeparatorForPair(flat[k], flat[k + 1], between, false)
    s += sep + `{{${tagIds[k - i + 1]}}}`
  }
  return s.trim()
}

/**
 * Текст для поля «Шаблон вставки» при составном теге: между {{…}} подставляются видимые \\n / \\t
 * по фактическому DOM (в т.ч. &lt;br&gt;), а не по Range.toString().
 */
function buildComposerTemplateFromCluster(flat: FlatTagMatch[], i: number, j: number, tagIds: string[]): string {
  let s = `{{${tagIds[0]}}}`
  for (let k = i; k < j; k++) {
    const between = textBetweenMatches(flat[k], flat[k + 1])
    const sep = compositeSeparatorForPair(flat[k], flat[k + 1], between, true)
    s += sep + `{{${tagIds[k - i + 1]}}}`
  }
  return s.trim()
}

/**
 * Собирает теги из предпросмотра: подряд идущие {{id}} в порядке документа; между ними —
 * только разделители (в т.ч. перенос после \\n или <br> между текстовыми узлами), показываются как один пункт.
 */
function collectPreviewTagAnchors(root: HTMLDivElement, fields: FieldDef[]): {
  anchors: PreviewTagAnchor[]
  elementsByKey: Record<string, HTMLElement>
} {
  const fullText = normalizeTagFindText(root.innerText)
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const counts = new Map<string, number>()
  const anchors: PreviewTagAnchor[] = []
  const elementsByKey: Record<string, HTMLElement> = {}
  const regex = /\{\{([a-zA-Z0-9_]+)\}\}/g

  const flat: FlatTagMatch[] = []
  while (walker.nextNode()) {
    const node = walker.currentNode as Text
    const text = node.textContent ?? ''
    if (!text.includes('{{')) continue
    for (const m of text.matchAll(regex)) {
      flat.push({ tagId: m[1], node, start: m.index ?? 0, len: m[0].length })
    }
  }

  if (flat.length === 0) {
    return { anchors, elementsByKey }
  }

  let i = 0
  while (i < flat.length) {
    let j = i
    while (j + 1 < flat.length) {
      const between = textBetweenMatches(flat[j], flat[j + 1])
      if (canMergeCompositePair(flat[j], flat[j + 1], between)) {
        j += 1
      } else {
        break
      }
    }

    const first = flat[i]
    const last = flat[j]

    const tagIds = flat.slice(i, j + 1).map((x) => x.tagId)
    const isComposite = tagIds.length > 1

    for (const tid of tagIds) {
      const nextOcc = (counts.get(tid) ?? 0) + 1
      counts.set(tid, nextOcc)
    }

    const rangeRaw = document.createRange()
    rangeRaw.setStart(first.node, first.start)
    rangeRaw.setEnd(last.node, last.start + last.len)
    const rangeStr = rangeRaw.toString()
    const rawTrimFromRange = rangeStr.trim()
    if (!rawTrimFromRange) {
      i = j + 1
      continue
    }

    let rawTextForAnchor = rawTrimFromRange
    if (isComposite) {
      rawTextForAnchor = buildCanonicalCompositeRawText(flat, i, j, tagIds)
    }
    rawTextForAnchor = normalizeTagFindText(rawTextForAnchor)

    const composerTemplate = isComposite
      ? buildComposerTemplateFromCluster(flat, i, j, tagIds)
      : docPlainTextToComposerTemplate(rawTextForAnchor)

    // occurrenceIndex и findText в apply-tag должны относиться к одной и той же строке.
    // Для составных тегов rawTextForAnchor (канон с \n) часто ≠ rawTrimFromRange (Range.toString()).
    const anchorStartAt = textOffsetFromRootTo(root, first.node, first.start)
    const occurrenceIdx = occurrenceIndexAt(fullText, rawTextForAnchor, anchorStartAt)
    const firstTag = tagIds[0]
    const occurrence = counts.get(firstTag) ?? 1
    const labels = tagIds.map((id) => fields.find((f) => f.id === id)?.label ?? id)
    const label = isComposite ? labels.join(' · ') : labels[0]
    const key = `${tagIds.join('+')}::${anchorStartAt}`

    const rangeForAnchor = document.createRange()
    rangeForAnchor.setStart(first.node, first.start)
    rangeForAnchor.setEnd(last.node, last.start + last.len)
    let common: Node = rangeForAnchor.commonAncestorContainer
    if (common.nodeType === Node.TEXT_NODE) {
      common = common.parentNode as Node
    }
    const highlightEl =
      common instanceof HTMLElement ? common : first.node.parentElement
    if (!highlightEl) {
      i = j + 1
      continue
    }

    anchors.push({
      key,
      tagIds,
      label,
      occurrence,
      rawText: rawTextForAnchor,
      composerTemplate,
      occurrenceIndex: occurrenceIdx,
      isComposite,
      anchorStartAt,
    })
    elementsByKey[key] = highlightEl
    highlightEl.classList.add('preview-tag-anchor-target')

    i = j + 1
  }

  return { anchors, elementsByKey }
}

/**
 * Сопоставляет якоря со слотами только по тексту шаблона и порядку в документе.
 * Индекс вхождения в предпросмотре (occurrenceIndex) не совпадает с глобальным индексом в DOCX — не используем его для матчинга.
 */
function assignTagSlotsToAnchors(anchors: PreviewTagAnchor[], slots: TagSlot[]): PreviewTagAnchor[] {
  const ordered = [...anchors].sort((a, b) => a.anchorStartAt - b.anchorStartAt)
  const pool = [...slots].sort((a, b) => {
    const ai = typeof a.currentOccurrenceIndex === 'number' ? a.currentOccurrenceIndex : 1e9
    const bi = typeof b.currentOccurrenceIndex === 'number' ? b.currentOccurrenceIndex : 1e9
    if (ai !== bi) return ai - bi
    return (a.createdAtUtc ?? '').localeCompare(b.createdAtUtc ?? '')
  })
  const used = new Set<string>()
  const idByKey = new Map<string, string>()
  const slotById = new Map(slots.map((s) => [s.id, s]))

  for (const a of ordered) {
    const m = pool.find(
      (s) =>
        !used.has(s.id) &&
        normalizeSlotComparableText(s.currentTemplate) === normalizeSlotComparableText(a.rawText),
    )
    if (m) {
      used.add(m.id)
      idByKey.set(a.key, m.id)
    }
  }
  return anchors.map((a) => {
    const sid = idByKey.get(a.key)
    if (!sid) return { ...a }
    const slot = slotById.get(sid)
    const occ =
      slot != null && typeof slot.currentOccurrenceIndex === 'number'
        ? slot.currentOccurrenceIndex
        : a.occurrenceIndex
    return {
      ...a,
      tagSlotId: sid,
      slotCurrentTemplate: slot?.currentTemplate,
      slotOccurrenceIndex: occ,
    }
  })
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
  const [replacementTemplate, setReplacementTemplate] = useState('')
  const [showAdvancedComposer, setShowAdvancedComposer] = useState(false)
  const [published, setPublished] = useState(false)
  /** Локально: поля формы не сохранены в схему. */
  const [schemaDraftDirty, setSchemaDraftDirty] = useState(false)
  const [isDragOverDocx, setIsDragOverDocx] = useState(false)
  const [docxReplacePanelOpen, setDocxReplacePanelOpen] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [loading, setLoading] = useState(true)
  const [tagComboOpen, setTagComboOpen] = useState(false)
  const [tagComboHighlight, setTagComboHighlight] = useState(0)
  const [tagInputValue, setTagInputValue] = useState('')
  const [isApplyingTag, setIsApplyingTag] = useState(false)
  const [tagSlots, setTagSlots] = useState<TagSlot[]>([])
  const [activeTagSlotId, setActiveTagSlotId] = useState<string | null>(null)
  const [revertTarget, setRevertTarget] = useState<PreviewTagAnchor | null>(null)

  const previewRef = useRef<HTMLDivElement>(null)
  const previewTagElementsRef = useRef<Record<string, HTMLElement>>({})
  const replaceDocxInputRef = useRef<HTMLInputElement>(null)
  const tagComboRef = useRef<HTMLDivElement>(null)
  /** После «Редактировать» не сбрасываем tagSlotId, если выделение в превью совпадает с тем же фрагментом. */
  const editSlotContextRef = useRef<{
    rawText: string
    occurrenceIndex: number
    tagSlotId: string
  } | null>(null)

  const tid = templateId ?? ''
  const fields: FieldDef[] = useMemo(() => fieldRows.map(({ clientKey: _c, ...f }) => f), [fieldRows])
  const filteredTagFields = useMemo(() => filterFieldsByTagQuery(fields, tagInputValue), [fields, tagInputValue])

  const insertTagBlockReason = useMemo(() => {
    const editingExistingSlot = Boolean(activeTagSlotId)
    if (!editingExistingSlot && !selectedDocxText.trim())
      return 'Нет выделенного текста для поиска в DOCX'
    if (!editingExistingSlot && (selectedOccurrenceIndex == null || selectedOccurrenceIndex < 0))
      return 'Нет позиции вхождения — нажмите «Редактировать» у тега или выделите текст в предпросмотре'
    if (!tagTargetId.trim() && !replacementTemplate.trim())
      return 'Заполните «Шаблон вставки» или выберите тег в поле «Тег»'
    return null
  }, [activeTagSlotId, selectedDocxText, selectedOccurrenceIndex, tagTargetId, replacementTemplate])

  const insertTagDisabled = insertTagBlockReason != null || isApplyingTag

  const refreshTagSlots = useCallback(
    async (versionOverride?: string | null) => {
      const vid = versionOverride ?? versionId
      if (!tid || !vid) {
        setTagSlots([])
        return
      }
      const r = await fetch(`${API_BASE}/templates/${tid}/versions/${vid}/tag-slots`)
      if (!r.ok) {
        setTagSlots([])
        return
      }
      const data = (await r.json()) as TagSlot[]
      setTagSlots(Array.isArray(data) ? data : [])
    },
    [tid, versionId],
  )

  const previewAnchorsWithSlots = useMemo(
    () => assignTagSlotsToAnchors(previewTagAnchors, tagSlots),
    [previewTagAnchors, tagSlots],
  )

  const refreshPreview = useCallback(async (t: string, v: string) => {
    const el = previewRef.current
    if (!el) return
    const r = await fetch(`${API_BASE}/templates/${t}/versions/${v}/docx-file`, {
      cache: 'no-store',
    })
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
    setTagSlots([])
    setActiveTagSlotId(null)
    editSlotContextRef.current = null
    setRevertTarget(null)
    setShowAdvancedComposer(false)
    setFieldRows([])
    setFormValues({})

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
    if (!tid || !versionId || loading) return
    void refreshTagSlots()
  }, [tid, versionId, loading, refreshTagSlots])

  useEffect(() => {
    if (!fields.length) return
    setTagTargetId((prev) => (prev && fields.some((f) => f.id === prev) ? prev : ''))
  }, [fields])

  useEffect(() => {
    setDocxReplacePanelOpen(false)
  }, [versionId])

  useEffect(() => {
    if (tagComboOpen) return
    const f = fields.find((x) => x.id === tagTargetId)
    if (f) {
      setTagInputValue(`${f.label} (${f.id})`)
    } else if (tagTargetId) {
      setTagInputValue(tagTargetId)
    } else {
      setTagInputValue('')
    }
  }, [tagTargetId, fields, tagComboOpen])

  useEffect(() => {
    if (!tagComboOpen) return
    const onDocDown = (e: MouseEvent) => {
      if (tagComboRef.current && !tagComboRef.current.contains(e.target as Node)) {
        setTagComboOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocDown)
    return () => document.removeEventListener('mousedown', onDocDown)
  }, [tagComboOpen])

  useEffect(() => {
    if (!tagComboOpen) return
    setTagComboHighlight((h) => Math.min(h, Math.max(0, filteredTagFields.length - 1)))
  }, [filteredTagFields.length, tagComboOpen])

  const selectTagField = useCallback((f: FieldDef) => {
    setTagTargetId(f.id)
    setTagInputValue(`${f.label} (${f.id})`)
    setTagComboOpen(false)
  }, [])

  const commitTagInputFromValue = useCallback(() => {
    const raw = tagInputValue.trim()
    if (!raw) {
      setTagTargetId('')
      return
    }
    const exact = fields.find((f) => `${f.label} (${f.id})` === raw)
    if (exact) {
      setTagTargetId(exact.id)
      return
    }
    const byId = fields.find((f) => f.id === raw)
    if (byId) {
      setTagTargetId(byId.id)
      setTagInputValue(`${byId.label} (${byId.id})`)
      return
    }
    const m = raw.match(/\(([^)]+)\)\s*$/)
    if (m) {
      const id = sanitizeFieldId(m[1])
      if (id) {
        setTagTargetId(id)
        const nf = fields.find((x) => x.id === id)
        if (nf) setTagInputValue(`${nf.label} (${nf.id})`)
      }
      return
    }
    const id = sanitizeFieldId(raw)
    if (id) {
      setTagTargetId(id)
      const nf = fields.find((x) => x.id === id)
      if (nf) setTagInputValue(`${nf.label} (${nf.id})`)
    }
  }, [tagInputValue, fields])

  const onTagComboBlur = () => {
    commitTagInputFromValue()
    setTagComboOpen(false)
  }

  const onTagComboKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      setTagComboOpen(false)
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!fields.length) return
      if (!tagComboOpen) {
        setTagComboOpen(true)
        setTagComboHighlight(0)
      } else {
        setTagComboHighlight((h) => Math.min(h + 1, Math.max(0, filteredTagFields.length - 1)))
      }
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (!fields.length) return
      if (!tagComboOpen) {
        setTagComboOpen(true)
        setTagComboHighlight(Math.max(0, filteredTagFields.length - 1))
      } else {
        setTagComboHighlight((h) => Math.max(h - 1, 0))
      }
      return
    }
    if (e.key === 'Enter') {
      if (tagComboOpen && filteredTagFields.length > 0) {
        e.preventDefault()
        const f = filteredTagFields[tagComboHighlight]
        if (f) selectTagField(f)
        return
      }
      e.preventDefault()
      commitTagInputFromValue()
      setTagComboOpen(false)
    }
  }

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
    await refreshTagSlots(newVid)
    if (tab === 'design') await refreshPreview(detail.id, newVid)
  }

  const insertFieldTag = (fieldId: string) => {
    setMessage(`Тег {{${fieldId}}} используйте в DOCX-шаблоне и затем загрузите файл заново.`)
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
    setMessage(`Загружен файл: ${file.name}. Версия опубликована — можно сразу формировать документ.`)
    setDocxReplacePanelOpen(false)
    await refreshTemplateDetailFromApi()
    await refreshTagSlots()
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
    const selected = normalizeTagFindText(sel.toString()).trim()
    if (!selected) return

    const pre = range.cloneRange()
    pre.selectNodeContents(host)
    pre.setEnd(range.startContainer, range.startOffset)
    const beforeText = normalizeTagFindText(pre.toString())

    let count = 0
    let pos = 0
    while (true) {
      const i = beforeText.indexOf(selected, pos)
      if (i < 0) break
      count += 1
      pos = i + selected.length
    }
    const ctx = editSlotContextRef.current
    const matchesEditContext =
      ctx != null &&
      normalizeTagFindText(selected).trim() === normalizeTagFindText(ctx.rawText).trim() &&
      count === ctx.occurrenceIndex
    if (!matchesEditContext) {
      setActiveTagSlotId(null)
    }
    setSelectedDocxText(selected)
    setSelectedOccurrenceIndex(count)
  }

  const applyTagInDocx = async () => {
    setTagComboOpen(false)
    if (!tid || !versionId) {
      setMessage('Не удалось применить: шаблон или версия не загружены.')
      return
    }
    if (!isBinaryDocxMode) {
      setMessage('Вставка тегов доступна только при загруженном DOCX этой версии.')
      return
    }
    let slotIdForEdit: string | null = activeTagSlotId ?? editSlotContextRef.current?.tagSlotId ?? null
    if (!slotIdForEdit && selectedDocxText.trim()) {
      const selectedNorm = normalizeSlotComparableText(selectedDocxText)
      const localMatches = tagSlots.filter(
        (s) => normalizeSlotComparableText(s.currentTemplate) === selectedNorm,
      )
      if (localMatches.length === 1) {
        slotIdForEdit = localMatches[0].id
      } else {
        const rSlots = await fetch(`${API_BASE}/templates/${tid}/versions/${versionId}/tag-slots`)
        if (rSlots.ok) {
          const slotsRemote = (await rSlots.json()) as TagSlot[]
          const remoteMatches = slotsRemote.filter(
            (s) => normalizeSlotComparableText(s.currentTemplate) === selectedNorm,
          )
          if (remoteMatches.length === 1) {
            slotIdForEdit = remoteMatches[0].id
          }
        }
      }
    }

    const editingExistingSlot = Boolean(slotIdForEdit)
    if (!editingExistingSlot && !selectedDocxText.trim()) {
      setMessage('Сначала выделите фрагмент текста в предпросмотре документа.')
      return
    }
    const trimmedReplacement = replacementTemplate.trim()
    const trimmedTag = tagTargetId.trim()
    if (!trimmedReplacement && !trimmedTag) {
      setMessage('Укажите тег в поле «Тег» или заполните «Шаблон вставки».')
      return
    }
    const template = trimmedReplacement || `{{${trimmedTag}}}`
    if (!editingExistingSlot && (selectedOccurrenceIndex == null || selectedOccurrenceIndex < 0)) {
      setMessage('Не удалось определить позицию выделения. Нажмите «Редактировать» у тега в списке ещё раз.')
      return
    }
    setIsApplyingTag(true)
    try {
      const r = await fetch(`${API_BASE}/templates/${tid}/versions/${versionId}/apply-tag`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          findText: editingExistingSlot ? '' : normalizeTagFindText(selectedDocxText).trim(),
          tagId: trimmedTag,
          replacementTemplate: template,
          replaceAll: false,
          occurrenceIndex: editingExistingSlot ? 0 : (selectedOccurrenceIndex as number),
          ...(editingExistingSlot && slotIdForEdit ? { tagSlotId: slotIdForEdit } : {}),
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
      setTagTargetId('')
      setTagInputValue('')
      setTagComboOpen(false)
      setReplacementTemplate('')
      setActiveTagSlotId(null)
      editSlotContextRef.current = null
      await refreshTagSlots()
      if (tab === 'design') await refreshPreview(tid, versionId)
    } catch (e) {
      setMessage(e instanceof Error ? `Ошибка сети: ${e.message}` : 'Не удалось отправить запрос к серверу.')
    } finally {
      setIsApplyingTag(false)
    }
  }

  const revertTagInDocx = async (anchor: PreviewTagAnchor) => {
    if (!tid || !versionId) {
      setMessage('Не удалось восстановить: шаблон или версия не загружены.')
      return
    }
    if (!anchor.tagSlotId) {
      setMessage(
        'Восстановление исходного текста недоступно для этого фрагмента. Выполните вставку тега после обновления страницы или заново выделите текст и вставьте тег.',
      )
      return
    }
    setIsApplyingTag(true)
    try {
      const r = await fetch(`${API_BASE}/templates/${tid}/versions/${versionId}/revert-tag`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tagSlotId: anchor.tagSlotId,
          findText: normalizeTagFindText(anchor.rawText),
          occurrenceIndex: anchor.occurrenceIndex,
        }),
      })
      const raw = await r.text()
      if (!r.ok) {
        setMessage(parseLoadErrorText(raw))
        return
      }
      setPublished(false)
      setMessage('Исходный текст восстановлен в DOCX.')
      setRevertTarget(null)
      setActiveTagSlotId(null)
      editSlotContextRef.current = null
      await refreshTagSlots()
      if (tab === 'design') await refreshPreview(tid, versionId)
    } catch (e) {
      setMessage(e instanceof Error ? `Ошибка сети: ${e.message}` : 'Не удалось отправить запрос к серверу.')
    } finally {
      setIsApplyingTag(false)
    }
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

  const beginEditAnchor = async (anchor: PreviewTagAnchor) => {
    let findTextBase = anchor.slotCurrentTemplate
    let occ: number | undefined = anchor.slotOccurrenceIndex
    let slotId: string | null = anchor.tagSlotId ?? null

    const needSlots =
      tid &&
      versionId &&
      (!slotId ||
        findTextBase == null ||
        findTextBase === '' ||
        typeof occ !== 'number')
    if (needSlots) {
      const r = await fetch(`${API_BASE}/templates/${tid}/versions/${versionId}/tag-slots`)
      if (r.ok) {
        const list = (await r.json()) as TagSlot[]
        const byId = slotId ? list.find((x) => x.id === slotId) : undefined
        const byText =
          byId ??
          list.find(
            (s) =>
              normalizeSlotComparableText(s.currentTemplate) === normalizeSlotComparableText(anchor.rawText),
          )
        if (byText) {
          slotId = byText.id
          findTextBase = byText.currentTemplate
          if (typeof byText.currentOccurrenceIndex === 'number') occ = byText.currentOccurrenceIndex
        }
      }
    }
    if (!findTextBase?.trim()) {
      findTextBase = anchor.rawText
    }
    if (typeof occ !== 'number') {
      occ = anchor.occurrenceIndex
    }

    const findTextNorm = normalizeTagFindText(findTextBase)

    setReplacementTemplate(anchor.composerTemplate)
    setSelectedDocxText(findTextNorm)
    setSelectedOccurrenceIndex(occ)
    setActiveTagSlotId(slotId)
    editSlotContextRef.current =
      slotId != null
        ? {
            rawText: findTextNorm,
            occurrenceIndex: occ,
            tagSlotId: slotId,
          }
        : null
    setTagTargetId('')
    setTagInputValue('')
    setTagComboOpen(false)
    setShowAdvancedComposer(true)
    scrollToPreviewTag(anchor.key)
    setMessage(
      'Измените «Шаблон вставки» и нажмите «Вставить тег», чтобы заменить этот фрагмент в DOCX.',
    )
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
            <button
              type="button"
              className={tab === 'design' ? 'tab tab-active' : 'tab'}
              data-main-tab="design"
              onClick={() => setTab('design')}
            >
              Шаблон
            </button>
            <button
              type="button"
              className={tab === 'fields' ? 'tab tab-active' : 'tab'}
              data-main-tab="fields"
              onClick={() => setTab('fields')}
            >
              Поля
            </button>
            <button
              type="button"
              className={tab === 'document' ? 'tab tab-active' : 'tab'}
              data-main-tab="document"
              onClick={() => setTab('document')}
            >
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
            {!isBinaryDocxMode ? (
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
            ) : (
              <div className="docx-upload-filled">
                <div className="docx-dropzone docx-dropzone-uploaded">
                  <div className="docx-file-row">
                    <span className="hint">Загруженный файл</span>
                    <p className="docx-file-name">{currentVersion?.sourceFileName ?? 'template.docx'}</p>
                  </div>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => setDocxReplacePanelOpen((open) => !open)}
                  >
                    {docxReplacePanelOpen ? 'Скрыть' : 'Заменить файл'}
                  </button>
                </div>
                {docxReplacePanelOpen && (
                  <>
                    <div className="message message-warn docx-replace-warning">
                      <p className="docx-replace-warning-text">
                        <strong>Внимание</strong> — новый файл заменит текущий DOCX этой версии. Вставленные в документ теги,
                        правки в предпросмотре и несохранённые локальные изменения шаблона будут потеряны. Схему полей на
                        вкладке «Поля» это не удаляет, но несохранённые правки в редакторе могут потеряться.
                      </p>
                      <div className="row">
                        <button type="button" onClick={() => replaceDocxInputRef.current?.click()}>
                          Выбрать новый файл
                        </button>
                        <button type="button" className="btn-secondary" onClick={() => setDocxReplacePanelOpen(false)}>
                          Отмена
                        </button>
                      </div>
                    </div>
                    <input
                      ref={replaceDocxInputRef}
                      type="file"
                      className="docx-hidden-file-input"
                      accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                      onChange={onUploadDocx}
                    />
                    <div
                      className={isDragOverDocx ? 'docx-dropzone docx-dropzone-active' : 'docx-dropzone'}
                      onDragOver={onDocxDragOver}
                      onDragEnter={onDocxDragOver}
                      onDragLeave={onDocxDragLeave}
                      onDrop={(e) => void onDocxDrop(e)}
                    >
                      <p className="hint docx-replace-drop-hint">Или перетащите новый .docx сюда</p>
                    </div>
                  </>
                )}
              </div>
            )}
            <p className="hint">
              Плейсхолдеры в Word — одним фрагментом, например <code>{'{{price_amount}}'}</code>.
            </p>
          </section>

          <section className="card">
            <h2>Предпросмотр шаблона</h2>
            {isBinaryDocxMode && (
              <>
                <div className="preview-tag-toolbar">
                  <label className="preview-tag-toolbar-text">
                    <span className="preview-selected-text-header">
                      <span>Выделенный текст</span>
                      <button
                        type="button"
                        className="btn-text"
                        disabled={!selectedDocxText.trim()}
                        onClick={() => {
                          setSelectedDocxText('')
                          setSelectedOccurrenceIndex(null)
                          setActiveTagSlotId(null)
                          editSlotContextRef.current = null
                        }}
                      >
                        Сбросить
                      </button>
                    </span>
                    <textarea
                      className="preview-selected-docx-text"
                      value={selectedDocxText}
                      readOnly
                      rows={3}
                      onKeyDown={(e: KeyboardEvent<HTMLTextAreaElement>) => {
                        if (e.key !== 'Backspace' && e.key !== 'Delete') return
                        if (!selectedDocxText) return
                        e.preventDefault()
                        setSelectedDocxText('')
                        setSelectedOccurrenceIndex(null)
                        setActiveTagSlotId(null)
                        editSlotContextRef.current = null
                      }}
                      placeholder="Выделите фрагмент в документе"
                      spellCheck={false}
                      autoComplete="off"
                      title="Backspace или Delete — очистить выделение целиком"
                    />
                  </label>
                  <label className="tag-field-combobox-label">
                    Тег
                    <div className="tag-field-combobox" ref={tagComboRef}>
                      <input
                        type="text"
                        role="combobox"
                        aria-expanded={tagComboOpen}
                        aria-controls={tagComboOpen ? 'tag-field-combobox-listbox' : undefined}
                        aria-autocomplete="list"
                        value={tagInputValue}
                        onChange={(e) => {
                          setTagInputValue(e.target.value)
                          setTagComboHighlight(0)
                          setTagComboOpen(true)
                        }}
                        onFocus={() => {
                          setTagComboOpen(true)
                          setTagComboHighlight(0)
                        }}
                        onBlur={onTagComboBlur}
                        onKeyDown={onTagComboKeyDown}
                        placeholder={
                          fields.length
                            ? 'Поиск по id или подписи…'
                            : 'Введите id тега (латиница, цифры, _) или добавьте поля на вкладке «Поля»'
                        }
                        autoComplete="off"
                        spellCheck={false}
                      />
                      {tagComboOpen && fields.length > 0 ? (
                        <div
                          className="tag-field-combobox-dropdown"
                          id="tag-field-combobox-listbox"
                          role="listbox"
                        >
                          {filteredTagFields.length === 0 ? (
                            <div className="tag-mention-empty">Ничего не найдено</div>
                          ) : (
                            filteredTagFields.map((f, i) => (
                              <button
                                key={f.id}
                                type="button"
                                role="option"
                                className={`tag-mention-item${i === tagComboHighlight ? ' active' : ''}`}
                                onMouseDown={(ev) => ev.preventDefault()}
                                onClick={() => selectTagField(f)}
                              >
                                <span>{f.label}</span>
                                <code>{f.id}</code>
                              </button>
                            ))
                          )}
                        </div>
                      ) : null}
                    </div>
                  </label>
                  <button
                    type="button"
                    onClick={() => void applyTagInDocx()}
                    disabled={insertTagDisabled}
                    title={
                      insertTagBlockReason ??
                      (isApplyingTag ? 'Отправка запроса…' : 'Подставить шаблон в DOCX по выделенному тексту')
                    }
                  >
                    {isApplyingTag ? 'Применение…' : 'Вставить тег'}
                  </button>
                  <button type="button" className="btn-secondary" onClick={() => setShowAdvancedComposer((v) => !v)}>
                    {showAdvancedComposer ? 'Короткая форма' : 'Полная форма'}
                  </button>
                  <span className="hint">
                    {selectedOccurrenceIndex == null ? 'Выделите текст в предпросмотре.' : `Позиция: ${selectedOccurrenceIndex + 1}-е вхождение.`}
                  </span>
                </div>
                {showAdvancedComposer && (
                  <div className="preview-tag-composer">
                    <label>
                      Шаблон вставки
                      <textarea
                        className="composite-template-textarea"
                        value={replacementTemplate}
                        onChange={(e) => setReplacementTemplate(e.target.value)}
                        placeholder={'{{buyer_name}}\\n{{buyer_inn}}'}
                        spellCheck={false}
                      />
                    </label>
                    <p className="hint">
                      Свободный текст и поля <code>{'{{id}}'}</code>. Обычный слэш <code>/</code> или дефис — просто символы в тексте, они{' '}
                      <strong>не</strong> делают перенос строки. Перенос внутри абзаца в Word — только два символа: обратный слэш и{' '}
                      <code>n</code> (<code>{'\\n'}</code> в строке). Новый абзац: <code>{PARA_BREAK_MARKER}</code>.
                    </p>
                  </div>
                )}
                <div className="preview-tag-list">
                  <div className="preview-tag-list-header">
                    <h3>Добавленные теги</h3>
                    <span className="hint">
                      {previewAnchorsWithSlots.length > 0 ? `${previewAnchorsWithSlots.length} шт.` : 'Пока не найдены'}
                    </span>
                  </div>
                  {previewAnchorsWithSlots.length > 0 ? (
                    <div className="preview-tag-list-items">
                      {previewAnchorsWithSlots.map((anchor) => (
                        <div key={anchor.key} className="preview-tag-list-row">
                          <button
                            type="button"
                            className="preview-tag-list-item"
                            onClick={() => scrollToPreviewTag(anchor.key)}
                          >
                            <span>{anchor.label}</span>
                            <span className="preview-tag-codes">
                              {anchor.tagIds.map((id) => (
                                <code key={`${anchor.key}-${id}`}>{`{{${id}}}`}</code>
                              ))}
                            </span>
                            {anchor.isComposite ? (
                              <span className="hint preview-tag-composite-badge">составной</span>
                            ) : null}
                            <span className="hint">#{anchor.occurrence}</span>
                          </button>
                          <button
                            type="button"
                            className="btn-secondary preview-tag-edit-btn"
                            onClick={() => void beginEditAnchor(anchor)}
                          >
                            Редактировать
                          </button>
                          <button
                            type="button"
                            className="btn-text btn-danger preview-tag-delete-btn"
                            disabled={!anchor.tagSlotId || isApplyingTag}
                            title={
                              anchor.tagSlotId
                                ? 'Восстановить исходный текст из документа'
                                : 'Нет данных для восстановления — вставьте тег после обновления страницы'
                            }
                            onClick={() => setRevertTarget(anchor)}
                          >
                            Удалить тег
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="hint">После вставки тегов здесь появится список переходов по документу.</p>
                  )}
                </div>
              </>
            )}
            <div ref={previewRef} className="docx-preview-mount" onMouseUp={captureSelectionFromPreview} />
            {revertTarget ? (
              <div
                className="revert-tag-modal-backdrop"
                role="dialog"
                aria-modal="true"
                aria-labelledby="revert-tag-title"
              >
                <div className="revert-tag-modal">
                  <h3 id="revert-tag-title">Удалить тег и восстановить текст?</h3>
                  <p className="hint">В DOCX будет восстановлен исходный фрагмент (как до первой вставки тега):</p>
                  <pre className="revert-tag-original">
                    {tagSlots.find((s) => s.id === revertTarget.tagSlotId)?.originalPlainText ?? '—'}
                  </pre>
                  <div className="revert-tag-modal-actions">
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => setRevertTarget(null)}
                      disabled={isApplyingTag}
                    >
                      Отмена
                    </button>
                    <button
                      type="button"
                      className="btn-danger"
                      onClick={() => void revertTagInDocx(revertTarget)}
                      disabled={isApplyingTag}
                    >
                      Восстановить
                    </button>
                  </div>
                </div>
              </div>
            ) : null}
          </section>

          <section className="card">
            <h2>Публикация</h2>
            <div className="row">
              <button type="button" onClick={() => void publishTemplate()} disabled={effectivePublished}>
                {effectivePublished ? 'Эта версия опубликована' : hasUnpublishedChanges ? 'Опубликовать версию снова' : 'Опубликовать версию'}
              </button>
              <span className="hint">
                {effectivePublished
                  ? 'После изменения схемы полей или DOCX снова нажмите «Опубликовать», если кнопка станет активной.'
                  : 'Без публикации нельзя сформировать файл на вкладке «Документ». Загрузка .docx публикует версию автоматически.'}
              </span>
            </div>
          </section>
        </>
      )}

      {tab === 'fields' && (
        <section className="card">
          <h2>Динамические поля</h2>
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

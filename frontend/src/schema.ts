import type { FieldDef } from './types'

/** Разбор schemaJson шаблона в список полей для формы. */
export function schemaJsonToFields(schemaJson: string): FieldDef[] {
  try {
    const o = JSON.parse(schemaJson) as Record<string, { label?: string }>
    if (!o || typeof o !== 'object' || Array.isArray(o)) return []
    return Object.entries(o).map(([id, meta]) => ({
      id,
      label: meta?.label ?? id,
    }))
  } catch {
    return []
  }
}

/** Сериализация полей в schemaJson (порядок строк совпадает с порядком в массиве). */
export function fieldsToSchemaJson(fields: FieldDef[]): string {
  const o: Record<string, { label: string }> = {}
  for (const f of fields) {
    o[f.id] = { label: f.label }
  }
  return JSON.stringify(o, null, 2)
}

/** Идентификатор поля в плейсхолдерах: латиница, цифры, подчёркивание. */
export function sanitizeFieldId(raw: string): string {
  const s = raw
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '_')
    .replace(/[^a-z0-9_]/g, '')
    .replace(/^_+|_+$/g, '')
  return s || 'field'
}

/** После смены набора полей — сохранить введённые значения по совпадающим id. */
export function mergeFormValues(prev: Record<string, string>, fields: FieldDef[]): Record<string, string> {
  const next: Record<string, string> = {}
  for (const f of fields) {
    next[f.id] = prev[f.id] ?? ''
  }
  return next
}

export function emptyForm(fields: FieldDef[]): Record<string, string> {
  return Object.fromEntries(fields.map((f) => [f.id, '']))
}

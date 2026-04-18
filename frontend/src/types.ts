export type FieldDef = { id: string; label: string }

export type TemplateVersionRow = {
  id: string
  version: number
  status: number
  publishedAtUtc?: string | null
}

export type TemplateListItem = {
  id: string
  name: string
  status: number
  createdAtUtc: string
  currentVersionId?: string | null
  versions: TemplateVersionRow[]
}

/** Слот тега на сервере (для восстановления исходного текста). */
export type TagSlot = {
  id: string
  originalPlainText: string
  currentTemplate: string
  currentOccurrenceIndex?: number | null
  createdAtUtc?: string | null
}

export type ConditionalBlock = {
  id: string
  findTemplate: string
  occurrenceIndex: number
  conditionField: string
  equalsValue: string
  branch: 'if' | 'else'
  elseGroupId?: string | null
  createdAtUtc?: string | null
}

export type TemplateDetail = {
  id: string
  name: string
  status: number
  schemaJson: string
  createdBy: string
  createdAtUtc: string
  currentVersionId?: string | null
  versions: (TemplateVersionRow & { createdAtUtc: string; sourceFileName?: string | null })[]
}

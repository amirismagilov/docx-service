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

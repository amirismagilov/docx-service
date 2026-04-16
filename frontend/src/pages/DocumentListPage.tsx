import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { API_BASE } from '../api'
import type { TemplateListItem } from '../types'

const statusLabel = (s: number) => {
  if (s === 1) return 'Опубликован'
  if (s === 2) return 'Архив'
  return 'Черновик'
}

export default function DocumentListPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<TemplateListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setMessage('')
    try {
      const r = await fetch(`${API_BASE}/templates`)
      if (!r.ok) throw new Error(await r.text())
      const data = (await r.json()) as TemplateListItem[]
      setItems(data)
    } catch (e) {
      setMessage(`Не удалось загрузить список: ${e instanceof Error ? e.message : String(e)}`)
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const createEmpty = async () => {
    const name = window.prompt('Название документа', 'Новый документ')
    if (name === null) return
    setMessage('')
    try {
      const r = await fetch(`${API_BASE}/templates/bootstrap-empty`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim() || 'Новый документ' }),
      })
      if (!r.ok) throw new Error(await r.text())
      const data = (await r.json()) as { templateId: string }
      await load()
      navigate(`/documents/${data.templateId}/edit`)
    } catch (e) {
      setMessage(`Пустой шаблон: ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const rename = async (id: string, currentName: string) => {
    const name = window.prompt('Новое название', currentName)
    if (name === null || !name.trim()) return
    setBusyId(id)
    setMessage('')
    try {
      const r = await fetch(`${API_BASE}/templates/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim() }),
      })
      if (!r.ok) throw new Error(await r.text())
      await load()
    } catch (e) {
      setMessage(`Переименование: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusyId(null)
    }
  }

  const remove = async (id: string, label: string) => {
    if (!window.confirm(`Удалить «${label}»? Все версии будут удалены.`)) return
    setBusyId(id)
    setMessage('')
    try {
      const r = await fetch(`${API_BASE}/templates/${id}`, { method: 'DELETE' })
      if (!r.ok && r.status !== 204) throw new Error(await r.text())
      await load()
    } catch (e) {
      setMessage(`Удаление: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <main className="page">
      <header className="app-header">
        <h1>Документы</h1>
        <p className="lead">Список шаблонов: создание, переименование, удаление и переход к редактированию.</p>
        <div className="row">
          <button type="button" onClick={createEmpty}>
            Новый документ
          </button>
          <button type="button" className="btn-secondary" onClick={() => void load()} disabled={loading}>
            Обновить
          </button>
        </div>
      </header>

      {loading ? (
        <p className="hint">Загрузка…</p>
      ) : items.length === 0 ? (
        <section className="card">
          <p>Нет документов. Создайте новый пустой документ.</p>
        </section>
      ) : (
        <section className="card table-card">
          <table className="doc-table">
            <thead>
              <tr>
                <th>Название</th>
                <th>Статус</th>
                <th>Версий</th>
                <th>Создан</th>
                <th className="th-actions">Действия</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.id}>
                  <td>
                    {/* Нативная ссылка: надёжный переход даже если клиентский роутер не срабатывает (встроенные браузеры, перехват кликов). */}
                    <a className="doc-link" href={`/documents/${row.id}/edit`}>
                      {row.name}
                    </a>
                  </td>
                  <td>{statusLabel(row.status)}</td>
                  <td>{row.versions?.length ?? 0}</td>
                  <td className="cell-muted">{new Date(row.createdAtUtc).toLocaleString('ru-RU')}</td>
                  <td className="td-actions">
                    <a className="btn-link" href={`/documents/${row.id}/edit`}>
                      Редактировать
                    </a>
                    <button
                      type="button"
                      className="btn-text"
                      disabled={busyId === row.id}
                      onClick={() => void rename(row.id, row.name)}
                    >
                      Переименовать
                    </button>
                    <button
                      type="button"
                      className="btn-text btn-danger"
                      disabled={busyId === row.id}
                      onClick={() => void remove(row.id, row.name)}
                    >
                      Удалить
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {message && <p className="message">{message}</p>}
    </main>
  )
}

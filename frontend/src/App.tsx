import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import DocumentEditPage from './pages/DocumentEditPage'
import DocumentListPage from './pages/DocumentListPage'

/** key сбрасывает состояние при переходе между разными id (React Router переиспользует экран). */
function DocumentEditRoute() {
  const { templateId } = useParams()
  return <DocumentEditPage key={templateId} />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<DocumentListPage />} />
        <Route path="/documents/:templateId/edit" element={<DocumentEditRoute />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

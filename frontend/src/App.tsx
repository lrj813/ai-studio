import { Route, Routes, useLocation } from 'react-router-dom'
import Home from './pages/Home'
import Editor from './pages/Editor'
import Settings from './pages/Settings'

function ProjectEditorRoute() {
  const location = useLocation()
  return <Editor key={location.pathname} />
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/project/:id" element={<ProjectEditorRoute />} />
      <Route path="/settings" element={<Settings />} />
    </Routes>
  )
}

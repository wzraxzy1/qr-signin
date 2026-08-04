import React from 'react'
import { Routes, Route, NavLink, useNavigate } from 'react-router-dom'
import AdminPanel from './components/AdminPanel.jsx'
import QRDisplay from './components/QRDisplay.jsx'
import SignInPage from './components/SignInPage.jsx'

function App() {
  const navigate = useNavigate()
  return (
    <div className="app-layout">
      <header className="app-header">
        <h1>📋 二维码签到系统</h1>
        <nav>
          <NavLink
            to="/"
            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
            end
          >
            管理面板
          </NavLink>
        </nav>
      </header>
      <div className="app-content">
        <Routes>
          <Route path="/" element={<AdminPanel />} />
          <Route path="/qr/:sessionId" element={<QRDisplay />} />
          <Route path="/signin" element={<SignInPage />} />
        </Routes>
      </div>
    </div>
  )
}

export default App

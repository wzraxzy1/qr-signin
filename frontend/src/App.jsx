import React from 'react'
import { Routes, Route, NavLink, useNavigate } from 'react-router-dom'
import AdminPanel from './components/AdminPanel.jsx'
import QRDisplay from './components/QRDisplay.jsx'
import SignInPage from './components/SignInPage.jsx'
import Login from './components/Login.jsx'
import UsersManager from './components/UsersManager.jsx'
import { isLoggedIn, getUser, clearAuth } from './auth.js'

function RequireAuth({ children }) {
  const navigate = useNavigate()
  if (!isLoggedIn()) {
    navigate('/login', { replace: true })
    return null
  }
  return children
}

function RequireSuperAdmin({ children }) {
  const navigate = useNavigate()
  const user = getUser()
  if (!isLoggedIn()) {
    navigate('/login', { replace: true })
    return null
  }
  if (user?.role !== 'super_admin') {
    navigate('/', { replace: true })
    return null
  }
  return children
}

function App() {
  const navigate = useNavigate()
  const user = getUser()
  const loggedIn = isLoggedIn()

  const handleLogout = () => {
    if (!window.confirm('确定退出登录吗？')) return
    clearAuth()
    navigate('/login')
  }

  return (
    <div className="app-layout">
      <header className="app-header">
        <h1>📋 二维码签到系统</h1>
        <nav>
          {loggedIn && (
            <>
              <NavLink
                to="/"
                className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                end
              >
                管理面板
              </NavLink>
              {user?.role === 'super_admin' && (
                <NavLink
                  to="/users"
                  className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                >
                  用户管理
                </NavLink>
              )}
              <span className="nav-user">
                {user?.username}
                <button className="nav-logout" onClick={handleLogout}>退出</button>
              </span>
            </>
          )}
        </nav>
      </header>
      <div className="app-content">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signin" element={<SignInPage />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <AdminPanel />
              </RequireAuth>
            }
          />
          <Route
            path="/qr/:sessionId"
            element={
              <RequireAuth>
                <QRDisplay />
              </RequireAuth>
            }
          />
          <Route
            path="/users"
            element={
              <RequireSuperAdmin>
                <UsersManager />
              </RequireSuperAdmin>
            }
          />
        </Routes>
      </div>
    </div>
  )
}

export default App

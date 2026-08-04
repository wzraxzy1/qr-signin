import React, { useState } from 'react'
import axios from 'axios'
import { useNavigate } from 'react-router-dom'
import { setAuth } from '../auth.js'

const API = '/api'

export default function Login() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (submitting) return
    if (!username.trim() || !password) {
      setError('请输入用户名和密码')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const res = await axios.post(`${API}/auth/login`, {
        username: username.trim(),
        password,
      })
      setAuth(res.data.token, res.data.user)
      navigate('/')
    } catch (err) {
      setError(err.response?.data?.detail || '登录失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-container">
      <div className="login-card">
        <div className="login-logo">📋</div>
        <h1 className="login-title">二维码签到系统</h1>
        <p className="login-subtitle">请登录后管理签到会话</p>

        {error && (
          <div className="login-error">{error}</div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">用户名</label>
            <input
              className="form-input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="请输入用户名"
              autoFocus
            />
          </div>
          <div className="form-group">
            <label className="form-label">密码</label>
            <input
              className="form-input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入密码"
            />
          </div>
          <button
            className="btn-login"
            type="submit"
            disabled={submitting}
          >
            {submitting ? '登录中...' : '登 录'}
          </button>
        </form>

        <p className="login-hint">
          默认账号：admin / admin123
        </p>
      </div>
    </div>
  )
}

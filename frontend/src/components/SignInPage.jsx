import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { useSearchParams } from 'react-router-dom'

const API = '/api'

export default function SignInPage() {
  const [searchParams] = useSearchParams()
  const sessionId = searchParams.get('session')
  const token = searchParams.get('token')

  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null) // 'success' | 'error' | null
  const [errorMsg, setErrorMsg] = useState('')
  const [formData, setFormData] = useState({})

  // Fetch session info
  useEffect(() => {
    if (!sessionId || !token) {
      setLoading(false)
      return
    }
    const fetchSession = async () => {
      try {
        const res = await axios.get(`${API}/sessions/${sessionId}`)
        if (res.data.status !== 'active') {
          setErrorMsg('签到会话已关闭')
          setResult('error')
        } else {
          setSession(res.data)
        }
      } catch (err) {
        setErrorMsg('签到会话不存在')
        setResult('error')
      } finally {
        setLoading(false)
      }
    }
    fetchSession()
  }, [sessionId, token])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (submitting) return

    // Validate required fields
    for (const field of session.fields_config) {
      if (field.required && !String(formData[field.name] || '').trim()) {
        setErrorMsg(`请填写${field.label}`)
        setResult('error')
        return
      }
    }

    setSubmitting(true)
    setResult(null)
    try {
      const res = await axios.post(`${API}/sessions/${sessionId}/signin`, {
        token,
        field_data: formData,
      })
      if (res.data.status === 'success') {
        setResult('success')
      }
    } catch (err) {
      const detail = err.response?.data?.detail || '签到失败'
      setErrorMsg(detail)
      setResult('error')
    } finally {
      setSubmitting(false)
    }
  }

  const handleChange = (name, value) => {
    setFormData({ ...formData, [name]: value })
  }

  if (loading) {
    return (
      <div className="signin-container">
        <div className="signin-card">
          <div className="empty-state">加载中...</div>
        </div>
      </div>
    )
  }

  if (!sessionId || !token) {
    return (
      <div className="signin-container">
        <div className="signin-card">
          <div className="empty-state">
            <div className="empty-icon">❌</div>
            <p>无效的签到链接</p>
            <p style={{ fontSize: 13, marginTop: 8 }}>请扫描正确的二维码</p>
          </div>
        </div>
      </div>
    )
  }

  if (result === 'success') {
    return (
      <div className="signin-container">
        <div className="signin-card">
          <div className="signin-success">
            <div className="success-icon">✅</div>
            <h2>签到成功</h2>
            <p style={{ color: 'var(--text-light)', marginTop: 8 }}>
              签到时间：{new Date().toLocaleString('zh-CN')}
            </p>
          </div>
        </div>
      </div>
    )
  }

  if (result === 'error') {
    return (
      <div className="signin-container">
        <div className="signin-card">
          <div className="signin-success">
            <div className="success-icon">⚠️</div>
            <h2 style={{ color: 'var(--danger)' }}>签到失败</h2>
            <p style={{ color: 'var(--text-light)', marginTop: 8 }}>{errorMsg}</p>
            {errorMsg.includes('过期') && (
              <p style={{ fontSize: 13, marginTop: 8, color: 'var(--warning)' }}>
                请重新扫描最新二维码
              </p>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (!session) return null

  return (
    <div className="signin-container">
      <div className="signin-card">
        <h2>{session.name}</h2>
        {errorMsg && !result && (
          <div className="toast error" style={{ position: 'static', transform: 'none', marginBottom: 12 }}>
            {errorMsg}
          </div>
        )}
        <form onSubmit={handleSubmit}>
          {session.fields_config.map((field) => (
            <div key={field.name} className="form-group">
              <label className="form-label">
                {field.label}
                {field.required && <span style={{ color: 'var(--danger)' }}> *</span>}
              </label>
              {field.type === 'select' ? (
                <select
                  className="form-select"
                  value={formData[field.name] || ''}
                  onChange={(e) => handleChange(field.name, e.target.value)}
                >
                  <option value="">请选择</option>
                  {(field.options || '').split(',').filter(Boolean).map((opt) => (
                    <option key={opt.trim()} value={opt.trim()}>{opt.trim()}</option>
                  ))}
                </select>
              ) : (
                <input
                  className="form-input"
                  type={field.type}
                  value={formData[field.name] || ''}
                  onChange={(e) => handleChange(field.name, e.target.value)}
                  placeholder={`请输入${field.label}`}
                />
              )}
            </div>
          ))}
          <button
            className="btn btn-primary"
            type="submit"
            disabled={submitting}
            style={{ width: '100%', marginTop: 8 }}
          >
            {submitting ? '提交中...' : '确认签到'}
          </button>
        </form>
      </div>
    </div>
  )
}

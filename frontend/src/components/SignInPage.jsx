import React, { useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import { useSearchParams } from 'react-router-dom'

const API = '/api'

// 设备指纹：每台浏览器生成一次并持久化在 localStorage，不随 token / session 变化。
// 随每次签到上报给后端，用于"同一设备在同一会话内只能成功签到一次"的防作弊校验。
// 注：清浏览器缓存可重置该指纹（属震慑性防作弊，非绝对不可破解）。
function getDeviceId() {
  let id = localStorage.getItem('qr_signin_device_id')
  if (!id) {
    try {
      id = (window.crypto && window.crypto.randomUUID)
        ? window.crypto.randomUUID()
        : `dev_${Date.now()}_${Math.random().toString(36).slice(2)}`
    } catch (e) {
      id = `dev_${Date.now()}_${Math.random().toString(36).slice(2)}`
    }
    localStorage.setItem('qr_signin_device_id', id)
  }
  return id
}

export default function SignInPage() {
  const [searchParams] = useSearchParams()
  const sessionId = searchParams.get('session')
  const token = searchParams.get('token')

  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null) // 'success' | 'error' | null
  const [errorMsg, setErrorMsg] = useState('')
  const [windowMsg, setWindowMsg] = useState('')
  const [formData, setFormData] = useState({})
  // 同一二维码(同 session+token)签到成功后标记，返回上一页再次进入时直接展示“已签到”，
  // 防止“签到完返回不重新扫码又提交一次”的重复签到漏洞。
  const [alreadySigned, setAlreadySigned] = useState(false)
  // 已签到卡片上展示的具体原因（默认文案兜底；409 时展示后端返回的真实原因）
  const [signedNote, setSignedNote] = useState('')
  const signedKey = `qr_signin_signed_${sessionId}_${token}`
  // 设备级已签标记（不随 token 变化）：重扫新码重新进入时也能即时提示"已签到"，
  // 与后端设备去重互为表里（前端即时反馈、后端权威拦截）。
  const deviceSignedKey = `qr_signin_device_signed_${sessionId}`

  // 评估签到时间窗口：未开始/已结束/已关闭 -> 不允许签到
  const evaluateWindow = (data) => {
    const now = Date.now() / 1000
    if (data.status !== 'active') {
      setErrorMsg('签到会话已关闭')
      setResult('error')
      return false
    }
    if (data.start_at && now < data.start_at) {
      setWindowMsg('签到尚未开始，请在开始时间后签到')
      return false
    }
    if (data.expires_at && now > data.expires_at) {
      setWindowMsg('签到已结束，无法继续签到')
      return false
    }
    if (data.max_signins != null && data.sign_in_count >= data.max_signins) {
      setWindowMsg(`签到人数已满（上限 ${data.max_signins} 人），无法继续签到`)
      return false
    }
    setWindowMsg('')
    return true
  }

  // 手机端拉取会话信息（公开接口，无需登录）
  const fetchSession = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/sessions/${sessionId}/public`)
      setSession(res.data)
      evaluateWindow(res.data)
    } catch (err) {
      setErrorMsg('签到会话不存在')
      setResult('error')
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  useEffect(() => {
    if (!sessionId || !token) {
      setLoading(false)
      return
    }
    // 该二维码已成功签到过，或本设备本场签到已签过（重扫新码）-> 直接展示“已签到”
    if (localStorage.getItem(signedKey) === '1' || localStorage.getItem(deviceSignedKey) === '1') {
      setAlreadySigned(true)
      setSignedNote('该设备已成功签到，请勿重复签到。如需为他人签到，请换一台设备。')
      setLoading(false)
      return
    }
    fetchSession()
  }, [sessionId, token, fetchSession, signedKey])

  // 未开始时定时轮询，到达开始时间后自动开放表单
  useEffect(() => {
    if (windowMsg && windowMsg.includes('尚未开始')) {
      const t = setInterval(fetchSession, 15000)
      return () => clearInterval(t)
    }
  }, [windowMsg, fetchSession])

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
        device_id: getDeviceId(),
      })
      if (res.data.status === 'success') {
        localStorage.setItem(signedKey, '1')
        localStorage.setItem(deviceSignedKey, '1')
        setResult('success')
      }
    } catch (err) {
      const detail = err.response?.data?.detail || '签到失败'
      const status = err.response?.status
      if (status === 409) {
        // 409 分两类，不能一概而论：
        // ① 人数已满 —— 用户并未签到成功，按普通失败展示（绝不标“已签到”）；
        // ② 该身份/该设备已签到（同 token 一码一签 / 身份证/工号等强唯一字段重复 /
        //    同一设备重复进入）——
        //    写“已签到”标记防再次提交，并展示后端返回的真实原因，避免误导。
        if (detail.includes('已满')) {
          setErrorMsg(detail)
          setResult('error')
          return
        }
        localStorage.setItem(signedKey, '1')
        localStorage.setItem(deviceSignedKey, '1')
        setAlreadySigned(true)
        setSignedNote(detail)
        setErrorMsg('')
        setResult(null)
        return
      }
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

  if (alreadySigned) {
    return (
      <div className="signin-container">
        <div className="signin-card">
          <div className="signin-success">
            <div className="success-icon">✅</div>
            <h2>您已签到</h2>
            <p style={{ color: 'var(--text-light)', marginTop: 8 }}>
              {signedNote || '该二维码已成功签到，请勿重复签到。'}
            </p>
            <p style={{ fontSize: 13, marginTop: 8, color: 'var(--warning)' }}>
              如需为他人签到，请重新扫描最新二维码
            </p>
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
            <p style={{ fontSize: 13, marginTop: 8, color: 'var(--warning)' }}>
              如需为他人签到，请重新扫描最新二维码
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

  // 未开始 / 已结束
  if (windowMsg) {
    return (
      <div className="signin-container">
        <div className="signin-card">
          <div className="signin-success">
            <div className="success-icon">⏳</div>
            <h2 style={{ fontSize: 20 }}>{windowMsg}</h2>
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

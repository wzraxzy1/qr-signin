import React, { useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import { useNavigate } from 'react-router-dom'

const API = '/api'

const defaultFields = [
  { name: 'name', label: '姓名', type: 'text', required: true },
  { name: 'phone', label: '手机号', type: 'tel', required: true },
]

const fieldTypes = [
  { value: 'text', label: '文本' },
  { value: 'tel', label: '手机号' },
  { value: 'email', label: '邮箱' },
  { value: 'number', label: '数字' },
  { value: 'date', label: '日期' },
  { value: 'select', label: '下拉选择' },
]

// epoch(秒) <-> datetime-local 字符串（本地时区）
function epochToLocalInput(epoch) {
  if (!epoch) return ''
  const d = new Date(epoch * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function localInputToEpoch(val) {
  if (!val) return null
  const t = new Date(val).getTime() / 1000
  return isNaN(t) ? null : t
}

// 计算会话实际可签到状态（综合 status 字段与时间窗口）
function sessionStatus(s, nowMs) {
  const now = nowMs / 1000
  if (s.status !== 'active') return { label: '已关闭', cls: 'badge-closed' }
  if (s.start_at && now < s.start_at) return { label: '未开始', cls: 'badge-pending' }
  if (s.expires_at && now > s.expires_at) return { label: '已结束', cls: 'badge-closed' }
  return { label: '进行中', cls: 'badge-active' }
}

function fmtWindowTime(t) {
  if (!t) return '不限'
  return new Date(t * 1000).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

export default function AdminPanel() {
  const navigate = useNavigate()
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [viewSession, setViewSession] = useState(null)
  const [toast, setToast] = useState(null)
  const [nowTick, setNowTick] = useState(Date.now())

  // Create form state
  const [form, setForm] = useState({
    name: '',
    refresh_interval: 10,
    fields: [...defaultFields],
    start_at: '',
    expires_at: '',
  })

  const showToast = (msg, type = '') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  const fetchSessions = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/sessions`)
      setSessions(res.data.sessions)
    } catch (err) {
      showToast('加载会话列表失败', 'error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  // 每 30 秒刷新一次，使列表中的时间窗口状态（未开始/进行中/已结束）保持实时
  useEffect(() => {
    const t = setInterval(() => setNowTick(Date.now()), 30000)
    return () => clearInterval(t)
  }, [])

  const updateField = (index, key, value) => {
    const fields = [...form.fields]
    fields[index] = { ...fields[index], [key]: value }
    setForm({ ...form, fields })
  }

  const addField = () => {
    setForm({
      ...form,
      fields: [...form.fields, { name: '', label: '', type: 'text', required: false }],
    })
  }

  const removeField = (index) => {
    setForm({ ...form, fields: form.fields.filter((_, i) => i !== index) })
  }

  const handleCreate = async () => {
    if (!form.name.trim()) {
      showToast('请输入会话名称', 'error')
      return
    }
    // Validate fields
    for (const f of form.fields) {
      if (!f.name.trim() || !f.label.trim()) {
        showToast('请完整填写字段名称和标签', 'error')
        return
      }
    }
    // Ensure unique field names
    const names = form.fields.map(f => f.name)
    if (new Set(names).size !== names.length) {
      showToast('字段名称不能重复', 'error')
      return
    }

    // Time window validation
    const startAt = localInputToEpoch(form.start_at)
    const expiresAt = localInputToEpoch(form.expires_at)
    if (startAt && expiresAt && startAt >= expiresAt) {
      showToast('开始时间必须早于停止时间', 'error')
      return
    }

    try {
      const res = await axios.post(`${API}/sessions`, {
        name: form.name,
        refresh_interval: form.refresh_interval,
        fields_config: form.fields,
        start_at: startAt,
        expires_at: expiresAt,
      })
      showToast('创建成功', 'success')
      setShowCreate(false)
      setForm({ name: '', refresh_interval: 10, fields: [...defaultFields], start_at: '', expires_at: '' })
      fetchSessions()
    } catch (err) {
      showToast('创建失败', 'error')
    }
  }

  const handleDelete = async (id, name) => {
    if (!window.confirm(`确定删除会话"${name}"及其所有签到记录吗？`)) return
    try {
      await axios.delete(`${API}/sessions/${id}`)
      showToast('删除成功', 'success')
      fetchSessions()
    } catch (err) {
      showToast('删除失败', 'error')
    }
  }

  const handleClose = async (id) => {
    if (!window.confirm('确定关闭此签到会话？关闭后将无法继续签到。')) return
    try {
      await axios.put(`${API}/sessions/${id}`, { status: 'closed' })
      showToast('已关闭', 'success')
      fetchSessions()
    } catch (err) {
      showToast('操作失败', 'error')
    }
  }

  if (viewSession) {
    return (
      <SessionDetail
        session={viewSession}
        onBack={() => {
          setViewSession(null)
          fetchSessions()
        }}
        showToast={showToast}
      />
    )
  }

  return (
    <div>
      {toast && <div className={`toast ${toast.type}`}>{toast.msg}</div>}

      <div className="card">
        <div className="card-title">
          <span>签到会话管理</span>
          <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(!showCreate)}>
            {showCreate ? '取消' : '+ 创建会话'}
          </button>
        </div>

        {showCreate && (
          <div style={{ marginBottom: 24, padding: 20, background: '#f8fafc', borderRadius: 12 }}>
            <div className="form-group">
              <label className="form-label">会话名称</label>
              <input
                className="form-input"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="如：周一晨会签到"
              />
            </div>

            <div className="form-group">
              <label className="form-label">二维码刷新间隔</label>
              <div style={{ display: 'flex', gap: 12 }}>
                {[5, 10, 15].map((v) => (
                  <button
                    key={v}
                    className={`btn btn-sm ${form.refresh_interval === v ? 'btn-primary' : 'btn-secondary'}`}
                    onClick={() => setForm({ ...form, refresh_interval: v })}
                  >
                    {v} 秒
                  </button>
                ))}
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">开始时间（可选）</label>
              <input
                className="form-input"
                type="datetime-local"
                value={form.start_at}
                onChange={(e) => setForm({ ...form, start_at: e.target.value })}
                style={{ maxWidth: 280 }}
              />
              <p style={{ fontSize: 12, color: 'var(--text-light)', marginTop: 4 }}>
                留空表示不限制，到时间前不可签到
              </p>
            </div>

            <div className="form-group">
              <label className="form-label">停止时间（可选）</label>
              <input
                className="form-input"
                type="datetime-local"
                value={form.expires_at}
                onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
                style={{ maxWidth: 280 }}
              />
              <p style={{ fontSize: 12, color: 'var(--text-light)', marginTop: 4 }}>
                留空表示不限制，到时间后自动停止签到
              </p>
            </div>

            <div className="form-group">
              <label className="form-label">签到字段配置</label>
              {form.fields.map((field, i) => (
                <div key={i} className="field-config-item">
                  <input
                    className="form-input"
                    placeholder="字段标识(英文)"
                    value={field.name}
                    onChange={(e) => updateField(i, 'name', e.target.value)}
                    style={{ maxWidth: 140 }}
                  />
                  <input
                    className="form-input"
                    placeholder="显示标签"
                    value={field.label}
                    onChange={(e) => updateField(i, 'label', e.target.value)}
                    style={{ maxWidth: 120 }}
                  />
                  <select
                    className="form-select"
                    value={field.type}
                    onChange={(e) => updateField(i, 'type', e.target.value)}
                    style={{ maxWidth: 120 }}
                  >
                    {fieldTypes.map((t) => (
                      <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                  </select>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, whiteSpace: 'nowrap' }}>
                    <input
                      type="checkbox"
                      checked={field.required}
                      onChange={(e) => updateField(i, 'required', e.target.checked)}
                    />
                    必填
                  </label>
                  <button className="btn btn-danger btn-sm btn-remove" onClick={() => removeField(i)}>
                    删除
                  </button>
                </div>
              ))}
              <button className="btn btn-secondary btn-sm" onClick={addField} style={{ marginTop: 8 }}>
                + 添加字段
              </button>
            </div>

            <button className="btn btn-primary" onClick={handleCreate}>
              确认创建
            </button>
          </div>
        )}

        {loading ? (
          <div className="empty-state">加载中...</div>
        ) : sessions.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">📋</div>
            <p>暂无签到会话，点击上方创建</p>
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>会话名称</th>
                <th>刷新间隔</th>
                <th>创建时间</th>
                <th>签到时间窗口</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => {
                const st = sessionStatus(s, nowTick)
                return (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td>{s.refresh_interval}s</td>
                  <td>{new Date(s.created_at * 1000).toLocaleString('zh-CN')}</td>
                  <td style={{ fontSize: 13, color: 'var(--text-light)' }}>
                    开始 {fmtWindowTime(s.start_at)}<br />
                    停止 {fmtWindowTime(s.expires_at)}
                  </td>
                  <td>
                    <span className={`badge ${st.cls}`}>{st.label}</span>
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={() => navigate(`/qr/${s.id}`)}
                        disabled={s.status !== 'active'}
                      >
                        显示二维码
                      </button>
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => setViewSession(s)}
                      >
                        查看/导出
                      </button>
                      {s.status === 'active' && (
                        <button className="btn btn-secondary btn-sm" onClick={() => handleClose(s.id)}>
                          关闭
                        </button>
                      )}
                      <button className="btn btn-danger btn-sm" onClick={() => handleDelete(s.id, s.name)}>
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ==================== Session Detail Component ====================
function SessionDetail({ session, onBack, showToast }) {
  const [records, setRecords] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [startInput, setStartInput] = useState(epochToLocalInput(session.start_at))
  const [endInput, setEndInput] = useState(epochToLocalInput(session.expires_at))
  const [savingTime, setSavingTime] = useState(false)

  const handleSaveTime = async () => {
    const sa = localInputToEpoch(startInput)
    const ea = localInputToEpoch(endInput)
    if (sa && ea && sa >= ea) {
      showToast('开始时间必须早于停止时间', 'error')
      return
    }
    setSavingTime(true)
    try {
      await axios.put(`${API}/sessions/${session.id}`, { start_at: sa, expires_at: ea })
      showToast('时间设置已保存', 'success')
      onBack()
    } catch (err) {
      showToast('保存失败', 'error')
    } finally {
      setSavingTime(false)
    }
  }

  useEffect(() => {
    const load = async () => {
      try {
        const res = await axios.get(`${API}/sessions/${session.id}/records`)
        setRecords(res.data)
      } catch (err) {
        showToast('加载记录失败', 'error')
      }
    }
    load()
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [session.id, refreshKey])

  if (!records) return <div className="empty-state">加载中...</div>

  return (
    <div>
      <div className="card">
        <div className="card-title">
          <span>{session.name} - 签到记录</span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className="btn btn-success btn-sm"
              onClick={() => window.open(`${API}/sessions/${session.id}/export`)}
            >
              📥 导出 CSV
            </button>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setRefreshKey(k => k + 1)}
            >
              🔄 刷新
            </button>
            <button className="btn btn-secondary btn-sm" onClick={onBack}>
              返回
            </button>
          </div>
        </div>

        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-value">{records.total}</div>
            <div className="stat-label">签到人数</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{session.refresh_interval}s</div>
            <div className="stat-label">刷新间隔</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{records.fields_config.length}</div>
            <div className="stat-label">字段数量</div>
          </div>
        </div>

        <div className="card" style={{ marginTop: 20 }}>
          <div className="card-title"><span>签到时间窗口</span></div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div className="form-group" style={{ margin: 0 }}>
              <label className="form-label">开始时间（可选）</label>
              <input
                className="form-input"
                type="datetime-local"
                value={startInput}
                onChange={(e) => setStartInput(e.target.value)}
                style={{ maxWidth: 260 }}
              />
            </div>
            <div className="form-group" style={{ margin: 0 }}>
              <label className="form-label">停止时间（可选）</label>
              <input
                className="form-input"
                type="datetime-local"
                value={endInput}
                onChange={(e) => setEndInput(e.target.value)}
                style={{ maxWidth: 260 }}
              />
            </div>
            <button className="btn btn-primary btn-sm" onClick={handleSaveTime} disabled={savingTime}>
              {savingTime ? '保存中...' : '保存时间'}
            </button>
          </div>
          <p style={{ fontSize: 12, color: 'var(--text-light)', marginTop: 10 }}>
            留空表示不限制。设置后：未到开始时间不可签到、超过停止时间自动停止签到。
          </p>
        </div>

        {records.records.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">📝</div>
            <p>暂无签到记录</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="table">
              <thead>
                <tr>
                  {records.fields_config.map((f) => (
                    <th key={f.name}>{f.label}</th>
                  ))}
                  <th>签到时间</th>
                  <th>IP地址</th>
                </tr>
              </thead>
              <tbody>
                {records.records.map((r) => (
                  <tr key={r.id}>
                    {records.fields_config.map((f) => (
                      <td key={f.name}>{r[f.name]}</td>
                    ))}
                    <td>{r.time_str}</td>
                    <td>{r.ip_address}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

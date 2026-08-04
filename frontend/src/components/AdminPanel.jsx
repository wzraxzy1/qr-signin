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

export default function AdminPanel() {
  const navigate = useNavigate()
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [viewSession, setViewSession] = useState(null)
  const [toast, setToast] = useState(null)

  // Create form state
  const [form, setForm] = useState({
    name: '',
    refresh_interval: 10,
    fields: [...defaultFields],
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

    try {
      const res = await axios.post(`${API}/sessions`, {
        name: form.name,
        refresh_interval: form.refresh_interval,
        fields_config: form.fields,
      })
      showToast('创建成功', 'success')
      setShowCreate(false)
      setForm({ name: '', refresh_interval: 10, fields: [...defaultFields] })
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
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td>{s.refresh_interval}s</td>
                  <td>{new Date(s.created_at * 1000).toLocaleString('zh-CN')}</td>
                  <td>
                    <span className={`badge ${s.status === 'active' ? 'badge-active' : 'badge-closed'}`}>
                      {s.status === 'active' ? '进行中' : '已关闭'}
                    </span>
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
              ))}
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

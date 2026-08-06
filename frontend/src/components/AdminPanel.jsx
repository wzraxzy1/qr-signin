import React, { useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import { useNavigate } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import { getUser } from '../auth'
import LocationPicker from './LocationPicker'

const API = '/api'

const defaultFields = [
  { name: 'name', label: '姓名', type: 'text', required: true },
  { name: 'phone', label: '手机号', type: 'tel', required: true },
  { name: 'employee_id', label: '工号', type: 'text', required: false },
  { name: 'id_card', label: '身份证号', type: 'text', required: false },
  { name: 'student_number', label: '学号', type: 'text', required: false },
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

  // 当前登录用户角色：仅超级管理员能看到「创建者」列
  const me = getUser()
  const isSuper = me?.role === 'super_admin'

  // Create form state
  const [form, setForm] = useState({
    name: '',
    refresh_interval: 10,
    fields: [...defaultFields],
    start_at: '',
    expires_at: '',
    max_signins: '',
    anti_photo: false,
    location_enabled: false,
    center_lat: null,
    center_lng: null,
    radius_m: null,
    location_fallback: 'reject',
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
      const maxVal = form.max_signins === '' ? null : parseInt(form.max_signins, 10)
      const res = await axios.post(`${API}/sessions`, {
        name: form.name,
        refresh_interval: form.refresh_interval,
        fields_config: form.fields,
        start_at: startAt,
        expires_at: expiresAt,
        max_signins: isNaN(maxVal) ? null : maxVal,
        anti_photo: form.anti_photo,
        location_enabled: form.location_enabled,
        center_lat: form.location_enabled ? form.center_lat : null,
        center_lng: form.location_enabled ? form.center_lng : null,
        radius_m: form.location_enabled ? (parseInt(form.radius_m, 10) || null) : null,
        location_fallback: form.location_fallback,
      })
      showToast('创建成功', 'success')
      setShowCreate(false)
      setForm({ name: '', refresh_interval: 10, fields: [...defaultFields], start_at: '', expires_at: '', max_signins: '', anti_photo: false, location_enabled: false, center_lat: null, center_lng: null, radius_m: null, location_fallback: 'reject' })
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
              {form.start_at && form.expires_at && (() => {
                const sT = localInputToEpoch(form.start_at)
                const eT = localInputToEpoch(form.expires_at)
                if (sT && eT && eT > sT && eT - sT < 3600) {
                  return (
                    <p style={{ fontSize: 12, color: 'var(--warning)', marginTop: 4 }}>
                      ⚠️ 开始到停止仅 {Math.round((eT - sT) / 60)} 分钟，到达停止时间后签到将自动结束，请确认是否符合预期
                    </p>
                  )
                }
                return null
              })()}
            </div>

            <div className="form-group">
              <label className="form-label">最多签到人数（可选）</label>
              <input
                className="form-input"
                type="number"
                min="1"
                placeholder="不限制"
                value={form.max_signins}
                onChange={(e) => setForm({ ...form, max_signins: e.target.value })}
                style={{ maxWidth: 200 }}
              />
              <p style={{ fontSize: 12, color: 'var(--text-light)', marginTop: 4 }}>
                留空表示不限制；填写正整数后，签到达到该人数将自动拒绝新签到
              </p>
            </div>

            <div className="form-group">
              <label className="checkbox-label" style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={form.anti_photo}
                  onChange={(e) => setForm({ ...form, anti_photo: e.target.checked })}
                />
                <span>🛡️ 防拍照（动态短时效二维码）</span>
              </label>
              <p style={{ fontSize: 12, color: 'var(--text-light)', marginTop: 4 }}>
                开启后二维码有效期按字段数量自动延长（每个字段约 10 秒填写时间），字段多的表单也有足够时间填写；拍照留存或转发给他人会迅速过期、无法签到。现场扫描屏幕上的活码不受影响。不需要导入名单也能防拍照。
              </p>
            </div>

            <div className="form-group">
              <label className="checkbox-label" style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={form.location_enabled}
                  onChange={(e) => setForm({ ...form, location_enabled: e.target.checked })}
                />
                <span>📍 定位限制（仅允许在指定范围内签到）</span>
              </label>
              <p style={{ fontSize: 12, color: 'var(--text-light)', marginTop: 4 }}>
                开启后，签到者必须位于你设定的中心点半径范围内才能签到（现场围栏，防远程/代签）。在手机上由系统获取 GPS，服务端校验，无法绕过。
              </p>
              {form.location_enabled && (
                <div style={{ marginTop: 12 }}>
                  <LocationPicker
                    center={form.center_lat != null ? { lat: form.center_lat, lng: form.center_lng } : null}
                    radius={form.radius_m}
                    onChange={({ center, radius }) =>
                      setForm({ ...form, center_lat: center.lat, center_lng: center.lng, radius_m: radius })
                    }
                  />
                  <div className="form-group" style={{ marginTop: 12 }}>
                    <label className="form-label">无定位时如何处理</label>
                    <select
                      className="form-select"
                      style={{ maxWidth: 280 }}
                      value={form.location_fallback}
                      onChange={(e) => setForm({ ...form, location_fallback: e.target.value })}
                    >
                      <option value="reject">拒绝签到（严格，防代签最有效）</option>
                      <option value="allow_flag">允许签到但标记「位置异常」供核对</option>
                    </select>
                    <p style={{ fontSize: 12, color: 'var(--text-light)', marginTop: 4 }}>
                      用户拒绝授权定位或无 GPS 时：选「拒绝」则直接拒签；选「允许并标记」则放行并在记录里标注异常，由你事后核对。
                    </p>
                  </div>
                </div>
              )}
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
              <p style={{ fontSize: 12, color: 'var(--text-light)', marginTop: 8, lineHeight: 1.6 }}>
                💡 <strong>防重复签到：</strong>若需确保「同一个人改了姓名/手机号也无法再次签到」，
                请配置一个<strong>强唯一字段</strong>（字段标识填 <code>employee_id</code> 工号、
                <code>id_card</code> 身份证号、或 <code>student_number</code> 学号）。
                未配置时，系统按「姓名+手机号」组合判重，同一个人换个手机号仍可签到。
              </p>
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
                {isSuper && <th>创建者</th>}
                <th>签到时间窗口</th>
                <th>人数上限</th>
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
                  {isSuper && (
                    <td>{s.created_by_username || '超级管理员'}</td>
                  )}
                  <td style={{ fontSize: 13, color: 'var(--text-light)' }}>
                    开始 {fmtWindowTime(s.start_at)}<br />
                    停止 {fmtWindowTime(s.expires_at)}
                  </td>
                  <td>{s.max_signins != null ? `${s.max_signins} 人` : '不限制'}</td>
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
  const [maxInput, setMaxInput] = useState(session.max_signins != null ? String(session.max_signins) : '')
  const [savingTime, setSavingTime] = useState(false)
  const [antiPhoto, setAntiPhoto] = useState(!!session.anti_photo)
  const [locEnabled, setLocEnabled] = useState(!!session.location_enabled)
  const [locCenterLat, setLocCenterLat] = useState(session.center_lat)
  const [locCenterLng, setLocCenterLng] = useState(session.center_lng)
  const [locRadius, setLocRadius] = useState(session.radius_m)
  const [locFallback, setLocFallback] = useState(session.location_fallback || 'reject')

  // 仅超级管理员能看到创建者
  const me = getUser()
  const isSuper = me?.role === 'super_admin'

  const handleSaveTime = async () => {
    const sa = localInputToEpoch(startInput)
    const ea = localInputToEpoch(endInput)
    if (sa && ea && sa >= ea) {
      showToast('开始时间必须早于停止时间', 'error')
      return
    }
    const maxVal = maxInput === '' ? null : parseInt(maxInput, 10)
    if (maxInput !== '' && (isNaN(maxVal) || maxVal < 1)) {
      showToast('最多签到人数需为正整数', 'error')
      return
    }
    setSavingTime(true)
    try {
      await axios.put(`${API}/sessions/${session.id}`, {
        start_at: sa,
        expires_at: ea,
        max_signins: maxVal,
        anti_photo: antiPhoto,
        location_enabled: locEnabled,
        center_lat: locEnabled ? locCenterLat : null,
        center_lng: locEnabled ? locCenterLng : null,
        radius_m: locEnabled ? (parseInt(locRadius, 10) || null) : null,
        location_fallback: locFallback,
      })
      showToast('时间设置已保存', 'success')
      onBack()
    } catch (err) {
      showToast('保存失败', 'error')
    } finally {
      setSavingTime(false)
    }
  }

  // 导出 CSV：用 axios（自带 token）拉取 blob 再触发下载，避免 window.open 不带鉴权导致 401
  const handleExport = async () => {
    try {
      const res = await axios.get(`${API}/sessions/${session.id}/export`, { responseType: 'blob' })
      const url = window.URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      const cd = res.headers['content-disposition'] || ''
      let fname = `signin_${session.name}.csv`
      const m = cd.match(/filename\*=UTF-8''([^;]+)/) || cd.match(/filename="?([^";]+)"?/)
      if (m) fname = decodeURIComponent(m[1])
      a.download = fname
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      showToast('导出失败，请重试', 'error')
    }
  }

  // ---- 名单导入 / 校对 ----
  const [rosterFile, setRosterFile] = useState(null)
  const [matchField, setMatchField] = useState('')
  const [rosterInfo, setRosterInfo] = useState(null)
  const [importing, setImporting] = useState(false)
  const [reconcile, setReconcile] = useState(null)
  const [reconLoading, setReconLoading] = useState(false)
  // 一人一码：个人签到码弹窗
  const [rosterQRCodes, setRosterQRCodes] = useState([])
  const [showQRModal, setShowQRModal] = useState(false)
  const [qrLoading, setQrLoading] = useState(false)

  useEffect(() => {
    // 载入已有名单概览，回填匹配列
    (async () => {
      try {
        const r = await axios.get(`${API}/sessions/${session.id}/roster`)
        setRosterInfo(r.data)
        if (r.data.match_field) setMatchField(r.data.match_field)
      } catch (e) { /* 无名单时不报错 */ }
    })()
  }, [session.id])

  // 拉取每位名单人员的专属签到码（一人一码），打开弹窗
  const handleOpenRosterQR = async () => {
    setQrLoading(true)
    try {
      const res = await axios.get(`${API}/sessions/${session.id}/roster/qrcodes`)
      setRosterQRCodes(res.data.items || [])
      setShowQRModal(true)
    } catch (err) {
      showToast(err.response?.data?.detail || '获取个人签到码失败', 'error')
    } finally {
      setQrLoading(false)
    }
  }

  const handleImportRoster = async () => {
    if (!rosterFile) { showToast('请先选择名单文件', 'error'); return }
    if (!matchField) { showToast('请选择匹配列', 'error'); return }
    setImporting(true)
    try {
      const fd = new FormData()
      fd.append('file', rosterFile)
      fd.append('match_field', matchField)
      const res = await axios.post(`${API}/sessions/${session.id}/roster`, fd)
      setRosterInfo({ count: res.data.count, match_field: res.data.match_field, imported: true })
      setReconcile(null)
      showToast(`已导入 ${res.data.count} 条名单`, 'success')
    } catch (err) {
      const msg = err.response?.data?.detail || '导入失败'
      showToast(msg, 'error')
    } finally {
      setImporting(false)
    }
  }

  const handleLoadReconcile = async () => {
    setReconLoading(true)
    try {
      const res = await axios.get(`${API}/sessions/${session.id}/reconcile`)
      setReconcile(res.data)
    } catch (err) {
      const msg = err.response?.data?.detail || '校对失败'
      showToast(msg, 'error')
    } finally {
      setReconLoading(false)
    }
  }

  const handleExportReconcile = async () => {
    try {
      const res = await axios.get(`${API}/sessions/${session.id}/reconcile/export`, { responseType: 'blob' })
      const url = window.URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      const cd = res.headers['content-disposition'] || ''
      let fname = `reconcile_${session.name}.csv`
      const m = cd.match(/filename\*=UTF-8''([^;]+)/) || cd.match(/filename="?([^";]+)"?/)
      if (m) fname = decodeURIComponent(m[1])
      a.download = fname
      document.body.appendChild(a); a.click(); a.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) { showToast('导出失败，请重试', 'error') }
  }

  const handleDownloadTemplate = () => {
    const labels = (session.fields_config || []).map(f => f.label).join(',')
    const csv = '﻿' + labels + '\n'
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `名单模板_${session.name}.csv`
    document.body.appendChild(a); a.click(); a.remove()
    window.URL.revokeObjectURL(url)
  }

  const renderReconcileTable = (title, list, matchFieldVal, withTime) => {
    if (!list || list.length === 0) return null
    const cols = (session.fields_config || []).filter(f => f.name !== matchFieldVal)
    return (
      <div style={{ marginBottom: 16 }}>
        <div className="card-title" style={{ fontSize: 14, marginTop: 10 }}>{title}（{list.length}）</div>
        <div style={{ overflowX: 'auto' }}>
          <table className="table">
            <thead>
              <tr>
                {cols.map(f => <th key={f.name}>{f.label}</th>)}
                {withTime && <th>签到时间</th>}
              </tr>
            </thead>
            <tbody>
              {list.map((row, i) => (
                <tr key={i}>
                  {cols.map(f => <td key={f.name}>{row[f.name]}</td>)}
                  {withTime && <td>{row._time_str || ''}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
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
          {session.anti_photo && (
            <span className="badge badge-active" style={{ marginLeft: 8 }}>🛡️ 防拍照</span>
          )}
          {session.location_enabled && (
            <span className="badge badge-active" style={{ marginLeft: 8 }}>📍 定位限制</span>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className="btn btn-success btn-sm"
              onClick={handleExport}
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

        {isSuper && session.created_by_username && (
          <p style={{ fontSize: 13, color: 'var(--text-light)', marginTop: -8, marginBottom: 12 }}>
            创建者：{session.created_by_username}
          </p>
        )}

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
          <div className="stat-card">
            <div className="stat-value">
              {session.max_signins != null ? `${records.total} / ${session.max_signins}` : records.total}
            </div>
            <div className="stat-label">签到进度</div>
          </div>
        </div>

        <div className="card" style={{ marginTop: 20 }}>
          <div className="card-title"><span>签到时间窗口与人数上限</span></div>
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
            <div className="form-group" style={{ margin: 0 }}>
              <label className="form-label">最多签到人数（可选）</label>
              <input
                className="form-input"
                type="number"
                min="1"
                placeholder="不限制"
                value={maxInput}
                onChange={(e) => setMaxInput(e.target.value)}
                style={{ maxWidth: 200 }}
              />
            </div>
            <div className="form-group" style={{ margin: 0 }}>
              <label className="checkbox-label" style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={antiPhoto}
                  onChange={(e) => setAntiPhoto(e.target.checked)}
                />
                <span>🛡️ 防拍照（动态短时效二维码）</span>
              </label>
              <p style={{ fontSize: 12, color: 'var(--text-light)', marginTop: 4 }}>
                开启后二维码有效期按字段数量自动延长（每个字段约 10 秒填写时间），拍照留存/转发仍会迅速过期无法签到；现场扫活码不受影响。
              </p>
            </div>
            <div className="form-group" style={{ margin: 0, flexBasis: '100%' }}>
              <label className="checkbox-label" style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={locEnabled}
                  onChange={(e) => setLocEnabled(e.target.checked)}
                />
                <span>📍 定位限制（仅允许在指定范围内签到）</span>
              </label>
              <p style={{ fontSize: 12, color: 'var(--text-light)', marginTop: 4 }}>
                开启后，签到者必须位于你设定的中心点半径范围内才能签到（现场围栏，防远程/代签）。
              </p>
              {locEnabled && (
                <div style={{ marginTop: 12 }}>
                  <LocationPicker
                    center={locCenterLat != null ? { lat: locCenterLat, lng: locCenterLng } : null}
                    radius={locRadius}
                    onChange={({ center, radius }) => {
                      setLocCenterLat(center.lat)
                      setLocCenterLng(center.lng)
                      setLocRadius(radius)
                    }}
                  />
                  <div className="form-group" style={{ marginTop: 12 }}>
                    <label className="form-label">无定位时如何处理</label>
                    <select
                      className="form-select"
                      style={{ maxWidth: 280 }}
                      value={locFallback}
                      onChange={(e) => setLocFallback(e.target.value)}
                    >
                      <option value="reject">拒绝签到（严格，防代签最有效）</option>
                      <option value="allow_flag">允许签到但标记「位置异常」供核对</option>
                    </select>
                  </div>
                </div>
              )}
            </div>
            <button className="btn btn-primary btn-sm" onClick={handleSaveTime} disabled={savingTime}>
              {savingTime ? '保存中...' : '保存设置'}
            </button>
          </div>
          <p style={{ fontSize: 12, color: 'var(--text-light)', marginTop: 10 }}>
            时间留空表示不限制：未到开始时间不可签到、超过停止时间自动停止签到。人数上限留空表示不限制，填写正整数后达到上限将自动拒绝新签到。
          </p>
        </div>

        {/* 名单导入与校对 */}
        <div className="card" style={{ marginTop: 20 }}>
          <div className="card-title">
            <span>名单导入与签到校对</span>
            <button className="btn btn-secondary btn-sm" onClick={handleDownloadTemplate}>⬇️ 下载模板</button>
          </div>
          <p style={{ fontSize: 12, color: 'var(--text-light)', marginTop: -4, marginBottom: 12 }}>
            导入参会人员名单后，可一键比对「谁已签到 / 谁未到 / 名单外签到」。匹配列用于把名单与签到记录对应（建议选工号 / 身份证 / 学号等唯一字段）。
          </p>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div className="form-group" style={{ margin: 0 }}>
              <label className="form-label">选择名单文件（.csv / .xlsx）</label>
              <input type="file" accept=".csv,.xlsx" onChange={(e) => setRosterFile(e.target.files[0])} />
            </div>
            <div className="form-group" style={{ margin: 0 }}>
              <label className="form-label">匹配列</label>
              <select
                className="form-input"
                value={matchField}
                onChange={(e) => setMatchField(e.target.value)}
                style={{ maxWidth: 220 }}
              >
                <option value="">请选择</option>
                {(session.fields_config || []).map((f) => (
                  <option key={f.name} value={f.name}>{f.label}（{f.name}）</option>
                ))}
              </select>
            </div>
            <button className="btn btn-primary btn-sm" onClick={handleImportRoster} disabled={importing}>
              {importing ? '导入中...' : '导入名单'}
            </button>
            <button className="btn btn-success btn-sm" onClick={handleLoadReconcile} disabled={reconLoading}>
              {reconLoading ? '计算中...' : '生成校对报告'}
            </button>
            <button className="btn btn-warning btn-sm" onClick={handleOpenRosterQR} disabled={qrLoading || !rosterInfo?.imported}>
              {qrLoading ? '生成中...' : '生成个人签到码'}
            </button>
            {reconcile && (
              <button className="btn btn-secondary btn-sm" onClick={handleExportReconcile}>⬇️ 导出校对 CSV</button>
            )}
          </div>
          {rosterInfo?.imported && (
            <p style={{ fontSize: 13, color: 'var(--text-light)', marginTop: 10 }}>
              已导入名单 {rosterInfo.count} 条，匹配列：{rosterInfo.match_field}
            </p>
          )}

          {reconcile && (
            <div style={{ marginTop: 16 }}>
              <div style={{ display: 'flex', gap: 16, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
                <span className="badge badge-active">已到 {reconcile.counts.present}</span>
                <span className="badge badge-pending">未到 {reconcile.counts.absent}</span>
                <span className="badge badge-closed">名单外 {reconcile.counts.extra}</span>
                <span style={{ fontSize: 12, color: 'var(--text-light)' }}>
                  名单 {reconcile.roster_total} 人 · 签到 {reconcile.signin_total} 人 · 匹配列：{reconcile.match_field_label}
                </span>
              </div>
              {renderReconcileTable('未到（名单内但未签到）', reconcile.absent, reconcile.match_field, false)}
              {renderReconcileTable('已到（名单内且已签到）', reconcile.present, reconcile.match_field, true)}
              {renderReconcileTable('名单外（签到但不在名单）', reconcile.extra, reconcile.match_field, true)}
            </div>
          )}
        </div>

        {/* 一人一码：个人签到码弹窗 */}
        {showQRModal && (
          <div className="modal-overlay" onClick={() => setShowQRModal(false)}>
            <div className="modal qr-sheet-modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3>个人签到码（一人一码）</h3>
                <button className="btn btn-secondary btn-sm" onClick={() => setShowQRModal(false)}>关闭</button>
              </div>
              <p>
                每位人员一张专属二维码，扫码即以<b>本人身份</b>签到，且只能成功使用一次。
                把码拍照发给别人，对方扫了也是以<b>你的身份</b>签到，无法冒签他人——从根本上杜绝代签/照片分享。
                建议逐一发给本人，或点右下角「打印整页」后裁开发放。
              </p>
              <div className="qr-sheet-grid">
                {rosterQRCodes.map((item) => (
                  <div key={item.seq} className="qr-sheet-item">
                    <QRCodeSVG value={item.url} size={120} level="M" includeMargin={true} />
                    <div className="qr-sheet-name">{item.display}</div>
                    <div className={`badge ${item.signed ? 'badge-active' : 'badge-pending'}`}>
                      {item.signed ? '已签到' : '未签到'}
                    </div>
                  </div>
                ))}
              </div>
              <div style={{ padding: '0 20px 16px', textAlign: 'right' }}>
                <button className="btn btn-secondary btn-sm" onClick={() => window.print()}>🖨️ 打印整页</button>
              </div>
            </div>
          </div>
        )}

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
                {session.location_enabled && <th>位置异常</th>}
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
                  {session.location_enabled && (
                    <td>
                      {r.location_abnormal
                        ? <span style={{ color: '#cf1322', fontWeight: 600 }}>⚠️ 异常</span>
                        : <span style={{ color: '#1a7f43' }}>正常</span>}
                    </td>
                  )}
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

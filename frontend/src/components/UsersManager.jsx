import React, { useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import { getUser } from '../auth.js'

const API = '/api'

const roleLabels = {
  super_admin: '超级管理员',
  admin: '管理员',
}

export default function UsersManager() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ username: '', password: '', role: 'admin' })
  const [editing, setEditing] = useState(null) // {id, role, is_active}
  const [toast, setToast] = useState(null)

  const currentUser = getUser()

  const showToast = (msg, type = '') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  const fetchUsers = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/users`)
      setUsers(res.data.users)
    } catch (err) {
      showToast('加载用户列表失败', 'error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchUsers()
  }, [fetchUsers])

  const handleCreate = async () => {
    if (!form.username.trim() || !form.password) {
      showToast('请输入用户名和密码', 'error')
      return
    }
    try {
      await axios.post(`${API}/users`, form)
      showToast('创建成功', 'success')
      setShowCreate(false)
      setForm({ username: '', password: '', role: 'admin' })
      fetchUsers()
    } catch (err) {
      showToast(err.response?.data?.detail || '创建失败', 'error')
    }
  }

  const handleSaveEdit = async (id) => {
    const target = editing
    try {
      await axios.put(`${API}/users/${id}`, {
        role: target.role,
        is_active: target.is_active ? 1 : 0,
      })
      showToast('已保存', 'success')
      setEditing(null)
      fetchUsers()
    } catch (err) {
      showToast(err.response?.data?.detail || '保存失败', 'error')
    }
  }

  const handleResetPassword = async (id) => {
    const newPass = window.prompt('请输入新密码（至少 6 位）：')
    if (!newPass) return
    if (newPass.length < 6) {
      showToast('密码至少 6 位', 'error')
      return
    }
    try {
      await axios.put(`${API}/users/${id}`, { password: newPass })
      showToast('密码已重置', 'success')
    } catch (err) {
      showToast(err.response?.data?.detail || '重置失败', 'error')
    }
  }

  const handleDelete = async (user) => {
    if (!window.confirm(`确定删除用户"${user.username}"吗？`)) return
    try {
      await axios.delete(`${API}/users/${user.id}`)
      showToast('删除成功', 'success')
      fetchUsers()
    } catch (err) {
      showToast(err.response?.data?.detail || '删除失败', 'error')
    }
  }

  return (
    <div>
      {toast && <div className={`toast ${toast.type}`}>{toast.msg}</div>}
      <div className="card">
      <div className="card-title">
        <span>用户管理</span>
        <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? '取消' : '+ 新建用户'}
        </button>
      </div>

      {showCreate && (
        <div style={{ marginBottom: 24, padding: 20, background: '#f8fafc', borderRadius: 12 }}>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <div className="form-group" style={{ flex: 1, minWidth: 160 }}>
              <label className="form-label">用户名</label>
              <input
                className="form-input"
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                placeholder="登录用户名"
              />
            </div>
            <div className="form-group" style={{ flex: 1, minWidth: 160 }}>
              <label className="form-label">初始密码</label>
              <input
                className="form-input"
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder="至少 6 位"
              />
            </div>
            <div className="form-group" style={{ flex: 1, minWidth: 140 }}>
              <label className="form-label">角色</label>
              <select
                className="form-select"
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
              >
                <option value="admin">管理员</option>
                <option value="super_admin">超级管理员</option>
              </select>
            </div>
          </div>
          <button className="btn btn-primary" onClick={handleCreate}>
            确认创建
          </button>
        </div>
      )}

      {loading ? (
        <div className="empty-state">加载中...</div>
      ) : users.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">👤</div>
          <p>暂无用户</p>
        </div>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>用户名</th>
              <th>角色</th>
              <th>状态</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>
                  {u.username}
                  {u.id === currentUser?.id && (
                    <span className="badge badge-active" style={{ marginLeft: 8 }}>当前账号</span>
                  )}
                </td>
                <td>
                  {editing?.id === u.id ? (
                    <select
                      className="form-select"
                      style={{ padding: '4px 8px', fontSize: 13 }}
                      value={editing.role}
                      onChange={(e) => setEditing({ ...editing, role: e.target.value })}
                    >
                      <option value="admin">管理员</option>
                      <option value="super_admin">超级管理员</option>
                    </select>
                  ) : (
                    roleLabels[u.role] || u.role
                  )}
                </td>
                <td>
                  {editing?.id === u.id ? (
                    <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13 }}>
                      <input
                        type="checkbox"
                        checked={editing.is_active === 1}
                        onChange={(e) => setEditing({ ...editing, is_active: e.target.checked ? 1 : 0 })}
                      />
                      启用
                    </label>
                  ) : (
                    <span className={`badge ${u.is_active ? 'badge-active' : 'badge-closed'}`}>
                      {u.is_active ? '正常' : '已禁用'}
                    </span>
                  )}
                </td>
                <td>{new Date(u.created_at * 1000).toLocaleString('zh-CN')}</td>
                <td>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {editing?.id === u.id ? (
                      <>
                        <button className="btn btn-success btn-sm" onClick={() => handleSaveEdit(u.id)}>
                          保存
                        </button>
                        <button className="btn btn-secondary btn-sm" onClick={() => setEditing(null)}>
                          取消
                        </button>
                      </>
                    ) : (
                      <button className="btn btn-secondary btn-sm" onClick={() => setEditing({ id: u.id, role: u.role, is_active: u.is_active })}>
                        编辑
                      </button>
                    )}
                    <button className="btn btn-secondary btn-sm" onClick={() => handleResetPassword(u.id)}>
                      重置密码
                    </button>
                    <button
                      className="btn btn-danger btn-sm"
                      onClick={() => handleDelete(u)}
                      disabled={u.id === currentUser?.id}
                      title={u.id === currentUser?.id ? '不能删除当前账号' : ''}
                    >
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

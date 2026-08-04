import React, { useState } from 'react'
import axios from 'axios'

const API = '/api'

/**
 * 通用改密码弹窗。
 * mode="self"  -> 用户自助改密（需填当前密码），调用 POST /api/users/me/change-password
 * mode="reset" -> 超管重置他人密码（无需旧密码），调用 PUT /api/users/{userId}
 */
export default function ChangePasswordModal({ mode, userId, username, onClose, onSuccess }) {
  const isSelf = mode === 'self'
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSuccess('')
    if (newPassword.length < 6) {
      setError('新密码至少 6 位')
      return
    }
    if (newPassword !== confirm) {
      setError('两次输入的新密码不一致')
      return
    }
    if (isSelf && !oldPassword) {
      setError('请输入当前密码')
      return
    }
    setSubmitting(true)
    try {
      if (isSelf) {
        await axios.post(`${API}/users/me/change-password`, {
          old_password: oldPassword,
          new_password: newPassword,
        })
      } else {
        await axios.put(`${API}/users/${userId}`, { password: newPassword })
      }
      setSuccess('密码修改成功')
      if (onSuccess) onSuccess()
      setTimeout(() => onClose(), 1200)
    } catch (err) {
      setError(err.response?.data?.detail || '操作失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{isSelf ? '修改密码' : `重置「${username}」的密码`}</h3>
          <button className="modal-close" onClick={onClose} type="button">×</button>
        </div>
        <form onSubmit={handleSubmit}>
          {isSelf && (
            <div className="form-group">
              <label className="form-label">当前密码</label>
              <input
                className="form-input"
                type="password"
                value={oldPassword}
                onChange={(e) => setOldPassword(e.target.value)}
                autoFocus
              />
            </div>
          )}
          <div className="form-group">
            <label className="form-label">{isSelf ? '新密码' : '新密码（至少 6 位）'}</label>
            <input
              className="form-input"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="至少 6 位"
              autoFocus={!isSelf}
            />
          </div>
          <div className="form-group">
            <label className="form-label">确认新密码</label>
            <input
              className="form-input"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </div>
          {error && <div className="login-error">{error}</div>}
          {success && <div className="form-success">{success}</div>}
          <div className="modal-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              取消
            </button>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? '提交中...' : '确认'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

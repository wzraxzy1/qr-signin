import React, { useState, useEffect, useRef, useCallback } from 'react'
import axios from 'axios'
import { useParams, useNavigate } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'

const API = '/api'

// 评估签到时间窗口：返回 'open' | 'pending' | 'ended'
function evalWindow(s, now) {
  if (s.start_at && now < s.start_at) return 'pending'
  if (s.expires_at && now > s.expires_at) return 'ended'
  return 'open'
}

export default function QRDisplay() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const [session, setSession] = useState(null)
  const [qrData, setQrData] = useState(null)
  const [countdown, setCountdown] = useState(0)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [nowTick, setNowTick] = useState(Date.now() / 1000)
  const [windowState, setWindowState] = useState('open')
  const timerRef = useRef(null)
  const countdownRef = useRef(null)
  const tickRef = useRef(null)

  const fetchQR = useCallback(async () => {
    try {
      setIsRefreshing(true)
      const res = await axios.get(`${API}/sessions/${sessionId}/qr`)
      setQrData(res.data)
      setCountdown(res.data.expires_in)
      setTimeout(() => setIsRefreshing(false), 300)
    } catch (err) {
      console.error('Failed to fetch QR:', err)
    }
  }, [sessionId])

  // 拉取会话信息；定时刷新以捕获管理员对状态/时间窗口的修改
  useEffect(() => {
    const fetchSession = async () => {
      try {
        const res = await axios.get(`${API}/sessions/${sessionId}`)
        setSession(res.data)
        if (res.data.status !== 'active') {
          navigate('/')
          return
        }
      } catch (err) {
        console.error('Session not found')
      }
    }
    fetchSession()
    const sid = setInterval(fetchSession, 30000)
    return () => clearInterval(sid)
  }, [sessionId, navigate])

  // 每秒更新时钟，用于实时判断时间窗口边界
  useEffect(() => {
    tickRef.current = setInterval(() => setNowTick(Date.now() / 1000), 1000)
    return () => clearInterval(tickRef.current)
  }, [])

  // 时间窗口状态（仅在状态变化时更新，避免每秒重渲染）
  useEffect(() => {
    if (!session) return
    const ws = evalWindow(session, nowTick)
    setWindowState((prev) => (prev === ws ? prev : ws))
  }, [session, nowTick])

  // 仅在窗口开放时拉取/刷新二维码；否则清空并停止刷新
  useEffect(() => {
    if (!session || windowState !== 'open') {
      setQrData(null)
      return
    }
    fetchQR()
    const interval = (session.refresh_interval || 10) * 1000
    timerRef.current = setInterval(fetchQR, interval)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [session, windowState, fetchQR])

  // Countdown timer
  useEffect(() => {
    countdownRef.current = setInterval(() => {
      setCountdown((prev) => Math.max(0, prev - 0.1))
    }, 100)
    return () => {
      if (countdownRef.current) clearInterval(countdownRef.current)
    }
  }, [])

  if (!session) {
    return <div className="empty-state">加载中...</div>
  }

  const fmtTime = (t) =>
    t ? new Date(t * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '不限'
  const windowText = `开始：${fmtTime(session.start_at)} · 停止：${fmtTime(session.expires_at)}`

  // 未开始 / 已结束：显示状态卡，不显示可用二维码
  if (windowState !== 'open') {
    const isPending = windowState === 'pending'
    const remain = isPending && session.start_at
      ? Math.max(0, Math.ceil(session.start_at - nowTick))
      : 0
    const remainText = remain > 0
      ? `（约 ${Math.floor(remain / 60)} 分 ${remain % 60} 秒后开放）`
      : ''
    return (
      <div className="qr-container">
        <div className="qr-card">
          <h2>{session.name}</h2>
          <div className="qr-window-status">
            <div className="qr-window-icon">{isPending ? '⏳' : '🔴'}</div>
            <div className="qr-window-title">
              {isPending ? '签到尚未开始' : '签到已结束'}
            </div>
            <div className="qr-window-sub">
              {isPending
                ? `开始时间：${fmtTime(session.start_at)}${remainText}`
                : `结束时间：${fmtTime(session.expires_at)}`}
            </div>
            {(session.start_at || session.expires_at) && (
              <div className="qr-time-window">{windowText}</div>
            )}
          </div>
          <button
            className="btn btn-secondary btn-sm"
            style={{ marginTop: 16 }}
            onClick={() => navigate('/')}
          >
            ← 返回管理面板
          </button>
        </div>
      </div>
    )
  }

  if (!qrData) {
    return <div className="empty-state">加载中...</div>
  }

  const progressPercent = qrData.interval > 0
    ? (countdown / qrData.interval) * 100
    : 0

  return (
    <div className="qr-container">
      <div className="qr-card">
        <h2>扫码签到</h2>
        <div className="session-name">{session.name}</div>
        {(session.start_at || session.expires_at) && (
          <div className="qr-time-window">{windowText}</div>
        )}

        <div className={`qr-wrapper ${isRefreshing ? 'refreshing' : ''}`}>
          <QRCodeSVG
            value={qrData.url}
            size={240}
            level="M"
            includeMargin={true}
          />
        </div>

        <div className="countdown-bar">
          <div
            className="countdown-fill"
            style={{ width: `${progressPercent}%` }}
          />
        </div>

        <div className="qr-hint">
          二维码每 <strong>{qrData.interval}</strong> 秒自动刷新
          {countdown < 1 && ' · 正在刷新...'}
        </div>

        {qrData.anti_photo && (
          <div className="qr-antiphoto-hint">
            🛡️ 防拍照模式：二维码约 <strong>{qrData.validity_seconds}</strong> 秒内有效（已按字段数量自动延长填写时间），拍照留存或转发给他人会迅速过期、无法签到。请现场扫描屏幕上当前显示的活码。
          </div>
        )}

        <div className="qr-instructions">
          📱 请使用手机扫描上方二维码完成签到<br />
          二维码过期后需重新扫描最新二维码
        </div>

        <button
          className="btn btn-secondary btn-sm"
          style={{ marginTop: 16 }}
          onClick={() => navigate('/')}
        >
          ← 返回管理面板
        </button>
      </div>
    </div>
  )
}

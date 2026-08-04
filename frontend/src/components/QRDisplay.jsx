import React, { useState, useEffect, useRef, useCallback } from 'react'
import axios from 'axios'
import { useParams, useNavigate } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'

const API = '/api'

export default function QRDisplay() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const [session, setSession] = useState(null)
  const [qrData, setQrData] = useState(null)
  const [countdown, setCountdown] = useState(0)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const timerRef = useRef(null)
  const countdownRef = useRef(null)

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

  // Fetch session info
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
  }, [sessionId, navigate])

  // Fetch QR data on interval
  useEffect(() => {
    if (!session) return
    fetchQR()
    // Set up interval based on refresh_interval
    const interval = (session.refresh_interval || 10) * 1000
    timerRef.current = setInterval(fetchQR, interval)

    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [session, fetchQR])

  // Countdown timer
  useEffect(() => {
    countdownRef.current = setInterval(() => {
      setCountdown((prev) => Math.max(0, prev - 0.1))
    }, 100)
    return () => {
      if (countdownRef.current) clearInterval(countdownRef.current)
    }
  }, [])

  if (!session || !qrData) {
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

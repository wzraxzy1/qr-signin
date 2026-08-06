import React, { useEffect, useRef, useState } from 'react'

// 合规地图源：腾讯地图 GL JS（国内合规，禁用 Google/Apple/OSM/Mapbox 等）。
// 非默认场景：key 由用户自己在腾讯位置服务申请，经环境变量 VITE_TMAP_KEY 注入；
// 未配置 key 时降级为「手动填经纬度」，保证功能仍可用。
const TMAP_KEY = import.meta.env.VITE_TMAP_KEY || ''

// 中心点坐标系：腾讯地图使用 GCJ-02（火星坐标）。地图点选返回的坐标即为 GCJ-02，
// 与后端存储、签到校验完全一致，切勿再本地转换。手动输入也应填 GCJ-02 坐标
// （可用腾讯/高德地图拾取器获取，例如 https://lbs.qq.com/getPoint/）。
const DEFAULT_CENTER = { lat: 39.984104, lng: 116.307503 } // 北京（GCJ-02）

let _sdkPromise = null
function loadTMap(key) {
  if (window.TMap) return Promise.resolve()
  if (_sdkPromise) return _sdkPromise
  _sdkPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = `https://map.qq.com/api/gljs?v=1.exp&key=${encodeURIComponent(key)}`
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('地图 SDK 加载失败'))
    document.head.appendChild(script)
  })
  return _sdkPromise
}

/**
 * 定位中心点 + 半径选择组件。
 * - 有 key：腾讯地图点选设中心，滑块/输入设半径，地图上绘制范围圈。
 * - 无 key：手动输入经纬度(GCJ-02) + 半径。
 *
 * props:
 *   center: { lat, lng } | null   —— 当前中心点
 *   radius: number                —— 当前半径(米)
 *   onChange: ({ center, radius }) => void
 */
export default function LocationPicker({ center, radius, onChange }) {
  const mapElRef = useRef(null)
  const mapRef = useRef(null)
  const circleRef = useRef(null)
  const [mapReady, setMapReady] = useState(false)
  const [mapError, setMapError] = useState(false)
  const [localCenter, setLocalCenter] = useState(center || DEFAULT_CENTER)
  const [localRadius, setLocalRadius] = useState(radius && radius > 0 ? radius : 200)

  // 中心点变化时同步本地状态（编辑已有会话时父组件传入）
  useEffect(() => {
    if (center && typeof center.lat === 'number') setLocalCenter(center)
  }, [center])
  useEffect(() => {
    if (radius && radius > 0) setLocalRadius(radius)
  }, [radius])

  const emit = (c, r) => {
    onChange && onChange({ center: c, radius: r })
  }

  const drawCircle = () => {
    if (!mapRef.current) return
    const TMap = window.TMap
    const centerLL = new TMap.LatLng(localCenter.lat, localCenter.lng)
    if (circleRef.current) {
      circleRef.current.setGeometries([
        { center: centerLL, radius: localRadius, styleId: 'locCircle' },
      ])
    } else {
      circleRef.current = new TMap.MultiCircle({
        map: mapRef.current,
        styles: {
          locCircle: new TMap.CircleStyle({
            color: 'rgba(24,144,255,0.15)',
            borderColor: '#1890ff',
            borderWidth: 2,
          }),
        },
        geometries: [{ center: centerLL, radius: localRadius, styleId: 'locCircle' }],
      })
    }
  }

  useEffect(() => {
    if (!TMAP_KEY || TMAP_KEY.includes('Please apply')) {
      setMapError(true)
      return
    }
    let cancelled = false
    loadTMap(TMAP_KEY)
      .then(() => {
        if (cancelled || !mapElRef.current) return
        const TMap = window.TMap
        mapRef.current = new TMap.Map(mapElRef.current, {
          center: new TMap.LatLng(localCenter.lat, localCenter.lng),
          zoom: 15,
        })
        mapRef.current.on('click', (evt) => {
          const ll = evt.latLng
          const c = { lat: ll.lat, lng: ll.lng }
          setLocalCenter(c)
          emit(c, localRadius)
          drawCircle()
        })
        drawCircle()
        setMapReady(true)
      })
      .catch(() => {
        if (!cancelled) setMapError(true)
      })
    return () => {
      cancelled = true
      try { mapRef.current && mapRef.current.destroy && mapRef.current.destroy() } catch (e) { /* noop */ }
      mapRef.current = null
      circleRef.current = null
    }
    // 仅在挂载时初始化地图；center/radius 变化由点击/输入事件驱动
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 半径变化：更新地图圈 + 通知父组件
  const onRadiusChange = (r) => {
    const rr = Math.max(10, Math.round(Number(r) || 0))
    setLocalRadius(rr)
    emit(localCenter, rr)
    drawCircle()
  }

  // 手动经纬度输入（无 key 降级 / 也供微调）
  const onManualCenter = (field, val) => {
    const n = parseFloat(val)
    if (Number.isNaN(n)) return
    const c = { ...localCenter, [field]: n }
    setLocalCenter(c)
    emit(c, localRadius)
    if (mapRef.current) {
      mapRef.current.setCenter(new window.TMap.LatLng(c.lat, c.lng))
      drawCircle()
    }
  }

  return (
    <div className="location-picker">
      {mapReady ? (
        <div className="location-map" ref={mapElRef} />
      ) : mapError ? (
        <div className="location-map-fallback">
          ⚠️ 未配置地图 Key，使用手动输入（坐标请填 <b>GCJ-02</b>，可用腾讯地图坐标拾取器获取）
        </div>
      ) : (
        <div className="location-map-fallback">地图加载中...</div>
      )}

      <div className="location-fields">
        <div className="location-row">
          <label>中心纬度 (GCJ-02)</label>
          <input
            className="form-input"
            type="number"
            step="0.000001"
            value={localCenter.lat}
            onChange={(e) => onManualCenter('lat', e.target.value)}
          />
        </div>
        <div className="location-row">
          <label>中心经度 (GCJ-02)</label>
          <input
            className="form-input"
            type="number"
            step="0.000001"
            value={localCenter.lng}
            onChange={(e) => onManualCenter('lng', e.target.value)}
          />
        </div>
        <div className="location-row">
          <label>允许半径：{localRadius} 米</label>
          <input
            type="range"
            min="10"
            max="5000"
            step="10"
            value={localRadius}
            onChange={(e) => onRadiusChange(e.target.value)}
          />
          <input
            className="form-input location-radius-num"
            type="number"
            min="10"
            value={localRadius}
            onChange={(e) => onRadiusChange(e.target.value)}
          />
        </div>
      </div>
    </div>
  )
}

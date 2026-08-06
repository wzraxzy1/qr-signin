import React, { useEffect, useRef, useState } from 'react'

// 合规地图源：腾讯地图 GL JS（国内合规，禁用 Google/Apple/OSM/Mapbox 等）。
// 非默认场景：key 由用户自己在腾讯位置服务申请，经环境变量 VITE_TMAP_KEY 注入；
// 未配置 key 时降级为「手动填经纬度」，保证功能仍可用。
const TMAP_KEY = import.meta.env.VITE_TMAP_KEY || ''

// 中心点坐标系：腾讯地图使用 GCJ-02（火星坐标）。地图点选返回的坐标即为 GCJ-02，
// 与后端存储、签到校验完全一致，切勿再本地转换。手动输入也应填 GCJ-02 坐标
// （可用腾讯/高德地图拾取器获取，例如 https://lbs.qq.com/getPoint/）。
const DEFAULT_CENTER = { lat: 39.984104, lng: 116.307503 } // 北京（GCJ-02）

// ── WGS-84 → GCJ-02（火星坐标）转换（前端版，与后端 config.py 一致）──
// 浏览器 navigator.geolocation 返回 WGS-84，要在腾讯 GCJ-02 地图上正确居中必须先转换。
const GCJ02_A = 6378245.0
const GCJ02_EE = 0.00669342162296594323
function _outOfChina(lat, lng) {
  return !(lng > 73.66 && lng < 135.05 && lat > 3.86 && lat < 53.55)
}
function _transformLat(x, y) {
  let ret =
    -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x))
  ret += ((20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0) / 3.0
  ret += ((20.0 * Math.sin(y * Math.PI) + 40.0 * Math.sin((y / 3.0) * Math.PI)) * 2.0) / 3.0
  ret += ((160.0 * Math.sin((y / 12.0) * Math.PI) + 320 * Math.sin((y * Math.PI) / 30.0)) * 2.0) / 3.0
  return ret
}
function _transformLng(x, y) {
  let ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x))
  ret += ((20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0) / 3.0
  ret += ((20.0 * Math.sin(x * Math.PI) + 40.0 * Math.sin((x / 3.0) * Math.PI)) * 2.0) / 3.0
  ret += ((150.0 * Math.sin((x / 12.0) * Math.PI) + 300.0 * Math.sin((x / 30.0) * Math.PI)) * 2.0) / 3.0
  return ret
}
export function wgs84ToGcj02(lat, lng) {
  if (_outOfChina(lat, lng)) return { lat, lng }
  const dLat = _transformLat(lng - 105.0, lat - 35.0)
  const dLng = _transformLng(lng - 105.0, lat - 35.0)
  const radLat = (lat / 180.0) * Math.PI
  let magic = Math.sin(radLat)
  magic = 1 - GCJ02_EE * magic * magic
  const sqrtMagic = Math.sqrt(magic)
  const nLat = lat + ((dLat * 180.0) / (((GCJ02_A * (1 - GCJ02_EE)) / (magic * sqrtMagic)) * Math.PI))
  const nLng = lng + ((dLng * 180.0) / ((GCJ02_A / sqrtMagic) * Math.cos(radLat) * Math.PI))
  return { lat: nLat, lng: nLng }
}

let _sdkPromise = null
function loadTMap(key) {
  if (window.TMap) return Promise.resolve()
  if (_sdkPromise) return _sdkPromise
  _sdkPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = `https://map.qq.com/api/gljs?v=1.exp&key=${encodeURIComponent(key)}`
    script.async = true
    // 腾讯对无效 key 也返回 HTTP 200 + 完整 JS（不会触发 onerror），
    // 所以必须加超时兜底，避免无限「加载中」。
    const timer = setTimeout(() => {
      reject(new Error('地图 SDK 加载超时（15s 内未响应，可能网络受限或被拦截）'))
    }, 15000)
    script.onload = () => {
      clearTimeout(timer)
      resolve()
    }
    script.onerror = () => {
      clearTimeout(timer)
      reject(new Error('地图 SDK 脚本加载失败（网络或域名拦截）'))
    }
    document.head.appendChild(script)
  })
  return _sdkPromise
}

/**
 * 定位中心点 + 半径选择组件。
 * - 有 key：腾讯地图点选设中心，滑块/输入设半径，地图上绘制范围圈 + 中心点标记。
 * - 无 key：手动输入经纬度(GCJ-02) + 半径。
 * - 挂载时若未传入已有中心点，尝试定位到用户当前位置（WGS-84 转 GCJ-02 后居中）。
 *
 * props:
 *   center: { lat, lng } | null   —— 当前中心点（编辑已有会话时由父组件传入）
 *   radius: number                —— 当前半径(米)
 *   onChange: ({ center, radius }) => void
 */
export default function LocationPicker({ center, radius, onChange }) {
  const mapElRef = useRef(null)
  const mapRef = useRef(null)
  const circleRef = useRef(null)
  const markerRef = useRef(null)
  const [mapReady, setMapReady] = useState(false)
  const [mapError, setMapError] = useState(false)
  const [mapDetail, setMapDetail] = useState('')
  // 用 ref 保存最新中心/半径，避免点击事件闭包拿到旧值（stale closure）导致
  // 画的圈/标记停在初始点、不跟随点击移动。
  const centerRef = useRef(center && typeof center.lat === 'number' ? center : DEFAULT_CENTER)
  const radiusRef = useRef(radius && radius > 0 ? radius : 200)
  const [localCenter, setLocalCenter] = useState(centerRef.current)
  const [localRadius, setLocalRadius] = useState(radiusRef.current)

  const emit = () => {
    onChange && onChange({ center: { ...centerRef.current }, radius: radiusRef.current })
  }

  // 绘制/更新中心点标记（图钉），让"选中的点"清晰可见
  const drawMarker = () => {
    if (!mapRef.current) return
    const TMap = window.TMap
    const ll = new TMap.LatLng(centerRef.current.lat, centerRef.current.lng)
    if (markerRef.current) {
      markerRef.current.setGeometries([{ id: 'center', position: ll }])
    } else {
      markerRef.current = new TMap.MultiMarker({
        map: mapRef.current,
        geometries: [{ id: 'center', position: ll }],
      })
    }
  }

  const drawCircle = () => {
    if (!mapRef.current) return
    const TMap = window.TMap
    const centerLL = new TMap.LatLng(centerRef.current.lat, centerRef.current.lng)
    if (circleRef.current) {
      circleRef.current.setGeometries([
        { center: centerLL, radius: radiusRef.current, styleId: 'locCircle' },
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
        geometries: [{ center: centerLL, radius: radiusRef.current, styleId: 'locCircle' }],
      })
    }
  }

  // 中心/半径变化时同步输入框展示值
  useEffect(() => {
    if (center && typeof center.lat === 'number') {
      centerRef.current = center
      setLocalCenter(center)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [center])
  useEffect(() => {
    if (radius && radius > 0) {
      radiusRef.current = radius
      setLocalRadius(radius)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [radius])

  useEffect(() => {
    if (!TMAP_KEY || TMAP_KEY.includes('Please apply')) {
      setMapError(true)
      setMapDetail('未配置 VITE_TMAP_KEY，已降级为手动填经纬度（GCJ-02）')
      return
    }
    let cancelled = false
    loadTMap(TMAP_KEY)
      .then(() => {
        if (cancelled || !mapElRef.current) return
        const TMap = window.TMap
        try {
          mapRef.current = new TMap.Map(mapElRef.current, {
            center: new TMap.LatLng(centerRef.current.lat, centerRef.current.lng),
            zoom: 15,
          })
          mapRef.current.on('click', (evt) => {
            const ll = evt.latLng
            const c = { lat: ll.lat, lng: ll.lng }
            centerRef.current = c
            setLocalCenter(c)
            emit()
            drawCircle()
            drawMarker()
          })
          drawCircle()
          drawMarker()
          setMapReady(true)
          // 腾讯对无效/未授权 key：脚本照常 onload，但容器显示鉴权错误文字。
          // 延时检测容器内的腾讯报错文字，把「静默坏图」转成明确提示。
          setTimeout(() => {
            if (cancelled || !mapElRef.current) return
            const txt = mapElRef.current.innerText || ''
            if (/抱歉|未授权|无效|鉴权|key\s*错误|key\s*无效/i.test(txt)) {
              setMapReady(false)
              setMapError(true)
              setMapDetail(
                '腾讯地图返回鉴权错误（容器内显示：「' +
                  txt.trim().slice(0, 40) +
                  '…」）。请在腾讯位置服务控制台检查：①该 key 是否已启用「JavaScript API GL」；②「域名白名单」是否包含你的部署域名（测试阶段可留空）；③key 是否复制完整、无多余空格。'
              )
            }
          }, 5000)
          // 未传入已有中心点 → 尝试定位到用户当前位置（WGS-84 转 GCJ-02 后居中）
          if (!(center && typeof center.lat === 'number') && navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
              (pos) => {
                if (cancelled) return
                const g = wgs84ToGcj02(pos.coords.latitude, pos.coords.longitude)
                centerRef.current = g
                setLocalCenter(g)
                if (mapRef.current) mapRef.current.setCenter(new TMap.LatLng(g.lat, g.lng))
                drawCircle()
                drawMarker()
                emit()
              },
              () => {
                /* 定位失败/用户拒绝：保持默认中心，不强制 */
              },
              { enableHighAccuracy: true, timeout: 8000 }
            )
          }
        } catch (e) {
          if (!cancelled) {
            setMapError(true)
            setMapDetail('地图初始化异常：' + (e && e.message ? e.message : String(e)))
          }
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setMapError(true)
          setMapDetail(err.message)
        }
      })
    return () => {
      cancelled = true
      try {
        mapRef.current && mapRef.current.destroy && mapRef.current.destroy()
      } catch (e) {
        /* noop */
      }
      mapRef.current = null
      circleRef.current = null
      markerRef.current = null
    }
    // 仅在挂载时初始化地图；center/radius 变化由点击/输入事件驱动
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 半径变化：更新地图圈 + 通知父组件
  const onRadiusChange = (r) => {
    const rr = Math.max(10, Math.round(Number(r) || 0))
    radiusRef.current = rr
    setLocalRadius(rr)
    emit()
    drawCircle()
  }

  // 手动经纬度输入（无 key 降级 / 也供微调）
  const onManualCenter = (field, val) => {
    const n = parseFloat(val)
    if (Number.isNaN(n)) return
    const c = { ...centerRef.current, [field]: n }
    centerRef.current = c
    setLocalCenter(c)
    emit()
    if (mapRef.current) {
      mapRef.current.setCenter(new window.TMap.LatLng(c.lat, c.lng))
      drawCircle()
      drawMarker()
    }
  }

  return (
    <div className="location-picker">
      {/* 地图容器必须始终存在于 DOM（初始化时 mapReady 还是 false，
          若条件渲染则 ref 为 null，new TMap.Map(null) 会让地图永远出不来）。
          加载中/报错以浮层覆盖在地图上方。 */}
      <div className="location-map-box">
        <div className="location-map" ref={mapElRef} />
        {!mapReady && !mapError && (
          <div className="location-map-overlay">地图加载中...</div>
        )}
        {mapError && (
          <div className="location-map-overlay">
            ⚠️ 地图无法加载：{mapDetail || '未配置地图 Key'}。
            <br />
            若已配置 key 仍失败，请检查：① 腾讯位置服务控制台该 key 是否启用「JavaScript API GL」；②「域名白名单」是否包含你的部署域名（测试阶段可留空）；③ key 是否复制完整、无多余空格。
            <br />
            临时可用下方手动输入（坐标请填 <b>GCJ-02</b>，可用腾讯地图坐标拾取器获取）。
          </div>
        )}
      </div>

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

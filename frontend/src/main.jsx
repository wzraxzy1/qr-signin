import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import App from './App.jsx'
import './styles.css'

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }
  componentDidCatch(error, info) {
    console.error('React Error:', error, info)
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 40, textAlign: 'center', fontFamily: 'sans-serif' }}>
          <h2 style={{ color: '#ef4444' }}>页面出错了</h2>
          <p style={{ color: '#64748b', marginTop: 8 }}>
            {String(this.state.error)}
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              marginTop: 16, padding: '8px 24px', border: 'none',
              borderRadius: 8, background: '#4f46e5', color: 'white',
              cursor: 'pointer', fontSize: 14
            }}
          >
            刷新重试
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <HashRouter>
        <App />
      </HashRouter>
    </ErrorBoundary>
  </React.StrictMode>
)

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { http } from '../api'

type Model = {
  id: string
  role: string
  status: string
  progress_pct: number
  version: string
  size_gb: number
  license: string
}

type Device = {
  name: string
  chip: string
  mem_gb: number
  os: string
  backend: string
}

const modelStatus: Record<string, string> = {
  ready: '已就绪',
  missing: '未配置 / 未下载',
  partial: '文件不完整',
  downloading: '下载中',
}

export default function Settings() {
  const [device, setDevice] = useState<Device | null>(null)
  const [models, setModels] = useState<Model[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    void Promise.all([http.get('/device'), http.get('/models')])
      .then(([deviceInfo, modelInfo]) => {
        setDevice(deviceInfo)
        setModels(modelInfo)
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : '设备与模型状态暂时无法读取')
      })
  }, [])

  return (
    <main className="settings-shell">
      <header className="editor-header">
        <Link className="editor-brand" to="/">
          <span className="editor-brand-mark">A</span><span>AI STUDIO</span>
        </Link>
        <span className="header-divider" />
        <strong>运行与模型</strong>
        <div className="editor-header-spacer" />
        <Link className="toolbar-button" to="/">返回项目</Link>
      </header>
      <div className="settings-main">
        <p className="eyebrow">RUNTIME & MODEL PROFILE</p>
        <h1>了解当前演示如何运行</h1>
        <p className="settings-intro">
          当前浏览器演示与正式本地部署设计是两套明确区分的方案。这里展示的是运行时检测结果，不读取或展示 API 密钥。
        </p>
        {error && <div className="inline-error" role="alert">{error}</div>}

        <section className="settings-card">
          <div className="settings-card-heading">
            <div><h2>当前设备</h2><p>来自本机运行环境检测</p></div>
            <span className="provider-chip">本地运行</span>
          </div>
          {device ? (
            <div className="settings-facts">
              <div><span>设备</span><strong>{device.name}</strong></div>
              <div><span>处理器</span><strong>{device.chip}</strong></div>
              <div><span>内存</span><strong>{device.mem_gb} GB</strong></div>
              <div><span>系统 / 推理设备</span><strong>{device.os} · {device.backend.toUpperCase()}</strong></div>
            </div>
          ) : <div className="empty-panel">正在读取设备状态…</div>}
        </section>

        <section className="settings-card">
          <div className="settings-card-heading">
            <div><h2>当前演示模型</h2><p>抠图使用本地 U2Net；图片生成使用百炼 API。</p></div>
            <span className="provider-chip">不触发生成调用</span>
          </div>
          <div className="model-list">
            {models.map((model) => (
              <article className="model-row" key={model.id}>
                <div className="model-icon">{model.role === 'matting' ? '分' : '生'}</div>
                <div className="model-description">
                  <strong>{model.id}</strong>
                  <span>{model.version} · {model.size_gb ? `${model.size_gb} GB` : '云端服务'} · {model.license}</span>
                </div>
                <span className={`model-state ${model.role === 'matting' && model.status === 'ready' ? 'is-ready' : ''}`}>
                  {model.role === 'matting' ? modelStatus[model.status] || model.status : 'API /额度未核实'}
                </span>
              </article>
            ))}
            {models.length === 0 && !error && <div className="empty-panel">正在读取模型状态…</div>}
          </div>
          <div className="settings-warning">
            百炼账号剩余额度、免费额度和当前计费价格没有通过此应用核实。生成前请在阿里云控制台确认；页面不会自动充值或发起生成。
          </div>
        </section>

        <section className="settings-card">
          <div className="settings-card-heading">
            <div><h2>正式本地部署目标</h2><p>保留推理扩展接口；不会在此下载大型模型。</p></div>
            <span className="provider-chip">方案 · 未部署</span>
          </div>
          <div className="settings-facts">
            <div><span>主生成模型</span><strong>SDXL 1.0 + ControlNet</strong></div>
            <div><span>商品抠图</span><strong>BiRefNet（目标）</strong></div>
            <div><span>运行框架</span><strong>Diffusers + PyTorch</strong></div>
            <div><span>执行状态</span><strong>接口保留；权重未下载/未实测</strong></div>
          </div>
          <div className="settings-warning">
            当前原型的文生图调用百炼，提示词会发送至云端；这不满足题目“全部推理在本地”的目标要求。正式本地生成尚未实现，不能宣称素材始终不出设备。
          </div>
        </section>

        <section className="settings-card">
          <div className="settings-card-heading">
            <div><h2>模型评估与质量取舍</h2><p>标准沿用开发规格，实测数据不以目标值代替。</p></div>
          </div>
          <div className="settings-evaluation">
            <div><strong>客观指标</strong><span>FID · CLIP Score · LPIPS/SSIM · 抠图 IoU · 端到端耗时 · 冷启动 · 内存峰值</span></div>
            <div><strong>主观评分</strong><span>可用性 · 真实感 · 商品保真 · 构图 · 文字清晰度（1–5 分）</span></div>
            <div><strong>决策原则</strong><span>质量优先；后台队列和边生成边编辑改善等待体验。当前质量/速度/费用样本尚待确认。</span></div>
            <div><strong>授权状态</strong><span>演示未提供真实账号、激活或离线授权系统。</span></div>
          </div>
        </section>
      </div>
    </main>
  )
}

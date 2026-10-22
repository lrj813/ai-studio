import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { assetUrl, http } from '../api'

type ProjectCard = {
  id: string
  name: string
  canvas: { w: number; h: number }
  updated_at: string
  cover?: string
  taskCount: number
}

export default function Home() {
  const [projects, setProjects] = useState<ProjectCard[]>([])
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const nav = useNavigate()

  const load = useCallback(async () => {
    try {
      const items = await http.get('/projects')
      const cards = await Promise.all(
        items.map(async (project: Omit<ProjectCard, 'cover' | 'taskCount'>) => {
          const [assets, tasks] = await Promise.all([
            http.get(`/projects/${project.id}/assets`),
            http.get(`/projects/${project.id}/generations`),
          ])
          return {
            ...project,
            cover: assets[0]?.id ? assetUrl(assets[0].id, true) : undefined,
            taskCount: tasks.length,
          }
        }),
      )
      setProjects(cards)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : '项目列表暂时无法加载')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void Promise.resolve().then(load)
  }, [load])

  const create = async () => {
    setBusy(true)
    setError('')
    try {
      const project = await http.post('/projects', {
        name: name.trim() || '未命名项目',
        canvas: { w: 1080, h: 1080 },
      })
      nav(`/project/${project.id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : '项目创建失败')
    } finally {
      setBusy(false)
    }
  }

  const createPreset = async () => {
    setBusy(true)
    setError('')
    try {
      const project = await http.post('/projects/preset')
      nav(`/project/${project.id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : '示例作品创建失败')
    } finally {
      setBusy(false)
    }
  }

  const rename = async (project: ProjectCard) => {
    const value = window.prompt('项目名称（最多 50 个字）', project.name)
    if (value === null || value.trim() === project.name) return
    try {
      await http.patch(`/projects/${project.id}`, { name: value.trim() })
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '重命名失败')
    }
  }

  const remove = async (project: ProjectCard) => {
    if (!window.confirm(`确定删除「${project.name}」？项目中的素材和作品文件也会删除。`)) return
    try {
      await http.del(`/projects/${project.id}`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败')
    }
  }

  return (
    <main className="home-shell">
      <header className="home-topbar">
        <a className="brand-lockup" href="/" aria-label="AI Studio 首页">
          <span className="brand-mark">A</span>
          <span>AI STUDIO <small>VISUAL WORKSPACE</small></span>
        </a>
        <span className="topbar-note">电商视觉创作工作台</span>
      </header>

      <section className="home-main">
        <div className="home-hero">
          <div className="hero-copy">
            <p className="eyebrow">从商品素材，到成套视觉内容</p>
            <h1>把创意，落在画布上。</h1>
            <p className="hero-description">
              导入商品、抠出主体、构思背景、排版图层，再一次导出多种规格。
              生成任务在后台运行，画布始终可以继续编辑。
            </p>
            <div className="hero-actions">
              <label className="project-name-input">
                <span className="sr-only">项目名称</span>
                <input
                  value={name}
                  maxLength={50}
                  onChange={(event) => setName(event.target.value)}
                  onKeyDown={(event) => event.key === 'Enter' && void create()}
                  placeholder="给新项目起个名字"
                />
              </label>
              <button className="button button-primary" onClick={() => void create()} disabled={busy}>
                {busy ? '正在准备…' : '＋ 新建画布'}
              </button>
            </div>
            <button className="text-button" onClick={() => void createPreset()} disabled={busy}>
              先打开一份可编辑的香氛海报示例 →
            </button>
          </div>
          <div className="hero-art" aria-label="电商视觉创作工作流示意">
            <div className="hero-art-card hero-art-back">
              <span>PRODUCT STORY</span>
              <div className="hero-art-bottle" />
            </div>
            <div className="hero-art-card hero-art-front">
              <span className="hero-art-kicker">STUDIO NOTES / 01</span>
              <div className="hero-art-line" />
              <strong>一张商品图<br />三种上新场景</strong>
              <span className="hero-art-caption">COMPOSE · REFINE · EXPORT</span>
            </div>
            <span className="hero-orbit hero-orbit-one" />
            <span className="hero-orbit hero-orbit-two" />
          </div>
        </div>

        <aside className="privacy-notice" role="note">
          <span className="notice-icon">i</span>
          <div>
            <strong>演示版的数据边界</strong>
            <p>
              题目目标要求所有推理在本地；当前原型仅 U2Net 抠图在本机运行，文生图会把提示词发送至阿里云百炼，
              尚不满足题目目标。生成可能计费，请先在控制台核对额度与价格；本演示不代表正式本地部署方案。
            </p>
          </div>
          <span className="provider-chip">本地抠图 · 云端生成</span>
        </aside>

        <section className="projects-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">WORK IN PROGRESS</p>
              <h2>最近的项目</h2>
            </div>
            <span className="project-count">{projects.length} 个项目</span>
          </div>

          {error && (
            <div className="inline-error" role="alert">
              <span>{error}</span>
              <button className="text-button" onClick={() => { setLoading(true); void load() }}>重试</button>
            </div>
          )}
          {loading ? (
            <div className="project-empty">正在载入项目…</div>
          ) : projects.length === 0 ? (
            <div className="project-empty">
              <div className="empty-icon">＋</div>
              <strong>你的第一个创作，从这里开始</strong>
              <span>新建空白画布，或先打开一份带图层的可编辑示例。</span>
            </div>
          ) : (
            <div className="project-grid">
              {projects.map((project) => (
                <article
                  key={project.id}
                  className="project-card"
                  onDoubleClick={() => nav(`/project/${project.id}`)}
                >
                  <button
                    className="project-cover"
                    onClick={() => nav(`/project/${project.id}`)}
                    aria-label={`打开${project.name}`}
                  >
                    {project.cover ? (
                      <img src={project.cover} alt="" />
                    ) : (
                      <span className="cover-placeholder">CANVAS<br /><b>{project.canvas.w} × {project.canvas.h}</b></span>
                    )}
                    <span className="cover-open">打开项目 ↗</span>
                  </button>
                  <div className="project-card-body">
                    <div>
                      <h3>{project.name}</h3>
                      <p>{project.canvas.w} × {project.canvas.h} · {project.taskCount} 个任务</p>
                    </div>
                    <div className="project-card-actions">
                      <button className="icon-button" onClick={() => void rename(project)} aria-label={`重命名${project.name}`}>···</button>
                      <button className="icon-button danger-action" onClick={() => void remove(project)} aria-label={`删除${project.name}`}>删除</button>
                    </div>
                  </div>
                  <time>{new Date(project.updated_at).toLocaleString()}</time>
                </article>
              ))}
            </div>
          )}
        </section>

        <footer className="home-footer">
          <span>AI Studio · Visual workspace</span>
          <span>质量优先 · 任务排队 · 图层可编辑</span>
        </footer>
      </section>
    </main>
  )
}

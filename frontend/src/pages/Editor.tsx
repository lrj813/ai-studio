import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  Image as KonvaImage,
  Layer as KonvaLayer,
  Rect as KonvaRect,
  Stage,
  Text as KonvaText,
  Transformer,
} from 'react-konva'
import { assetUrl, http } from '../api'

type LayerData = {
  id: string
  project_id: string
  type: 'image' | 'text' | 'shape'
  name: string
  z: number
  x: number
  y: number
  w: number
  h: number
  rotation: number
  opacity: number
  visible: boolean
  locked: boolean
  blend: string
  content: Record<string, any>
  created_at?: string
  updated_at?: string
}

type AssetData = {
  id: string
  project_id: string
  kind: string
  filename: string
  width: number
  height: number
  created_at: string
}

type TaskData = {
  id: string
  project_id: string
  params: Record<string, any>
  status: string
  progress: number
  stage: string
  result_asset_ids: string[]
  error?: string | null
  created_at: string
  queue_position?: number
}

type ProjectData = {
  id: string
  name: string
  canvas: { w: number; h: number }
  updated_at: string
}

type ExportFile = { filename: string; url: string; width: number; height: number }
type History = { past: LayerData[][]; future: LayerData[][] }
type PanelTab = 'assets' | 'layers' | 'generate' | 'tasks' | 'export'

function fitSize(w: number, h: number, maxW: number, maxH: number) {
  const scale = Math.min(maxW / w, maxH / h, 1)
  return { w: Math.round(w * scale), h: Math.round(h * scale) }
}

function newLayer(partial: Partial<LayerData>): LayerData {
  return {
    id: crypto.randomUUID(),
    project_id: '',
    type: 'image',
    name: '',
    z: 0,
    x: 0,
    y: 0,
    w: 200,
    h: 200,
    rotation: 0,
    opacity: 1,
    visible: true,
    locked: false,
    blend: 'normal',
    content: {},
    ...partial,
  }
}

function useImage(url?: string) {
  const [image, setImage] = useState<HTMLImageElement>()
  useEffect(() => {
    if (!url) return
    const loadedImage = new window.Image()
    loadedImage.crossOrigin = 'anonymous'
    loadedImage.onload = () => setImage(loadedImage)
    loadedImage.onerror = () => setImage(undefined)
    loadedImage.src = url
    return () => {
      loadedImage.onload = null
      loadedImage.onerror = null
    }
  }, [url])
  return image
}

function ImageNode({
  layer,
  onRef,
  onSelect,
  onEdit,
  update,
  onTransformEnd,
}: {
  layer: LayerData
  onRef: (node: any) => void
  onSelect: () => void
  onEdit: () => void
  update: (id: string, patch: Partial<LayerData>) => void
  onTransformEnd: (event: any) => void
}) {
  const image = useImage(layer.content.asset_id ? assetUrl(layer.content.asset_id) : undefined)
  if (!image) return null
  return (
    <KonvaImage
      ref={onRef}
      image={image}
      x={layer.x}
      y={layer.y}
      width={layer.w}
      height={layer.h}
      rotation={layer.rotation || 0}
      draggable={!layer.locked}
      opacity={layer.opacity}
      onClick={onSelect}
      onTap={onSelect}
      onDblClick={onEdit}
      onDragEnd={(event) => update(layer.id, { x: event.target.x(), y: event.target.y() })}
      onTransformEnd={onTransformEnd}
    />
  )
}

function isCloudTask(task: TaskData) {
  return task.params.provider === 'dashscope' || (!task.params.provider && task.params.mode === 'txt2img')
}

function statusLabel(status: string, cloudTask = false) {
  return ({
    queued: '排队中',
    running: '生成中',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消',
    interrupted: cloudTask ? '云端状态待确认' : '本地任务中断',
  })[status] || status
}

export default function Editor() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const projectId = id || ''
  const [project, setProject] = useState<ProjectData | null>(null)
  const [layers, setLayers] = useState<LayerData[]>([])
  const [assets, setAssets] = useState<AssetData[]>([])
  const [tasks, setTasks] = useState<TaskData[]>([])
  const [tab, setTab] = useState<PanelTab>('assets')
  const [prompt, setPrompt] = useState('')
  const [numImages, setNumImages] = useState(1)
  const [costConfirmed, setCostConfirmed] = useState(false)
  const [scale, setScale] = useState(0.5)
  const [saveState, setSaveState] = useState<'saved' | 'saving' | 'error'>('saved')
  const [saveMessage, setSaveMessage] = useState('')
  const [loadError, setLoadError] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [historyState, setHistoryState] = useState({ canUndo: false, canRedo: false })
  const [recoveryDraft, setRecoveryDraft] = useState<{ layers: LayerData[]; savedAt: string } | null>(null)
  const [uploading, setUploading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')
  const [exportFormat, setExportFormat] = useState<'png' | 'jpeg'>('png')
  const [exportFiles, setExportFiles] = useState<ExportFile[]>([])
  const [manifestUrl, setManifestUrl] = useState('')
  const [exportDir, setExportDir] = useState('')
  const wrapRef = useRef<HTMLDivElement>(null)
  const saveTimer = useRef<number | undefined>(undefined)
  const layersRef = useRef<LayerData[]>([])
  const revisionRef = useRef(0)
  const saveChainRef = useRef<Promise<unknown>>(Promise.resolve())
  const saveNowRef = useRef<() => void>(() => undefined)
  const lastSavedRef = useRef('')
  const projectLoadedRef = useRef(false)
  const historyRef = useRef<History>({ past: [], future: [] })
  const nodeRefs = useRef<Record<string, any>>({})
  const transformerRef = useRef<any>(null)
  const stageRef = useRef<any>(null)
  const exitSavedRef = useRef(false)
  const undoRef = useRef<() => void>(() => undefined)
  const redoRef = useRef<() => void>(() => undefined)

  const updateHistoryState = useCallback((history: History) => {
    setHistoryState({ canUndo: history.past.length > 0, canRedo: history.future.length > 0 })
  }, [])

  const sortedLayers = useMemo(() => [...layers].sort((a, b) => a.z - b.z), [layers])
  const selectedLayer = layers.find((layer) => layer.id === selectedId) || null

  const loadAssets = useCallback(async () => {
    if (!projectId) return
    setAssets(await http.get(`/projects/${projectId}/assets`))
  }, [projectId])

  const loadTasks = useCallback(async () => {
    if (!projectId) return
    setTasks(await http.get(`/projects/${projectId}/generations`))
  }, [projectId])

  const saveLayers = useCallback(
    (snapshot: LayerData[], revision: number) => {
      const serialized = JSON.stringify(snapshot)
      const saveRequest = saveChainRef.current.then(() =>
        http.put(`/projects/${projectId}/layers`, { layers: snapshot }),
      )
      saveChainRef.current = saveRequest.catch(() => undefined)
      void saveRequest.then(
        () => {
          if (revision !== revisionRef.current) return
          lastSavedRef.current = serialized
          try {
            localStorage.removeItem(`aistudio:draft:${projectId}`)
          } catch {
            setSaveMessage('已保存到项目；浏览器恢复缓存无法清理')
          }
          setSaveState('saved')
          setSaveMessage('')
        },
        (error: unknown) => {
          if (revision === revisionRef.current) {
            setSaveState('error')
            setSaveMessage(error instanceof Error ? error.message : '自动保存失败；草稿保留在本机')
          }
        },
      )
    },
    [projectId],
  )

  const saveNow = useCallback(() => {
    if (!projectId || !projectLoadedRef.current) return
    window.clearTimeout(saveTimer.current)
    const snapshot = layersRef.current
    const serialized = JSON.stringify(snapshot)
    if (serialized === lastSavedRef.current) return
    const revision = revisionRef.current
    setSaveState('saving')
    saveLayers(snapshot, revision)
  }, [projectId, saveLayers])

  useEffect(() => {
    saveNowRef.current = saveNow
  }, [saveNow])

  const commitLayers = useCallback(
    (next: LayerData[], addHistory = true) => {
      const previous = layersRef.current
      if (JSON.stringify(previous) === JSON.stringify(next)) return
      if (addHistory) {
        historyRef.current = {
          past: [...historyRef.current.past, previous].slice(-50),
          future: [],
        }
        updateHistoryState(historyRef.current)
      }
      layersRef.current = next
      setLayers(next)
      revisionRef.current += 1
      exitSavedRef.current = false
      setSaveState('saving')
      setSaveMessage('')
      try {
        localStorage.setItem(
          `aistudio:draft:${projectId}`,
          JSON.stringify({ layers: next, savedAt: new Date().toISOString() }),
        )
      } catch {
        setSaveMessage('本机草稿缓存失败；请等待项目保存完成后再离开')
      }
      window.clearTimeout(saveTimer.current)
      saveTimer.current = window.setTimeout(() => saveNowRef.current(), 2000)
    },
    [projectId, updateHistoryState],
  )

  const loadProject = useCallback(async () => {
    projectLoadedRef.current = false
    try {
      const [projectData, savedLayers, snapshot] = await Promise.all([
        http.get(`/projects/${projectId}`),
        http.get(`/projects/${projectId}/layers`),
        http.get(`/projects/${projectId}/layers/snapshot`),
      ])
      const initialLayers = snapshot?.layers || savedLayers
      const savedAt = snapshot?.created_at || ''
      projectLoadedRef.current = true
      layersRef.current = initialLayers
      historyRef.current = { past: [], future: [] }
      setHistoryState({ canUndo: false, canRedo: false })
      setProject(projectData)
      setLayers(initialLayers)
      lastSavedRef.current = JSON.stringify(initialLayers)
      try {
        const storedDraft = localStorage.getItem(`aistudio:draft:${projectId}`)
        if (storedDraft) {
          const draft = JSON.parse(storedDraft) as { layers: LayerData[]; savedAt: string }
          if (
            Array.isArray(draft.layers) &&
            draft.layers.length <= 500 &&
            draft.savedAt &&
            (!savedAt || draft.savedAt > savedAt) &&
            JSON.stringify(draft.layers) !== JSON.stringify(initialLayers)
          ) {
            setRecoveryDraft(draft)
          } else {
            localStorage.removeItem(`aistudio:draft:${projectId}`)
          }
        }
      } catch {
        setSaveMessage('本机恢复草稿无法读取；已打开项目中最后成功保存的版本')
      }
      await Promise.all([loadAssets(), loadTasks()])
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : '项目加载失败')
    }
  }, [projectId, loadAssets, loadTasks])

  useEffect(() => {
    void Promise.resolve().then(loadProject)
    return () => {
      window.clearTimeout(saveTimer.current)
      if (projectLoadedRef.current && JSON.stringify(layersRef.current) !== lastSavedRef.current) {
        saveLayers(layersRef.current, revisionRef.current)
      }
    }
  }, [loadProject, projectId, saveLayers])

  useEffect(() => {
    const saveOnExit = () => {
      if (!projectId || !projectLoadedRef.current || exitSavedRef.current) return
      const snapshot = layersRef.current
      const serialized = JSON.stringify(snapshot)
      if (serialized === lastSavedRef.current) return
      try {
        const body = new Blob([JSON.stringify({ layers: snapshot })], { type: 'application/json' })
        exitSavedRef.current = navigator.sendBeacon(`/api/projects/${projectId}/layers/beacon`, body)
        if (!exitSavedRef.current) setSaveMessage('离开前保存请求未被浏览器接收；本机草稿仍保留')
      } catch {
        setSaveMessage('离开前保存失败；本机草稿仍保留')
      }
    }
    window.addEventListener('beforeunload', saveOnExit)
    window.addEventListener('pagehide', saveOnExit)
    return () => {
      window.removeEventListener('beforeunload', saveOnExit)
      window.removeEventListener('pagehide', saveOnExit)
    }
  }, [projectId])

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (layersRef.current.length || lastSavedRef.current !== '[]') saveNowRef.current()
      void loadTasks().catch(() => undefined)
    }, 30000)
    return () => window.clearInterval(timer)
  }, [loadTasks])

  useEffect(() => {
    const eventSource = new EventSource(`/api/sse/tasks?project_id=${projectId}`)
    eventSource.addEventListener('task_update', (event) => {
      const update = JSON.parse((event as MessageEvent).data)
      setTasks((current) =>
        current.map((task) =>
          task.id === update.job_id
            ? { ...task, status: update.status, progress: update.progress, stage: update.stage, error: update.error }
            : task,
        ),
      )
    })
    eventSource.addEventListener('done', () => {
      void loadTasks()
      void loadAssets()
    })
    eventSource.addEventListener('error', (event) => {
      const messageEvent = event as MessageEvent
      if (!messageEvent.data) return
      const update = JSON.parse(messageEvent.data)
      setTasks((current) =>
        current.map((task) =>
          task.id === update.job_id
            ? { ...task, status: 'failed', error: update.error?.message || '任务失败' }
            : task,
        ),
      )
      void loadTasks()
    })
    return () => eventSource.close()
  }, [projectId, loadAssets, loadTasks])

  useEffect(() => {
    const element = wrapRef.current
    if (!element || !project) return
    const resize = () => {
      const fit = Math.min((element.clientWidth - 32) / project.canvas.w, (element.clientHeight - 32) / project.canvas.h)
      setScale(Math.max(0.08, Math.min(1, fit)))
    }
    const observer = new ResizeObserver(resize)
    observer.observe(element)
    return () => observer.disconnect()
  }, [project])

  useEffect(() => {
    const transformer = transformerRef.current
    if (!transformer) return
    const selected = selectedId ? layers.find((layer) => layer.id === selectedId) : null
    const node = selected && !selected.locked ? nodeRefs.current[selectedId!] : null
    transformer.nodes(node ? [node] : [])
    transformer.getLayer()?.batchDraw()
  }, [selectedId, layers])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest('input, textarea, select, [contenteditable="true"]')) return
      const key = event.key.toLowerCase()
      if ((event.metaKey || event.ctrlKey) && key === 'z') {
        event.preventDefault()
        if (event.shiftKey) redoRef.current()
        else undoRef.current()
      }
      if ((event.metaKey || event.ctrlKey) && key === 's') {
        event.preventDefault()
        saveNowRef.current()
      }
      if (key === 'escape') setSelectedId(null)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  })

  const undo = useCallback(() => {
    const past = historyRef.current.past
    if (!past.length) return
    const previous = past[past.length - 1]
    historyRef.current = {
      past: past.slice(0, -1),
      future: [layersRef.current, ...historyRef.current.future].slice(0, 50),
    }
    updateHistoryState(historyRef.current)
    commitLayers(previous, false)
  }, [commitLayers, updateHistoryState])

  const redo = useCallback(() => {
    const future = historyRef.current.future
    if (!future.length) return
    const next = future[0]
    historyRef.current = {
      past: [...historyRef.current.past, layersRef.current].slice(-50),
      future: future.slice(1),
    }
    updateHistoryState(historyRef.current)
    commitLayers(next, false)
  }, [commitLayers, updateHistoryState])

  useEffect(() => {
    undoRef.current = undo
    redoRef.current = redo
  }, [undo, redo])

  const updateLayer = (layerId: string, patch: Partial<LayerData>) => {
    commitLayers(layersRef.current.map((layer) => (layer.id === layerId ? { ...layer, ...patch } : layer)))
  }

  const setNodeRef = (layerId: string) => (node: any) => {
    if (node) nodeRefs.current[layerId] = node
    else delete nodeRefs.current[layerId]
  }

  const onTransformEnd = (layer: LayerData) => (event: any) => {
    const node = event.target
    const scaleX = node.scaleX()
    const scaleY = node.scaleY()
    const patch: Partial<LayerData> = { x: node.x(), y: node.y(), rotation: node.rotation() }
    if (layer.type === 'text') {
      patch.content = { ...layer.content, font_size: Math.max(8, Math.round((layer.content.font_size || 36) * scaleX)) }
    } else {
      patch.w = Math.max(8, layer.w * scaleX)
      patch.h = Math.max(8, layer.h * scaleY)
    }
    node.scaleX(1)
    node.scaleY(1)
    updateLayer(layer.id, patch)
  }

  const placeAsset = (asset: AssetData | { id: string; filename: string; width?: number; height?: number }) => {
    if (!project) return
    const { w, h } = fitSize(asset.width || 512, asset.height || 512, project.canvas.w * 0.72, project.canvas.h * 0.72)
    const layer = newLayer({
      project_id: projectId,
      type: 'image',
      name: asset.filename || '素材',
      z: layersRef.current.length,
      x: (project.canvas.w - w) / 2,
      y: (project.canvas.h - h) / 2,
      w,
      h,
      content: { asset_id: asset.id },
    })
    commitLayers([...layersRef.current, layer])
    setSelectedId(layer.id)
    setTab('layers')
  }

  const addText = () => {
    if (!project) return
    const layer = newLayer({
      project_id: projectId,
      type: 'text',
      name: '新文字',
      z: layersRef.current.length,
      x: Math.round(project.canvas.w * 0.12),
      y: Math.round(project.canvas.h * 0.12),
      content: { text: '双击编辑文字', font_size: 42, color: '#332b23' },
    })
    commitLayers([...layersRef.current, layer])
    setSelectedId(layer.id)
    setTab('layers')
  }

  const addShape = () => {
    if (!project) return
    const layer = newLayer({
      project_id: projectId,
      type: 'shape',
      name: '色块',
      z: layersRef.current.length,
      x: Math.round(project.canvas.w * 0.1),
      y: Math.round(project.canvas.h * 0.1),
      w: 220,
      h: 80,
      content: { shape: 'rect', fill: '#c5a678', radius: 8 },
    })
    commitLayers([...layersRef.current, layer])
    setSelectedId(layer.id)
    setTab('layers')
  }

  const editText = (layer: LayerData) => {
    const text = window.prompt('文字内容', layer.content.text || '')
    if (text !== null) updateLayer(layer.id, { content: { ...layer.content, text } })
  }

  const moveLayer = (index: number, direction: -1 | 1) => {
    const nextIndex = index + direction
    if (nextIndex < 0 || nextIndex >= sortedLayers.length) return
    const next = [...sortedLayers]
    ;[next[index], next[nextIndex]] = [next[nextIndex], next[index]]
    commitLayers(next.map((layer, z) => ({ ...layer, z })))
  }

  const removeLayer = (layerId: string) => {
    if (!window.confirm('删除这个图层？原始素材不会删除。')) return
    commitLayers(layersRef.current.filter((layer) => layer.id !== layerId))
    if (selectedId === layerId) setSelectedId(null)
  }

  const duplicateLayer = (layer: LayerData) => {
    const copy = newLayer({
      ...layer,
      id: crypto.randomUUID(),
      name: `${layer.name || '图层'} 副本`,
      z: layersRef.current.length,
      x: layer.x + 24,
      y: layer.y + 24,
      content: { ...layer.content },
    })
    commitLayers([...layersRef.current, copy])
    setSelectedId(copy.id)
  }

  const renameProject = async (value: string) => {
    if (!project || !value.trim() || value.trim() === project.name) return
    try {
      const renamed = await http.patch(`/projects/${projectId}`, { name: value.trim() })
      setProject(renamed)
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : '项目重命名失败')
      setSaveState('error')
    }
  }

  const uploadFiles = async (files: FileList | File[]) => {
    const selectedFiles = Array.from(files)
    if (!selectedFiles.length) return
    setUploading(true)
    setSaveMessage('')
    try {
      for (const file of selectedFiles) {
        if (file.size > 40 * 1024 * 1024) throw new Error(`${file.name} 超过 40MB 限制`)
        const form = new FormData()
        form.append('file', file)
        await http.upload(`/projects/${projectId}/assets`, form)
      }
      await loadAssets()
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : '素材导入失败')
    } finally {
      setUploading(false)
    }
  }

  const submitTask = async (body: Record<string, unknown>) => {
    saveNowRef.current()
    await saveChainRef.current
    const result = await http.post(`/projects/${projectId}/generations`, body)
    await loadTasks()
    setTab('tasks')
    return result as { job_id: string; job_ids?: string[] }
  }

  const startMatting = async (assetId: string) => {
    try {
      saveNowRef.current()
      await saveChainRef.current
      const result = await http.post(`/assets/${assetId}/matting`)
      setTasks((current) => [
        {
          id: result.job_id,
          project_id: projectId,
          params: { mode: 'matting' },
          status: 'queued',
          progress: 0,
          stage: 'queued',
          result_asset_ids: [],
          created_at: new Date().toISOString(),
        },
        ...current,
      ])
      setTab('tasks')
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : '抠图任务提交失败')
    }
  }

  const generate = async () => {
    if (!prompt.trim()) {
      setSaveMessage('先写一句背景描述，再提交生成')
      return
    }
    if (!costConfirmed) {
      setSaveMessage('这会调用云端图片生成；请先确认费用与额度')
      return
    }
    try {
      const result = await submitTask({
        mode: 'txt2img',
        prompt: prompt.trim(),
        width: project?.canvas.w || 1024,
        height: project?.canvas.h || 1024,
        num_images: numImages,
        confirm_cost: true,
      })
      setTasks((current) => {
        const jobs = (result.job_ids || [result.job_id]).map((jobId) => ({
          id: jobId,
          project_id: projectId,
          params: { mode: 'txt2img', prompt: prompt.trim(), width: project?.canvas.w, height: project?.canvas.h },
          status: 'queued',
          progress: 0,
          stage: 'queued',
          result_asset_ids: [],
          created_at: new Date().toISOString(),
        }))
        const known = new Set(current.map((task) => task.id))
        return [...jobs.filter((task) => !known.has(task.id)), ...current]
      })
      setCostConfirmed(false)
      setSaveMessage('')
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : '生成任务提交失败')
    }
  }

  const cancelTask = async (task: TaskData) => {
    try {
      const result = await http.post(`/generations/${task.id}/cancel`)
      setTasks((current) => current.map((item) => (item.id === task.id ? result : item)))
      setSaveMessage(result.error || (result.status === 'cancelled' ? '任务已取消。' : '任务状态已更新。'))
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : '取消任务失败')
    }
  }

  const retryTask = async (task: TaskData) => {
    const cloudTask = isCloudTask(task)
    const confirmCost =
      !cloudTask ||
      window.confirm('重试会再次提交一条百炼图片生成请求，可能产生费用。请先核对账号额度和当前价格；确认继续吗？')
    if (!confirmCost) return
    const confirmUnknownStatus =
      cloudTask && task.status === 'interrupted' &&
      window.confirm('中断任务可能已在百炼生成并计费。请先检查账号任务记录；只有确认没有生成/扣费后再继续。现在确认重试吗？')
    if (cloudTask && task.status === 'interrupted' && !confirmUnknownStatus) return
    try {
      const result = await http.post(`/generations/${task.id}/retry`, {
        confirm_unknown_status: confirmUnknownStatus,
        confirm_cost: confirmCost,
      })
      setTasks((current) => [
        {
          id: result.job_id,
          project_id: projectId,
          params: task.params,
          status: 'queued',
          progress: 0,
          stage: 'queued',
          result_asset_ids: [],
          created_at: new Date().toISOString(),
        },
        ...current,
      ])
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : '重试任务失败')
    }
  }

  const exportSizes = async () => {
    const stage = stageRef.current
    const transformer = transformerRef.current
    if (!stage || !project) {
      setExportError('画布尚未就绪')
      return
    }
    setExporting(true)
    setExportError('')
    const currentScale = stage.scaleX()
    const wasTransformerVisible = transformer?.visible() ?? false
    try {
      saveNowRef.current()
      await saveChainRef.current
      transformer?.hide()
      stage.scale({ x: 1, y: 1 })
      stage.batchDraw()
      const image = stage.toDataURL({ mimeType: 'image/png', pixelRatio: 1 })
      stage.scale({ x: currentScale, y: currentScale })
      if (wasTransformerVisible) transformer.show()
      stage.batchDraw()
      const response = await http.post(`/projects/${projectId}/export`, {
        image_base64: image,
        sizes: [[800, 800], [750, 1000], [1080, 1080]],
        format: exportFormat,
      })
      setExportFiles(response.files)
      setManifestUrl(response.manifest_url)
      setExportDir(response.dir)
      setTab('export')
    } catch (error) {
      stage.scale({ x: currentScale, y: currentScale })
      if (wasTransformerVisible) transformer?.show()
      stage.batchDraw()
      setExportError(error instanceof Error ? error.message : '导出失败')
    } finally {
      setExporting(false)
    }
  }

  const restoreDraft = () => {
    if (!recoveryDraft) return
    commitLayers(recoveryDraft.layers, false)
    setRecoveryDraft(null)
    setSaveMessage('已恢复本机草稿，正在保存到项目…')
  }

  const discardDraft = () => {
    localStorage.removeItem(`aistudio:draft:${projectId}`)
    setRecoveryDraft(null)
  }

  const renderLayer = (layer: LayerData) => {
    if (!layer.visible) return null
    const common = {
      key: layer.id,
      ref: setNodeRef(layer.id),
      x: layer.x,
      y: layer.y,
      rotation: layer.rotation || 0,
      draggable: !layer.locked,
      opacity: layer.opacity,
      onClick: () => setSelectedId(layer.id),
      onTap: () => setSelectedId(layer.id),
      onDblClick: () => layer.type === 'text' && editText(layer),
      onDragEnd: (event: any) => updateLayer(layer.id, { x: event.target.x(), y: event.target.y() }),
      onTransformEnd: onTransformEnd(layer),
    }
    if (layer.type === 'image') {
      return (
        <ImageNode
          key={layer.id}
          layer={layer}
          onRef={setNodeRef(layer.id)}
          onSelect={() => setSelectedId(layer.id)}
          onEdit={() => undefined}
          update={updateLayer}
          onTransformEnd={onTransformEnd(layer)}
        />
      )
    }
    if (layer.type === 'text') {
      return <KonvaText {...common} text={layer.content.text || ''} fontSize={layer.content.font_size || 36} fill={layer.content.color || '#332b23'} />
    }
    if (layer.type === 'shape') {
      return (
        <KonvaRect
          {...common}
          width={layer.w}
          height={layer.h}
          fill={layer.content.fill || '#c5a678'}
          cornerRadius={layer.content.radius || 0}
        />
      )
    }
    return null
  }

  if (loadError) {
    return (
      <main className="home-shell project-empty">
        <strong>无法打开这个项目</strong>
        <span>{loadError}</span>
        <button className="button button-secondary" onClick={() => navigate('/')}>返回项目列表</button>
      </main>
    )
  }
  if (!project) return <main className="home-shell project-empty">正在打开项目…</main>

  const queuedTasks = tasks.filter((task) => task.status === 'queued').sort((a, b) => a.created_at.localeCompare(b.created_at))
  const renderTask = (task: TaskData) => {
    const queuePosition = queuedTasks.findIndex((queued) => queued.id === task.id) + 1
    return (
      <article className="task-card" key={task.id}>
        <div className="task-heading">
          <strong>{task.params?.mode === 'matting' ? '商品抠图' : '图片生成'}</strong>
          <span className="task-state" data-state={task.status}>{statusLabel(task.status, isCloudTask(task))}</span>
        </div>
        <div className="helper-text">
          {task.status === 'queued' ? `队列第 ${queuePosition} 位` : ''}
          {task.status === 'running' ? `${task.progress || 0}% · ${task.stage || '处理中'}` : ''}
          {task.created_at ? ` · ${new Date(task.created_at).toLocaleTimeString()}` : ''}
        </div>
        {(task.status === 'running' || task.status === 'queued') && (
          <div className="task-progress"><span style={{ width: `${task.status === 'queued' ? 0 : task.progress || 3}%` }} /></div>
        )}
        {task.error && <div className="task-error">{task.error}</div>}
        <div className="task-actions">
          {(task.status === 'queued' || task.status === 'running') && (
            <button className="small-button small-button-danger" onClick={() => void cancelTask(task)}>取消任务</button>
          )}
          {['failed', 'cancelled', 'interrupted'].includes(task.status) && (
            <button className="small-button" onClick={() => void retryTask(task)}>
              {task.status === 'interrupted' && isCloudTask(task) ? '核对云端后重试' : '使用相同参数重试'}
            </button>
          )}
        </div>
        {(task.result_asset_ids || []).map((assetId) => (
          <div key={assetId}>
            <img className="result-image" src={assetUrl(assetId)} alt="任务生成结果" />
            <button
              className="small-button small-button-primary"
              onClick={() => placeAsset({ id: assetId, filename: task.params?.mode === 'matting' ? '商品抠图结果' : '生成结果' })}
            >
              置入画布
            </button>
          </div>
        ))}
      </article>
    )
  }

  return (
    <main className="editor-shell">
      <header className="editor-header">
        <a className="editor-brand" href="/" aria-label="返回项目列表">
          <span className="editor-brand-mark">A</span><span>AI STUDIO</span>
        </a>
        <span className="header-divider" />
        <input
          className="project-title-input"
          aria-label="项目名称"
          maxLength={50}
          defaultValue={project.name}
          key={project.name}
          onBlur={(event) => void renameProject(event.target.value)}
          onKeyDown={(event) => event.key === 'Enter' && event.currentTarget.blur()}
        />
        <span className={`save-indicator ${saveState === 'saving' ? 'is-saving' : ''} ${saveState === 'error' ? 'is-error' : ''}`}>
          <i className="save-dot" />
          {saveState === 'saved' ? '已保存' : saveState === 'saving' ? '保存中…' : '保存失败'}
        </span>
        <div className="editor-header-spacer" />
        <button className="toolbar-button" onClick={undo} disabled={!historyState.canUndo} title="撤销 (⌘Z)">↶ <span className="toolbar-label">撤销</span></button>
        <button className="toolbar-button" onClick={redo} disabled={!historyState.canRedo} title="重做 (⇧⌘Z)">↷ <span className="toolbar-label">重做</span></button>
        <button className="toolbar-button" onClick={addText}>＋ <span className="toolbar-label">文字</span></button>
        <button className="toolbar-button" onClick={addShape}>＋ <span className="toolbar-label">形状</span></button>
        <Link className="toolbar-button" to="/settings" title="查看设备与模型状态">模型状态</Link>
        <button className="toolbar-button toolbar-export" onClick={() => void exportSizes()} disabled={exporting}>
          {exporting ? '导出中…' : '导出套图'}
        </button>
      </header>

      {recoveryDraft && (
        <div className="recovery-banner" role="status">
          <span>发现较新的本机草稿（{new Date(recoveryDraft.savedAt).toLocaleString()}），可能包含上次未成功保存的修改。</span>
          <div className="recovery-actions">
            <button className="small-button small-button-primary" onClick={restoreDraft}>恢复草稿</button>
            <button className="small-button" onClick={discardDraft}>使用项目已保存版本</button>
          </div>
        </div>
      )}

      <div className="editor-layout">
        <section className="canvas-column">
          <div className="canvas-toolbar">
            <span>画布 · {project.canvas.w} × {project.canvas.h}</span>
            <span>{Math.round(scale * 100)}% · 点击图层进行编辑</span>
          </div>
          <div className="canvas-viewport" ref={wrapRef}>
            <Stage
              ref={stageRef}
              width={project.canvas.w}
              height={project.canvas.h}
              scaleX={scale}
              scaleY={scale}
              style={{
                width: project.canvas.w * scale,
                height: project.canvas.h * scale,
                overflow: 'hidden',
                boxShadow: '0 10px 35px rgba(45, 40, 32, 0.18)',
              }}
              onMouseDown={(event) => {
                if (event.target === event.target.getStage()) setSelectedId(null)
              }}
              onTouchStart={(event) => {
                if (event.target === event.target.getStage()) setSelectedId(null)
              }}
            >
              <KonvaLayer>
                {sortedLayers.map(renderLayer)}
                <Transformer
                  ref={transformerRef}
                  rotateEnabled
                  anchorSize={8}
                  anchorFill="#fffefa"
                  anchorStroke="#7b6548"
                  borderStroke="#7b6548"
                  borderDash={[4, 3]}
                />
              </KonvaLayer>
            </Stage>
          </div>
          <div className="canvas-hint">⌘Z 撤销 · ⇧⌘Z 重做 · 双击文字可编辑 · 生成任务运行时仍可继续编辑</div>
        </section>

        <aside className="editor-sidebar">
          <nav className="sidebar-tabs" aria-label="工作面板">
            {([
              ['assets', `素材 ${assets.length}`],
              ['layers', `图层 ${layers.length}`],
              ['generate', '生成'],
              ['tasks', '任务'],
              ['export', '导出'],
            ] as [PanelTab, string][]).map(([value, label]) => (
              <button key={value} className={`sidebar-tab ${tab === value ? 'is-active' : ''}`} onClick={() => setTab(value)}>
                {label}
              </button>
            ))}
          </nav>

          <div className="sidebar-content">
            {tab === 'assets' && (
              <section>
                <div className="panel-heading">
                  <div><h2>素材库</h2><p>导入商品原图；抠图会在本机用 U2Net 处理。</p></div>
                  <span className="panel-count">{assets.length}</span>
                </div>
                <label
                  className="dropzone"
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={(event) => {
                    event.preventDefault()
                    void uploadFiles(event.dataTransfer.files)
                  }}
                >
                  <strong>{uploading ? '正在导入素材…' : '点击选择或拖入商品图片'}</strong>
                  <span>PNG / JPG / WebP · 每张不超过 40MB</span>
                  <input
                    className="sr-only"
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    multiple
                    onChange={(event) => {
                      if (event.target.files) void uploadFiles(event.target.files)
                      event.target.value = ''
                    }}
                  />
                </label>
                {assets.length === 0 && <div className="empty-panel">导入一张商品图，开始制作。<br />抠图不会删除原图。</div>}
                {assets.map((asset) => (
                  <article className="asset-card" key={asset.id}>
                    <div className="asset-preview"><img src={assetUrl(asset.id, true)} alt={asset.filename} /></div>
                    <div className="asset-details">
                      <div className="asset-name" title={asset.filename}>{asset.filename}</div>
                      <div className="asset-meta">{asset.width} × {asset.height} · {asset.kind === 'original' ? '原始素材' : asset.kind === 'matting' ? '本地抠图结果' : '生成结果'}</div>
                      <div className="asset-actions">
                        <button className="small-button small-button-primary" onClick={() => placeAsset(asset)}>置入画布</button>
                        {asset.kind === 'original' && <button className="small-button" onClick={() => void startMatting(asset.id)}>本地抠图</button>}
                        <a className="small-button" href={assetUrl(asset.id)} target="_blank" rel="noreferrer">查看原图</a>
                      </div>
                    </div>
                  </article>
                ))}
              </section>
            )}

            {tab === 'layers' && (
              <section>
                <div className="panel-heading">
                  <div><h2>图层与属性</h2><p>调整顺序、显示、锁定和透明度；选择后编辑位置。</p></div>
                  <span className="panel-count">{layers.length}</span>
                </div>
                <div className="button-row">
                  <button className="small-button" onClick={addText}>＋ 添加文字</button>
                  <button className="small-button" onClick={addShape}>＋ 添加色块</button>
                </div>
                {sortedLayers.length === 0 && <div className="empty-panel">画布还没有图层。<br />从素材库置入商品，或添加文字和色块。</div>}
                {[...sortedLayers].reverse().map((layer, reverseIndex) => {
                  const index = sortedLayers.length - 1 - reverseIndex
                  return (
                    <article className={`layer-card ${selectedId === layer.id ? 'is-selected' : ''}`} key={layer.id}>
                      <div className="layer-row">
                        <span className="layer-type">{layer.type === 'image' ? '图' : layer.type === 'text' ? '字' : '形'}</span>
                        <button className="layer-name layer-control" onClick={() => setSelectedId(layer.id)} title={layer.name}>
                          {layer.name || (layer.type === 'text' ? '文字' : layer.type === 'image' ? '图片' : '形状')}
                        </button>
                        <button className="layer-control" title={layer.visible ? '隐藏图层' : '显示图层'} onClick={() => updateLayer(layer.id, { visible: !layer.visible })}>
                          {layer.visible ? '显' : '隐'}
                        </button>
                        <button className="layer-control" title={layer.locked ? '解锁图层' : '锁定图层'} onClick={() => updateLayer(layer.id, { locked: !layer.locked })}>
                          {layer.locked ? '解' : '锁'}
                        </button>
                        <button className="layer-control" title="上移一层" onClick={() => moveLayer(index, 1)}>↑</button>
                        <button className="layer-control" title="下移一层" onClick={() => moveLayer(index, -1)}>↓</button>
                        <button className="layer-control" title="复制图层" onClick={() => duplicateLayer(layer)}>复制</button>
                        <button className="layer-control" title="删除图层" onClick={() => removeLayer(layer.id)}>×</button>
                      </div>
                      <div className="field" style={{ margin: '9px 0 0' }}>
                        <label htmlFor={`opacity-${layer.id}`}>不透明度 · {Math.round(layer.opacity * 100)}%</label>
                        <input
                          id={`opacity-${layer.id}`}
                          type="range"
                          min="0"
                          max="1"
                          step="0.05"
                          value={layer.opacity}
                          onChange={(event) => updateLayer(layer.id, { opacity: Number(event.target.value) })}
                        />
                      </div>
                    </article>
                  )
                })}
                {selectedLayer && (
                  <div className="form-divider">
                    <h3 style={{ margin: '12px 0', fontSize: 11 }}>选中图层属性</h3>
                    <div className="field">
                      <label htmlFor="layer-name">图层名称</label>
                      <input id="layer-name" value={selectedLayer.name} onChange={(event) => updateLayer(selectedLayer.id, { name: event.target.value })} />
                    </div>
                    <div className="property-grid">
                      <div className="field"><label htmlFor="layer-x">X</label><input id="layer-x" type="number" value={Math.round(selectedLayer.x)} onChange={(event) => updateLayer(selectedLayer.id, { x: Number(event.target.value) })} /></div>
                      <div className="field"><label htmlFor="layer-y">Y</label><input id="layer-y" type="number" value={Math.round(selectedLayer.y)} onChange={(event) => updateLayer(selectedLayer.id, { y: Number(event.target.value) })} /></div>
                    </div>
                    {selectedLayer.type === 'text' && (
                      <>
                        <div className="field"><label htmlFor="layer-text">文字内容</label><textarea id="layer-text" value={selectedLayer.content.text || ''} onChange={(event) => updateLayer(selectedLayer.id, { content: { ...selectedLayer.content, text: event.target.value } })} /></div>
                        <div className="property-grid">
                          <div className="field"><label htmlFor="text-size">字号</label><input id="text-size" type="number" min="8" max="400" value={selectedLayer.content.font_size || 36} onChange={(event) => updateLayer(selectedLayer.id, { content: { ...selectedLayer.content, font_size: Number(event.target.value) } })} /></div>
                          <div className="field"><label htmlFor="text-color">文字颜色</label><input id="text-color" type="color" value={selectedLayer.content.color || '#332b23'} onChange={(event) => updateLayer(selectedLayer.id, { content: { ...selectedLayer.content, color: event.target.value } })} /></div>
                        </div>
                      </>
                    )}
                    {selectedLayer.type === 'shape' && (
                      <div className="field"><label htmlFor="shape-fill">色块颜色</label><input id="shape-fill" type="color" value={selectedLayer.content.fill || '#c5a678'} onChange={(event) => updateLayer(selectedLayer.id, { content: { ...selectedLayer.content, fill: event.target.value } })} /></div>
                    )}
                    {selectedLayer.type !== 'text' && (
                      <div className="property-grid">
                        <div className="field"><label htmlFor="layer-width">宽度</label><input id="layer-width" type="number" min="1" value={Math.round(selectedLayer.w)} onChange={(event) => updateLayer(selectedLayer.id, { w: Math.max(1, Number(event.target.value)) })} /></div>
                        <div className="field"><label htmlFor="layer-height">高度</label><input id="layer-height" type="number" min="1" value={Math.round(selectedLayer.h)} onChange={(event) => updateLayer(selectedLayer.id, { h: Math.max(1, Number(event.target.value)) })} /></div>
                      </div>
                    )}
                  </div>
                )}
              </section>
            )}

            {tab === 'generate' && (
              <section>
                <div className="panel-heading">
                  <div><h2>背景生成</h2><p>提交后进入后台队列；画布编辑不受阻塞。</p></div>
                </div>
                <div className="cost-notice">
                  <strong>云端调用 · 先核对费用</strong>
                  当前原型使用阿里云百炼，提示词会发送到云端；费用与账号额度未核实。题目目标要求全部推理本地完成，本原型的云端文生图尚不满足该要求。
                </div>
                <div className="form-divider" />
                <div className="field">
                  <label htmlFor="generation-mode">生成方式</label>
                  <select id="generation-mode" value="background" onChange={() => undefined}>
                    <option value="background">生成电商背景（文生图）</option>
                    <option value="product">图生图 / 局部重绘（后续接入）</option>
                  </select>
                  <span className="helper-text">当前可提交文生图背景；参考图编辑、遮罩重绘和 ControlNet 尚未接入，不会伪装成已支持。</span>
                </div>
                <div className="field">
                  <label htmlFor="prompt">背景描述</label>
                  <textarea
                    id="prompt"
                    maxLength={2000}
                    value={prompt}
                    onChange={(event) => setPrompt(event.target.value)}
                    placeholder="例如：暖调石材台面，柔和侧光，淡玫瑰色氛围，画面中央为产品预留空间"
                  />
                  <span className="helper-text">{prompt.length} / 2000</span>
                </div>
                <div className="field">
                  <label htmlFor="image-count">生成张数</label>
                  <select id="image-count" value={numImages} onChange={(event) => setNumImages(Number(event.target.value))}>
                    {[1, 2, 3, 4].map((count) => <option key={count} value={count}>{count} 张 · 费用以百炼控制台为准</option>)}
                  </select>
                </div>
                <label className="consent-check">
                  <input type="checkbox" checked={costConfirmed} onChange={(event) => setCostConfirmed(event.target.checked)} />
                  <span>我已核对账号额度与当前价格，并确认本次会向百炼提交 {numImages} 张图片请求。</span>
                </label>
                <button className="button button-primary" style={{ width: '100%', marginTop: 12 }} onClick={() => void generate()} disabled={!costConfirmed}>
                  提交背景生成任务
                </button>
                <div className="status-message">题目目标：所有推理在本地。当前原型的文生图调用百炼，尚未满足该目标；不自动下载大型模型。</div>
              </section>
            )}

            {tab === 'tasks' && (
              <section>
                <div className="panel-heading">
                  <div><h2>任务中心</h2><p>任务在后台排队；中断任务不会自动重提。云端状态不明时，先核对远端再重试。</p></div>
                  <span className="panel-count">{tasks.length}</span>
                </div>
                {tasks.length === 0 ? <div className="empty-panel">还没有任务。<br />抠图和背景生成的进度会显示在这里。</div> : tasks.map(renderTask)}
              </section>
            )}

            {tab === 'export' && (
              <section>
                <div className="panel-heading">
                  <div><h2>多尺寸导出</h2><p>导出包含当前画布全部可见图层，不包含选中框和变换手柄。</p></div>
                </div>
                <div className="cost-notice">
                  <strong>本次规格</strong>
                  等比缩放并留白 · 800×800 / 750×1000 / 1080×1080
                </div>
                <div className="field" style={{ marginTop: 12 }}>
                  <label htmlFor="export-format">文件格式</label>
                  <select id="export-format" value={exportFormat} onChange={(event) => setExportFormat(event.target.value as 'png' | 'jpeg')}>
                    <option value="png">PNG（透明背景保留）</option>
                    <option value="jpeg">JPEG（白色背景，质量 90）</option>
                  </select>
                </div>
                <button className="button button-primary" style={{ width: '100%', marginTop: 12 }} onClick={() => void exportSizes()} disabled={exporting}>
                  {exporting ? '正在合成并导出…' : '导出当前画布'}
                </button>
                {exportError && <div className="status-message is-error" role="alert">{exportError}</div>}
                {exportFiles.length > 0 && (
                  <div style={{ marginTop: 16 }}>
                    <div className="panel-heading"><div><h2>成品文件</h2><p>点击下载，文件保存在浏览器下载目录。</p></div></div>
                    {exportFiles.map((file) => (
                      <div className="export-file" key={file.filename}>
                        <span>{file.width} × {file.height}</span>
                        <a href={file.url} download={file.filename}>{file.filename} · 下载</a>
                      </div>
                    ))}
                    {manifestUrl && <div className="export-file"><span>导出清单</span><a href={manifestUrl} download>CSV · 下载</a></div>}
                    <div className="status-message">项目目录：{exportDir}</div>
                  </div>
                )}
                {exportFiles.length === 0 && <div className="empty-panel">导出会按画布构图生成完整成品，文件不会只包含某一张背景图。</div>}
              </section>
            )}

            {saveMessage && (
              <div className={`status-message ${saveState === 'error' ? 'is-error' : ''}`} role="status">
                {saveMessage}
                {saveState === 'error' && <button className="text-button" onClick={saveNow}>立即重试保存</button>}
              </div>
            )}
          </div>
        </aside>
      </div>
    </main>
  )
}

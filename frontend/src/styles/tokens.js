/*
 * 把 theme.css 里的 token 解析成真实色值。
 *
 * 为什么不直接在 SVG 上写 stroke="var(--cm-plane-control)":
 * SVG 的 presentation attribute 里用 var() 各浏览器支持不一致(内联 style 才稳),
 * 而这个工具要跑在 WebView2 和现场各种版本的浏览器里, 不值得赌。
 *
 * 所以统一在这里读一次, 之后拿到的都是普通的 #RRGGBB 字符串, 写进属性也好、
 * 写进 canvas 也好都没问题。颜色仍然只在 theme.css 里定义一处。
 */

const PLANE_KEYS = ['management', 'control', 'data_front', 'data_back']

let cache = null

function readVar(name, fallback) {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return v || fallback
  } catch (e) {
    return fallback
  }
}

/** 三平面色, 解析成真实色值 */
export function planeColors() {
  if (cache) return cache
  const fallback = {
    management: '#5A6B7F',
    control: '#6D28D9',
    data_front: '#0E7490',
    data_back: '#BE185D',
  }
  cache = {}
  PLANE_KEYS.forEach(k => { cache[k] = readVar(`--cm-plane-${k}`, fallback[k]) })
  return cache
}

/** 线宽本身就是带宽提示: GE 细, 10GE 中, 100GE 粗 */
export const PLANE_WIDTH = {
  management: 1.5,
  control: 2.2,
  data_front: 3.2,
  data_back: 3.2,
}

/** 后段 RDMA 画虚线 —— 多一层区分, 红绿色盲也分得开 */
export const isDashed = (plane) => plane === 'data_back'

export const PLANE_LABEL = {
  management: '管理面 GE',
  control: '控制面 10GE',
  data_front: '前段 DPDK',
  data_back: '后段 RDMA',
}

export function statusColors() {
  return {
    online: readVar('--cm-ok', '#157F3D'),
    degraded: readVar('--cm-warn', '#A9600A'),
    offline: readVar('--cm-crit', '#B4231A'),
    planned: '#CBD3DD',
  }
}

export function uiColors() {
  return {
    surface: readVar('--cm-surface', '#FFFFFF'),
    surface2: readVar('--cm-surface-2', '#EDF1F6'),
    border: readVar('--cm-border', '#D8DFE8'),
    text: readVar('--cm-text', '#17202E'),
    text2: readVar('--cm-text-2', '#5B6675'),
    text3: readVar('--cm-text-3', '#6E7A8A'),
    brand: readVar('--cm-brand', '#2457D6'),
  }
}

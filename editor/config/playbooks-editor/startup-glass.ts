import { buildSdf, TEX } from './startup-logo-distance'
import { FRAG, VERT } from './startup-shaders'
import { endOf, frameAt, LOOKS } from './startup-timeline'

const LOGO_TEXTURE_FRACTION = 0.75
const SPEED = 3

async function prepareLogo(source: string) {
  const image = new Image()
  image.src = source
  await image.decode()
  const sample = document.createElement('canvas')
  sample.width = TEX
  sample.height = TEX
  const ctx = sample.getContext('2d', { willReadFrequently: true })
  if (!ctx) {
    throw new Error('The Coding Opus logo texture is unavailable')
  }
  const fit = TEX / Math.max(image.naturalWidth, image.naturalHeight)
  const width = image.naturalWidth * fit
  const height = image.naturalHeight * fit
  ctx.drawImage(image, (TEX - width) / 2, (TEX - height) / 2, width, height)
  const pixels = ctx.getImageData(0, 0, TEX, TEX).data
  let left = TEX
  let top = TEX
  let right = -1
  let bottom = -1
  for (let y = 0; y < TEX; y++) {
    for (let x = 0; x < TEX; x++) {
      if (pixels[(y * TEX + x) * 4 + 3] > 8) {
        left = Math.min(left, x)
        top = Math.min(top, y)
        right = Math.max(right, x)
        bottom = Math.max(bottom, y)
      }
    }
  }
  if (right < left || bottom < top) {
    throw new Error('The Coding Opus logo is empty')
  }
  const canvas = document.createElement('canvas')
  canvas.width = TEX
  canvas.height = TEX
  const textureContext = canvas.getContext('2d')
  if (!textureContext) {
    throw new Error('The Coding Opus logo could not be rendered')
  }
  const cropWidth = right - left + 1
  const cropHeight = bottom - top + 1
  const scale = (TEX * LOGO_TEXTURE_FRACTION) / Math.max(cropWidth, cropHeight)
  const w = cropWidth * scale
  const h = cropHeight * scale
  textureContext.imageSmoothingQuality = 'high'
  textureContext.drawImage(
    sample,
    left,
    top,
    cropWidth,
    cropHeight,
    (TEX - w) / 2,
    (TEX - h) / 2,
    w,
    h
  )
  return { canvas, sdf: buildSdf(canvas) }
}

function compileShader(gl: WebGL2RenderingContext, type: number, source: string) {
  const shader = gl.createShader(type)
  if (!shader) {
    throw new Error('Could not allocate the startup shader')
  }
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const reason = gl.getShaderInfoLog(shader)
    gl.deleteShader(shader)
    throw new Error(reason || 'Could not compile the startup shader')
  }
  return shader
}

function makeRenderer(gl: WebGL2RenderingContext) {
  const program = gl.createProgram()
  if (!program) {
    throw new Error('Could not allocate the startup renderer')
  }
  const vertex = compileShader(gl, gl.VERTEX_SHADER, VERT)
  const fragment = compileShader(gl, gl.FRAGMENT_SHADER, FRAG)
  gl.attachShader(program, vertex)
  gl.attachShader(program, fragment)
  gl.linkProgram(program)
  gl.deleteShader(vertex)
  gl.deleteShader(fragment)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(program) || 'Could not start the startup renderer')
  }
  gl.useProgram(program)
  const buffer = gl.createBuffer()
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW)
  const position = gl.getAttribLocation(program, 'aPos')
  gl.enableVertexAttribArray(position)
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0)

  const uniforms = new Map<string, WebGLUniformLocation | null>()
  for (let i = 0; i < Number(gl.getProgramParameter(program, gl.ACTIVE_UNIFORMS)); i++) {
    const info = gl.getActiveUniform(program, i)
    if (info) {
      uniforms.set(info.name, gl.getUniformLocation(program, info.name))
    }
  }
  const at = (key: string) => uniforms.get(key) ?? null
  const sdfTexture = gl.createTexture()
  const colorTexture = gl.createTexture()
  gl.uniform1i(at('uSdf'), 0)
  gl.uniform1i(at('uCol'), 1)
  gl.uniform1f(at('uTexSize'), TEX)
  gl.uniform1f(at('uBoxFrac'), LOGO_TEXTURE_FRACTION)

  const filter = (min: number) => {
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, min)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
  }

  return {
    upload(logo: Awaited<ReturnType<typeof prepareLogo>>) {
      gl.activeTexture(gl.TEXTURE0)
      gl.bindTexture(gl.TEXTURE_2D, sdfTexture)
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.R16F, TEX, TEX, 0, gl.RED, gl.FLOAT, logo.sdf)
      filter(gl.LINEAR)
      gl.activeTexture(gl.TEXTURE1)
      gl.bindTexture(gl.TEXTURE_2D, colorTexture)
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true)
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, logo.canvas)
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false)
      gl.generateMipmap(gl.TEXTURE_2D)
      filter(gl.LINEAR_MIPMAP_LINEAR)
    },
    draw(frame: ReturnType<typeof frameAt>, width: number, height: number, tile: number) {
      gl.viewport(0, 0, width, height)
      gl.uniform2f(at('uCenter'), width / 2, height / 2)
      gl.uniform1f(at('uTile'), tile)
      for (const [key, value] of Object.entries(frame)) {
        if (typeof value === 'number') {
          gl.uniform1f(at(key), value)
        }
      }
      gl.uniform3fv(at('uBg'), frame.uBg)
      gl.uniform3fv(at('uPlateCol'), frame.uPlateCol)
      gl.uniform3fv(at('uLogoCol'), frame.uLogoCol)
      gl.uniform2fv(at('uLogoOff'), frame.uLogoOff)
      gl.drawArrays(gl.TRIANGLES, 0, 3)
    },
    dispose() {
      gl.deleteBuffer(buffer)
      gl.deleteTexture(sdfTexture)
      gl.deleteTexture(colorTexture)
      gl.deleteProgram(program)
    }
  }
}

export function playStartupGlass(
  canvas: HTMLCanvasElement,
  logo: string,
  reveal: (animated: boolean) => void
) {
  const gl = canvas.getContext('webgl2', { antialias: false })
  if (!gl) {
    return () => undefined
  }
  const appearance = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  const colors = getComputedStyle(canvas)
  const settings = {
    ...LOOKS[appearance],
    background: colors.getPropertyValue('--environment').trim(),
    logoColor: colors.getPropertyValue('--foreground').trim(),
    tileSize: 232,
    logoScale: 0.6,
    finalScale: 0.8
  }
  let renderer: ReturnType<typeof makeRenderer> | undefined
  let animation = 0
  let disposed = false
  let ready = false
  let start = 0
  let elapsed = 0

  const draw = () => {
    const ratio = Math.min(window.devicePixelRatio || 1, 1.5)
    const width = Math.max(1, Math.round(canvas.clientWidth * ratio))
    const height = Math.max(1, Math.round(canvas.clientHeight * ratio))
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width
      canvas.height = height
    }
    const tile = Math.min(settings.tileSize * ratio, Math.min(width, height) / 1.75)
    renderer?.draw(frameAt(elapsed, settings), width, height, tile)
  }
  const tick = (now: number) => {
    start ||= now
    elapsed = Math.min(endOf(settings), 0.1 + ((now - start) / 1000) * SPEED)
    draw()
    if (!ready) {
      ready = true
      reveal(true)
    }
    if (elapsed < endOf(settings)) {
      animation = requestAnimationFrame(tick)
    }
  }
  const stop = () => {
    cancelAnimationFrame(animation)
    resize.disconnect()
    if (!disposed) {
      reveal(false)
    }
  }
  const resize = new ResizeObserver(() => {
    if (ready && !gl.isContextLost()) {
      draw()
    }
  })
  canvas.addEventListener('webglcontextlost', stop)
  void prepareLogo(logo)
    .then((texture) => {
      if (!disposed && !gl.isContextLost()) {
        renderer = makeRenderer(gl)
        renderer.upload(texture)
        resize.observe(canvas)
        animation = requestAnimationFrame(tick)
      }
    })
    .catch(stop)
  return () => {
    disposed = true
    cancelAnimationFrame(animation)
    resize.disconnect()
    canvas.removeEventListener('webglcontextlost', stop)
    renderer?.dispose()
  }
}

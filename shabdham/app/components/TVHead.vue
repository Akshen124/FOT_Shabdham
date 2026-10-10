<template>
  <div
    ref="containerRef"
    class="tvhead"
    :class="{ 'tvhead--loaded': isLoaded }"
    aria-hidden="true"
  />
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'

// ── State ──
// ── State ──
const containerRef = ref<HTMLDivElement | null>(null)
const isLoaded = ref(false)
const isStarted = ref(false)

defineExpose({ isLoaded, isStarted, triggerStart, triggerBlink })

const emit = defineEmits<{
  (e: 'loaded'): void
  (e: 'error', err: Error): void
  (e: 'started'): void
}>()

// ── Three.js variables ──
let renderer: any = null
let scene: any = null
let camera: any = null
let characterGroup: any = null
let staticBody: any = null
let neckPivot: any = null
let tvHeadPivot: any = null
let screenMesh: any = null
let screenCanvas: HTMLCanvasElement | null = null
let screenCtx: CanvasRenderingContext2D | null = null
let screenTexture: any = null
let rafId: number = 0
let clock: any = null
let THREE: any = null

// Pointer tracking
let mouseX = 0
let mouseY = 0
let targetRotX = 0
let targetRotY = 0
let currentRotX = 0
let currentRotY = 0

// Eye tracking (pupil reacts immediately to cursor)
let eyeTargetX = 0
let eyeTargetY = 0
let eyeCurrentX = 0
let eyeCurrentY = 0

// Model constants
const MODEL_CENTER_Y = 0.95
const SPLIT_Y = 0.815

// Layout & Entrance Transition Positions (Center -> Right on Click)
let basePosZ = 0
let finalPosX = 0.58
let finalPosY = -0.36
let finalScale = 1.06
let startPosX = 0.0
let startPosY = -0.32
let startScale = 0.94

let targetPosX = 0.0
let targetPosY = -0.32
let targetScale = 0.94
let currentPosX = 0.0
let currentPosY = -0.32
let currentScale = 0.94

// Reduced motion / touch
let prefersReducedMotion = false
let isTouchDevice = false

// ── Screen animation state ──
type ScreenMode = 'eye' | 'start' | 'boot' | 'terminal'
let currentScreenMode: ScreenMode = 'eye'
let screenModeTimer = 0
let startPulseTimer = 0

// Eye animation state
let blinkState: 'open' | 'closing' | 'closed' | 'opening' = 'open'
let blinkTimer = 0
let nextBlinkTime = 3.5
let blinkProgress = 0
let eyeMicroX = 0
let eyeMicroY = 0
let eyeMicroTimer = 0

// Boot sequence state
let bootTimer = 0
let bootCursorVisible = true
let bootCursorTimer = 0

// Terminal state
let termCurrentLine = 0
let termCharIndex = 0
let termTimer = 0
let termCursorVisible = true
let termCursorTimer = 0

// Glitch state
let glitchTimer = 0
let nextGlitchTime = 7.5
let glitchActive = false
let glitchDuration = 0

// CRT scanline offset
let scanlineOffset = 0

// Terminal content
const TERM_LINES = [
  'GENLAB OS v3.7.1 [RELEASE]',
  '----------------------------',
  '> initializing neural core...',
  '> loading assistant personality...',
  '> optical sensors: ONLINE',
  '> synaptic sync: 99.4%',
  '',
  'genlab@assistant:~$ status',
  '[SYS] STATUS: ONLINE',
  '[SYS] READY FOR INTERACTION.',
]

onMounted(async () => {
  if (!containerRef.value) return

  prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0

  THREE = await import('three')
  const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
  const { RoomEnvironment } = await import('three/examples/jsm/environments/RoomEnvironment.js')

  const container = containerRef.value
  const width = container.clientWidth
  const height = container.clientHeight

  // ── Renderer ──
  renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: 'high-performance',
  })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.15
  renderer.shadowMap.enabled = false
  renderer.setSize(width, height)
  container.appendChild(renderer.domElement)

  // ── Scene & Studio Reflection Environment ──
  scene = new THREE.Scene()
  const pmremGenerator = new THREE.PMREMGenerator(renderer)
  pmremGenerator.compileEquirectangularShader()
  const roomEnv = new RoomEnvironment()
  scene.environment = pmremGenerator.fromScene(roomEnv, 0.04).texture
  scene.environmentIntensity = 1.0
  pmremGenerator.dispose()

  // ── Camera: Close-up Bust Framing (FOV 35°, Z = 3.15, perfectly centered) ──
  camera = new THREE.PerspectiveCamera(35, width / height, 0.1, 100)
  camera.position.set(0, 0.05, 3.15)
  camera.lookAt(0, 0.02, 0)

  // ── Clock ──
  clock = new THREE.Clock()

  // ── Lighting: Soft Cinematic Studio ──
  setupLighting()

  // ── CRT Screen Canvas Texture ──
  setupScreenCanvas()

  // ── Character Hierarchy ──
  // characterGroup
  //   ├── staticBody   (complete continuous sweater torso + collar cup)
  //   └── tvHeadPivot  (mounted inside the collar socket at Y = 0.815, pivots with cursor)
  //         ├── tvMesh (grayish metallic silver TV casing, controls & cables)
  //         └── screenMesh (living AI CRT display)
  characterGroup = new THREE.Group()
  staticBody = new THREE.Group()
  tvHeadPivot = new THREE.Group()

  characterGroup.add(staticBody)
  characterGroup.add(tvHeadPivot)

  const SPLIT_Y = 0.815
  staticBody.position.set(0, -MODEL_CENTER_Y, 0)
  tvHeadPivot.position.set(0, SPLIT_Y - MODEL_CENTER_Y, 0)

  // ── Load Original Character Model: base.glb with seamless overlapping joint ──
  const loader = new GLTFLoader()
  try {
    const gltf = await loader.loadAsync('/models/base.glb')

    let originalMesh: any = null
    gltf.scene.traverse((child: any) => {
      if (child.isMesh) originalMesh = child
    })

    if (!originalMesh) {
      throw new Error('No mesh found in base.glb')
    }

    const geom = originalMesh.geometry
    const pos = geom.attributes.position
    const normal = geom.attributes.normal
    const uv = geom.attributes.uv
    const index = geom.index

    // 4cm overlap zone ensures airtight ball-and-socket joint with ZERO gaps or holes!
    const OVERLAP = 0.040
    const bodyIndices: number[] = []
    const tvIndices: number[] = []
    const numFaces = index ? index.count / 3 : pos.count / 3

    for (let f = 0; f < numFaces; f++) {
      const i0 = index ? index.getX(f * 3 + 0) : f * 3 + 0
      const i1 = index ? index.getX(f * 3 + 1) : f * 3 + 1
      const i2 = index ? index.getX(f * 3 + 2) : f * 3 + 2

      const y0 = pos.getY(i0)
      const y1 = pos.getY(i1)
      const y2 = pos.getY(i2)
      const avgY = (y0 + y1 + y2) / 3
      const maxY = Math.max(y0, y1, y2)
      const minY = Math.min(y0, y1, y2)

      if (minY <= SPLIT_Y + OVERLAP && avgY <= SPLIT_Y + OVERLAP) {
        bodyIndices.push(i0, i1, i2)
      }
      if (maxY >= SPLIT_Y - OVERLAP && avgY >= SPLIT_Y - OVERLAP) {
        tvIndices.push(i0, i1, i2)
      }
    }

    function buildSubMesh(indices: number[], name: string) {
      const newGeom = new THREE.BufferGeometry()
      const usedVerts = new Map<number, number>()
      const newPositions: number[] = []
      const newNormals: number[] = []
      const newUvs: number[] = []
      const newIdx: number[] = []

      for (let i = 0; i < indices.length; i++) {
        const origIdx = indices[i]
        if (!usedVerts.has(origIdx)) {
          const newVIdx = newPositions.length / 3
          usedVerts.set(origIdx, newVIdx)
          newPositions.push(pos.getX(origIdx), pos.getY(origIdx), pos.getZ(origIdx))
          if (normal) newNormals.push(normal.getX(origIdx), normal.getY(origIdx), normal.getZ(origIdx))
          if (uv) newUvs.push(uv.getX(origIdx), uv.getY(origIdx))
        }
        newIdx.push(usedVerts.get(origIdx)!)
      }

      newGeom.setAttribute('position', new THREE.Float32BufferAttribute(newPositions, 3))
      if (normal) newGeom.setAttribute('normal', new THREE.Float32BufferAttribute(newNormals, 3))
      if (uv) newGeom.setAttribute('uv', new THREE.Float32BufferAttribute(newUvs, 2))
      newGeom.setIndex(newIdx)
      newGeom.computeVertexNormals()

      const mesh = new THREE.Mesh(newGeom)
      mesh.name = name
      return mesh
    }

    // 1. Sweater Torso & Collar (Full continuous sweater in #817073 knit texture)
    const bodyMesh = buildSubMesh(bodyIndices, 'Sweater')
    const { normalTexture, diffuseTexture } = createSweaterTextures(THREE)
    bodyMesh.material = new THREE.MeshStandardMaterial({
      color: 0x817073,
      map: diffuseTexture,
      normalMap: normalTexture,
      normalScale: new THREE.Vector2(1.6, 1.6),
      roughness: 0.95,
      metalness: 0.0,
      envMapIntensity: 0.30,
    })
    bodyMesh.position.set(0, 0, 0)
    staticBody.add(bodyMesh)

    // 2. TV Head Assembly (Pivots seamlessly inside the collar cup in grayish metallic silver)
    const tvMesh = buildSubMesh(tvIndices, 'TV_Head')
    tvMesh.material = new THREE.MeshStandardMaterial({
      color: 0x8e97a4, // Sleek grayish metallic silver
      roughness: 0.28, // Brushed metallic finish
      metalness: 0.82, // Metallic depth
      envMapIntensity: 1.15, // Studio reflections
    })
    tvMesh.position.set(0, -SPLIT_Y, 0)
    tvHeadPivot.add(tvMesh)

    // 6. Seamless Curved CRT Screen Glass (Soft satin anti-glare CRT monitor finish)
    if (screenTexture) {
      // Dark inner TV tube cavity backing
      const cavityGeo = new THREE.PlaneGeometry(0.96, 0.86)
      const cavityMat = new THREE.MeshBasicMaterial({ color: 0x050608 })
      const cavityMesh = new THREE.Mesh(cavityGeo, cavityMat)
      cavityMesh.position.set(0.100, 1.401 - SPLIT_Y, 0.580)
      tvHeadPivot.add(cavityMesh)

      // Front 3D spherical CRT phosphor tube glass
      const screenWidth = 0.94
      const screenHeight = 0.84
      const screenGeo = new THREE.PlaneGeometry(screenWidth, screenHeight, 48, 48)

      const pos = screenGeo.attributes.position
      const halfW = screenWidth / 2
      const halfH = screenHeight / 2
      const maxCornerSq = halfW * halfW + halfH * halfH
      const sphereR = 1.80
      const cornerZ = Math.sqrt(sphereR * sphereR - maxCornerSq)
      const domeScale = 0.65

      for (let i = 0; i < pos.count; i++) {
        const px = pos.getX(i)
        const py = pos.getY(i)
        const distSq = px * px + py * py
        const z = (Math.sqrt(Math.max(0.001, sphereR * sphereR - distSq)) - cornerZ) * domeScale
        pos.setZ(i, Math.max(0, z))
      }
      screenGeo.computeVertexNormals()

      const screenMat = new THREE.MeshStandardMaterial({
        map: screenTexture,
        roughness: 0.42,
        metalness: 0.0,
        envMapIntensity: 0.25,
        toneMapped: false,
      })
      screenMesh = new THREE.Mesh(screenGeo, screenMat)
      screenMesh.renderOrder = 10
      screenMesh.position.set(0.100, 1.401 - SPLIT_Y, 0.590)
      tvHeadPivot.add(screenMesh)
    }

    // Initial responsive scale and positioning
    updateResponsiveDimensions(width, height)

    scene.add(characterGroup)

    // Start directly with living Eye screen mode
    currentScreenMode = 'eye'
    screenModeTimer = 0

    isLoaded.value = true
    emit('loaded')
  } catch (error: any) {
    console.error('[TVHead] Failed to load character model:', error)
    emit('error', error instanceof Error ? error : new Error(String(error)))
  }

  // ── Events ──
  if (!isTouchDevice) {
    window.addEventListener('pointermove', onPointerMove, { passive: true })
  }
  window.addEventListener('resize', onResize, { passive: true })
  if (containerRef.value) {
    containerRef.value.addEventListener('click', onCanvasClick)
  }

  // ── Render loop ──
  animate()
})

function setupLighting() {
  // Key Light: Upper-left soft studio light illuminating shoulders and TV
  const keyLight = new THREE.DirectionalLight(0xffffff, 2.5)
  keyLight.position.set(-2.5, 3.5, 3.8)
  scene.add(keyLight)

  // Fill Light: Soft right-side fill
  const fillLight = new THREE.DirectionalLight(0xedf2f7, 1.2)
  fillLight.position.set(2.8, 1.0, 3.0)
  scene.add(fillLight)

  // Top Light: Overhead soft illumination
  const topLight = new THREE.DirectionalLight(0xffffff, 0.9)
  topLight.position.set(0, 4.0, 1.5)
  scene.add(topLight)

  // Rim Light: Rear-right edge definition for cables, shoulders & casing
  const rimLight = new THREE.DirectionalLight(0xffffff, 1.3)
  rimLight.position.set(2.4, 1.8, -2.8)
  scene.add(rimLight)

  // Rear-left accent
  const backAccent = new THREE.DirectionalLight(0xd5dbed, 0.75)
  backAccent.position.set(-2.4, 1.5, -2.5)
  scene.add(backAccent)

  // Ambient & Hemisphere for soft shadows
  const ambient = new THREE.AmbientLight(0xe8e5e0, 0.7)
  scene.add(ambient)

  const hemi = new THREE.HemisphereLight(0xf5f3ee, 0x5a5650, 0.45)
  scene.add(hemi)
}

function setupScreenCanvas() {
  screenCanvas = document.createElement('canvas')
  screenCanvas.width = 512
  screenCanvas.height = 512
  screenCtx = screenCanvas.getContext('2d')!

  screenTexture = new THREE.CanvasTexture(screenCanvas)
  screenTexture.minFilter = THREE.LinearFilter
  screenTexture.magFilter = THREE.LinearFilter
  screenTexture.colorSpace = THREE.SRGBColorSpace
}

function createSweaterTextures(THREE: any) {
  const size = 512
  const wales = 12 // horizontal knit stitch columns
  const courses = 16 // vertical knit stitch rows

  // 1. Generate height and ambient occlusion data
  const heightMap = new Float32Array(size * size)
  const aoMap = new Float32Array(size * size)

  for (let y = 0; y < size; y++) {
    const vNorm = y / size
    const v = vNorm * courses
    const row = Math.floor(v)
    const vFrac = v - row // [0, 1] within stitch row
    // Stagger every other row by 0.5 (interlocking loop structure)
    const uShift = (row % 2) * 0.5

    for (let x = 0; x < size; x++) {
      const uNorm = x / size
      const u = (uNorm * wales + uShift) % 1
      const sx = u * 2 - 1 // [-1, 1] across stitch
      const sy = vFrac * 2 - 1 // [-1, 1] vertically

      // Interlocking knit loop V-shape
      const vTaper = 0.45 * (1 - sy * 0.25)
      const legDist = Math.abs(Math.abs(sx) - vTaper)
      const legHeight = Math.exp(-(legDist * legDist) / 0.05) * (1 - 0.25 * (sy * sy))

      // Top loop cross-strand
      const topLoop = Math.exp(-((sy - 0.75) * (sy - 0.75)) / 0.04) * 0.55 * Math.exp(-(sx * sx) / 0.3)
      const stitchHeight = Math.max(legHeight, topLoop)

      // Fine yarn twist structure (heather/ply fibers)
      const yarnTwist = Math.sin(sx * 28 + sy * 36) * 0.04 + Math.sin(sx * 56 - sy * 20) * 0.02

      const h = Math.max(0, Math.min(1, stitchHeight + yarnTwist))
      heightMap[y * size + x] = h

      // Crevice shadows / AO
      aoMap[y * size + x] = Math.pow(h, 0.45)
    }
  }

  // 2. Normal Map Canvas
  const normalCanvas = document.createElement('canvas')
  normalCanvas.width = size
  normalCanvas.height = size
  const normalCtx = normalCanvas.getContext('2d')!
  const normalImg = normalCtx.createImageData(size, size)
  const normalData = normalImg.data
  const bumpStrength = 3.2

  for (let y = 0; y < size; y++) {
    const yPrev = (y - 1 + size) % size
    const yNext = (y + 1) % size
    for (let x = 0; x < size; x++) {
      const xPrev = (x - 1 + size) % size
      const xNext = (x + 1) % size

      const dx = (heightMap[y * size + xNext] - heightMap[y * size + xPrev]) * bumpStrength
      const dy = (heightMap[yNext * size + x] - heightMap[yPrev * size + x]) * bumpStrength
      const dz = 1.0

      const len = Math.sqrt(dx * dx + dy * dy + dz * dz)
      const nx = -dx / len
      const ny = -dy / len
      const nz = dz / len

      const idx = (y * size + x) * 4
      normalData[idx + 0] = Math.round(((nx + 1) * 0.5) * 255)
      normalData[idx + 1] = Math.round(((ny + 1) * 0.5) * 255)
      normalData[idx + 2] = Math.round(((nz + 1) * 0.5) * 255)
      normalData[idx + 3] = 255
    }
  }
  normalCtx.putImageData(normalImg, 0, 0)

  // 3. Diffuse Fabric Detail Canvas (adds tactile yarn fiber shading & AO crevices to the base color)
  const diffuseCanvas = document.createElement('canvas')
  diffuseCanvas.width = size
  diffuseCanvas.height = size
  const diffuseCtx = diffuseCanvas.getContext('2d')!
  const diffuseImg = diffuseCtx.createImageData(size, size)
  const diffuseData = diffuseImg.data

  for (let i = 0; i < size * size; i++) {
    const ao = aoMap[i]
    const noise = (Math.random() - 0.5) * 14
    const val = Math.max(0, Math.min(255, Math.round(185 + ao * 70 + noise)))
    const idx = i * 4
    diffuseData[idx + 0] = val
    diffuseData[idx + 1] = val
    diffuseData[idx + 2] = val
    diffuseData[idx + 3] = 255
  }
  diffuseCtx.putImageData(diffuseImg, 0, 0)

  // 4. Create Three.js Textures
  const normalTexture = new THREE.CanvasTexture(normalCanvas)
  normalTexture.wrapS = THREE.RepeatWrapping
  normalTexture.wrapT = THREE.RepeatWrapping
  normalTexture.repeat.set(16, 16)

  const diffuseTexture = new THREE.CanvasTexture(diffuseCanvas)
  diffuseTexture.wrapS = THREE.RepeatWrapping
  diffuseTexture.wrapT = THREE.RepeatWrapping
  diffuseTexture.repeat.set(16, 16)

  return { normalTexture, diffuseTexture }
}

function onPointerMove(e: PointerEvent) {
  mouseX = (e.clientX / window.innerWidth) * 2 - 1
  mouseY = (e.clientY / window.innerHeight) * 2 - 1
}

function updateResponsiveDimensions(w: number, h: number) {
  if (!camera || !renderer) return
  camera.aspect = w / h
  camera.updateProjectionMatrix()
  renderer.setSize(w, h)

  if (w < 640) {
    // Mobile: centered layout lowered comfortably
    finalScale = 0.88
    finalPosX = 0
    finalPosY = -0.28
    startScale = 0.74
    startPosX = 0
    startPosY = -0.26
    camera.position.set(0, 0.05, 3.8)
    camera.lookAt(0, -0.05, 0)
  } else if (w < 900) {
    // Tablet: modest size on right
    finalScale = 0.96
    finalPosX = 0.40
    finalPosY = -0.34
    startScale = 0.82
    startPosX = 0
    startPosY = -0.30
    camera.position.set(0.06, 0.02, 3.6)
    camera.lookAt(0.18, -0.05, 0)
  } else if (w < 1180) {
    // Laptop: medium size on right
    finalScale = 1.02
    finalPosX = 0.50
    finalPosY = -0.36
    startScale = 0.88
    startPosX = 0
    startPosY = -0.32
    camera.position.set(0.10, 0.02, 3.5)
    camera.lookAt(0.25, -0.05, 0)
  } else {
    // Large desktop: right-aligned hero assistant lowered
    finalScale = 1.08
    finalPosX = 0.58
    finalPosY = -0.36
    startScale = 0.94
    startPosX = 0.0
    startPosY = -0.32
    camera.position.set(0.12, 0.02, 3.4)
    camera.lookAt(0.30, -0.05, 0)
  }

  if (!isStarted.value) {
    targetPosX = startPosX
    targetPosY = startPosY
    targetScale = startScale
  } else {
    targetPosX = finalPosX
    targetPosY = finalPosY
    targetScale = finalScale
  }
}

function onResize() {
  if (!containerRef.value) return
  updateResponsiveDimensions(containerRef.value.clientWidth, containerRef.value.clientHeight)
}

function triggerBlink() {
  blinkState = 'closing'
  blinkTimer = 0
  blinkProgress = 0
}

function triggerStart() {
  triggerBlink()
  if (!isStarted.value) {
    isStarted.value = true
    emit('started')
    if (containerRef.value) {
      updateResponsiveDimensions(containerRef.value.clientWidth, containerRef.value.clientHeight)
    }
  }
}

function onCanvasClick() {
  triggerBlink()
  if (!isStarted.value) {
    triggerStart()
  }
}

// ══════════════════════════════════════════════════
// CRT SCREEN RENDERING & ANIMATIONS
// ══════════════════════════════════════════════════

function updateScreen(elapsed: number, dt: number) {
  if (!screenCtx || !screenCanvas || !screenTexture) return

  const ctx = screenCtx
  const w = screenCanvas.width
  const h = screenCanvas.height

  // ── Glitch Trigger ──
  if (!glitchActive) {
    glitchTimer += dt
    if (glitchTimer > nextGlitchTime) {
      glitchActive = true
      glitchDuration = 0.08 + Math.random() * 0.14
      glitchTimer = 0
      nextGlitchTime = 8 + Math.random() * 12
    }
  }

  // Deep dark CRT phosphor background across the entire tube surface
  ctx.fillStyle = '#060709'
  ctx.fillRect(0, 0, w, h)

  // ── Draw Living Glowing Eyes ──
  drawEyeScreen(ctx, w, h, elapsed, dt)

  // ── Glitch Distortion Overlay ──
  if (glitchActive) {
    drawGlitch(ctx, w, h)
    glitchDuration -= dt
    if (glitchDuration <= 0) {
      glitchActive = false
    }
  }

  // ── CRT Phosphor Scanlines & Bezel Shading ──
  drawCRTEffects(ctx, w, h, elapsed)

  screenTexture.needsUpdate = true
}

function switchMode(mode: ScreenMode) {
  currentScreenMode = mode
  screenModeTimer = 0

  if (mode === 'terminal') {
    termCurrentLine = 0
    termCharIndex = 0
    termTimer = 0
  }
  if (mode === 'boot') {
    bootTimer = 0
  }
}

function drawStartScreen(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  elapsed: number,
  dt: number
) {
  // ── Top Header Bar ──
  ctx.save()
  ctx.font = 'bold 12px "Courier New", monospace'
  ctx.textAlign = 'left'
  ctx.fillStyle = '#00ff88'
  ctx.shadowColor = '#00ff88'
  ctx.shadowBlur = 6
  ctx.fillText('GENLAB OS // STANDBY', 42, 54)

  ctx.font = '11px "Courier New", monospace'
  ctx.fillStyle = 'rgba(0, 255, 140, 0.45)'
  ctx.shadowBlur = 2
  ctx.fillText('> SYSTEM READY: 64MB OK', 42, 74)
  ctx.fillText('> OPTICAL SENSORS: ONLINE', 42, 92)
  ctx.restore()

  // ── Center: Bold Glowing [ CLICK TO START ] ──
  ctx.save()
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'

  const pulse = Math.sin(elapsed * 3.6) * 0.25 + 0.75
  const glow = Math.sin(elapsed * 3.6) * 8 + 14

  // Outer prompt container box
  const boxW = 320
  const boxH = 54
  const boxX = (w - boxW) / 2
  const boxY = h / 2 - 16

  ctx.strokeStyle = `rgba(0, 255, 170, ${(pulse * 0.7).toFixed(2)})`
  ctx.lineWidth = 1.5
  ctx.shadowColor = '#00ffaa'
  ctx.shadowBlur = glow * 0.6
  ctx.strokeRect(boxX, boxY, boxW, boxH)

  // Inner bold pulsing text
  ctx.font = 'bold 24px "Courier New", monospace'
  ctx.fillStyle = `rgba(230, 255, 245, ${pulse.toFixed(2)})`
  ctx.shadowColor = '#00ffcc'
  ctx.shadowBlur = glow
  ctx.fillText('▶ CLICK TO START', w / 2, h / 2 + 11)

  // Sub-prompt below box
  ctx.font = '11px "Courier New", monospace'
  ctx.fillStyle = 'rgba(148, 163, 184, 0.6)'
  ctx.shadowBlur = 0
  ctx.fillText('• TOUCH OR CLICK TO INITIALIZE •', w / 2, h / 2 + 62)

  ctx.restore()
}

function drawBootScreen(ctx: CanvasRenderingContext2D, w: number, h: number, dt: number) {
  bootTimer += dt
  bootCursorTimer += dt

  if (bootCursorTimer > 0.4) {
    bootCursorVisible = !bootCursorVisible
    bootCursorTimer = 0
  }

  ctx.textAlign = 'center'

  // Header
  ctx.font = 'bold 30px "Courier New", monospace'
  ctx.fillStyle = '#00ff88'
  ctx.shadowColor = '#00ff88'
  ctx.shadowBlur = 12
  ctx.fillText('GENLAB OS', w / 2, h / 2 - 45)

  ctx.font = '14px monospace'
  ctx.fillStyle = '#00bb66'
  ctx.shadowBlur = 4
  ctx.fillText('v3.7.1 NEURAL CORE', w / 2, h / 2 - 18)

  // Initializing progress bar
  if (bootTimer < 3.0) {
    ctx.font = '13px monospace'
    ctx.fillStyle = '#00ffaa'
    ctx.shadowBlur = 6
    ctx.fillText('INITIALIZING SYSTEM...', w / 2, h / 2 + 25)

    const progress = Math.min(bootTimer / 2.8, 1)
    const barW = 240
    const barH = 14
    const barX = (w - barW) / 2
    const barY = h / 2 + 45

    ctx.strokeStyle = '#00aa55'
    ctx.lineWidth = 1.5
    ctx.strokeRect(barX, barY, barW, barH)

    ctx.fillStyle = '#00ff88'
    ctx.fillRect(barX + 3, barY + 3, (barW - 6) * progress, barH - 6)
  } else {
    ctx.font = '13px monospace'
    ctx.fillStyle = '#00ffaa'
    ctx.shadowBlur = 6
    ctx.fillText('PERSONALITY LOADED', w / 2, h / 2 + 25)

    ctx.font = 'bold 20px monospace'
    ctx.fillStyle = '#ffffff'
    ctx.shadowColor = '#00ff88'
    ctx.shadowBlur = 10
    ctx.fillText('READY.', w / 2, h / 2 + 58)

    if (bootCursorVisible) {
      ctx.fillStyle = '#00ff88'
      ctx.fillRect(w / 2 + 45, h / 2 + 46, 12, 16)
    }
  }

  ctx.shadowBlur = 0
}

function drawEyeScreen(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  elapsed: number,
  dt: number
) {
  const cx = w / 2
  const cy = h / 2

  // ── Saccades & Micro-movements ──
  eyeMicroTimer += dt
  if (eyeMicroTimer > 0.9 + Math.random() * 1.6) {
    eyeMicroX = (Math.random() - 0.5) * 4
    eyeMicroY = (Math.random() - 0.5) * 3
    eyeMicroTimer = 0
  }

  // ── Rapid Dual-Pupil Tracking ──
  eyeTargetX = mouseX * 20 + eyeMicroX
  eyeTargetY = mouseY * 14 + eyeMicroY
  eyeCurrentX += (eyeTargetX - eyeCurrentX) * 0.22
  eyeCurrentY += (eyeTargetY - eyeCurrentY) * 0.22

  // ── Smooth Robot Eye Blinking (Squash & Stretch) ──
  blinkTimer += dt
  switch (blinkState) {
    case 'open':
      if (blinkTimer > nextBlinkTime) {
        blinkState = 'closing'
        blinkTimer = 0
        blinkProgress = 0
      }
      break
    case 'closing':
      blinkProgress = Math.min(blinkTimer / 0.11, 1)
      if (blinkProgress >= 1) {
        blinkState = 'closed'
        blinkTimer = 0
      }
      break
    case 'closed':
      blinkProgress = 1
      if (blinkTimer > 0.06) {
        blinkState = 'opening'
        blinkTimer = 0
      }
      break
    case 'opening':
      blinkProgress = 1 - Math.min(blinkTimer / 0.13, 1)
      if (blinkProgress <= 0) {
        blinkState = 'open'
        blinkTimer = 0
        blinkProgress = 0
        nextBlinkTime = 2.5 + Math.random() * 3.0
      }
      break
  }

  // ── Double Rounded Circular Eyes Geometry (Adapted for 1.125:1 Screen) ──
  const eyeSpacing = 106
  const eyeRadius = 66

  const leftEyeX = cx - eyeSpacing
  const rightEyeX = cx + eyeSpacing
  const eyesY = cy

  // Draw Left Circular Eye
  drawSingleEye(
    ctx,
    leftEyeX,
    eyesY,
    eyeRadius,
    eyeCurrentX,
    eyeCurrentY,
    blinkProgress,
    elapsed,
    false
  )

  // Draw Right Circular Eye
  drawSingleEye(
    ctx,
    rightEyeX,
    eyesY,
    eyeRadius,
    eyeCurrentX,
    eyeCurrentY,
    blinkProgress,
    elapsed,
    true
  )
}

function drawSingleEye(
  ctx: CanvasRenderingContext2D,
  eyeX: number,
  eyeY: number,
  eyeRadius: number,
  pupilX: number,
  pupilY: number,
  blinkProgress: number,
  elapsed: number,
  isRight: boolean
) {
  // Smooth vertical squash when blinking
  const scaleY = Math.max(0.04, 1 - blinkProgress * 0.96)
  const scaleX = (1 + blinkProgress * 0.08) * (1 / 1.125) // Aspect ratio compensation for 3D world space

  // Pointer tracking micro-shift
  const cx = eyeX + pupilX * 0.35
  const cy = eyeY + pupilY * 0.35

  // 1. Ambient Outer Halo Bloom (Luminous electric cyan diffuse emission)
  ctx.save()
  ctx.translate(cx, cy)
  ctx.scale(1 / 1.125, 1)
  ctx.translate(-cx, -cy)

  const outerBloom = ctx.createRadialGradient(
    cx,
    cy,
    eyeRadius * 0.35,
    cx,
    cy,
    eyeRadius * 2.4
  )
  outerBloom.addColorStop(0, 'rgba(186, 230, 253, 0.48)') // Bright sky blue
  outerBloom.addColorStop(0.30, 'rgba(56, 189, 248, 0.26)') // Electric cyan
  outerBloom.addColorStop(0.65, 'rgba(14, 116, 144, 0.08)')
  outerBloom.addColorStop(1, 'rgba(0, 0, 0, 0)')
  ctx.fillStyle = outerBloom
  ctx.beginPath()
  ctx.arc(cx, cy, eyeRadius * 2.4, 0, Math.PI * 2)
  ctx.fill()
  ctx.restore()

  // 2. Transformed Glowing Light Orb with Blinking Squash
  ctx.save()
  ctx.translate(cx, cy)
  ctx.scale(scaleX, scaleY)
  ctx.translate(-cx, -cy)

  // Warm Amber-Orange Chromatic Fringe on the Outer Rim
  const chromaticEdge = ctx.createRadialGradient(
    cx,
    cy,
    eyeRadius * 0.72,
    cx,
    cy,
    eyeRadius * 1.10
  )
  chromaticEdge.addColorStop(0, 'rgba(255, 255, 255, 0)')
  chromaticEdge.addColorStop(0.48, 'rgba(245, 158, 11, 0.42)') // Warm golden-amber
  chromaticEdge.addColorStop(0.82, 'rgba(234, 88, 12, 0.28)') // Soft sunset orange
  chromaticEdge.addColorStop(1, 'rgba(0, 0, 0, 0)')
  ctx.fillStyle = chromaticEdge
  ctx.beginPath()
  ctx.arc(cx, cy, eyeRadius * 1.10, 0, Math.PI * 2)
  ctx.fill()

  // Cyan Electric Rim
  const cyanEdge = ctx.createRadialGradient(
    cx,
    cy,
    eyeRadius * 0.65,
    cx,
    cy,
    eyeRadius * 1.02
  )
  cyanEdge.addColorStop(0, 'rgba(255, 255, 255, 0)')
  cyanEdge.addColorStop(0.55, 'rgba(56, 189, 248, 0.60)') // Electric cyan rim
  cyanEdge.addColorStop(0.88, 'rgba(2, 132, 199, 0.32)')
  cyanEdge.addColorStop(1, 'rgba(0, 0, 0, 0)')
  ctx.fillStyle = cyanEdge
  ctx.beginPath()
  ctx.arc(cx, cy, eyeRadius * 1.02, 0, Math.PI * 2)
  ctx.fill()

  // Core Luminous White-Hot Light Orb
  const coreGrad = ctx.createRadialGradient(
    cx,
    cy,
    0,
    cx,
    cy,
    eyeRadius * 0.94
  )
  coreGrad.addColorStop(0, '#ffffff')
  coreGrad.addColorStop(0.60, '#ffffff')
  coreGrad.addColorStop(0.80, '#fefbf3') // Warm creamy white
  coreGrad.addColorStop(0.92, '#bae6fd') // Soft cyan transition
  coreGrad.addColorStop(1, 'rgba(125, 211, 252, 0.45)')

  ctx.shadowColor = '#bae6fd'
  ctx.shadowBlur = 28
  ctx.fillStyle = coreGrad
  ctx.beginPath()
  ctx.arc(cx, cy, eyeRadius * 0.94, 0, Math.PI * 2)
  ctx.fill()
  ctx.shadowBlur = 0

  // High-intensity white center hot spot
  const hotSpot = ctx.createRadialGradient(
    cx,
    cy,
    0,
    cx,
    cy,
    eyeRadius * 0.50
  )
  hotSpot.addColorStop(0, '#ffffff')
  hotSpot.addColorStop(0.75, 'rgba(255, 255, 255, 0.98)')
  hotSpot.addColorStop(1, 'rgba(255, 255, 255, 0)')
  ctx.fillStyle = hotSpot
  ctx.beginPath()
  ctx.arc(cx, cy, eyeRadius * 0.50, 0, Math.PI * 2)
  ctx.fill()

  ctx.restore()
}

function drawTerminalScreen(ctx: CanvasRenderingContext2D, w: number, h: number, dt: number) {
  termTimer += dt
  termCursorTimer += dt

  if (termCursorTimer > 0.4) {
    termCursorVisible = !termCursorVisible
    termCursorTimer = 0
  }

  // Typewriter line streaming
  if (termCurrentLine < TERM_LINES.length) {
    if (termTimer > 0.035) {
      termCharIndex++
      termTimer = 0
      if (termCharIndex >= TERM_LINES[termCurrentLine].length) {
        termCurrentLine++
        termCharIndex = 0
        termTimer = -0.18
      }
    }
  }

  ctx.font = '13px "Courier New", monospace'
  ctx.textAlign = 'left'

  const lineH = 22
  const startX = 36
  const startY = 48

  for (let i = 0; i <= Math.min(termCurrentLine, TERM_LINES.length - 1); i++) {
    const line = TERM_LINES[i]
    let displayText = line

    if (i === termCurrentLine && termCurrentLine < TERM_LINES.length) {
      displayText = line.substring(0, termCharIndex)
    }

    if (line.startsWith('>')) {
      ctx.fillStyle = '#00ff88'
      ctx.shadowColor = '#00ff88'
      ctx.shadowBlur = 4
    } else if (line.startsWith('genlab@')) {
      ctx.fillStyle = '#38bdf8'
      ctx.shadowColor = '#38bdf8'
      ctx.shadowBlur = 4
    } else if (line.includes('ONLINE') || line.includes('READY')) {
      ctx.fillStyle = '#4ade80'
      ctx.shadowColor = '#4ade80'
      ctx.shadowBlur = 6
    } else if (line.startsWith('GENLAB')) {
      ctx.fillStyle = '#ffffff'
      ctx.shadowColor = '#ffffff'
      ctx.shadowBlur = 8
    } else {
      ctx.fillStyle = '#94a3b8'
      ctx.shadowBlur = 0
    }

    ctx.fillText(displayText, startX, startY + i * lineH)
  }

  // Blinking block cursor
  if (termCursorVisible) {
    const cursorLine = Math.min(termCurrentLine, TERM_LINES.length - 1)
    const cursorText =
      termCurrentLine < TERM_LINES.length
        ? TERM_LINES[cursorLine].substring(0, termCharIndex)
        : TERM_LINES[TERM_LINES.length - 1]
    const textWidth = ctx.measureText(cursorText).width
    ctx.fillStyle = '#00ff88'
    ctx.shadowColor = '#00ff88'
    ctx.shadowBlur = 6
    ctx.fillRect(startX + textWidth + 2, startY + cursorLine * lineH - 12, 8, 15)
  }

  ctx.shadowBlur = 0
}

function drawGlitch(ctx: CanvasRenderingContext2D, w: number, h: number) {
  // Horizontal displacement slices
  const numSlices = 4 + Math.floor(Math.random() * 5)
  for (let i = 0; i < numSlices; i++) {
    const y = Math.random() * h
    const sliceH = 4 + Math.random() * 20
    const shift = (Math.random() - 0.5) * 36

    ctx.save()
    ctx.beginPath()
    ctx.rect(0, y, w, sliceH)
    ctx.clip()
    ctx.drawImage(ctx.canvas, shift, 0)
    ctx.restore()
  }

  // RGB chromatic aberration separation
  ctx.globalCompositeOperation = 'lighter'
  ctx.fillStyle = 'rgba(255, 20, 60, 0.12)'
  ctx.fillRect(Math.random() * 6 - 3, 0, w, h)
  ctx.fillStyle = 'rgba(0, 220, 255, 0.12)'
  ctx.fillRect(-(Math.random() * 6 - 3), 0, w, h)
  ctx.globalCompositeOperation = 'source-over'

  // Bright scanline beam
  ctx.fillStyle = 'rgba(255, 255, 255, 0.22)'
  ctx.fillRect(0, Math.random() * h, w, 2 + Math.random() * 4)
}

function drawCRTEffects(ctx: CanvasRenderingContext2D, w: number, h: number, elapsed: number) {
  // ── Phosphor Scanlines ──
  ctx.fillStyle = 'rgba(0, 0, 0, 0.16)'
  scanlineOffset = (scanlineOffset + 0.4) % 4
  for (let y = scanlineOffset; y < h; y += 4) {
    ctx.fillRect(0, y, w, 1.5)
  }

  // ── CRT Curved Bezel Inner Shadow & Corner Curvature ──
  const vigGrad = ctx.createRadialGradient(w / 2, h / 2, w * 0.32, w / 2, h / 2, w * 0.49)
  vigGrad.addColorStop(0, 'rgba(0, 0, 0, 0)')
  vigGrad.addColorStop(0.70, 'rgba(0, 0, 0, 0.20)')
  vigGrad.addColorStop(0.88, 'rgba(0, 0, 0, 0.60)')
  vigGrad.addColorStop(1, 'rgba(0, 0, 0, 0.92)')
  ctx.fillStyle = vigGrad
  ctx.fillRect(0, 0, w, h)

  // ── Subtle Glass Micro-Noise ──
  for (let i = 0; i < 25; i++) {
    const nx = Math.random() * w
    const ny = Math.random() * h
    ctx.fillStyle = 'rgba(0, 255, 170, 0.04)'
    ctx.fillRect(nx, ny, 1.5, 1.5)
  }

  // ── CRT Luminescence Flicker ──
  const flicker = Math.sin(elapsed * 55) * 0.008 + Math.sin(elapsed * 110) * 0.004
  if (flicker > 0) {
    ctx.fillStyle = `rgba(255, 255, 255, ${flicker})`
    ctx.fillRect(0, 0, w, h)
  }
}

// ══════════════════════════════════════════════════
// ANIMATION LOOP
// ══════════════════════════════════════════════════

function animate() {
  rafId = requestAnimationFrame(animate)

  if (!renderer || !scene || !camera) return

  const elapsed = clock.getElapsedTime()
  const dt = Math.min(clock.getDelta(), 0.05)

  // Update CRT screen texture
  updateScreen(elapsed, dt)

  if (!tvHeadPivot || !staticBody) {
    renderer.render(scene, camera)
    return
  }

  // ── Mouse Targets (responsive cursor tracking across neck and TV head) ──
  const motionScale = prefersReducedMotion ? 0.03 : 1
  targetRotY = mouseX * 0.32 * motionScale // ±18.3 degrees for expressive tracking
  targetRotX = mouseY * 0.20 * motionScale // ±11.5 degrees

  // ── Snappy Damped Physical Rotation (Faster response, zero sluggishness) ──
  currentRotX += (targetRotX - currentRotX) * 0.15
  currentRotY += (targetRotY - currentRotY) * 0.15

  // ── Subtle Natural Idle Motion ──
  let idleBodyY = 0
  let idleHeadRotZ = 0
  if (!prefersReducedMotion) {
    idleBodyY = Math.sin(elapsed * 0.75) * 0.003
    idleHeadRotZ = Math.sin(elapsed * 0.55 + 0.4) * 0.004
  }

  // 1. TV Head pivots smoothly inside the sweater collar socket
  tvHeadPivot.rotation.x = currentRotX
  tvHeadPivot.rotation.y = currentRotY
  tvHeadPivot.rotation.z = idleHeadRotZ
  tvHeadPivot.position.y = (SPLIT_Y - MODEL_CENTER_Y) + idleBodyY

  // 2. Static Body (Torso / Sweater) remains stable at shoulders with breathing motion
  staticBody.position.y = -MODEL_CENTER_Y + idleBodyY

  // 4. Smooth Position & Scale Animation (Center -> Right Transition on Click)
  currentPosX += (targetPosX - currentPosX) * 0.055
  currentPosY += (targetPosY - currentPosY) * 0.055
  currentScale += (targetScale - currentScale) * 0.055

  if (characterGroup) {
    characterGroup.position.set(currentPosX, currentPosY, basePosZ)
    characterGroup.scale.setScalar(currentScale)
  }

  renderer.render(scene, camera)
}

// ══════════════════════════════════════════════════
// CLEANUP
// ══════════════════════════════════════════════════

onBeforeUnmount(() => {
  if (rafId) cancelAnimationFrame(rafId)

  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('resize', onResize)
  if (containerRef.value) {
    containerRef.value.removeEventListener('click', onCanvasClick)
  }

  if (renderer) {
    renderer.dispose()
    renderer.forceContextLoss()
    if (containerRef.value && renderer.domElement.parentNode === containerRef.value) {
      containerRef.value.removeChild(renderer.domElement)
    }
  }

  if (characterGroup) {
    characterGroup.traverse((child: any) => {
      if (child.isMesh) {
        child.geometry?.dispose()
        if (Array.isArray(child.material)) {
          child.material.forEach((m: any) => {
            m.map?.dispose()
            m.dispose()
          })
        } else {
          child.material?.map?.dispose()
          child.material?.dispose()
        }
      }
    })
  }

  if (screenTexture) screenTexture.dispose()
  if (scene) scene.clear()
})
</script>

<style scoped>
.tvhead {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  transition: opacity 1.2s cubic-bezier(0.16, 1, 0.3, 1);
  pointer-events: auto;
  cursor: pointer;
}

.tvhead--loaded {
  opacity: 1;
}

.tvhead :deep(canvas) {
  display: block;
  width: 100% !important;
  height: 100% !important;
}
</style>

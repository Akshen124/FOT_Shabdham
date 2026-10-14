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
let shabdamModel: any = null
let headBone: any = null
let neck2Bone: any = null
let initialHeadRot: any = null
let initialNeck2Rot: any = null
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

// Model constants (TV screen center is Y=0.22 in Shabdam.glb)
const MODEL_CENTER_Y = 0.22

// Layout & Entrance Transition Positions (Center -> Right on Click)
let basePosZ = 0
let finalPosX = 1.05
let finalPosY = -0.34
let finalScale = 0.58
let finalBaseRotY = -0.24
let startPosX = 0.52
let startPosY = -0.28
let startScale = 0.54
let startBaseRotY = -0.16

let targetPosX = 0.52
let targetPosY = -0.28
let targetScale = 0.54
let targetBaseRotY = -0.16
let currentPosX = 0.52
let currentPosY = -0.28
let currentScale = 0.54
let currentBaseRotY = -0.16

// Reduced motion / touch
let prefersReducedMotion = false
let isTouchDevice = false

// ── Eye animation state ──
const BLINK_INTERVAL = 3.0 // Blink every 3 seconds
let blinkState: 'open' | 'closing' | 'closed' | 'opening' = 'open'
let blinkTimer = 0
let nextBlinkTime = BLINK_INTERVAL
let blinkProgress = 0
let eyeMicroX = 0
let eyeMicroY = 0
let eyeMicroTimer = 0

// ── Glitch state ──
let glitchTimer = 0
let nextGlitchTime = 7.5
let glitchActive = false
let glitchDuration = 0

// ── CRT scanline offset ──
let scanlineOffset = 0

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
  characterGroup = new THREE.Group()
  scene.add(characterGroup)

  // ── Load Shabdam Robot Model ──
  const loader = new GLTFLoader()
  try {
    const gltf = await loader.loadAsync('/models/Shabdam.glb')

    // Hide extraneous helper planes from the GLTF scene
    const plane = gltf.scene.getObjectByName('Plane001') || gltf.scene.getObjectByName('Plane.001')
    if (plane) plane.visible = false

    const maps = gltf.scene.getObjectByName('Maps')
    if (maps) maps.visible = false

    const empty = gltf.scene.getObjectByName('Empty002') || gltf.scene.getObjectByName('Empty.002')
    if (empty) empty.visible = false

    shabdamModel = gltf.scene.getObjectByName('Lisa') || gltf.scene
    characterGroup.add(shabdamModel)

    // Center Shabdam vertically around TV screen
    shabdamModel.position.set(0, -MODEL_CENTER_Y, 0)

    // Find bones for natural animated head and neck tracking
    headBone = shabdamModel.getObjectByName('head')
    neck2Bone = shabdamModel.getObjectByName('neck2')

    if (headBone) initialHeadRot = headBone.rotation.clone()
    if (neck2Bone) initialNeck2Rot = neck2Bone.rotation.clone()

    // Find the TV screen mesh and map dynamic CRT living canvas
    screenMesh = shabdamModel.getObjectByName('Screen')
    if (screenMesh && screenTexture) {
      screenMesh.material = new THREE.MeshStandardMaterial({
        map: screenTexture,
        emissive: new THREE.Color(0xffffff),
        emissiveMap: screenTexture,
        emissiveIntensity: 1.15,
        roughness: 0.32,
        metalness: 0.0,
        envMapIntensity: 0.25,
        toneMapped: false,
      })
    }

    // Hide occlusion overlay meshes
    const screenGlow = shabdamModel.getObjectByName('ScreenGlow')
    if (screenGlow) screenGlow.visible = false

    const raycasterMesh = shabdamModel.getObjectByName('Raycaster')
    if (raycasterMesh) raycasterMesh.visible = false

    // Tint shirt/sweater to rich dark blue while keeping original 4K fabric scan
    const bodyMesh = shabdamModel.getObjectByName('BodyHP')
    if (bodyMesh && bodyMesh.material) {
      bodyMesh.material.color = new THREE.Color(0x0d235c)
      bodyMesh.material.roughness = 0.95
      bodyMesh.material.metalness = 0.0
    }

    // Enhance studio reflections on TV casing and materials
    shabdamModel.traverse((child: any) => {
      if (child.isMesh) {
        child.castShadow = false
        child.receiveShadow = false
        if (child.material) {
          if (Array.isArray(child.material)) {
            child.material.forEach((m: any) => { m.envMapIntensity = 1.0 })
          } else {
            child.material.envMapIntensity = 1.0
          }
        }
      }
    })

    // Initial responsive scale and positioning
    updateResponsiveDimensions(width, height)

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
  screenTexture.wrapS = THREE.RepeatWrapping
  screenTexture.repeat.x = -1
  screenTexture.offset.x = 1
  screenTexture.minFilter = THREE.LinearFilter
  screenTexture.magFilter = THREE.LinearFilter
  screenTexture.colorSpace = THREE.SRGBColorSpace
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
    // Mobile: centered layout
    finalScale = 0.42
    finalPosX = 0.12
    finalPosY = -0.24
    finalBaseRotY = 0
    startScale = 0.38
    startPosX = 0.12
    startPosY = -0.20
    startBaseRotY = 0
    camera.position.set(0, -0.05, 3.8)
    camera.lookAt(0, -0.14, 0)
  } else if (w < 900) {
    // Tablet: modest size on right
    finalScale = 0.48
    finalPosX = 0.62
    finalPosY = -0.28
    finalBaseRotY = -0.14
    startScale = 0.44
    startPosX = 0.22
    startPosY = -0.24
    startBaseRotY = -0.08
    camera.position.set(0.08, -0.07, 3.6)
    camera.lookAt(0.28, -0.14, 0)
  } else if (w < 1180) {
    // Laptop: medium size on right, squared up to user
    finalScale = 0.52
    finalPosX = 0.92
    finalPosY = -0.34
    finalBaseRotY = -0.22
    startScale = 0.48
    startPosX = 0.42
    startPosY = -0.28
    startBaseRotY = -0.15
    camera.position.set(0.12, -0.08, 3.5)
    camera.lookAt(0.42, -0.16, 0)
  } else {
    // Large desktop: right-aligned hero assistant, perfectly facing viewer
    finalScale = 0.58
    finalPosX = 1.05
    finalPosY = -0.34
    finalBaseRotY = -0.25
    startScale = 0.54
    startPosX = 0.52
    startPosY = -0.28
    startBaseRotY = -0.18
    camera.position.set(0.14, -0.08, 3.4)
    camera.lookAt(0.48, -0.16, 0)
  }

  if (!isStarted.value) {
    targetPosX = startPosX
    targetPosY = startPosY
    targetScale = startScale
    targetBaseRotY = startBaseRotY
  } else {
    targetPosX = finalPosX
    targetPosY = finalPosY
    targetScale = finalScale
    targetBaseRotY = finalBaseRotY
  }

  if (!isLoaded.value) {
    currentPosX = targetPosX
    currentPosY = targetPosY
    currentScale = targetScale
    currentBaseRotY = targetBaseRotY
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
        nextBlinkTime = BLINK_INTERVAL
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

  const rawDt = clock.getDelta() // must come first
  const elapsed = clock.elapsedTime // property, doesn't consume delta
  const dt = Math.min(rawDt, 0.05)

  // Update CRT screen texture
  updateScreen(elapsed, dt)

  if (!shabdamModel) {
    renderer.render(scene, camera)
    return
  }

  // ── Mouse Targets (responsive cursor tracking across neck and TV head) ──
  const motionScale = prefersReducedMotion ? 0.03 : 1
  targetRotY = mouseX * 0.28 * motionScale // horizontal rotation
  targetRotX = mouseY * 0.18 * motionScale // vertical nod

  // ── Snappy Damped Physical Rotation ──
  currentRotX += (targetRotX - currentRotX) * 0.14
  currentRotY += (targetRotY - currentRotY) * 0.14

  // ── Subtle Natural Idle Motion ──
  let idleBodyY = 0
  let idleHeadRotZ = 0
  if (!prefersReducedMotion) {
    idleBodyY = Math.sin(elapsed * 0.75) * 0.003
    idleHeadRotZ = Math.sin(elapsed * 0.55 + 0.4) * 0.004
  }

  // 1. Skinned TV Head & Neck tracking
  if (headBone && initialHeadRot) {
    headBone.rotation.x = initialHeadRot.x + currentRotX * 0.75
    headBone.rotation.y = initialHeadRot.y + currentRotY * 0.85
    headBone.rotation.z = initialHeadRot.z - currentRotY * 0.12 + idleHeadRotZ
  }

  if (neck2Bone && initialNeck2Rot) {
    neck2Bone.rotation.x = initialNeck2Rot.x + currentRotX * 0.20
    neck2Bone.rotation.y = initialNeck2Rot.y + currentRotY * 0.25
  }

  // 2. Smooth Position & Scale Animation (Center -> Right Transition on Click)
  currentPosX += (targetPosX - currentPosX) * 0.055
  currentPosY += (targetPosY - currentPosY) * 0.055
  currentScale += (targetScale - currentScale) * 0.055
  currentBaseRotY += (targetBaseRotY - currentBaseRotY) * 0.055

  if (characterGroup) {
    characterGroup.position.set(currentPosX, currentPosY + idleBodyY, basePosZ)
    characterGroup.rotation.y = currentBaseRotY + currentRotY * 0.10
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

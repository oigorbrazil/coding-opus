/* Spring timeline adapted from the glass-icon-reveal sample. See startup-shaders.ts for the notice. */
type Look = 'light' | 'dark'

type GlassTuning = {
  /** How far the slab stands above the logo, so how hard the rim bends it */
  opticalDepth: number
  /** Colour split of everything the rim draws in */
  dispersion: number
  /** Soft colour glow inside the rim */
  colorBleed: number
  doubleBevel: number
  bevelWidth: number
  /** Superellipse exponent of the tile: 2 is a circle, ~5 an app icon */
  corner: number
  cornerPull: number
  cornerWidth: number
  cornerFocus: number
  edgeSmear: number
  stretch: number
  tilt: number
  /** Ball-lens bulge of the young droplet */
  bulge: number
  specular: number
  halo: number
  shadow: number
  ripple: number
  /** Droplet spring: 0 = no overshoot */
  bounce: number
  /** Droplet spring period, seconds */
  response: number
  startSize: number
  startZoom: number
  /** Seconds the logo takes to glide out of the droplet's magnification: the stretch where the rim bends it */
  glide: number
  /** Seconds the logo stays in glass */
  present: number
  drift: number
  swell: number
  focus: number
  /** Soft band of light that crosses the glass while it holds the logo (0 = none) */
  sheen: number
  /** How far the light turns round the rim while the glass holds, radians */
  lightTurn: number
}

type Settings = {
  tileSize: number
  logoScale: number
  finalScale: number
  logoOffset: [number, number]
  iconPlate: boolean
  keepPlate: boolean
  originalColors: boolean
  background: string
  plateColor: string
  logoColor: string
} & GlassTuning

const LIGHT: Settings = {
  tileSize: 256,
  logoScale: 0.7,
  finalScale: 0.69,
  logoOffset: [0, 0],
  iconPlate: false,
  keepPlate: false,
  originalColors: false,
  opticalDepth: 1.1,
  dispersion: 1.7,
  colorBleed: 1.25,
  doubleBevel: 1,
  bevelWidth: 0.14,
  corner: 4.8,
  cornerPull: 2.1,
  cornerWidth: 2.2,
  cornerFocus: 0.58,
  edgeSmear: 2.85,
  stretch: 0,
  tilt: 0.35,
  bulge: 1,
  specular: 1,
  halo: 0,
  shadow: 1,
  ripple: 1,
  bounce: 0,
  response: 0.42,
  startSize: 0.2,
  startZoom: 2.6,
  glide: 2.3,
  present: 2.4,
  drift: 0.12,
  swell: 0.5,
  focus: 1,
  sheen: 1,
  lightTurn: 0.9,
  background: '#e9e9eb',
  plateColor: '#ffffff',
  logoColor: '#0e1428'
}

export const LOOKS: Record<Look, Settings> = {
  light: LIGHT,
  dark: {
    ...LIGHT,
    logoScale: 0.72,
    finalScale: 1,
    iconPlate: true,
    halo: 1,
    shadow: 0,
    ripple: 0.5,
    startZoom: 1.6,
    drift: 0.05,
    opticalDepth: 0.75,
    bevelWidth: 0.22,
    dispersion: 0.9,
    colorBleed: 0.45,
    corner: 5,
    cornerPull: 1.4,
    edgeSmear: 1.2,
    tilt: 0,
    cornerWidth: 1.2,
    cornerFocus: 0.4,
    background: '#000000',
    plateColor: '#05070b',
    logoColor: '#ffffff'
  }
}

const TAIL = 1.1 // from the glass letting go to everything at rest, seconds
export const endOf = (P: Settings) => P.present + TAIL

const clamp01 = (x: number) => Math.min(1, Math.max(0, x))
const mix = (a: number, b: number, t: number) => a + (b - a) * t
const smooth = (a: number, b: number, x: number) => {
  const t = clamp01((x - a) / (b - a))
  return t * t * (3 - 2 * t)
}
const smoother = (a: number, b: number, x: number) => {
  const t = clamp01((x - a) / (b - a))
  return t * t * t * (t * (t * 6 - 15) + 10)
}

function hexToRgb(hex: string): [number, number, number] {
  let h = hex.replace('#', '')
  if (h.length === 3) {
    h = h.replace(/./g, '$&$&')
  }
  const v = Number.parseInt(h.slice(0, 6), 16) || 0
  return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255]
}
const luminance = ([r, g, b]: number[]) => 0.2126 * r + 0.7152 * g + 0.0722 * b

// Step response of a spring released at t = 0, from 0 toward 1 (damping 1 = no overshoot,
// response = period of the undamped spring, seconds).
function spring(t: number, response: number, damping: number) {
  if (t <= 0) {
    return 0
  }
  const w = (2 * Math.PI) / response
  if (damping >= 1) {
    return 1 - Math.exp(-w * t) * (1 + w * t)
  }
  const wd = w * Math.sqrt(1 - damping * damping)
  return (
    1 - Math.exp(-damping * w * t) * (Math.cos(wd * t) + ((damping * w) / wd) * Math.sin(wd * t))
  )
}

const reachCache = new Map<string, number>()
function timeToReach(level: number, response: number, damping: number) {
  const key = `${level}/${response}/${damping}`
  let t = reachCache.get(key)
  if (t === undefined) {
    let lo = 0
    let hi = 3
    for (let i = 0; i < 40; i++) {
      const mid = (lo + hi) / 2
      if (spring(mid, response, damping) < level) {
        lo = mid
      } else {
        hi = mid
      }
    }
    reachCache.set(key, (t = hi))
  }
  return t
}

// All motion lives here; the shader only sees the resulting numbers. The droplet grows on one spring,
// spreads from circle to squircle as it lands, the logo glides out of its magnification and the glass
// holds it while a band of light crosses the face and the rim light turns. Then the glass lets go: the
// bare logo stays, or with keepPlate the glass settles into a flat icon plate.
export function frameAt(T: number, P: Settings) {
  const tx = P.present
  const keep = P.keepPlate ? 1 : 0
  const damping = 1 - P.bounce
  const grow = spring(T + 0.01, P.response, damping)
  const tl = timeToReach(0.85, P.response, damping) - 0.01 // the droplet lands: the ripple leaves
  const tm = timeToReach(0.92, P.response, damping) - 0.01 // and spreads into the tile
  const morph = spring(T - tm, 0.4, 1)
  const drop = 1 - smooth(0.05, 1, morph)
  const appear = smooth(0, 0.08, T)
  const drift = P.drift * spring(T - 0.3, 2.2, 1)
  // A quarter of the zoom goes with the landing droplet, the rest glides slowly so the logo lingers
  // big against the rim, where the glass bends it most.
  const zoomIn = 0.25 * spring(T, 0.7, 1) + 0.75 * smoother(0, P.glide, T)
  const settle = spring(T - 0.5, 2.4, 1)
  const exit = spring(T - tx, 0.95, 1)
  const release = spring(T - tx - 0.05, 0.65, 1)
  const dome = 0.15 * P.bulge * (1 - smooth(0.4, 0.95, grow))
  const view =
    (1 + (P.startZoom - 1) * (1 - zoomIn)) * (1 - 0.045 * settle) * mix(1, P.finalScale, exit)
  const bandW = mix(P.bevelWidth, Math.max(P.bevelWidth, 0.4), drop)
  const plateScale =
    mix(P.startSize, 1, grow) *
    (1 + drift) *
    (1 + 0.14 * release * (1 - keep)) *
    (1 - keep * (0.03 * release))
  const bg = hexToRgb(P.background)
  return {
    uPlateScale: plateScale,
    uShapeN: mix(2, P.corner, morph),
    uCornerN: P.corner,
    uOptics: 1 - smooth(0.55, 1, release),
    uPlateAlpha: keep ? appear : appear * (1 - smooth(0.45, 1, release)),
    uLogoHalf: P.logoScale * view,
    uLogoOff: [P.logoOffset[0] * view, P.logoOffset[1] * view] as [number, number],
    uKeep: keep,
    uSheen: P.sheen,
    uSweep: mix(-1.6, 1.6, smoother(0.9, tx - 0.1, T)),
    uLightAng: P.lightTurn * smoother(0.4, tx + 0.4, T),
    uBold: P.swell * 0.03 * (1 - zoomIn),
    uBlur: P.focus * 0.05 * (1 - smooth(0.3, 0.95, grow)),
    uFrost: P.focus * (1 - smooth(0.5, 0.95, grow)),
    uPinch: 0.38 * P.stretch * smooth(0.1, 0.9, morph) * smooth(0.75, 0.97, zoomIn),
    uTilt: P.tilt,
    uDome: dome,
    uDrop: drop,
    uRim: 1 + 0.8 * drop,
    uHalo: P.halo * (0.5 + 0.5 * drop) * (1 - keep * release),
    uShadow: Math.max(
      P.shadow * smooth(0.45, 0.8, grow) * (1 - smooth(0, 0.6, morph)),
      0.8 * P.shadow * keep * release
    ),
    uGhost: smooth(0, 0.03, T) * (1 - smooth(0.04, 0.08, T)),
    uRipR: 1 + 0.9 * Math.max(0, T - tl),
    uRipA: P.ripple * smooth(tl, tl + 0.06, T) * Math.exp(-Math.max(0, T - tl) / 0.6),
    uBare: (1 - keep) * smooth(tx - 0.25, tx, T),
    uReach: bandW * plateScale,
    uCornerPull: P.cornerPull,
    uStreak: P.edgeSmear,
    uWiden: P.cornerWidth,
    uSlab: 0.3 * P.opticalDepth,
    uEtaSpread: 0.06,
    uFocus: P.cornerFocus,
    uFocusK: 1,
    uFocusSplit: 0.056 * P.colorBleed,
    uRimLine: 0.09,
    uCornerOn: smooth(0.35, 1, morph),
    uGlow: 0.012 * P.colorBleed,
    uFaceDisp: 0.012 * P.dispersion,
    uVivid: 0.85,
    uDissolve: release,
    uDisp: P.dispersion,
    uDouble: P.doubleBevel,
    uBevelW: bandW * (1 - release),
    uSpec: P.specular,
    uIconPlate: P.iconPlate ? 1 : 0,
    uUseColor: P.originalColors ? 1 : 0,
    uLightScene: luminance(bg) > 0.5 ? 1 : 0,
    uLightGlass: luminance(P.iconPlate ? hexToRgb(P.plateColor) : bg) > 0.5 ? 1 : 0,
    uBg: bg,
    uPlateCol: hexToRgb(P.plateColor),
    uLogoCol: hexToRgb(P.logoColor)
  }
}

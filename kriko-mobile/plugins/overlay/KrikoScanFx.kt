package __PACKAGE__.overlay

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Shader
import android.view.View
import android.view.animation.LinearInterpolator
import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.floor
import kotlin.math.sin

/**
 * The liquid scan that crosses the page while a capture is read.
 *
 * It is the same sweep the old ribbon drew, read as liquid: a flowing
 * metaball-like crest travels bottom to top, a fixed set of deterministic
 * droplets rises ahead of it, and a fine LED-dot matrix trails underneath. The
 * four capture brackets ride with the crest, so the sweep still says "scanning
 * this", not "loading".
 *
 * Built to sit over a page without costing frames: every Paint, Path, array and
 * matrix is reused, no object is allocated per frame, the particle count is
 * fixed at [DROPLETS] plus the LED grid (at most 120 together), one ValueAnimator
 * is the clock, and the animators are cancelled on detach. With the phone's
 * animations turned off it draws one still crest and leaves at once.
 */
internal class LiquidScanView(context: Context, private val ui: KrikoUi) : View(context) {
  private val bandPaint = Paint(Paint.ANTI_ALIAS_FLAG)
  private val crestPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    style = Paint.Style.STROKE
    strokeCap = Paint.Cap.ROUND
    strokeJoin = Paint.Join.ROUND
  }
  private val glowPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    style = Paint.Style.STROKE
    strokeCap = Paint.Cap.ROUND
    strokeJoin = Paint.Join.ROUND
  }
  private val dropletPaint = Paint(Paint.ANTI_ALIAS_FLAG)
  private val ledPaint = Paint(Paint.ANTI_ALIAS_FLAG)
  private val bracketPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    style = Paint.Style.STROKE
    strokeCap = Paint.Cap.ROUND
    strokeJoin = Paint.Join.ROUND
  }
  private val ribbon = Path()
  private val crest = Path()
  private val brackets = Path()
  private val shaderMatrix = Matrix()
  private var bandShader: LinearGradient? = null
  private var originX = 0f
  private var envelope = 0f
  private var progress = 0f
  private var fade: ValueAnimator? = null
  private var clock: ValueAnimator? = null
  private var onGone: (() -> Unit)? = null
  private val bandHalfHeight = dpf(92f)
  private var ledCols = 8

  // Deterministic particles: index -> lane, phase, speed and size. Nothing here
  // changes between frames, so the same screen always looks the same.
  private val dropletLane = FloatArray(DROPLETS)
  private val dropletSeed = FloatArray(DROPLETS)
  private val dropletSpeed = FloatArray(DROPLETS)
  private val dropletSize = FloatArray(DROPLETS)

  init {
    for (i in 0 until DROPLETS) {
      dropletLane[i] = ((i * 7919 + 131) % 1000) / 1000f
      dropletSeed[i] = ((i * 3571 + 17) % 997) / 997f
      dropletSpeed[i] = 0.55f + 0.9f * (((i * 1291 + 53) % 811) / 811f)
      dropletSize[i] = 0.30f + 0.70f * (((i * 4409 + 97) % 613) / 613f)
    }
  }

  fun begin(x: Float, y: Float, hole: Float = 0f) {
    // y and hole are accepted for the existing overlay call site; this
    // full-width vertical sweep uses its own bottom-to-top path.
    originX = x
    fade?.cancel()
    if (!animationsEnabled()) {
      envelope = 1f
      progress = 0.55f
      invalidate()
      return
    }
    envelope = 0f
    progress = 0f
    ramp(1f, 260L)
    if (clock == null) {
      clock = ValueAnimator.ofFloat(0f, 1f).apply {
        duration = 3000L
        repeatCount = ValueAnimator.INFINITE
        interpolator = LinearInterpolator()
        addUpdateListener {
          progress = it.animatedValue as Float
          invalidate()
        }
        start()
      }
    }
  }

  fun finish(onGone: () -> Unit) {
    this.onGone = onGone
    if (!animationsEnabled()) {
      envelope = 0f
      invalidate()
      onGone()
      this.onGone = null
      return
    }
    ramp(0f, 460L) {
      clock?.cancel()
      clock = null
      this.onGone?.invoke()
      this.onGone = null
    }
  }

  private fun ramp(target: Float, duration: Long, then: (() -> Unit)? = null) {
    fade?.cancel()
    fade = ValueAnimator.ofFloat(envelope, target).apply {
      this.duration = duration
      addUpdateListener {
        envelope = it.animatedValue as Float
        invalidate()
      }
      addListener(object : AnimatorListenerAdapter() {
        private var cancelled = false
        override fun onAnimationCancel(animation: Animator) { cancelled = true }
        override fun onAnimationEnd(animation: Animator) {
          if (!cancelled) then?.invoke()
        }
      })
      start()
    }
  }

  override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
    super.onSizeChanged(w, h, oldw, oldh)
    if (w <= 0 || h <= 0) return
    val accent = ui.palette.accent
    val clear = Color.argb(0, Color.red(accent), Color.green(accent), Color.blue(accent))
    bandShader = LinearGradient(0f, -bandHalfHeight, 0f, bandHalfHeight,
      intArrayOf(clear, KrikoColor.tint(accent, 0.08f), KrikoColor.tint(accent, 0.16f),
        KrikoColor.tint(accent, 0.08f), clear),
      floatArrayOf(0f, 0.24f, 0.5f, 0.76f, 1f), Shader.TileMode.CLAMP)
    bandPaint.shader = bandShader
    // Keep the LED grid inside the particle budget: 14 columns x 6 rows = 84.
    ledCols = ((w / dpf(22f)).toInt()).coerceIn(4, LED_COLS_MAX)
  }

  override fun onDetachedFromWindow() {
    fade?.cancel()
    clock?.cancel()
    fade = null
    clock = null
    onGone = null
    super.onDetachedFromWindow()
  }

  override fun onDraw(canvas: Canvas) {
    val w = width.toFloat()
    val h = height.toFloat()
    if (w <= 0f || h <= 0f || envelope <= 0.002f) return
    val accent = ui.palette.accent
    val bright = KrikoColor.mix(accent, Color.WHITE, 0.66f)
    val crestY = h + bandHalfHeight - progress * (h + 2f * bandHalfHeight)
    val phase = progress * (Math.PI * 2.0).toFloat()
    val segments = 32
    val dx = w / segments

    // The liquid plate: a translucent body hanging under the crest. Its shader
    // follows the moving surface so the tint stays a narrow band over the text.
    shaderMatrix.setTranslate(0f, crestY)
    bandShader?.setLocalMatrix(shaderMatrix)
    bandPaint.alpha = (255f * envelope).toInt()
    ribbon.reset()
    for (i in 0..segments) {
      val x = i * dx
      val y = crestY + surface(x, w, phase)
      if (i == 0) ribbon.moveTo(x, y - bandHalfHeight) else ribbon.lineTo(x, y - bandHalfHeight)
    }
    for (i in segments downTo 0) {
      val x = i * dx
      val y = crestY + surface(x, w, phase)
      ribbon.lineTo(x, y + bandHalfHeight)
    }
    ribbon.close()
    canvas.drawPath(ribbon, bandPaint)

    // The crest itself: a soft wide pass under a crisp bright edge, both reusing
    // the same path so the liquid reads as one surface with depth.
    crest.reset()
    for (i in 0..segments) {
      val x = i * dx
      val y = crestY + surface(x, w, phase)
      if (i == 0) crest.moveTo(x, y) else crest.lineTo(x, y)
    }
    glowPaint.color = accent
    glowPaint.strokeWidth = dpf(9f)
    glowPaint.alpha = (52f * envelope).toInt()
    canvas.drawPath(crest, glowPaint)
    crestPaint.color = bright
    crestPaint.strokeWidth = dpf(2.2f)
    crestPaint.alpha = (242f * envelope).toInt()
    canvas.drawPath(crest, crestPaint)

    // Droplets rise ahead of the crest, each on its own deterministic phase.
    dropletPaint.color = bright
    for (i in 0 until DROPLETS) {
      val rise = fract(progress * dropletSpeed[i] + dropletSeed[i])
      val wobble = sin(phase + i * 1.7f) * 0.035f
      val laneMin = dpf(8f)
      val laneMax = (w - dpf(8f)).coerceAtLeast(laneMin)
      val x = ((dropletLane[i] + wobble) * w).coerceIn(laneMin, laneMax)
      val y = crestY + surface(x, w, phase) - dpf(6f) - rise * dpf(88f)
      if (y < -dpf(24f) || y > h + dpf(24f)) continue
      val fadeOut = sin(rise * Math.PI.toFloat())
      dropletPaint.alpha = (200f * fadeOut * envelope).toInt().coerceIn(0, 255)
      val radius = dpf(0.7f + dropletSize[i] * 1.5f) * (0.55f + 0.45f * (1f - rise))
      canvas.drawCircle(x, y, radius, dropletPaint)
    }

    // A fine LED-dot matrix trails under the crest, shimmering column by column.
    ledPaint.color = accent
    val cell = w / ledCols
    for (col in 0 until ledCols) {
      for (row in 0 until LED_ROWS) {
        val y = crestY + dpf(12f) + row * dpf(15f)
        if (y > h + dpf(8f)) continue
        val shimmer = 0.55f + 0.45f * sin(phase * 2f + col * 0.9f + row * 1.3f)
        val falloff = 1f - row * 0.16f
        ledPaint.alpha = (62f * shimmer * falloff * envelope).toInt().coerceIn(0, 255)
        canvas.drawCircle((col + 0.5f) * cell, y, dpf(1.5f), ledPaint)
      }
    }

    // Four corner brackets ride just outside the central part of the crest,
    // giving the sweep a deliberate scan/capture identity rather than loader dots.
    val bracketY = crestY + surface(w * 0.5f, w, phase)
    val bracketW = minOf(w * 0.24f, dpf(92f))
    val minLeft = dpf(24f)
    val maxLeft = (w - dpf(24f) - bracketW).coerceAtLeast(minLeft)
    val left = (originX - bracketW).coerceIn(minLeft, maxLeft)
    val right = left + bracketW
    val bracketH = dpf(26f)
    val yTop = bracketY - dpf(42f)
    val yBottom = bracketY + dpf(42f)
    val corner = dpf(12f)
    brackets.reset()
    brackets.moveTo(left + corner, yTop); brackets.lineTo(left, yTop); brackets.lineTo(left, yTop + bracketH)
    brackets.moveTo(right - corner, yTop); brackets.lineTo(right, yTop); brackets.lineTo(right, yTop + bracketH)
    brackets.moveTo(left, yBottom - bracketH); brackets.lineTo(left, yBottom); brackets.lineTo(left + corner, yBottom)
    brackets.moveTo(right, yBottom - bracketH); brackets.lineTo(right, yBottom); brackets.lineTo(right - corner, yBottom)
    bracketPaint.color = bright
    bracketPaint.strokeWidth = dpf(1.7f)
    bracketPaint.alpha = (175f * envelope * edgeVisibility(bracketY, h)).toInt()
    canvas.drawPath(brackets, bracketPaint)
  }

  /**
   * The crest's height at `x` relative to `crestY`: three slow sine swells plus
   * three travelling gaussian bumps, which is what makes the edge read as a
   * metaball surface rather than a plain wave. Allocates nothing.
   */
  private fun surface(x: Float, width: Float, phase: Float): Float {
    val t = if (width <= 0f) 0f else x / width
    var y = 0.55f * sin(t * (PI * 2.0).toFloat() + phase)
    y += 0.26f * sin(t * (PI * 5.6).toFloat() - phase * 0.8f + 1.3f)
    y += 0.16f * sin(t * (PI * 9.4).toFloat() + phase * 1.6f + 0.4f)
    for (i in 0 until METABALLS) {
      val center = fract(phase * 0.32f + i * 0.29f)
      val d = t - center
      val spread = 0.085f + 0.03f * i
      y += 0.9f * exp((-(d * d) / (spread * spread)).toDouble()).toFloat()
    }
    return dpf(16f) * y
  }

  private fun fract(value: Float): Float = value - floor(value)

  private fun edgeVisibility(y: Float, height: Float): Float =
    ((y + dpf(30f)) / dpf(30f)).coerceIn(0f, 1f) * ((height + dpf(30f) - y) / dpf(30f)).coerceIn(0f, 1f)

  private companion object {
    const val DROPLETS = 24
    const val METABALLS = 3
    const val LED_ROWS = 6
    const val LED_COLS_MAX = 14
  }
}

/**
 * The drop target that appears while the floating button is being dragged:
 * letting go of the button on it stops sharing. Grows and turns red when the
 * button is over it.
 */
internal class DismissTargetView(context: Context, private val ui: KrikoUi) : View(context) {
  private val glass = GlassPainter(resources.displayMetrics.density)
  private val strokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    style = Paint.Style.STROKE
    strokeCap = Paint.Cap.ROUND
  }
  private val box = android.graphics.RectF()
  private var hover = 0f
  private var animator: ValueAnimator? = null

  override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
    setMeasuredDimension(dp(SIZE_DP), dp(SIZE_DP))
  }

  fun setHover(over: Boolean) {
    animator?.cancel()
    val target = if (over) 1f else 0f
    if (!animationsEnabled()) {
      hover = target
      invalidate()
      return
    }
    animator = ValueAnimator.ofFloat(hover, target).apply {
      duration = 160L
      addUpdateListener { animation ->
        hover = animation.animatedValue as Float
        scaleX = 1f + 0.22f * hover
        scaleY = 1f + 0.22f * hover
        invalidate()
      }
      start()
    }
  }

  override fun onDetachedFromWindow() {
    animator?.cancel()
    super.onDetachedFromWindow()
  }

  override fun onDraw(canvas: Canvas) {
    val w = width.toFloat()
    val h = height.toFloat()
    val palette = ui.palette
    val tint = KrikoColor.mix(0xFF0C0E14.toInt(), palette.risk, 0.55f * hover)
    box.set(dpf(1f), dpf(1f), w - dpf(1f), h - dpf(1f))
    glass.draw(canvas, box, w / 2f, tint, 0.55f + 0.30f * hover, dark = true)
    strokePaint.strokeWidth = dpf(2.4f)
    strokePaint.color = Color.WHITE
    val m = w * 0.34f
    canvas.drawLine(m, m, w - m, h - m, strokePaint)
    canvas.drawLine(w - m, m, m, h - m, strokePaint)
  }

  companion object {
    const val SIZE_DP = 60
  }
}

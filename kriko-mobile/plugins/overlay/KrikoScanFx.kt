package __PACKAGE__.overlay

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
import kotlin.math.sin

/** A full-page scan ribbon that carries the capture into the working state. */
internal class PixelWaveView(context: Context, private val ui: KrikoUi) : View(context) {
  private val bandPaint = Paint(Paint.ANTI_ALIAS_FLAG)
  private val crestPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    style = Paint.Style.STROKE
    strokeCap = Paint.Cap.ROUND
    strokeJoin = Paint.Join.ROUND
  }
  private val trailPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    style = Paint.Style.STROKE
    strokeCap = Paint.Cap.ROUND
    strokeJoin = Paint.Join.ROUND
  }
  private val bracketPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    style = Paint.Style.STROKE
    strokeCap = Paint.Cap.ROUND
    strokeJoin = Paint.Join.ROUND
  }
  private val ribbon = Path()
  private val crest = Path()
  private val upperContour = Path()
  private val lowerContour = Path()
  private val brackets = Path()
  private val shaderMatrix = Matrix()
  private var bandShader: LinearGradient? = null
  private var originX = 0f
  private var envelope = 0f
  private var progress = 0f
  private var fade: ValueAnimator? = null
  private var clock: ValueAnimator? = null
  private var onGone: (() -> Unit)? = null
  private val bandHalfHeight = dpf(96f)

  fun begin(x: Float, y: Float, hole: Float = 0f) {
    // y and hole remain accepted for the existing overlay caller; this full-width
    // vertical sweep deliberately uses a consistent bottom-to-top path.
    originX = x
    fade?.cancel()
    if (!animationsEnabled()) {
      envelope = 1f
      progress = 0.52f
      invalidate()
      return
    }
    envelope = 0f
    progress = 0f
    ramp(1f, 240L)
    if (clock == null) {
      clock = ValueAnimator.ofFloat(0f, 1f).apply {
        duration = 2600L
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
    ramp(0f, 520L) {
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
      addListener(object : android.animation.AnimatorListenerAdapter() {
        private var cancelled = false
        override fun onAnimationCancel(animation: android.animation.Animator) { cancelled = true }
        override fun onAnimationEnd(animation: android.animation.Animator) {
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
      intArrayOf(clear, KrikoColor.tint(accent, 0.10f), KrikoColor.tint(accent, 0.17f),
        KrikoColor.tint(accent, 0.10f), clear),
      floatArrayOf(0f, 0.28f, 0.5f, 0.72f, 1f), Shader.TileMode.CLAMP)
    bandPaint.shader = bandShader
  }

  override fun onDetachedFromWindow() {
    fade?.cancel()
    clock?.cancel()
    fade = null
    clock = null
    super.onDetachedFromWindow()
  }

  override fun onDraw(canvas: Canvas) {
    val w = width.toFloat()
    val h = height.toFloat()
    if (w <= 0f || h <= 0f || envelope <= 0.002f) return
    val accent = ui.palette.accent
    val bright = KrikoColor.mix(accent, Color.WHITE, 0.62f)
    val crestY = h + bandHalfHeight - progress * (h + 2f * bandHalfHeight)
    val amp = dpf(18f)
    val phase = progress * (Math.PI * 2.0).toFloat()
    val segments = 32
    val dx = w / segments

    // Filled ribbon, with its shader following the moving crest. It tints only a
    // narrow strip so page text remains easy to read under the scan.
    shaderMatrix.setTranslate(0f, crestY)
    bandShader?.setLocalMatrix(shaderMatrix)
    bandPaint.alpha = (255f * envelope).toInt()
    ribbon.reset()
    for (i in 0..segments) {
      val x = i * dx
      val y = crestY + waveOffset(x, w, amp, phase)
      if (i == 0) ribbon.moveTo(x, y - bandHalfHeight) else ribbon.lineTo(x, y - bandHalfHeight)
    }
    for (i in segments downTo 0) {
      val x = i * dx
      val y = crestY + waveOffset(x, w, amp, phase)
      ribbon.lineTo(x, y + bandHalfHeight)
    }
    ribbon.close()
    canvas.drawPath(ribbon, bandPaint)

    crest.reset()
    upperContour.reset()
    lowerContour.reset()
    for (i in 0..segments) {
      val x = i * dx
      val y = crestY + waveOffset(x, w, amp, phase)
      if (i == 0) {
        crest.moveTo(x, y)
        upperContour.moveTo(x, y - dpf(14f))
        lowerContour.moveTo(x, y + dpf(22f))
      } else {
        crest.lineTo(x, y)
        upperContour.lineTo(x, y - dpf(14f))
        lowerContour.lineTo(x, y + dpf(22f))
      }
    }
    crestPaint.color = bright
    crestPaint.strokeWidth = dpf(2.2f)
    crestPaint.alpha = (242f * envelope).toInt()
    trailPaint.color = accent
    trailPaint.strokeWidth = dpf(1.1f)
    trailPaint.alpha = (125f * envelope).toInt()
    canvas.drawPath(upperContour, trailPaint)
    canvas.drawPath(lowerContour, trailPaint)
    canvas.drawPath(crest, crestPaint)

    // Four corner brackets ride just outside the central part of the crest,
    // giving the sweep a deliberate scan/capture identity rather than loader dots.
    val bracketY = crestY + waveOffset(w * 0.5f, w, amp, phase)
    val bracketW = minOf(w * 0.24f, dpf(92f))
    val left = (originX - bracketW).coerceIn(dpf(24f), w - dpf(24f) - bracketW)
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

  private fun waveOffset(x: Float, width: Float, amplitude: Float, phase: Float): Float {
    val across = if (width <= 0f) 0f else x / width
    return amplitude * (0.68f * sin(across * Math.PI * 2.0 + phase).toFloat() +
      0.32f * sin(across * Math.PI * 5.0 - phase * 0.72f).toFloat())
  }

  private fun edgeVisibility(y: Float, height: Float): Float =
    ((y + dpf(30f)) / dpf(30f)).coerceIn(0f, 1f) * ((height + dpf(30f) - y) / dpf(30f)).coerceIn(0f, 1f)
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

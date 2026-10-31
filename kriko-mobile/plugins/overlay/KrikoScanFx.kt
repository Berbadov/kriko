package __PACKAGE__.overlay

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.SystemClock
import android.view.View
import android.view.animation.LinearInterpolator
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.sin

/**
 * The wave of pixels that crosses the reader's page while Kriko reads it.
 *
 * It lives in a window of its own that never takes a touch, so the page under it
 * stays usable. Rings of small squares leave the point the scan came from (the
 * floating button, or the bottom edge for the phone assistant), brightening the
 * squares they pass and leaving a faint grid behind, until the answer starts to
 * arrive and the wave fades.
 *
 * Nothing is allocated while it draws, and it is not drawn at all when the phone
 * has animations turned off.
 */
internal class PixelWaveView(context: Context, private val ui: KrikoUi) : View(context) {
  private val paint = Paint()
  private val cell = dpf(10f)
  private val gap = dpf(2.2f)
  private val step = cell + gap
  private var originX = 0f
  private var originY = 0f
  private var hole = 0f
  private var startedAt = 0L
  private var envelope = 0f
  private var fade: ValueAnimator? = null
  private var clock: ValueAnimator? = null
  private var onGone: (() -> Unit)? = null

  private companion object {
    /** A new ring leaves the origin this often. */
    const val RING_EVERY_MS = 780f
    /** The faint grid's breathing cycle. */
    const val BREATH_MS = 1150f
    /** After this long the rings soften, down to under half strength over the span. */
    const val LULL_FROM_MS = 9000f
    const val LULL_SPAN_MS = 7000f
  }

  /**
   * Begin leaving `(x, y)` (screen pixels; the window is full-screen). Squares
   * closer than `hole` stay dark, so the floating button is not buried in them.
   */
  fun begin(x: Float, y: Float, hole: Float = 0f) {
    originX = x
    originY = y
    this.hole = hole
    startedAt = SystemClock.uptimeMillis()
    fade?.cancel()
    envelope = 0f
    ramp(1f, 220L)
    if (clock == null) {
      clock = ValueAnimator.ofFloat(0f, 1f).apply {
        duration = 1000L
        repeatCount = ValueAnimator.INFINITE
        interpolator = LinearInterpolator()
        addUpdateListener { invalidate() }
        start()
      }
    }
  }

  /** Let the wave die away, then call back so the window can be removed. */
  fun finish(onGone: () -> Unit) {
    this.onGone = onGone
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
      addUpdateListener { animation ->
        envelope = animation.animatedValue as Float
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
    // The wave is drawn over the reader's own page, light or dark, so it never fades
    // to white: a vivid blue that crests to a lighter blue reads on both.
    val body = ui.palette.accent
    val glow = KrikoColor.mix(body, Color.WHITE, 0.38f)
    val now = (SystemClock.uptimeMillis() - startedAt).toFloat()
    val speed = dpf(860f) / 1000f
    val thick = step * 3.6f
    val reach = hypot(max(originX, w - originX), max(originY, h - originY)) + thick
    val cols = ceil(w / step).toInt()
    val rows = ceil(h / step).toInt()
    val sparkTick = (now / 120f).toInt()
    // A new ring leaves the origin on every beat, for as long as the wave lives, so the
    // page keeps being swept while it is read. Up to three are on screen; the newest is
    // the brightest, and they soften once the read has gone on a while.
    val beat = RING_EVERY_MS
    val newest = (now / beat).toInt()
    val lull = 1f - 0.55f * ((now - LULL_FROM_MS) / LULL_SPAN_MS).coerceIn(0f, 1f)
    val loop = ((now % BREATH_MS) / BREATH_MS)

    for (row in 0 until rows) {
      val cy = (row + 0.5f) * step
      for (col in 0 until cols) {
        val cx = (col + 0.5f) * step
        val d = hypot(cx - originX, cy - originY)
        if (d < hole) continue
        var v = 0f
        for (age in 0..2) {
          val born = (newest - age) * beat
          if (born < 0f) break
          v = max(v, ringValue(d, (now - born) * speed, thick, reach, (1f - 0.2f * age) * lull))
        }
        // A faint grid under the wave, breathing outward from the origin.
        val breathe = 0.055f + 0.045f * (sin((d / dpf(120f) - loop * 2f) * PI).toFloat() * 0.5f + 0.5f)
        val level = max(v, breathe)
        if (level < 0.035f) continue
        val spark = 0.72f + 0.28f * hash(col, row, sparkTick)
        val size = cell * (0.46f + 0.54f * minOf(1f, v * 1.35f))
        val crest = v * v
        paint.color = Color.rgb(
          mix(Color.red(body), Color.red(glow), crest),
          mix(Color.green(body), Color.green(glow), crest),
          mix(Color.blue(body), Color.blue(glow), crest),
        )
        paint.alpha = (255f * minOf(1f, level * 0.95f) * spark * envelope).toInt()
        val half = size / 2f
        canvas.drawRect(cx - half, cy - half, cx + half, cy + half, paint)
      }
    }
  }

  private fun ringValue(distance: Float, radius: Float, thick: Float, reach: Float, amp: Float): Float {
    if (radius < 0f || radius > reach) return 0f
    val x = abs(distance - radius) / thick
    if (x >= 1f) return 0f
    val k = 1f - x
    // Fade the ring as it leaves the screen so it does not end on a hard edge.
    val tail = 1f - (radius / reach) * 0.55f
    return k * k * amp * tail
  }

  private fun mix(a: Int, b: Int, t: Float): Int = (a + (b - a) * t.coerceIn(0f, 1f)).toInt()

  /** A cheap stable noise in `0..1` for the sparkle on each square. */
  private fun hash(x: Int, y: Int, t: Int): Float {
    var n = x * 73856093 xor y * 19349663 xor t * 83492791
    n = n xor (n ushr 13)
    n *= 1274126177
    return ((n ushr 8) and 0xFFFF) / 65535f
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

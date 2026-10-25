package __PACKAGE__.overlay

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Shader
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.animation.AccelerateDecelerateInterpolator
import android.view.animation.LinearInterpolator
import kotlin.math.PI
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin

/**
 * The floating K, drawn as a page: a rounded sheet with a folded corner, the K
 * on it and two lines of text beneath. It is not a circle on purpose; it is the
 * thing Kriko reads.
 *
 * Its see-through-ness is drawn by hand, per part, rather than with one view
 * alpha, so the K stays legible when the page itself is nearly glass:
 *
 *  - `wake` runs 0..1. At 0 the page rests at the reader's chosen opacity; at 1
 *    (a touch, a running scan, a waiting answer, an open tray) it is solid.
 *  - there is no elevation shadow, because a shadow does not fade with alpha and
 *    shows as a dark smudge around a "transparent" button.
 *
 * Motion, all of it off when the phone has animations turned off:
 *  - a glint crosses the fold and the text lines every few seconds while idle;
 *  - while research runs a band of light sweeps down the page, and the K pulses;
 *  - when an answer arrives the page flips over once;
 *  - a press tilts it a few degrees and squeezes it.
 */
internal class KrikoPuckView(
  context: Context,
  private val ui: KrikoUi,
  private val fonts: KrikoFonts,
) : View(context) {
  enum class Mode { IDLE, SCANNING, PAUSED }

  private val ticker = Handler(Looper.getMainLooper())
  private val page = Path()
  private val fold = Path()
  private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
  private val foldPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
  private val edgePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
  private val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
  private val glyphPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    color = KrikoTheme.ON_ACCENT
    typeface = fonts.semiBold
    textAlign = Paint.Align.CENTER
  }
  private val bandPaint = Paint(Paint.ANTI_ALIAS_FLAG)
  private val box = RectF()

  var mode: Mode = Mode.IDLE
    private set
  /** 0 = resting at the chosen opacity, 1 = solid. */
  private var wake = 1f
  private var wakeAnimator: ValueAnimator? = null
  private var pressAmount = 0f
  private var pressAnimator: ValueAnimator? = null
  private var sweep = 0f
  private var sweepAnimator: ValueAnimator? = null
  private var pulse = 0f
  /** A pass of light across the page, 0..1; negative when none is running. */
  private var glint = -1f
  private var glintAnimator: ValueAnimator? = null
  private var attached = false

  private val glintLoop = object : Runnable {
    override fun run() {
      if (!attached || mode != Mode.IDLE) return
      playGlint()
      ticker.postDelayed(this, GLINT_EVERY_MS)
    }
  }

  override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
    setMeasuredDimension(dp(PAGE_W_DP), dp(PAGE_H_DP))
  }

  /** The opacity the page rests at, `0.2..1`. Takes effect on the next draw. */
  fun settle() = animateWake(0f, 420L)

  fun awaken() = animateWake(1f, 150L)

  fun isSettled(): Boolean = wake <= 0.001f

  fun setMode(value: Mode) {
    if (mode == value) return
    mode = value
    ticker.removeCallbacks(glintLoop)
    if (value == Mode.SCANNING) startSweep() else stopSweep()
    if (value == Mode.IDLE && attached) ticker.postDelayed(glintLoop, 2200L)
    invalidate()
  }

  /** Turn the page over once; played when an answer is waiting. */
  fun flip() {
    if (!animationsEnabled()) return
    cameraDistance = resources.displayMetrics.density * 9000f
    animate().cancel()
    animate().rotationY(360f).setDuration(560L)
      .setInterpolator(AccelerateDecelerateInterpolator())
      .withEndAction { rotationY = 0f }
      .start()
  }

  fun setPress(down: Boolean) {
    pressAnimator?.cancel()
    val target = if (down) 1f else 0f
    if (!animationsEnabled()) {
      pressAmount = target
      invalidate()
      return
    }
    pressAnimator = ValueAnimator.ofFloat(pressAmount, target).apply {
      duration = if (down) 90L else 200L
      interpolator = if (down) AccelerateDecelerateInterpolator() else android.view.animation.OvershootInterpolator(2.2f)
      addUpdateListener { animation ->
        pressAmount = animation.animatedValue as Float
        invalidate()
      }
      start()
    }
  }

  private fun animateWake(target: Float, duration: Long) {
    wakeAnimator?.cancel()
    if (!animationsEnabled() || !attached) {
      wake = target
      invalidate()
      return
    }
    wakeAnimator = ValueAnimator.ofFloat(wake, target).apply {
      this.duration = duration
      interpolator = LinearInterpolator()
      addUpdateListener { animation ->
        wake = animation.animatedValue as Float
        invalidate()
      }
      start()
    }
  }

  private fun playGlint() {
    if (!animationsEnabled()) return
    glintAnimator?.cancel()
    glintAnimator = ValueAnimator.ofFloat(0f, 1f).apply {
      duration = 1100L
      interpolator = AccelerateDecelerateInterpolator()
      addUpdateListener { animation ->
        glint = animation.animatedValue as Float
        invalidate()
      }
      addListener(object : android.animation.AnimatorListenerAdapter() {
        override fun onAnimationEnd(animation: android.animation.Animator) {
          glint = -1f
          invalidate()
        }
      })
      start()
    }
  }

  private fun startSweep() {
    sweepAnimator?.cancel()
    if (!animationsEnabled() || !attached) return
    sweepAnimator = ValueAnimator.ofFloat(0f, 1f).apply {
      duration = 1500L
      repeatCount = ValueAnimator.INFINITE
      interpolator = LinearInterpolator()
      addUpdateListener { animation ->
        sweep = animation.animatedValue as Float
        pulse = (sin(sweep * 2 * PI).toFloat() + 1f) / 2f
        invalidate()
      }
      start()
    }
  }

  private fun stopSweep() {
    sweepAnimator?.cancel()
    sweepAnimator = null
    sweep = 0f
    pulse = 0f
  }

  override fun onAttachedToWindow() {
    super.onAttachedToWindow()
    attached = true
    if (mode == Mode.SCANNING) startSweep()
    if (mode == Mode.IDLE) ticker.postDelayed(glintLoop, 2200L)
  }

  override fun onDetachedFromWindow() {
    attached = false
    ticker.removeCallbacks(glintLoop)
    wakeAnimator?.cancel()
    pressAnimator?.cancel()
    glintAnimator?.cancel()
    stopSweep()
    animate().cancel()
    super.onDetachedFromWindow()
  }

  override fun onDraw(canvas: Canvas) {
    val w = width.toFloat()
    val h = height.toFloat()
    if (w <= 0f || h <= 0f) return
    val palette = ui.palette
    val rest = ui.puckOpacity
    // Effective opacity: the chosen one at rest, solid when awake.
    val o = rest + (1f - rest) * wake
    val base = if (mode == Mode.PAUSED) palette.ink3 else palette.accent
    val top = KrikoColor.mix(base, KrikoTheme.ON_ACCENT, 0.24f)

    val cornerRadius = dpf(10f)
    val foldSize = dpf(14f)
    page.reset()
    page.moveTo(cornerRadius, 0f)
    page.lineTo(w - foldSize, 0f)
    page.lineTo(w, foldSize)
    page.lineTo(w, h - cornerRadius)
    page.quadTo(w, h, w - cornerRadius, h)
    page.lineTo(cornerRadius, h)
    page.quadTo(0f, h, 0f, h - cornerRadius)
    page.lineTo(0f, cornerRadius)
    page.quadTo(0f, 0f, cornerRadius, 0f)
    page.close()

    canvas.save()
    // Press: a few degrees of tilt and a gentle squeeze around the centre.
    val squeeze = 1f - 0.07f * pressAmount
    canvas.rotate(-4f * pressAmount, w / 2, h / 2)
    canvas.scale(squeeze, squeeze, w / 2, h / 2)

    fillPaint.shader = LinearGradient(0f, 0f, 0f, h, top, base, Shader.TileMode.CLAMP)
    fillPaint.alpha = (255 * min(1f, o * 0.96f)).toInt()
    canvas.drawPath(page, fillPaint)

    edgePaint.strokeWidth = dpf(1f)
    edgePaint.color = Color.WHITE
    edgePaint.alpha = (255 * (0.18f + 0.22f * o)).toInt()
    canvas.drawPath(page, edgePaint)

    // The folded corner: a lighter triangle with a crease.
    fold.reset()
    fold.moveTo(w - foldSize, 0f)
    fold.lineTo(w, foldSize)
    fold.lineTo(w - foldSize, foldSize)
    fold.close()
    foldPaint.color = Color.WHITE
    foldPaint.alpha = (255 * (0.20f + 0.20f * o)).toInt()
    canvas.drawPath(fold, foldPaint)

    canvas.save()
    canvas.clipPath(page)

    // The K. Held more solid than the page so it reads when the page is glass.
    glyphPaint.textSize = dpf(24f) * (1f + 0.05f * pulse)
    glyphPaint.alpha = (255 * min(1f, o + 0.34f)).toInt()
    val metrics = glyphPaint.fontMetrics
    val centreY = h * 0.43f
    canvas.drawText("K", w * 0.47f, centreY - (metrics.ascent + metrics.descent) / 2f, glyphPaint)

    // Lines of text, or the pause marks while the capture is paused.
    linePaint.color = Color.WHITE
    if (mode == Mode.PAUSED) {
      linePaint.alpha = (255 * (0.5f * o + 0.1f)).toInt()
      val barW = dpf(3.2f)
      val barH = dpf(10f)
      val y = h * 0.72f
      box.set(w / 2 - barW * 1.8f, y, w / 2 - barW * 0.8f, y + barH)
      canvas.drawRoundRect(box, barW / 2, barW / 2, linePaint)
      box.set(w / 2 + barW * 0.8f, y, w / 2 + barW * 1.8f, y + barH)
      canvas.drawRoundRect(box, barW / 2, barW / 2, linePaint)
    } else {
      linePaint.alpha = (255 * (0.34f + 0.26f * o)).toInt()
      val lineH = dpf(2.8f)
      val left = w * 0.2f
      box.set(left, h * 0.74f, w * 0.8f, h * 0.74f + lineH)
      canvas.drawRoundRect(box, lineH, lineH, linePaint)
      box.set(left, h * 0.84f, w * 0.58f, h * 0.84f + lineH)
      canvas.drawRoundRect(box, lineH, lineH, linePaint)
    }

    // Scanning: a band of light sweeps from the top of the page to the bottom.
    if (mode == Mode.SCANNING) {
      val band = h * 0.42f
      val y = -band + (h + band) * sweep
      bandPaint.shader = LinearGradient(0f, y, 0f, y + band,
        intArrayOf(Color.argb(0, 255, 255, 255), Color.argb((255 * 0.55f).toInt(), 255, 255, 255), Color.argb(0, 255, 255, 255)),
        floatArrayOf(0f, 0.5f, 1f), Shader.TileMode.CLAMP)
      canvas.drawRect(0f, y, w, y + band, bandPaint)
    }

    // Idle: a diagonal glint crosses the page now and then.
    if (glint >= 0f) {
      val band = w * 0.5f
      val x = -band + (w + band) * glint
      bandPaint.shader = LinearGradient(x, 0f, x + band, h * 0.5f,
        intArrayOf(Color.argb(0, 255, 255, 255), Color.argb((255 * 0.42f * max(0.4f, o)).toInt(), 255, 255, 255), Color.argb(0, 255, 255, 255)),
        floatArrayOf(0f, 0.5f, 1f), Shader.TileMode.CLAMP)
      canvas.drawRect(0f, 0f, w, h, bandPaint)
    }
    canvas.restore()
    canvas.restore()
  }

  companion object {
    const val PAGE_W_DP = 42
    const val PAGE_H_DP = 54
    private const val GLINT_EVERY_MS = 6500L
  }
}

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
import android.graphics.SweepGradient
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.animation.AccelerateDecelerateInterpolator
import android.view.animation.LinearInterpolator
import kotlin.math.PI
import kotlin.math.max
import kotlin.math.sin

/**
 * The floating Kriko button: a small pane of liquid glass with the Kriko mark
 * on it. Tap it to scan, press and hold for the menu, drag it anywhere.
 *
 * How see-through it is belongs to the reader (Settings → Transparency) and is
 * part of the glass itself, always: a running scan or a waiting answer lifts it a
 * little so it is easy to find, but never turns it solid unless the reader chose
 * Solid. The mark is drawn more firmly than the glass so it reads even when the
 * glass is nearly clear.
 *
 * Motion, all of it off when the phone has animations turned off:
 *  - a glint crosses the glass every few seconds while idle;
 *  - while research runs a point of light travels around the rim and the mark
 *    breathes;
 *  - when an answer arrives the button turns over once;
 *  - a press squeezes it, and holding fills a ring that ends in the menu.
 */
internal class KrikoPuckView(
  context: Context,
  private val ui: KrikoUi,
  @Suppress("unused") private val fonts: KrikoFonts,
) : View(context) {
  enum class Mode { IDLE, SCANNING, PAUSED }

  private val ticker = Handler(Looper.getMainLooper())
  private val glass = GlassPainter(resources.displayMetrics.density)
  private val logo = Path()
  private val markPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
  private val bandPaint = Paint(Paint.ANTI_ALIAS_FLAG)
  private val rimLight = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
  private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    style = Paint.Style.STROKE
    strokeCap = Paint.Cap.ROUND
  }
  private val box = RectF()
  private val clip = Path()

  var mode: Mode = Mode.IDLE
    private set
  /** 0 = resting at the chosen opacity, 1 = lifted. */
  private var wake = 1f
  private var wakeAnimator: ValueAnimator? = null
  private var pressAmount = 0f
  private var pressAnimator: ValueAnimator? = null
  private var hold = 0f
  private var holdAnimator: ValueAnimator? = null
  private var sweep = 0f
  private var sweepAnimator: ValueAnimator? = null
  private var pulse = 0f
  /** A pass of light across the glass, 0..1; negative when none is running. */
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
    setMeasuredDimension(dp(SIZE_DP), dp(SIZE_DP))
  }

  /** Back to the reader's chosen opacity. */
  fun settle() = animateWake(0f, 420L)

  /** A little clearer, so it is easy to find; never past what the reader allows. */
  fun awaken() = animateWake(1f, 150L)

  fun setMode(value: Mode) {
    if (mode == value) return
    mode = value
    ticker.removeCallbacks(glintLoop)
    if (value == Mode.SCANNING) startSweep() else stopSweep()
    if (value == Mode.IDLE && attached) ticker.postDelayed(glintLoop, 2200L)
    invalidate()
  }

  /** Turn over once; played when an answer is waiting. */
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

  /** The ring that fills while the reader holds: `durationMs` until the menu opens. */
  fun startHold(durationMs: Long) {
    holdAnimator?.cancel()
    if (!animationsEnabled()) return
    holdAnimator = ValueAnimator.ofFloat(0f, 1f).apply {
      duration = durationMs
      interpolator = LinearInterpolator()
      addUpdateListener { animation ->
        hold = animation.animatedValue as Float
        invalidate()
      }
      start()
    }
  }

  fun cancelHold() {
    holdAnimator?.cancel()
    holdAnimator = null
    if (hold == 0f) return
    hold = 0f
    invalidate()
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
      duration = 1300L
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
    holdAnimator?.cancel()
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
    // The glass keeps the reader's opacity; waking lifts it a quarter, no more.
    val lifted = minOf(1f, rest + 0.25f)
    val o = rest + (lifted - rest) * wake
    val paused = mode == Mode.PAUSED
    val tint = if (paused) KrikoColor.mix(palette.ink3, 0xFF14161C.toInt(), 0.55f)
    else KrikoColor.mix(palette.accent, 0xFF05091A.toInt(), 0.22f)

    val radius = dpf(16f)
    val pad = dpf(1f)
    box.set(pad, pad, w - pad, h - pad)

    canvas.save()
    // Press: a gentle squeeze around the centre; hold swells it a touch.
    val scale = 1f - 0.08f * pressAmount + 0.05f * hold
    canvas.scale(scale, scale, w / 2, h / 2)

    // A faint halo keeps clear glass findable on a busy page without a shadow.
    markPaint.color = if (paused) palette.ink3 else palette.accent
    markPaint.alpha = (255 * (0.10f + 0.22f * pulse + 0.10f * hold)).toInt()
    canvas.drawRoundRect(
      RectF(box.left - dpf(2f), box.top - dpf(2f), box.right + dpf(2f), box.bottom + dpf(2f)),
      radius + dpf(2f), radius + dpf(2f), markPaint,
    )

    glass.draw(canvas, box, radius, tint, o, dark = true)

    canvas.save()
    clip.reset()
    clip.addRoundRect(box, radius, radius, Path.Direction.CW)
    canvas.clipPath(clip)

    // A glint crosses the glass now and then while nothing else is happening.
    if (glint >= 0f) {
      val band = w * 0.6f
      val x = -band + (w + band) * glint
      bandPaint.shader = LinearGradient(x, 0f, x + band, h * 0.6f,
        intArrayOf(Color.argb(0, 255, 255, 255), Color.argb((255 * 0.40f * max(0.5f, o)).toInt(), 255, 255, 255), Color.argb(0, 255, 255, 255)),
        floatArrayOf(0f, 0.5f, 1f), Shader.TileMode.CLAMP)
      canvas.drawRect(0f, 0f, w, h, bandPaint)
    }

    // The mark. Firmer than the glass so it reads when the glass is nearly clear.
    val markHeight = h * (0.52f + 0.04f * pulse)
    KrikoLogo.fit(logo, w * 0.5f, h * 0.5f, markHeight)
    markPaint.color = Color.WHITE
    markPaint.alpha = (255 * minOf(1f, 0.62f + 0.38f * o)).toInt()
    canvas.drawPath(logo, markPaint)
    if (paused) {
      // Two pause marks beside the mark say capture is waiting for a tap.
      markPaint.alpha = (255 * 0.55f).toInt()
      val barW = dpf(2.6f)
      val barH = dpf(9f)
      box.set(w - dpf(11f), h / 2 - barH / 2, w - dpf(11f) + barW, h / 2 + barH / 2)
      canvas.drawRoundRect(box, barW / 2, barW / 2, markPaint)
      box.set(w - dpf(6.5f), h / 2 - barH / 2, w - dpf(6.5f) + barW, h / 2 + barH / 2)
      canvas.drawRoundRect(box, barW / 2, barW / 2, markPaint)
      box.set(pad, pad, w - pad, h - pad)
    }
    canvas.restore()

    // Scanning: a point of light runs around the rim.
    if (mode == Mode.SCANNING) {
      rimLight.strokeWidth = dpf(2.2f)
      val cx = w / 2
      val cy = h / 2
      rimLight.shader = SweepGradient(cx, cy,
        intArrayOf(Color.argb(0, 255, 255, 255), Color.argb(0, 255, 255, 255), Color.argb(255, 255, 255, 255), Color.argb(0, 255, 255, 255)),
        floatArrayOf(0f, 0.55f, 0.92f, 1f))
      canvas.save()
      canvas.rotate(sweep * 360f, cx, cy)
      canvas.drawRoundRect(box, radius, radius, rimLight)
      canvas.restore()
    }

    // Holding: a ring fills around the button, and the menu opens when it closes.
    if (hold > 0f) {
      ringPaint.strokeWidth = dpf(2.4f)
      ringPaint.color = Color.WHITE
      ringPaint.alpha = (255 * 0.9f).toInt()
      val out = dpf(3f)
      canvas.drawArc(RectF(-out, -out, w + out, h + out), -90f, 360f * hold, false, ringPaint)
    }
    canvas.restore()
  }

  companion object {
    const val SIZE_DP = 46
    private const val GLINT_EVERY_MS = 6500L
  }
}

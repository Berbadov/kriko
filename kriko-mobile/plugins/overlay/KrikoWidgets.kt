package __PACKAGE__.overlay

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.TimeInterpolator
import android.animation.ValueAnimator
import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Matrix
import android.graphics.Outline
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.os.Build
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.ViewOutlineProvider
import android.view.animation.DecelerateInterpolator
import android.view.animation.LinearInterpolator
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.util.WeakHashMap
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.roundToInt

internal fun Context.dp(value: Int): Int = (value * resources.displayMetrics.density).roundToInt()

internal fun Context.dpf(value: Float): Float = value * resources.displayMetrics.density

internal fun View.dp(value: Int): Int = context.dp(value)

internal fun View.dpf(value: Float): Float = context.dpf(value)

/** Whether the phone allows motion (Settings → Remove animations turns it off). */
internal fun animationsEnabled(): Boolean = Build.VERSION.SDK_INT < 26 || ValueAnimator.areAnimatorsEnabled()

/** The rounded fills, outlines and ripples every native window is drawn from. */
internal object KrikoDraw {
  fun shape(context: Context, color: Int, radiusDp: Int, strokeColor: Int = Color.TRANSPARENT): GradientDrawable =
    GradientDrawable().apply {
      shape = GradientDrawable.RECTANGLE
      setColor(color)
      cornerRadius = context.dp(radiusDp).toFloat()
      if (Color.alpha(strokeColor) > 0) setStroke(context.dp(1), strokeColor)
    }

  /** A hairline-edged rounded fill, optionally wrapped in a clipping press ripple. */
  fun capsule(context: Context, color: Int, radiusDp: Int, strokeColor: Int, rippleColor: Int? = null): Drawable {
    val content = shape(context, color, radiusDp, strokeColor)
    if (rippleColor == null) return content
    return RippleDrawable(ColorStateList.valueOf(rippleColor), content, shape(context, Color.WHITE, radiusDp))
  }

  fun circle(color: Int): GradientDrawable = GradientDrawable().apply {
    shape = GradientDrawable.OVAL
    setColor(color)
  }

  fun roundOutline(context: Context, radiusDp: Int): ViewOutlineProvider = object : ViewOutlineProvider() {
    override fun getOutline(view: View, outline: Outline) {
      outline.setRoundRect(0, 0, view.width, view.height, context.dp(radiusDp).toFloat())
    }
  }
}

/**
 * Springy, cancellable view motion. One instance per window owner: it remembers
 * which animator is driving which view so a new move replaces the old one.
 */
internal class KrikoMotion {
  private val active = WeakHashMap<View, ValueAnimator>()
  val spring = TimeInterpolator { input ->
    val t = input.coerceIn(0f, 1f).toDouble()
    (1.0 - exp(-8.2 * t) * cos(10.5 * t)).coerceIn(0.0, 1.08).toFloat()
  }

  fun cancel(view: View) {
    active.remove(view)?.cancel()
  }

  fun animateIn(view: View, initialScale: Float, duration: Long, fromTranslationY: Float = 0f) {
    if (view.visibility != View.VISIBLE) {
      view.alpha = 0f
      view.scaleX = initialScale
      view.scaleY = initialScale
      view.translationY = fromTranslationY
    }
    view.visibility = View.VISIBLE
    animate(view, 1f, 1f, 0f, duration, spring = true)
  }

  fun animate(
    view: View,
    alpha: Float,
    scale: Float,
    translationY: Float,
    duration: Long,
    spring: Boolean,
    onEnd: (() -> Unit)? = null,
  ) {
    active.remove(view)?.cancel()
    if (!animationsEnabled()) {
      view.alpha = alpha.coerceIn(0f, 1f)
      view.scaleX = scale
      view.scaleY = scale
      view.translationY = translationY
      onEnd?.invoke()
      return
    }
    val fromAlpha = view.alpha
    val fromScaleX = view.scaleX
    val fromScaleY = view.scaleY
    val fromTranslation = view.translationY
    var cancelled = false
    lateinit var animator: ValueAnimator
    animator = ValueAnimator.ofFloat(0f, 1f).apply {
      this.duration = duration
      interpolator = if (spring) this@KrikoMotion.spring else DecelerateInterpolator()
      addUpdateListener { valueAnimator ->
        val fraction = valueAnimator.animatedValue as Float
        view.alpha = (fromAlpha + (alpha - fromAlpha) * fraction).coerceIn(0f, 1f)
        view.scaleX = fromScaleX + (scale - fromScaleX) * fraction
        view.scaleY = fromScaleY + (scale - fromScaleY) * fraction
        view.translationY = fromTranslation + (translationY - fromTranslation) * fraction
      }
      addListener(object : AnimatorListenerAdapter() {
        override fun onAnimationCancel(animation: Animator) { cancelled = true }
        override fun onAnimationEnd(animation: Animator) {
          if (cancelled || active[view] !== animator) return
          active.remove(view)
          view.alpha = alpha.coerceIn(0f, 1f)
          view.scaleX = scale
          view.scaleY = scale
          view.translationY = translationY
          onEnd?.invoke()
        }
      })
    }
    active[view] = animator
    animator.start()
  }

  /** A short scale on press; the ripple comes from the background drawable. */
  fun pressMotion(view: View) {
    view.setOnTouchListener { pressedView, event ->
      when (event.actionMasked) {
        MotionEvent.ACTION_DOWN -> animate(pressedView, 1f, 0.97f, 0f, 90L, spring = true)
        MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> animate(pressedView, 1f, 1f, 0f, 150L, spring = true)
      }
      false
    }
  }
}

/**
 * The answer sheet's frame. One swipe up from anywhere that is not scrolling
 * content folds it away, with the sheet following the finger. The body gives way
 * first: while it can still scroll, a swipe on it scrolls it, so reading is never
 * fought; once it has reached its end, the same swipe folds the sheet.
 */
internal class SwipeSheet(context: Context) : LinearLayout(context) {
  /** The sheet was swiped away; the owner removes it. */
  var onMinimize: (() -> Unit)? = null
  /** A finger took hold: stop any entrance animation so the two do not fight. */
  var onGrab: (() -> Unit)? = null
  /** The scrolling part, so a swipe that starts on it can be left to it. */
  var body: ScrollView? = null

  private val slop = android.view.ViewConfiguration.get(context).scaledTouchSlop
  private var downX = 0f
  private var downY = 0f
  private var armed = false
  private var dragging = false
  private var tracker: android.view.VelocityTracker? = null
  private val at = IntArray(2)

  override fun onInterceptTouchEvent(event: MotionEvent): Boolean {
    when (event.actionMasked) {
      MotionEvent.ACTION_DOWN -> {
        downX = event.rawX
        downY = event.rawY
        dragging = false
        armed = startsOutsideLiveScroll(event)
        tracker?.recycle()
        tracker = android.view.VelocityTracker.obtain().also { it.addMovement(event) }
      }
      MotionEvent.ACTION_MOVE -> {
        tracker?.addMovement(event)
        if (beginSwipe(event)) return true
      }
      MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> release()
    }
    return false
  }

  /** A swipe up has started once the finger has travelled past the slop, mostly upward. */
  private fun beginSwipe(event: MotionEvent): Boolean {
    if (!armed || dragging) return false
    val dy = event.rawY - downY
    val dx = event.rawX - downX
    if (dy >= -slop || kotlin.math.abs(dy) <= kotlin.math.abs(dx) * 1.3f) return false
    dragging = true
    onGrab?.invoke()
    parent?.requestDisallowInterceptTouchEvent(true)
    return true
  }

  override fun onTouchEvent(event: MotionEvent): Boolean {
    // A touch that starts on a bare part of the sheet (the grabber, the header, the
    // padding) has no child to take it, so the intercept hook never sees its later
    // events: claim it here, or the swipe is lost after the first contact.
    if (event.actionMasked == MotionEvent.ACTION_DOWN) return true
    tracker?.addMovement(event)
    if (!dragging) {
      if (event.actionMasked == MotionEvent.ACTION_MOVE) beginSwipe(event)
      if (!dragging) {
        if (event.actionMasked == MotionEvent.ACTION_UP || event.actionMasked == MotionEvent.ACTION_CANCEL) release()
        return super.onTouchEvent(event)
      }
    }
    when (event.actionMasked) {
      MotionEvent.ACTION_MOVE -> {
        val dy = (event.rawY - downY).coerceAtMost(0f)
        translationY = dy
        alpha = (1f + dy / (height * 0.85f).coerceAtLeast(1f)).coerceIn(0.3f, 1f)
      }
      MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
        tracker?.computeCurrentVelocity(1000)
        val velocity = tracker?.yVelocity ?: 0f
        val fold = event.actionMasked == MotionEvent.ACTION_UP && (translationY < -dp(44) || velocity < -900f)
        dragging = false
        release()
        if (fold) {
          onMinimize?.invoke()
        } else {
          animate().translationY(0f).alpha(1f).setDuration(240L)
            .setInterpolator(android.view.animation.OvershootInterpolator(1.1f)).start()
        }
      }
    }
    return true
  }

  private fun startsOutsideLiveScroll(event: MotionEvent): Boolean {
    val scroller = body ?: return true
    if (!scroller.isShown) return true
    // The raw coordinates are the screen's. A view's global visible rect is relative to
    // its own window, which sits well down the screen, so it would call the header
    // "inside the body" and a swipe that starts there would never fold the sheet.
    scroller.getLocationOnScreen(at)
    val x = event.rawX.toInt()
    val y = event.rawY.toInt()
    if (x < at[0] || x > at[0] + scroller.width || y < at[1] || y > at[1] + scroller.height) return true
    return !scroller.canScrollVertically(1)
  }

  private fun release() {
    tracker?.recycle()
    tracker = null
  }
}

/** A scroll view that stops growing at a cap, so the buttons below it stay on screen. */
internal class CappedScroll(context: Context, private val capPx: Int) : ScrollView(context) {
  override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
    super.onMeasure(widthMeasureSpec, View.MeasureSpec.makeMeasureSpec(capPx, View.MeasureSpec.AT_MOST))
  }
}

/** The action glyphs, drawn in the app's own line weight so no icon font is needed. */
internal class GlyphView(context: Context, private val kind: String, private val color: Int) : View(context) {
  private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    style = Paint.Style.STROKE
    strokeCap = Paint.Cap.ROUND
    strokeJoin = Paint.Join.ROUND
  }

  override fun onDraw(canvas: Canvas) {
    val w = width.toFloat()
    val h = height.toFloat()
    paint.color = color
    paint.strokeWidth = w * 0.095f
    when (kind) {
      "scan" -> {
        // Four corner brackets around a small ring: the viewfinder.
        val m = w * 0.12f
        val l = w * 0.27f
        canvas.drawLine(m, m + l, m, m, paint); canvas.drawLine(m, m, m + l, m, paint)
        canvas.drawLine(w - m - l, m, w - m, m, paint); canvas.drawLine(w - m, m, w - m, m + l, paint)
        canvas.drawLine(m, h - m - l, m, h - m, paint); canvas.drawLine(m, h - m, m + l, h - m, paint)
        canvas.drawLine(w - m - l, h - m, w - m, h - m, paint); canvas.drawLine(w - m, h - m, w - m, h - m - l, paint)
        canvas.drawCircle(w / 2, h / 2, w * 0.12f, paint)
      }
      "list" -> {
        val x1 = w * 0.2f
        val x2 = w * 0.8f
        for (row in 0..2) {
          val y = h * (0.28f + row * 0.22f)
          canvas.drawLine(x1, y, if (row == 2) w * 0.56f else x2, y, paint)
        }
      }
      "stop" -> {
        val inset = w * 0.22f
        canvas.drawRoundRect(RectF(inset, inset, w - inset, h - inset), w * 0.1f, w * 0.1f, paint)
      }
      "copy" -> {
        val a = w * 0.2f
        val b = w * 0.66f
        canvas.drawRoundRect(RectF(a + w * 0.12f, a + w * 0.12f, b + w * 0.14f, b + w * 0.14f), w * 0.1f, w * 0.1f, paint)
        canvas.drawRoundRect(RectF(a - w * 0.04f, a - w * 0.04f, b - w * 0.04f, b - w * 0.04f), w * 0.1f, w * 0.1f, paint)
      }
      "check" -> {
        canvas.drawLine(w * 0.2f, h * 0.54f, w * 0.43f, h * 0.76f, paint)
        canvas.drawLine(w * 0.43f, h * 0.76f, w * 0.8f, h * 0.28f, paint)
      }
    }
  }
}

/** A thin sliding highlight: "working" without a percentage nobody can know. */
internal class IndeterminateBar(
  context: Context,
  track: Int,
  private val fill: Int,
) : FrameLayout(context) {
  private val runner = View(context)
  private var animator: ValueAnimator? = null

  init {
    background = KrikoDraw.shape(context, track, 2)
    clipChildren = true
    clipToOutline = true
    outlineProvider = KrikoDraw.roundOutline(context, 2)
    runner.background = KrikoDraw.shape(context, fill, 2)
    addView(runner, LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT))
  }

  override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
    super.onSizeChanged(w, h, oldw, oldh)
    runner.layoutParams = (runner.layoutParams as LayoutParams).apply { width = (w * 0.38f).roundToInt() }
    restart()
  }

  override fun onVisibilityChanged(changedView: View, visibility: Int) {
    super.onVisibilityChanged(changedView, visibility)
    if (changedView === this) restart()
  }

  private fun restart() {
    animator?.cancel()
    animator = null
    if (visibility != View.VISIBLE || width <= 0) return
    if (!animationsEnabled()) {
      runner.translationX = 0f
      return
    }
    val travel = width.toFloat()
    animator = ValueAnimator.ofFloat(-travel * 0.4f, travel).apply {
      duration = 1250
      repeatCount = ValueAnimator.INFINITE
      interpolator = android.view.animation.AccelerateDecelerateInterpolator()
      addUpdateListener { animation -> runner.translationX = animation.animatedValue as Float }
      start()
    }
  }

  override fun onDetachedFromWindow() {
    animator?.cancel()
    animator = null
    super.onDetachedFromWindow()
  }
}

/** A soft band of light that travels down its view while `active`. */
internal class SweepView(context: Context, private val bandColor: Int) : View(context) {
  private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
  private val shift = Matrix()
  private var shader: LinearGradient? = null
  private var progress = 0f
  private var animator: ValueAnimator? = null
  private var active = false

  fun setActive(value: Boolean) {
    if (active == value) return
    active = value
    restart()
  }

  private fun restart() {
    animator?.cancel()
    animator = null
    if (!active || !isAttachedToWindow) {
      invalidate()
      return
    }
    if (!animationsEnabled()) {
      progress = 0.5f
      invalidate()
      return
    }
    animator = ValueAnimator.ofFloat(0f, 1f).apply {
      duration = 1500
      repeatCount = ValueAnimator.INFINITE
      interpolator = LinearInterpolator()
      addUpdateListener { animation ->
        progress = animation.animatedValue as Float
        invalidate()
      }
      start()
    }
  }

  override fun onAttachedToWindow() {
    super.onAttachedToWindow()
    if (active) restart()
  }

  override fun onDetachedFromWindow() {
    animator?.cancel()
    animator = null
    super.onDetachedFromWindow()
  }

  override fun onDraw(canvas: Canvas) {
    if (!active || width <= 0 || height <= 0) return
    val band = height * 0.5f
    if (shader == null) {
      val clear = Color.argb(0, Color.red(bandColor), Color.green(bandColor), Color.blue(bandColor))
      shader = LinearGradient(0f, 0f, 0f, band, intArrayOf(clear, bandColor, clear),
        floatArrayOf(0f, 0.5f, 1f), Shader.TileMode.CLAMP)
      paint.shader = shader
    }
    val y = -band + (height + band) * progress
    shift.setTranslate(0f, y)
    shader?.setLocalMatrix(shift)
    canvas.drawRect(0f, y, width.toFloat(), y + band, paint)
  }
}

/** Placeholder lines for an answer that has not started to arrive. */
internal class SkeletonView(context: Context, private val track: Int, private val glint: Int) : View(context) {
  private val barPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = track }
  private val glintPaint = Paint(Paint.ANTI_ALIAS_FLAG)
  private val bars = floatArrayOf(0.94f, 0.82f, 0.6f)
  private val path = Path()
  private val shift = Matrix()
  private var shader: LinearGradient? = null
  private var progress = 0f
  private var animator: ValueAnimator? = null

  override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
    setMeasuredDimension(MeasureSpec.getSize(widthMeasureSpec), dp(52))
  }

  override fun onAttachedToWindow() {
    super.onAttachedToWindow()
    if (!animationsEnabled()) return
    animator = ValueAnimator.ofFloat(0f, 1f).apply {
      duration = 1400
      repeatCount = ValueAnimator.INFINITE
      interpolator = LinearInterpolator()
      addUpdateListener { animation ->
        progress = animation.animatedValue as Float
        invalidate()
      }
      start()
    }
  }

  override fun onDetachedFromWindow() {
    animator?.cancel()
    animator = null
    super.onDetachedFromWindow()
  }

  override fun onDraw(canvas: Canvas) {
    val w = width.toFloat()
    if (w <= 0f) return
    val barHeight = dpf(11f)
    val gap = dpf(9f)
    path.reset()
    bars.forEachIndexed { index, fraction ->
      val top = index * (barHeight + gap)
      path.addRoundRect(RectF(0f, top, w * fraction, top + barHeight), barHeight / 2, barHeight / 2, Path.Direction.CW)
    }
    canvas.drawPath(path, barPaint)
    if (!animationsEnabled()) return
    val band = w * 0.42f
    if (shader == null) {
      val clear = Color.argb(0, Color.red(glint), Color.green(glint), Color.blue(glint))
      shader = LinearGradient(0f, 0f, band, 0f, intArrayOf(clear, glint, clear),
        floatArrayOf(0f, 0.5f, 1f), Shader.TileMode.CLAMP)
      glintPaint.shader = shader
    }
    val x = -band + (w + band) * progress
    shift.setTranslate(x, 0f)
    shader?.setLocalMatrix(shift)
    canvas.save()
    canvas.clipPath(path)
    canvas.drawRect(x, 0f, x + band, height.toFloat(), glintPaint)
    canvas.restore()
  }
}

/**
 * The little picture of the page that was scanned. While research runs a light
 * passes over it, so the reader sees which page the words are about.
 */
internal class ScanThumb(context: Context, private val ui: KrikoUi, private val fonts: KrikoFonts) : FrameLayout(context) {
  private val picture = ImageView(context).apply { scaleType = ImageView.ScaleType.CENTER_CROP }
  private val sweep = SweepView(context, KrikoColor.tint(KrikoTheme.ON_ACCENT, 0.55f))
  private val letter = TextView(context).apply {
    text = "K"
    setTextColor(KrikoTheme.ON_ACCENT)
    textSize = 19f
    typeface = fonts.semiBold
    includeFontPadding = false
    gravity = Gravity.CENTER
  }

  init {
    val p = ui.palette
    background = KrikoDraw.shape(context, p.accent, 11, KrikoColor.tint(KrikoTheme.ON_ACCENT, 0.22f))
    clipToOutline = true
    outlineProvider = KrikoDraw.roundOutline(context, 11)
    addView(letter, LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
    addView(picture, LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
    addView(sweep, LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
    picture.visibility = View.GONE
  }

  fun setBitmap(bitmap: Bitmap?) {
    if (bitmap == null) {
      picture.setImageDrawable(null)
      picture.visibility = View.GONE
    } else {
      picture.setImageBitmap(bitmap)
      picture.visibility = View.VISIBLE
    }
  }

  fun setActive(value: Boolean) = sweep.setActive(value)
}

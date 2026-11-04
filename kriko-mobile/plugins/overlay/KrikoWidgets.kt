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
 * The answer sheet's frame. It is a window the reader can move, resize and
 * swipe away:
 *
 *  - dragging the header row moves the whole window (the owner applies x/y);
 *  - dragging the top handle down makes the sheet follow the finger and fills
 *    the close indicator; past [CLOSE_DP] or a fast downward flick it closes,
 *    otherwise it springs back. Dragging it up still folds it into the puck;
 *  - horizontal drags on the handle move the window instead of dismissing it;
 *  - the body keeps its scroll: a swipe there scrolls it first, and only once it
 *    reaches an end does the same finger take the sheet.
 */
internal class SwipeSheet(context: Context) : FrameLayout(context) {
  /** The sheet was swiped up; the owner folds it into the puck. */
  var onMinimize: (() -> Unit)? = null
  /** The sheet was swiped down; the owner closes it. */
  var onClose: (() -> Unit)? = null
  /** A finger took hold: stop any entrance animation so the two do not fight. */
  var onGrab: (() -> Unit)? = null
  /** The header is dragging: the owner moves the window by these raw deltas. */
  var onMoveDrag: ((dx: Float, dy: Float) -> Unit)? = null
  /** The header drag ended: the owner re-checks what the moved window covers. */
  var onMoveEnd: (() -> Unit)? = null
  /** How far a drag-down has come, 0..1, and whether a finger is holding it. */
  var onSwipeProgress: ((fraction: Float, active: Boolean) -> Unit)? = null
  /** The sheet is pulled down by its window (not translated), by this many px. */
  var onDismissDrag: ((offset: Float) -> Unit)? = null
  /** The drag-down ended below its threshold: put the window back where it was. */
  var onDismissSettle: (() -> Unit)? = null
  /** The bottom-right corner is dragged: the owner resizes the window. */
  var onResizeStart: (() -> Unit)? = null
  var onResizeDrag: ((dx: Float, dy: Float) -> Unit)? = null
  var onResizeEnd: (() -> Unit)? = null
  /** The scrolling part, so a swipe that starts on it can be left to it. */
  var body: ScrollView? = null
  /** The header row: the window's move handle. */
  var header: View? = null
  /** The top handle with chevron and hint: the swipe-close/fold target. */
  var handle: View? = null
  /** The resize grip; its own touch listener owns it, so gestures leave it alone. */
  var grip: View? = null

  /** Everything the sheet shows; the owner adds its rows here. */
  val content = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }

  private enum class Mode { NONE, MOVE, FOLD, CLOSE, RESIZE }
  private enum class Zone { BODY, HEADER, HANDLE, GRIP, RESIZE }

  private val slop = android.view.ViewConfiguration.get(context).scaledTouchSlop
  private var downX = 0f
  private var downY = 0f
  private var mode = Mode.NONE
  private var zone = Zone.BODY
  private var dismissOffset = 0f
  private var multiTouchRejected = false
  private var tracker: android.view.VelocityTracker? = null

  init {
    addView(content, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
  }

  override fun onInterceptTouchEvent(event: MotionEvent): Boolean {
    when (event.actionMasked) {
      MotionEvent.ACTION_DOWN -> {
        if (event.pointerCount != 1) {
          resetGesture()
          multiTouchRejected = true
          return false
        }
        startGesture(event)
      }
      MotionEvent.ACTION_MOVE -> {
        if (event.pointerCount != 1) {
          resetGesture()
          multiTouchRejected = true
          return false
        }
        if (multiTouchRejected) return false
        tracker?.addMovement(event)
        if (mode == Mode.NONE) beginGesture(event)
        if (mode != Mode.NONE) {
          parent?.requestDisallowInterceptTouchEvent(true)
          return true
        }
      }
      MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
        if (mode != Mode.NONE) {
          finishGesture(event, event.actionMasked == MotionEvent.ACTION_UP)
          return true
        }
        release()
      }
      MotionEvent.ACTION_POINTER_DOWN -> {
        resetGesture()
        multiTouchRejected = true
      }
    }
    return false
  }

  override fun onTouchEvent(event: MotionEvent): Boolean {
    // A touch that starts on a bare part of the sheet (the handle, the header, the
    // padding) has no child to take it, so the intercept hook never sees its later
    // events: claim it here, or the gesture is lost after the first contact.
    if (event.actionMasked == MotionEvent.ACTION_DOWN) {
      if (event.pointerCount != 1) {
        resetGesture()
        return false
      }
      if (tracker == null) startGesture(event)
      return true
    }
    if (event.actionMasked == MotionEvent.ACTION_POINTER_DOWN || event.pointerCount != 1) {
      resetGesture()
      multiTouchRejected = true
      return false
    }
    tracker?.addMovement(event)
    if (mode == Mode.NONE) {
      if (event.actionMasked == MotionEvent.ACTION_MOVE) beginGesture(event)
      if (mode == Mode.NONE) {
        if (event.actionMasked == MotionEvent.ACTION_UP || event.actionMasked == MotionEvent.ACTION_CANCEL) release()
        return super.onTouchEvent(event)
      }
    }
    when (event.actionMasked) {
      MotionEvent.ACTION_MOVE -> applyGesture(event)
      MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL ->
        finishGesture(event, event.actionMasked == MotionEvent.ACTION_UP)
    }
    return true
  }

  private fun startGesture(event: MotionEvent) {
    downX = event.rawX
    downY = event.rawY
    mode = Mode.NONE
    zone = zoneAt(event)
    tracker?.recycle()
    tracker = android.view.VelocityTracker.obtain().also { it.addMovement(event) }
  }

  /** Once the finger has crossed the slop, decide what this gesture is for. */
  private fun beginGesture(event: MotionEvent) {
    val dy = event.rawY - downY
    val dx = event.rawX - downX
    val mostlyVertical = kotlin.math.abs(dy) > kotlin.math.abs(dx) * 1.3f
    when (zone) {
      Zone.HEADER -> {
        mode = Mode.MOVE
        onGrab?.invoke()
      }
      Zone.HANDLE -> {
        if (!mostlyVertical) {
          mode = Mode.MOVE
          onGrab?.invoke()
        } else if (dy < 0f) {
          mode = Mode.FOLD
          onGrab?.invoke()
        } else {
          mode = Mode.CLOSE
          onGrab?.invoke()
        }
      }
      Zone.BODY -> {
        if (mostlyVertical && dy < 0f && (!isInsideBody(event) || isAtScrollEndUnder(event))) {
          mode = Mode.FOLD
          onGrab?.invoke()
        } else if (mostlyVertical && dy > 0f && (!isInsideBody(event) || isAtScrollTopUnder(event))) {
          mode = Mode.CLOSE
          onGrab?.invoke()
        }
      }
      Zone.GRIP -> Unit
      Zone.RESIZE -> {
        mode = Mode.RESIZE
        onGrab?.invoke()
        onResizeStart?.invoke()
      }
    }
    if (mode == Mode.NONE) return
    // The body may have scrolled under this same finger. Start from the boundary,
    // not from the original down point, so the sheet begins smoothly.
    downX = event.rawX
    downY = event.rawY
    translationY = 0f
    alpha = 1f
    tracker?.recycle()
    tracker = android.view.VelocityTracker.obtain().also { it.addMovement(event) }
    dismissOffset = 0f
    if (mode == Mode.CLOSE) onSwipeProgress?.invoke(0f, true)
  }

  private fun applyGesture(event: MotionEvent) {
    val dy = event.rawY - downY
    when (mode) {
      Mode.MOVE -> onMoveDrag?.invoke(event.rawX - downX, dy)
      Mode.FOLD -> {
        val offset = dy.coerceAtMost(0f)
        translationY = offset
        alpha = (1f + offset / (height * 0.85f).coerceAtLeast(1f)).coerceIn(0.3f, 1f)
      }
      Mode.CLOSE -> {
        // The window itself follows the finger, so the handle and its progress
        // line stay visible instead of being clipped by the sheet's own frame.
        dismissOffset = dy.coerceAtLeast(0f)
        onDismissDrag?.invoke(dismissOffset)
        onSwipeProgress?.invoke((dismissOffset / dp(CLOSE_DP)).coerceIn(0f, 1f), true)
      }
      Mode.RESIZE -> onResizeDrag?.invoke(event.rawX - downX, dy)
      Mode.NONE -> Unit
    }
  }

  private fun finishGesture(event: MotionEvent, released: Boolean) {
    tracker?.computeCurrentVelocity(1000)
    val velocity = tracker?.yVelocity ?: 0f
    val finished = mode
    mode = Mode.NONE
    release()
    when (finished) {
      Mode.MOVE -> {
        translationY = 0f
        alpha = 1f
        onMoveEnd?.invoke()
      }
      Mode.FOLD -> {
        val fold = released && (translationY < -dp(FOLD_DP) || velocity < -dp(FOLD_VELOCITY_DP))
        if (fold) onMinimize?.invoke() else springBack()
      }
      Mode.CLOSE -> {
        val close = released && (dismissOffset > dp(CLOSE_DP) || velocity > dp(CLOSE_VELOCITY_DP))
        if (close) (onClose ?: onMinimize)?.invoke() else onDismissSettle?.invoke()
      }
      Mode.RESIZE -> onResizeEnd?.invoke()
      Mode.NONE -> Unit
    }
    dismissOffset = 0f
    onSwipeProgress?.invoke(0f, false)
  }

  /** Back to rest, instantly when the reader asked the phone to remove animations. */
  private fun springBack() {
    if (!animationsEnabled()) {
      translationY = 0f
      alpha = 1f
      return
    }
    animate().translationY(0f).alpha(1f).setDuration(220L)
      .setInterpolator(android.view.animation.OvershootInterpolator(1.1f)).start()
  }

  private fun resetGesture() {
    val finished = mode
    mode = Mode.NONE
    translationY = 0f
    alpha = 1f
    dismissOffset = 0f
    onSwipeProgress?.invoke(0f, false)
    release()
    when (finished) {
      Mode.MOVE -> onMoveEnd?.invoke()
      Mode.CLOSE -> onDismissSettle?.invoke()
      Mode.RESIZE -> onResizeEnd?.invoke()
      else -> Unit
    }
  }

  private fun zoneAt(event: MotionEvent): Zone {
    // A hit on the grip itself is owned by the grip's own touch listener; the
    // corner zone below is the safety net for the same corner of the window, so
    // resizing still works if a touch ever slips past the grip's frame.
    if (isInside(grip, event)) return Zone.GRIP
    if (isInsideResizeCorner(event)) return Zone.RESIZE
    if (isInside(handle, event)) return Zone.HANDLE
    if (isInside(header, event)) return Zone.HEADER
    return Zone.BODY
  }

  /** The bottom-right square of the window: the resize affordance's area. */
  private fun isInsideResizeCorner(event: MotionEvent): Boolean {
    if (width <= 0 || height <= 0) return false
    val corner = dp(RESIZE_CORNER_DP).toFloat()
    return event.x >= width - corner && event.y >= height - corner &&
      event.x <= width && event.y <= height
  }

  private fun isInside(view: View?, event: MotionEvent): Boolean {
    val target = view ?: return false
    if (!target.isShown || target.width <= 0 || target.height <= 0) return false
    // Tested in this sheet's own coordinates (event.x/y), not with raw screen
    // coordinates: an overlay window's screen origin is exactly what used to
    // make the corner grip's hit area disagree with where its glyph is drawn.
    return pointInSheet(target, event.x, event.y)
  }

  /** Whether a point in this sheet's coordinates falls inside `target`'s frame. */
  private fun pointInSheet(target: View, xInSheet: Float, yInSheet: Float): Boolean {
    var x = 0f
    var y = 0f
    var node: View = target
    while (node !== this) {
      x += node.left + node.translationX
      y += node.top + node.translationY
      node = node.parent as? View ?: return false
    }
    return xInSheet >= x && xInSheet < x + target.width &&
      yInSheet >= y && yInSheet < y + target.height
  }

  /** Whether the finger is over the scroll body's own area (not the frame around it). */
  private fun isInsideBody(event: MotionEvent): Boolean {
    val scroller = body ?: return false
    if (!scroller.isShown) return false
    return isInside(scroller, event)
  }

  private fun isAtScrollEndUnder(event: MotionEvent): Boolean {
    val scroller = body ?: return true
    if (!scroller.isShown || scroller.canScrollVertically(1)) return false
    return isInside(scroller, event)
  }

  private fun isAtScrollTopUnder(event: MotionEvent): Boolean {
    val scroller = body ?: return true
    if (!scroller.isShown || scroller.canScrollVertically(-1)) return false
    return isInside(scroller, event)
  }

  private fun release() {
    tracker?.recycle()
    tracker = null
  }

  private companion object {
    /** Drag-down distance that closes instead of springing back. */
    const val CLOSE_DP = 88
    /** Drag-down speed (dp/s) that closes on its own. */
    const val CLOSE_VELOCITY_DP = 1000
    /** Drag-up distance that folds the sheet into the puck. */
    const val FOLD_DP = 44
    /** Drag-up speed (dp/s) that folds on its own. */
    const val FOLD_VELOCITY_DP = 900
    /** The bottom-right square of the sheet that starts a resize. */
    const val RESIZE_CORNER_DP = 72
  }
}

/**
 * A scroll view that stops growing at a cap, so the buttons below it stay on
 * screen. Once the reader resizes the sheet it fills the space left instead,
 * which is the same view under a different measure spec.
 */
internal class CappedScroll(context: Context, private var capPx: Int) : ScrollView(context) {
  /** True once the sheet has an explicit height: the body takes the remainder. */
  var fill: Boolean = false

  fun setCap(value: Int) {
    if (capPx == value) return
    capPx = value
    requestLayout()
  }

  override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
    if (fill) {
      super.onMeasure(widthMeasureSpec, heightMeasureSpec)
    } else {
      super.onMeasure(widthMeasureSpec, View.MeasureSpec.makeMeasureSpec(capPx, View.MeasureSpec.AT_MOST))
    }
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

/**
 * The sheet's top handle: a short grabber, a chevron pointing down, and a
 * progress line that fills as the reader drags the sheet down to close it. The
 * chevron deepens and the fill brightens with the drag, so the gesture explains
 * itself before the reader has let go.
 */
internal class SheetDragIndicator(context: Context, private val accent: Int, private val ink: Int) : View(context) {
  private val grabberPaint = Paint(Paint.ANTI_ALIAS_FLAG)
  private val chevronPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    style = Paint.Style.STROKE
    strokeCap = Paint.Cap.ROUND
    strokeJoin = Paint.Join.ROUND
  }
  private val trackPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    style = Paint.Style.STROKE
    strokeCap = Paint.Cap.ROUND
  }
  private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    style = Paint.Style.STROKE
    strokeCap = Paint.Cap.ROUND
  }
  private val chevron = Path()
  private var progress = 0f
  private var active = false

  /** `0..1` how far the drag-down has come; `dragging` while a finger holds it. */
  fun setProgress(value: Float, dragging: Boolean) {
    val next = value.coerceIn(0f, 1f)
    if (next == progress && dragging == active) return
    progress = next
    active = dragging
    invalidate()
  }

  override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
    setMeasuredDimension(MeasureSpec.getSize(widthMeasureSpec), dp(24))
  }

  override fun onDraw(canvas: Canvas) {
    val w = width.toFloat()
    val h = height.toFloat()
    if (w <= 0f) return
    val cx = w / 2f

    grabberPaint.color = ink
    grabberPaint.alpha = (56f + 64f * progress).toInt().coerceIn(0, 255)
    val barWidth = dpf(36f)
    val barHeight = dpf(3.5f)
    canvas.drawRoundRect(cx - barWidth / 2f, dpf(2f), cx + barWidth / 2f, dpf(2f) + barHeight,
      barHeight / 2f, barHeight / 2f, grabberPaint)

    chevronPaint.color = accent
    chevronPaint.alpha = (110f + 130f * progress).toInt().coerceIn(0, 255)
    chevronPaint.strokeWidth = dpf(1.7f)
    val top = dpf(9f) + dpf(2f) * progress
    chevron.reset()
    chevron.moveTo(cx - dpf(4.6f), top)
    chevron.lineTo(cx, top + dpf(3.6f))
    chevron.lineTo(cx + dpf(4.6f), top)
    canvas.drawPath(chevron, chevronPaint)

    val lineY = h - dpf(1.6f)
    val pad = dpf(20f)
    trackPaint.color = ink
    trackPaint.alpha = 34
    trackPaint.strokeWidth = dpf(1.6f)
    canvas.drawLine(pad, lineY, w - pad, lineY, trackPaint)
    if (progress > 0.002f) {
      fillPaint.color = accent
      fillPaint.alpha = (170f + 85f * progress).toInt().coerceIn(0, 255)
      fillPaint.strokeWidth = dpf(2.2f)
      val half = (w / 2f - pad) * progress
      canvas.drawLine(cx - half, lineY, cx + half, lineY, fillPaint)
    }
  }
}

/**
 * The sheet's bottom-right resize grip: two rails and an accent dot, enough to
 * say "this corner grows the window" without a label the reader must read.
 *
 * The view is deliberately larger than the glyph (the caller gives it 44x44dp)
 * so the corner is comfortable to grab; it is clickable and focusable and sits
 * above the content, so a drag on it is a resize and never a scroll.
 */
internal class SheetResizeGrip(context: Context, private val ink: Int, private val accent: Int) : View(context) {
  private val railPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    style = Paint.Style.STROKE
    strokeCap = Paint.Cap.ROUND
  }
  private val dotPaint = Paint(Paint.ANTI_ALIAS_FLAG)

  init {
    isClickable = true
    isFocusable = true
    elevation = dpf(1f)
  }

  override fun onDraw(canvas: Canvas) {
    val w = width.toFloat()
    val h = height.toFloat()
    if (w <= 0f || h <= 0f) return
    // The glyph stays small and anchored to the corner, even though the touch
    // target is the whole view.
    val inset = dpf(8f)
    val long = dpf(18f)
    railPaint.color = ink
    railPaint.strokeWidth = dpf(1.4f)
    canvas.drawLine(w - inset, h - inset, w - inset - long, h - inset, railPaint)
    canvas.drawLine(w - inset, h - inset, w - inset, h - inset - long, railPaint)
    val short = long * 0.5f
    canvas.drawLine(w - inset - dpf(5f), h - inset, w - inset - dpf(5f), h - inset - short, railPaint)
    dotPaint.color = accent
    dotPaint.alpha = 190
    canvas.drawCircle(w - inset - dpf(2f), h - inset - dpf(2f), dpf(1.7f), dotPaint)
  }
}

/**
 * A LED-dot matrix sweep: "working" without a percentage nobody can know. Two
 * thin rows of dots carry a short bright head and tail; with animations turned
 * off the dots rest in place.
 */
internal class IndeterminateBar(context: Context, track: Int, private val fill: Int) : View(context) {
  private val trackPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    color = track
    style = Paint.Style.STROKE
    strokeCap = Paint.Cap.ROUND
  }
  private val dotPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = fill }
  private var phase = 0f
  private var animator: ValueAnimator? = null

  override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
    val height = if (MeasureSpec.getMode(heightMeasureSpec) == MeasureSpec.EXACTLY) {
      MeasureSpec.getSize(heightMeasureSpec)
    } else {
      dp(6)
    }
    setMeasuredDimension(MeasureSpec.getSize(widthMeasureSpec), height)
  }

  override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
    super.onSizeChanged(w, h, oldw, oldh)
    syncMotion()
  }

  override fun onVisibilityChanged(changedView: View, visibility: Int) {
    super.onVisibilityChanged(changedView, visibility)
    if (changedView === this) syncMotion()
  }

  override fun onWindowVisibilityChanged(visibility: Int) {
    super.onWindowVisibilityChanged(visibility)
    syncMotion()
  }

  override fun onAttachedToWindow() {
    super.onAttachedToWindow()
    syncMotion()
  }

  private fun syncMotion() {
    animator?.cancel()
    animator = null
    if (!isAttachedToWindow || visibility != View.VISIBLE || !isShown || width <= 0) {
      invalidate()
      return
    }
    if (!animationsEnabled()) {
      phase = 0f
      invalidate()
      return
    }
    animator = ValueAnimator.ofFloat(0f, 1f).apply {
      duration = 1150L
      repeatCount = ValueAnimator.INFINITE
      interpolator = LinearInterpolator()
      addUpdateListener { animation ->
        phase = animation.animatedValue as Float
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
    val h = height.toFloat()
    if (w <= 0f || h <= 0f) return
    val margin = dpf(2f)
    val usable = (w - margin * 2f).coerceAtLeast(1f)
    val centerY = h / 2f
    trackPaint.strokeWidth = dpf(1f)
    trackPaint.alpha = 120
    canvas.drawLine(margin, centerY, w - margin, centerY, trackPaint)

    val spacing = dpf(7f)
    val count = ((usable / spacing).toInt()).coerceIn(1, 64)
    val travel = if (count > 1) (usable - spacing) / (count - 1) else 0f
    val rows = if (h >= dpf(6f)) 2 else 1
    val radius = minOf(dpf(1.3f), h / 4.5f)
    dotPaint.color = fill
    for (i in 0 until count) {
      val x = margin + i * travel
      val p = (x - margin) / usable
      val behind = ((phase - p) % 1f + 1f) % 1f
      // Only the head and a short tail are lit; the rest of the matrix rests.
      val strength = if (behind > 0.45f) 0f else {
        val lit = 1f - behind / 0.45f
        lit * lit
      }
      for (row in 0 until rows) {
        val y = if (rows == 1) centerY else centerY + (if (row == 0) -dpf(1.4f) else dpf(1.4f))
        dotPaint.alpha = (28f + 214f * strength).toInt().coerceIn(0, 255)
        canvas.drawCircle(x, y, radius, dotPaint)
      }
    }
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

/** Compact activity rhythm. It indicates work, never a fabricated percentage. */
internal class ResearchPulseView(context: Context, color: Int) : View(context) {
  private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color = color }
  private var phase = 0f
  private var animator: ValueAnimator? = null

  private fun syncMotion() {
    animator?.cancel()
    animator = null
    if (!isAttachedToWindow || windowVisibility != View.VISIBLE || !isShown || !animationsEnabled()) return
    animator = ValueAnimator.ofFloat(0f, 1f).apply {
      duration = 1300L
      repeatCount = ValueAnimator.INFINITE
      interpolator = LinearInterpolator()
      addUpdateListener { phase = it.animatedValue as Float; invalidate() }
      start()
    }
  }
  override fun onMeasure(w: Int, h: Int) { setMeasuredDimension(MeasureSpec.getSize(w), dp(32)) }
  override fun onAttachedToWindow() { super.onAttachedToWindow(); syncMotion() }
  override fun onWindowVisibilityChanged(visibility: Int) { super.onWindowVisibilityChanged(visibility); syncMotion() }
  override fun onVisibilityChanged(changedView: View, visibility: Int) { super.onVisibilityChanged(changedView, visibility); syncMotion() }
  override fun onDetachedFromWindow() { animator?.cancel(); animator = null; super.onDetachedFromWindow() }
  override fun onDraw(canvas: Canvas) {
    val top = (height - dpf(19f)) / 2f
    paint.strokeWidth = dpf(1f)
    for (i in 0..2) {
      val x = dpf(((phase * 30f + i * 13f) % 54f) - 8f)
      paint.alpha = (190f - i * 35f).roundToInt()
      paint.style = Paint.Style.STROKE
      canvas.drawRoundRect(x, top, x + dpf(13f), top + dpf(19f), dpf(3f), dpf(3f), paint)
      canvas.drawLine(x + dpf(3f), top + dpf(6f), x + dpf(10f), top + dpf(6f), paint)
      canvas.drawLine(x + dpf(3f), top + dpf(10f), x + dpf(8f), top + dpf(10f), paint)
    }
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
  private val sweep = SweepView(context, KrikoColor.tint(ui.palette.onAccent, 0.55f))
  private val letter = TextView(context).apply {
    text = "K"
    setTextColor(ui.palette.onAccent)
    textSize = 19f
    typeface = fonts.semiBold
    includeFontPadding = false
    gravity = Gravity.CENTER
  }

  init {
    val p = ui.palette
    background = KrikoDraw.shape(context, p.accent, 11, KrikoColor.tint(p.onAccent, 0.22f))
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

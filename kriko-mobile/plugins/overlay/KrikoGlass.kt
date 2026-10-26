package __PACKAGE__.overlay

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ColorFilter
import android.graphics.ColorMatrix
import android.graphics.ColorMatrixColorFilter
import android.graphics.LinearGradient
import android.graphics.Outline
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.RadialGradient
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.drawable.Drawable
import android.view.View
import kotlin.math.max

/**
 * The Kriko mark: the K with its tab. It is the first outline of the brand
 * wordmark in `src/assets/logoPaths.ts` (the other outlines are the letters
 * R, I, K and O), kept here as data so the floating button wears the same logo
 * as the app.
 */
internal object KrikoLogo {
  private const val OUTLINE =
    "M23.33 1.94L21.17 4.73L20.67 6.12L16.50 11.39L16.00 11.27L15.17 9.35L9.67 9.35L9.02 9.83L8.50 22.66" +
    "L3.83 22.67L3.50 18.17L2.50 17.83L1.13 18.00L0.93 29.33L1.50 30.01L3.50 29.70L3.64 25.67L4.00 25.06" +
    "L8.49 25.17L9.00 38.17L14.50 38.39L15.54 37.83L15.91 36.17L16.50 35.95L23.17 45.78L30.67 45.87" +
    "L31.39 45.50L31.30 45.17L17.83 25.67L18.50 24.94L26.17 24.94L26.96 25.33L27.50 26.72L32.47 26.33" +
    "L32.49 21.67L32.17 21.27L27.50 21.11L26.96 22.50L26.33 22.88L18.50 22.90L17.54 22.50L31.40 2.50L30.50 1.91Z"

  private val points: FloatArray by lazy { parse(OUTLINE) }
  private val minX: Float by lazy { (0 until points.size / 2).minOf { points[it * 2] } }
  private val maxX: Float by lazy { (0 until points.size / 2).maxOf { points[it * 2] } }
  private val minY: Float by lazy { (0 until points.size / 2).minOf { points[it * 2 + 1] } }
  private val maxY: Float by lazy { (0 until points.size / 2).maxOf { points[it * 2 + 1] } }

  /** Width over height of the mark. */
  val aspect: Float get() = (maxX - minX) / (maxY - minY)

  /** Fill `into` with the mark, fitted and centred in the box. */
  fun fit(into: Path, centerX: Float, centerY: Float, height: Float) {
    val scale = height / (maxY - minY)
    val width = (maxX - minX) * scale
    val left = centerX - width / 2f
    val top = centerY - height / 2f
    into.reset()
    for (index in 0 until points.size / 2) {
      val x = left + (points[index * 2] - minX) * scale
      val y = top + (points[index * 2 + 1] - minY) * scale
      if (index == 0) into.moveTo(x, y) else into.lineTo(x, y)
    }
    into.close()
  }

  /** The outline is only `M`, `L` and `Z` with absolute numbers. */
  private fun parse(text: String): FloatArray {
    val numbers = ArrayList<Float>()
    var index = 0
    while (index < text.length) {
      val c = text[index]
      if (c.isDigit() || c == '.' || c == '-') {
        val start = index
        index += 1
        while (index < text.length && (text[index].isDigit() || text[index] == '.')) index += 1
        numbers.add(text.substring(start, index).toFloat())
      } else {
        index += 1
      }
    }
    return numbers.toFloatArray()
  }
}

/** The Kriko mark as a small view, for the menu header and the assistant card. */
internal class LogoMarkView(context: Context, private var color: Int) : View(context) {
  private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
  private val path = Path()

  fun setColor(value: Int) {
    color = value
    invalidate()
  }

  override fun onDraw(canvas: Canvas) {
    val w = width.toFloat()
    val h = height.toFloat()
    if (w <= 0f || h <= 0f) return
    KrikoLogo.fit(path, w / 2f, h / 2f, kotlin.math.min(h, w / KrikoLogo.aspect))
    paint.color = color
    canvas.drawPath(path, paint)
  }
}

/**
 * A heavily blurred copy of the page the reader just scanned. The answer sheet
 * and the menu sit in front of that same page, so frosting them with it reads as
 * glass without any live blur (which Android only offers to whole windows, with
 * square corners).
 */
internal object KrikoBackdrop {
  @Volatile var bitmap: Bitmap? = null
    private set

  fun update(source: Bitmap) {
    try {
      var current = source
      var owned = false
      // Halve until it is small: a single big step would alias instead of blur.
      while (current.width > 180) {
        val next = Bitmap.createScaledBitmap(current, max(2, current.width / 2), max(2, current.height / 2), true)
        if (owned) current.recycle()
        current = next
        owned = true
      }
      // A mutable copy to blur in place; it is a few hundred pixels wide.
      val small = current.copy(Bitmap.Config.ARGB_8888, true) ?: return
      if (owned) current.recycle()
      boxBlur(small, 2)
      boxBlur(small, 2)
      // A little extra colour: glass should carry the page's hues through.
      val vivid = Bitmap.createBitmap(small.width, small.height, Bitmap.Config.ARGB_8888)
      val matrix = ColorMatrix().apply { setSaturation(1.35f) }
      Canvas(vivid).drawBitmap(small, 0f, 0f, Paint().apply { colorFilter = ColorMatrixColorFilter(matrix) })
      small.recycle()
      // The old copy is left to the collector: a window may be drawing it right now.
      bitmap = vivid
    } catch (_: Throwable) {
      // No backdrop is a plainer glass, never a failed scan.
    }
  }

  private fun boxBlur(source: Bitmap, radius: Int) {
    val w = source.width
    val h = source.height
    val pixels = IntArray(w * h)
    source.getPixels(pixels, 0, w, 0, 0, w, h)
    val out = IntArray(w * h)
    // Horizontal, then vertical.
    for (y in 0 until h) {
      for (x in 0 until w) {
        var r = 0; var g = 0; var b = 0; var n = 0
        for (k in -radius..radius) {
          val xx = (x + k).coerceIn(0, w - 1)
          val p = pixels[y * w + xx]
          r += Color.red(p); g += Color.green(p); b += Color.blue(p); n += 1
        }
        out[y * w + x] = Color.rgb(r / n, g / n, b / n)
      }
    }
    for (y in 0 until h) {
      for (x in 0 until w) {
        var r = 0; var g = 0; var b = 0; var n = 0
        for (k in -radius..radius) {
          val yy = (y + k).coerceIn(0, h - 1)
          val p = out[yy * w + x]
          r += Color.red(p); g += Color.green(p); b += Color.blue(p); n += 1
        }
        pixels[y * w + x] = Color.rgb(r / n, g / n, b / n)
      }
    }
    source.setPixels(pixels, 0, w, 0, 0, w, h)
  }
}

/**
 * Paints one pane of liquid glass: a tinted body whose see-through-ness is the
 * reader's own setting, a soft light across its top, a bright lens spot in the
 * corner, and a rim that is bright where light would hit and dark where it
 * would not. Used by the floating button, the menu and the answer sheet, so
 * they all read as one material.
 */
internal class GlassPainter(private val density: Float) {
  private val body = Paint(Paint.ANTI_ALIAS_FLAG)
  private val sheen = Paint(Paint.ANTI_ALIAS_FLAG)
  private val lens = Paint(Paint.ANTI_ALIAS_FLAG)
  private val rimPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
  private val shade = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
  private val backdropPaint = Paint(Paint.FILTER_BITMAP_FLAG or Paint.ANTI_ALIAS_FLAG)
  private val clip = Path()
  private val screen = RectF()
  private var lastW = -1f
  private var lastH = -1f
  private var lastDark = true

  /**
   * @param tint the colour of the glass body
   * @param alpha how much of the body shows, `0..1`; the rest is the page behind
   * @param dark glass over a dark surface carries a faint white film; over a light one a bright one
   * @param backdrop draws the frosted page first (clipped to this pane); null for none
   */
  fun draw(
    canvas: Canvas,
    rect: RectF,
    radius: Float,
    tint: Int,
    alpha: Float,
    dark: Boolean,
    backdrop: ((Canvas) -> Unit)? = null,
  ) {
    val a = alpha.coerceIn(0f, 1f)
    if (rect.width() != lastW || rect.height() != lastH || dark != lastDark) build(rect, dark)

    if (backdrop != null) {
      canvas.save()
      clip.reset()
      clip.addRoundRect(rect, radius, radius, Path.Direction.CW)
      canvas.clipPath(clip)
      backdrop(canvas)
      canvas.restore()
    }

    body.color = tint
    body.alpha = (255 * a).toInt()
    canvas.drawRoundRect(rect, radius, radius, body)
    // Glass is never perfectly flat: the light and lens fade with the body but
    // keep enough to read even when the body is nearly clear.
    val k = 0.45f + 0.55f * a
    sheen.alpha = (255 * k).toInt()
    canvas.drawRoundRect(rect, radius, radius, sheen)
    lens.alpha = (255 * k).toInt()
    canvas.drawRoundRect(rect, radius, radius, lens)

    val half = density * 0.6f
    val inset = RectF(rect.left + half, rect.top + half, rect.right - half, rect.bottom - half)
    shade.alpha = (255 * (0.30f + 0.20f * a)).toInt()
    canvas.drawRoundRect(inset, radius - half, radius - half, shade)
    rimPaint.alpha = (255 * (0.55f + 0.45f * a)).toInt()
    canvas.drawRoundRect(inset, radius - half, radius - half, rimPaint)
  }

  private fun build(rect: RectF, dark: Boolean) {
    lastW = rect.width()
    lastH = rect.height()
    lastDark = dark
    val w = rect.width()
    val h = rect.height()
    val film = if (dark) 0.18f else 0.62f
    sheen.shader = LinearGradient(
      rect.left, rect.top, rect.left, rect.bottom,
      intArrayOf(
        Color.argb((255 * film).toInt(), 255, 255, 255),
        Color.argb((255 * film * 0.22f).toInt(), 255, 255, 255),
        Color.argb(0, 255, 255, 255),
      ),
      floatArrayOf(0f, 0.38f, 1f), Shader.TileMode.CLAMP,
    )
    val glow = if (dark) 0.26f else 0.7f
    lens.shader = RadialGradient(
      rect.left + w * 0.26f, rect.top + h * 0.10f, max(w, h) * 0.62f,
      intArrayOf(Color.argb((255 * glow).toInt(), 255, 255, 255), Color.argb(0, 255, 255, 255)),
      null, Shader.TileMode.CLAMP,
    )
    rimPaint.strokeWidth = density * 1.3f
    rimPaint.shader = LinearGradient(
      rect.left, rect.top, rect.right, rect.bottom,
      intArrayOf(
        Color.argb(235, 255, 255, 255),
        Color.argb(if (dark) 46 else 120, 255, 255, 255),
        Color.argb(if (dark) 150 else 215, 255, 255, 255),
      ),
      floatArrayOf(0f, 0.52f, 1f), Shader.TileMode.CLAMP,
    )
    shade.strokeWidth = density * 1.3f
    shade.shader = LinearGradient(
      rect.left, rect.bottom, rect.right, rect.top,
      intArrayOf(
        Color.argb(if (dark) 120 else 60, 0, 0, 0),
        Color.argb(0, 0, 0, 0),
        Color.argb(if (dark) 70 else 30, 0, 0, 0),
      ),
      floatArrayOf(0f, 0.5f, 1f), Shader.TileMode.CLAMP,
    )
  }

  /** The frosted page, positioned so it lines up with the real page behind the pane. */
  fun frosted(view: View): ((Canvas) -> Unit)? {
    val picture = KrikoBackdrop.bitmap ?: return null
    return { canvas ->
      val where = IntArray(2)
      view.getLocationOnScreen(where)
      val metrics = view.resources.displayMetrics
      screen.set(0f, 0f, metrics.widthPixels.toFloat(), metrics.heightPixels.toFloat())
      canvas.save()
      canvas.translate(-where[0].toFloat(), -where[1].toFloat())
      canvas.drawBitmap(picture, null, screen, backdropPaint)
      canvas.restore()
    }
  }
}

/**
 * A window background of liquid glass. `strength` is read on every draw, so the
 * reader's transparency setting reaches a window that is already open.
 */
internal class GlassDrawable(
  context: Context,
  private val radiusDp: Float,
  private val tint: () -> Int,
  private val strength: () -> Float,
  private val dark: () -> Boolean,
  private val frosted: Boolean,
) : Drawable() {
  private val density = context.resources.displayMetrics.density
  private val painter = GlassPainter(density)
  private val rect = RectF()
  private var host: View? = null

  fun attach(view: View): GlassDrawable {
    host = view
    return this
  }

  override fun draw(canvas: Canvas) {
    val bounds = bounds
    if (bounds.width() <= 0 || bounds.height() <= 0) return
    rect.set(bounds)
    val view = host
    val backdrop = if (frosted && view != null) painter.frosted(view) else null
    painter.draw(canvas, rect, radiusDp * density, tint(), strength(), dark(), backdrop)
  }

  override fun getOutline(outline: Outline) {
    outline.setRoundRect(Rect(bounds), radiusDp * density)
    outline.alpha = 0f
  }

  override fun setAlpha(alpha: Int) = Unit
  override fun setColorFilter(colorFilter: ColorFilter?) = Unit
  @Deprecated("Deprecated in Java")
  override fun getOpacity(): Int = PixelFormat.TRANSLUCENT
}

/**
 * How the reader's transparency choice (`KrikoUi.puckOpacity`, 20..100 percent)
 * reaches each surface. Every surface keeps its own floor, so choosing "Faint"
 * never makes the answer hard to read.
 */
internal object KrikoGlassLevel {
  /** The floating button: the setting itself. */
  fun puck(ui: KrikoUi): Float = ui.puckOpacity

  /** The menu: clearer than the answer, never less than half there. */
  fun menu(ui: KrikoUi): Float = 0.52f + 0.44f * span(ui)

  /** The answer sheet: it carries paragraphs, so it stays mostly body. */
  fun sheet(ui: KrikoUi): Float = 0.66f + 0.30f * span(ui)

  private fun span(ui: KrikoUi): Float = ((ui.puckOpacity - 0.2f) / 0.8f).coerceIn(0f, 1f)

  /** Dark glass for the dark palette, bright glass for the light ones. */
  fun isDark(palette: Palette): Boolean = palette === KrikoTheme.DARK

  /** The body colour: a deep neutral for dark glass, the paper tone for light. */
  fun body(palette: Palette): Int = if (isDark(palette)) 0xFF0C0E14.toInt() else palette.panel

  /** The shade of the buttons that sit on glass: see-through, never solid grey. */
  fun chip(palette: Palette): Int = KrikoColor.tint(palette.ink, if (isDark(palette)) 0.10f else 0.07f)
}

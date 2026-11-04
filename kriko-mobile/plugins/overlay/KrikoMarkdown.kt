package __PACKAGE__.overlay

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.net.Uri
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.TextPaint
import android.text.method.LinkMovementMethod
import android.text.style.BackgroundColorSpan
import android.text.style.ClickableSpan
import android.text.style.ForegroundColorSpan
import android.text.style.MetricAffectingSpan
import android.text.style.ReplacementSpan
import android.text.style.StyleSpan
import android.text.style.TypefaceSpan
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONArray
import java.util.Locale

/** The only links the scanner will open: plain http(s) with a host and no credentials. */
internal fun safeHttpUrl(value: String): String {
  val url = Uri.parse(value.trim())
  val scheme = url.scheme?.lowercase()
  if (scheme != "http" && scheme != "https") return ""
  if (url.host.isNullOrBlank() || !url.userInfo.isNullOrBlank()) return ""
  return url.toString()
}

internal enum class MdKind { LEAD, PARAGRAPH, HEADING, LABEL, BULLET, NUMBER, QUOTE, RULE }

/** One visual block of an answer. Equal blocks render to equal views. */
internal data class MdBlock(val kind: MdKind, val text: String, val ordinal: Int = 0, val level: Int = 0)

/**
 * Markdown, read as the handful of shapes a short answer uses: a lead
 * sentence, headings, bold-only lines acting as labels, bullets, numbered
 * steps, quotes and rules. Anything else is a paragraph. It never throws and
 * never drops text: an unknown shape is shown as it was written.
 */
internal object KrikoMarkdown {
  private val HEADING = Regex("^#{1,4}\\s+(.+?)\\s*#*$")
  private val BULLET = Regex("^(\\s*)[-*•]\\s+(.+)$")
  private val NUMBER = Regex("^(\\s*)(\\d{1,2})[.)]\\s+(.+)$")
  private val QUOTE = Regex("^>\\s?(.*)$")
  private val RULE = Regex("^\\s*([-*_])(\\s*\\1){2,}\\s*$")
  private val BOLD_ONLY = Regex("^\\*\\*([^*]+)\\*\\*\\s*:?$")
  private val TABLE_SEPARATOR = Regex("^\\|?\\s*:?-{2,}:?(\\s*\\|\\s*:?-{2,}:?)*\\s*\\|?$")

  fun parse(markdown: String): List<MdBlock> {
    val blocks = ArrayList<MdBlock>()
    var inTable = false
    for (raw in markdown.replace("\r\n", "\n").split("\n")) {
      val line = raw.trimEnd()
      val trimmed = line.trim()
      if (trimmed.isEmpty()) {
        inTable = false
        continue
      }
      if (trimmed.startsWith("|")) {
        if (TABLE_SEPARATOR.matches(trimmed)) continue
        val cells = trimmed.trim('|').split('|').map { it.trim() }.filter { it.isNotEmpty() }
        if (cells.isEmpty()) continue
        blocks.add(MdBlock(if (inTable) MdKind.BULLET else MdKind.LABEL, cells.joinToString("  ·  ")))
        inTable = true
        continue
      }
      inTable = false
      val heading = HEADING.matchEntire(trimmed)
      val quote = QUOTE.matchEntire(trimmed)
      val bullet = BULLET.matchEntire(line)
      val number = NUMBER.matchEntire(line)
      val boldOnly = BOLD_ONLY.matchEntire(trimmed)
      when {
        RULE.matches(trimmed) -> blocks.add(MdBlock(MdKind.RULE, ""))
        heading != null -> blocks.add(MdBlock(MdKind.HEADING, heading.groupValues[1]))
        quote != null -> blocks.add(MdBlock(MdKind.QUOTE, quote.groupValues[1]))
        bullet != null -> blocks.add(MdBlock(MdKind.BULLET, bullet.groupValues[2].trim(),
          level = if (bullet.groupValues[1].length >= 2) 1 else 0))
        number != null -> blocks.add(MdBlock(MdKind.NUMBER, number.groupValues[3].trim(),
          ordinal = number.groupValues[2].toIntOrNull() ?: 0))
        boldOnly != null -> blocks.add(MdBlock(MdKind.LABEL, boldOnly.groupValues[1].trim().trimEnd(':')))
        else -> blocks.add(MdBlock(MdKind.PARAGRAPH, trimmed))
      }
    }
    if (blocks.isNotEmpty() && blocks[0].kind == MdKind.PARAGRAPH) {
      blocks[0] = blocks[0].copy(kind = MdKind.LEAD)
    }
    return blocks
  }

  /** The same answer without markdown, for the clipboard. */
  fun plain(markdown: String): String {
    val out = StringBuilder()
    for (block in parse(markdown)) {
      val text = stripInline(block.text)
      when (block.kind) {
        MdKind.HEADING, MdKind.LABEL -> {
          if (out.isNotEmpty()) out.append('\n')
          out.append(text).append('\n')
        }
        MdKind.BULLET -> out.append(if (block.level > 0) "    - " else "- ").append(text).append('\n')
        MdKind.NUMBER -> out.append(block.ordinal).append(". ").append(text).append('\n')
        MdKind.QUOTE -> out.append("> ").append(text).append('\n')
        MdKind.RULE -> out.append('\n')
        else -> out.append(text).append('\n')
      }
    }
    return out.toString().trim()
  }

  private fun stripInline(text: String): String = text
    .replace(Regex("\\[([^\\]\\n]+)]\\((https?://[^\\s)]+)\\)")) { "${it.groupValues[1]} (${it.groupValues[2]})" }
    .replace(Regex("\\*\\*(.+?)\\*\\*"), "$1")
    .replace(Regex("__(.+?)__"), "$1")
    .replace(Regex("`([^`\\n]+)`"), "$1")
    .replace(Regex("(?<![*\\w])\\*([^*\\n]+)\\*(?![*\\w])"), "$1")
}

/** Sets a typeface on a span of text, so a bold run uses the app's own bold face. */
internal class FontSpan(private val face: Typeface) : MetricAffectingSpan() {
  override fun updateDrawState(paint: TextPaint) { paint.typeface = face }
  override fun updateMeasureState(paint: TextPaint) { paint.typeface = face }
}

/** A tappable run. `styled` links get the accent colour; citation chips draw their own. */
internal class LinkSpan(
  private val url: String,
  private val color: Int,
  private val face: Typeface?,
  private val styled: Boolean,
  private val open: (String) -> Unit,
) : ClickableSpan() {
  override fun onClick(widget: View) = open(url)

  override fun updateDrawState(ds: TextPaint) {
    ds.isUnderlineText = false
    if (styled) {
      ds.color = color
      if (face != null) ds.typeface = face
    }
  }
}

/** A source number drawn as a small rounded chip: `[2]` becomes a tappable 2. */
internal class CitationSpan(
  private val fill: Int,
  private val ink: Int,
  private val density: Float,
  private val face: Typeface,
) : ReplacementSpan() {
  private fun chipPaint(source: Paint) = Paint(source).apply {
    textSize = source.textSize * 0.76f
    typeface = face
    color = ink
  }

  override fun getSize(paint: Paint, text: CharSequence, start: Int, end: Int, fm: Paint.FontMetricsInt?): Int {
    val chip = chipPaint(paint)
    return (chip.measureText(text, start, end) + 10 * density + 3 * density).toInt()
  }

  override fun draw(
    canvas: Canvas, text: CharSequence, start: Int, end: Int,
    x: Float, top: Int, bottom: Int, y: Int, paint: Paint,
  ) {
    val chip = chipPaint(paint)
    val width = chip.measureText(text, start, end) + 10 * density
    val height = chip.textSize * 1.5f
    val centre = y + (paint.ascent() + paint.descent()) / 2f
    val box = RectF(x + 2 * density, centre - height / 2f, x + 2 * density + width, centre + height / 2f)
    val background = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = fill }
    canvas.drawRoundRect(box, height / 2f, height / 2f, background)
    val baseline = centre - (chip.ascent() + chip.descent()) / 2f
    chip.textAlign = Paint.Align.CENTER
    canvas.drawText(text, start, end, box.centerX(), baseline, chip)
  }
}

/** Turns one line of inline markdown into styled, tappable text. */
internal class KrikoInline(
  private val ui: KrikoUi,
  private val fonts: KrikoFonts,
  private val density: Float,
  private val sources: Map<String, String>,
  private val open: (String) -> Unit,
) {
  private val token = Regex(
    "\\*\\*(.+?)\\*\\*|__(.+?)__|`([^`\\n]+)`|\\[([^\\]\\n]+)]\\((https?://[^\\s)]+)\\)|\\[(\\d{1,2})]|(?<![*\\w])\\*([^*\\n]+)\\*(?![*\\w])",
  )

  fun build(text: String): SpannableStringBuilder = SpannableStringBuilder().also { append(it, text, 0) }

  private fun append(out: SpannableStringBuilder, text: String, depth: Int) {
    if (depth >= 2) {
      out.append(text)
      return
    }
    val p = ui.palette
    var cursor = 0
    for (match in token.findAll(text)) {
      if (match.range.first > cursor) out.append(text, cursor, match.range.first)
      cursor = match.range.last + 1
      val start = out.length
      val groups = match.groups
      when {
        groups[1] != null || groups[2] != null -> {
          append(out, (groups[1] ?: groups[2])!!.value, depth + 1)
          out.setSpan(FontSpan(fonts.semiBold), start, out.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }
        groups[3] != null -> {
          out.append(groups[3]!!.value)
          out.setSpan(TypefaceSpan("monospace"), start, out.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
          out.setSpan(BackgroundColorSpan(KrikoColor.tint(p.ink, 0.10f)), start, out.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }
        groups[4] != null -> {
          val label = groups[4]!!.value
          val url = safeHttpUrl(groups[5]!!.value)
          out.append(label)
          if (url.isNotBlank()) {
            out.setSpan(LinkSpan(url, p.accentHi, fonts.medium, true, open), start, out.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
          }
        }
        groups[6] != null -> {
          val number = groups[6]!!.value
          val url = sources[number]
          if (url == null) {
            out.append("[").append(number).append("]")
          } else {
            out.append(number)
            out.setSpan(CitationSpan(KrikoColor.tint(p.accent, if (p === KrikoTheme.DARK) 0.30f else 0.14f), p.accentHi, density, fonts.semiBold),
              start, out.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            out.setSpan(LinkSpan(url, p.accentHi, null, false, open), start, out.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
          }
        }
        groups[7] != null -> {
          append(out, groups[7]!!.value, depth + 1)
          out.setSpan(StyleSpan(Typeface.ITALIC), start, out.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }
      }
    }
    if (cursor < text.length) out.append(text, cursor, text.length)
  }
}

/**
 * Draws an answer as stacked blocks rather than one wall of text, and updates
 * a streaming answer by changing only the blocks that changed, so text that is
 * still arriving does not flicker or lose the reader's scroll position.
 */
internal class KrikoAnswer(
  private val context: Context,
  private val ui: KrikoUi,
  private val fonts: KrikoFonts,
  private val open: (String) -> Unit,
) {
  private var rendered: List<MdBlock> = emptyList()
  private var renderedSources = ""
  private val views = ArrayList<View>()

  fun render(box: LinearLayout, markdown: String, sources: JSONArray) {
    val map = sourceMap(sources)
    val signature = map.toString()
    val blocks = KrikoMarkdown.parse(markdown)
    if (box.childCount != views.size) {
      box.removeAllViews()
      views.clear()
      rendered = emptyList()
    }
    var common = 0
    if (signature == renderedSources) {
      while (common < blocks.size && common < rendered.size && blocks[common] == rendered[common]) common++
    }
    while (views.size > common) box.removeView(views.removeAt(views.lastIndex))
    val inline = KrikoInline(ui, fonts, context.resources.displayMetrics.density, map, open)
    for (index in common until blocks.size) {
      val view = blockView(blocks[index], inline)
      box.addView(view)
      views.add(view)
    }
    rendered = blocks
    renderedSources = signature
  }

  private fun sourceMap(sources: JSONArray): Map<String, String> {
    val map = LinkedHashMap<String, String>()
    for (index in 0 until sources.length()) {
      val source = sources.optJSONObject(index) ?: continue
      val number = source.optString("n")
      val url = safeHttpUrl(source.optString("url"))
      if (number.isNotBlank() && url.isNotBlank()) map[number] = url
    }
    return map
  }

  private fun row(topDp: Int, view: View): View {
    view.layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
      .apply { topMargin = context.dp(topDp) }
    return view
  }

  private fun text(
    value: CharSequence, sizeSp: Float, color: Int, face: Typeface, extraLineDp: Float,
  ) = TextView(context).apply {
    text = value
    setTextColor(color)
    setTextSize(TypedValue.COMPLEX_UNIT_SP, sizeSp)
    typeface = face
    includeFontPadding = false
    setLineSpacing(context.dpf(extraLineDp), 1f)
    setLinkTextColor(ui.palette.accentHi)
    movementMethod = LinkMovementMethod.getInstance()
    highlightColor = Color.TRANSPARENT
  }

  private fun blockView(block: MdBlock, inline: KrikoInline): View {
    val p = ui.palette
    return when (block.kind) {
      MdKind.LEAD -> row(2, text(inline.build(block.text), 16f, p.ink, fonts.regular, 4.5f))
      MdKind.PARAGRAPH -> row(9, text(inline.build(block.text), 14.5f, p.ink, fonts.regular, 3.5f))
      MdKind.HEADING -> row(18, LinearLayout(context).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        addView(View(context).apply { background = KrikoDraw.shape(context, p.accent, 2) },
          LinearLayout.LayoutParams(context.dp(3), context.dp(16)).apply { marginEnd = context.dp(9) })
        addView(text(inline.build(block.text), 15.5f, p.ink, fonts.semiBold, 2f),
          LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
      })
      MdKind.LABEL -> row(16, text(
        SpannableStringBuilder(block.text.uppercase(Locale.getDefault())), 11f, p.ink3, fonts.semiBold, 1f,
      ).apply { letterSpacing = 0.08f })
      MdKind.BULLET -> row(8, LinearLayout(context).apply {
        orientation = LinearLayout.HORIZONTAL
        setPadding(context.dp(if (block.level > 0) 16 else 2), 0, 0, 0)
        addView(View(context).apply { background = KrikoDraw.circle(if (block.level > 0) p.ink3 else p.accentHi) },
          LinearLayout.LayoutParams(context.dp(5), context.dp(5)).apply {
            topMargin = context.dp(8)
            marginEnd = context.dp(11)
          })
        addView(text(inline.build(block.text), 14.5f, p.ink, fonts.regular, 3.5f),
          LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
      })
      MdKind.NUMBER -> row(9, LinearLayout(context).apply {
        orientation = LinearLayout.HORIZONTAL
        addView(TextView(context).apply {
          text = block.ordinal.toString()
          setTextColor(p.accentHi)
          setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
          typeface = fonts.semiBold
          includeFontPadding = false
          gravity = Gravity.CENTER
          background = KrikoDraw.shape(context, KrikoColor.tint(p.accent, if (p === KrikoTheme.DARK) 0.26f else 0.12f), 7)
        }, LinearLayout.LayoutParams(context.dp(22), context.dp(22)).apply {
          topMargin = context.dp(0)
          marginEnd = context.dp(10)
        })
        addView(text(inline.build(block.text), 14.5f, p.ink, fonts.regular, 3.5f),
          LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
      })
      MdKind.QUOTE -> row(9, LinearLayout(context).apply {
        orientation = LinearLayout.HORIZONTAL
        addView(View(context).apply { background = KrikoDraw.shape(context, KrikoColor.tint(p.accent, 0.7f), 2) },
          LinearLayout.LayoutParams(context.dp(3), ViewGroup.LayoutParams.MATCH_PARENT).apply { marginEnd = context.dp(11) })
        addView(text(inline.build(block.text), 14f, p.ink2, fonts.regular, 3.5f).apply { setTypeface(typeface, Typeface.ITALIC) },
          LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
      })
      MdKind.RULE -> row(14, View(context).apply { setBackgroundColor(p.edge) }).apply {
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 1).apply { topMargin = context.dp(14) }
      }
    }
  }
}

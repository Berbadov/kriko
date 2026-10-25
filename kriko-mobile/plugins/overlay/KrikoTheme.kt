package __PACKAGE__.overlay

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import org.json.JSONObject
import kotlin.math.roundToInt

/** One resolved palette; the values mirror `src/theme/palettes.ts`. */
internal data class Palette(
  val ground: Int,
  val panel: Int,
  val raised: Int,
  val edge: Int,
  val ink: Int,
  val ink2: Int,
  val ink3: Int,
  val accent: Int,
  val accentHi: Int,
  val risk: Int,
  val riskWash: Int,
  val ok: Int,
)

/**
 * The three palettes the app can resolve to, and the English words every native
 * window starts with. Every value mirrors `src/theme/palettes.ts`: dark, paper
 * and white. There is no fourth, hardcoded dark panel hiding anywhere.
 */
internal object KrikoTheme {
  const val ON_ACCENT = 0xFFFFFFFF.toInt()

  val DARK = Palette(
    ground = 0xFF000000.toInt(),
    panel = 0xFF111111.toInt(),
    raised = 0xFF1A1A1A.toInt(),
    edge = 0x26FFFFFF,
    ink = 0xFFF5F5F5.toInt(),
    ink2 = 0xFFB8B8B8.toInt(),
    ink3 = 0xFF989898.toInt(),
    accent = 0xFF3562E9.toInt(),
    accentHi = 0xFF99B1FF.toInt(),
    risk = 0xFFFF6B7A.toInt(),
    riskWash = 0x24FF6B7A,
    ok = 0xFF3DDC97.toInt(),
  )
  val PAPER = Palette(
    ground = 0xFFF4F0E6.toInt(),
    panel = 0xFFFFFDF7.toInt(),
    raised = 0xFFFAF7EF.toInt(),
    edge = 0xFFC5BDAD.toInt(),
    ink = 0xFF24231F.toInt(),
    ink2 = 0xFF5D5A52.toInt(),
    ink3 = 0xFF78756D.toInt(),
    accent = 0xFF2E5BEF.toInt(),
    accentHi = 0xFF2E5BEF.toInt(),
    risk = 0xFFB74739.toInt(),
    riskWash = 0xFFF6E7DF.toInt(),
    ok = 0xFF39735B.toInt(),
  )
  val WHITE = Palette(
    ground = 0xFFF7F8FA.toInt(),
    panel = 0xFFFFFFFF.toInt(),
    raised = 0xFFFFFFFF.toInt(),
    edge = 0xFFC8CDD4.toInt(),
    ink = 0xFF111318.toInt(),
    ink2 = 0xFF4A4F57.toInt(),
    ink3 = 0xFF6B7280.toInt(),
    accent = 0xFF2E5BEF.toInt(),
    accentHi = 0xFF2E5BEF.toInt(),
    risk = 0xFFB42318.toInt(),
    riskWash = 0xFFFDECEA.toInt(),
    ok = 0xFF1F7A54.toInt(),
  )

  fun paletteFor(name: String?): Palette = when (name) {
    "paper" -> PAPER
    "white" -> WHITE
    else -> DARK
  }

  /** English, used until the JS side sends its translated labels. */
  val DEFAULT_LABELS: Map<String, String> = linkedMapOf(
    "scan" to "Scan",
    "scanPage" to "Scan this page",
    "scanAgain" to "Scan again",
    "results" to "Results",
    "siteComments" to "Site comments",
    "queue" to "Queue",
    "stop" to "Stop",
    "now" to "Now",
    "all" to "All",
    "readSiteComments" to "Read site comments",
    "siteUrlHint" to "Review site (optional)",
    "cancel" to "Cancel",
    "close" to "Close",
    "queued" to "Queued",
    "running" to "Running",
    "reading" to "Reading",
    "done" to "Done",
    "error" to "Error",
    "cancelled" to "Cancelled",
    "productScan" to "Product scan",
    "sources" to "Sources",
    "queueFull" to "Queue is full",
    "dragHint" to "Drag Kriko, or tap it to open the scan panel",
    "notificationTitle" to "Kriko screen scan is active",
    "notificationText" to "Tap the floating K to scan one screen when you choose.",
    "stopSharing" to "Stop screen sharing",
    "channelName" to "Floating screen scan",
    "channelDescription" to "Shows when Kriko's user-started floating scan session is active.",
    "queueEmpty" to "Scan a product page. Each scan joins the queue here.",
    "answerEmpty" to "Scan a product page to see its answer and sources here.",
    "captureFailed" to "Could not read that screen. Try scanning again.",
    "sourceFailed" to "Could not open that source.",
    "copy" to "Copy",
    "copied" to "Copied",
    "scannedPage" to "Scanned page",
    "paused" to "Screen capture paused",
    "notificationPausedText" to "Screen capture stopped. Tap Scan on the floating K to start it again.",
    "resumeFailed" to "Open Kriko and start the scanner again.",
    "openingKriko" to "Opening Kriko…",
    "assistScanning" to "Scanning this screen",
    "assistNoShot" to "Kriko could not see your screen. In your phone's assistant settings, turn on “Use screenshot”.",
    "assistTitle" to "Kriko",
  )

  /** `0..100` percent from JS, as the fraction the puck draws with. Never fully invisible. */
  fun opacityFraction(percent: Int): Float = (percent.coerceIn(20, 100)) / 100f
}

/** The faces the windows draw with, copied from the Geist files the plugin ships. */
internal class KrikoFonts(private val context: Context) {
  val regular: Typeface by lazy { load("KrikoGeist-Regular", Typeface.DEFAULT) }
  val medium: Typeface by lazy { load("KrikoGeist-Medium", Typeface.DEFAULT) }
  val semiBold: Typeface by lazy { load("KrikoGeist-SemiBold", Typeface.DEFAULT_BOLD) }

  private fun load(name: String, fallback: Typeface): Typeface =
    runCatching { Typeface.createFromAsset(context.assets, "fonts/$name.ttf") }.getOrDefault(fallback)
}

/**
 * The reader's palette, words and puck opacity as the app last sent them.
 *
 * Kept on disk as well as in memory: a window the system starts (the assistant)
 * can open before JavaScript has run, and it must still speak the reader's
 * language in the reader's theme.
 */
internal class KrikoUi(private val context: Context) {
  var palette: Palette = KrikoTheme.DARK
    private set
  var puckOpacity: Float = 0.55f
    private set
  val labels: MutableMap<String, String> = LinkedHashMap(KrikoTheme.DEFAULT_LABELS)

  fun label(key: String): String = labels[key] ?: KrikoTheme.DEFAULT_LABELS[key] ?: key

  /** Read `{ theme, labels, puckOpacity }`; returns false when the text was not usable. */
  fun apply(json: String): Boolean {
    val parsed = try { JSONObject(json) } catch (_: Exception) { return false }
    if (parsed.has("theme")) palette = KrikoTheme.paletteFor(parsed.optString("theme"))
    if (parsed.has("puckOpacity")) puckOpacity = KrikoTheme.opacityFraction(parsed.optInt("puckOpacity", 55))
    val incoming = parsed.optJSONObject("labels")
    if (incoming != null) {
      for (key in KrikoTheme.DEFAULT_LABELS.keys) {
        val value = incoming.optString(key)
        if (value.isNotBlank()) labels[key] = value
      }
    }
    return true
  }

  fun save(json: String) {
    try { prefs().edit().putString(KEY, json).apply() } catch (_: Exception) { }
  }

  fun loadSaved(): KrikoUi {
    val saved = try { prefs().getString(KEY, null) } catch (_: Exception) { null }
    if (saved != null) apply(saved)
    return this
  }

  private fun prefs() = context.getSharedPreferences(FILE, Context.MODE_PRIVATE)

  private companion object {
    const val FILE = "kriko_overlay_ui"
    const val KEY = "ui"
  }
}

/** Small colour helpers shared by every native window. */
internal object KrikoColor {
  fun tint(color: Int, fraction: Float): Int = Color.argb(
    (255 * fraction).roundToInt().coerceIn(0, 255),
    Color.red(color), Color.green(color), Color.blue(color),
  )

  fun mix(color: Int, other: Int, fraction: Float): Int = Color.argb(
    Color.alpha(color),
    (Color.red(color) + (Color.red(other) - Color.red(color)) * fraction).roundToInt(),
    (Color.green(color) + (Color.green(other) - Color.green(color)) * fraction).roundToInt(),
    (Color.blue(color) + (Color.blue(other) - Color.blue(color)) * fraction).roundToInt(),
  )
}

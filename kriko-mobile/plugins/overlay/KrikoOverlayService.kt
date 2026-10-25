package __PACKAGE__.overlay

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.TimeInterpolator
import android.animation.ValueAnimator
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Outline
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.SystemClock
import android.provider.Settings
import android.text.Html
import android.text.InputType
import android.text.method.LinkMovementMethod
import android.util.Base64
import android.util.DisplayMetrics
import android.view.Display
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.ViewGroup
import android.view.ViewOutlineProvider
import android.view.WindowManager
import android.view.animation.DecelerateInterpolator
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import com.facebook.react.bridge.Arguments
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.util.WeakHashMap
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.roundToInt

/** One resolved palette; the values mirror `src/theme/palettes.ts`. */
private data class Palette(
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
 * The floating scanner, in three pieces that never cover each other:
 *
 *  - the **puck**: one round blue K the reader drags anywhere. It snaps to the
 *    nearest screen edge, dims when idle, spins a ring while research runs and
 *    carries a green count when answers are waiting;
 *  - the **tray**: tap the puck and a small card opens beside it with one big
 *    action (Scan this page), the results, and — deliberately apart — Stop;
 *  - the **sheet**: the answer, sized to its content and anchored to the bottom
 *    where a thumb reaches it, with the other scans as chips under it.
 *
 * The capture pipeline, the notification and the palette contract are those of
 * the previous capsule; only what the reader sees and touches changed.
 */
class KrikoOverlayService : Service() {
  companion object {
    const val ACTION_START = "__PACKAGE__.overlay.START"
    const val ACTION_STOP = "__PACKAGE__.overlay.STOP"
    const val ACTION_UPDATE = "__PACKAGE__.overlay.UPDATE"
    const val ACTION_UI = "__PACKAGE__.overlay.UI"
    const val ACTION_APP = "__PACKAGE__.overlay.APP"
    const val EXTRA_FOREGROUND = "foreground"
    const val EXTRA_RESULT_CODE = "resultCode"
    const val EXTRA_RESULT_DATA = "resultData"
    const val EXTRA_JOBS = "jobs"
    const val EXTRA_UI = "ui"
    private const val CHANNEL_ID = "kriko_screen_scan"
    private const val NOTIFICATION_ID = 7406
    private const val ON_ACCENT = 0xFFFFFFFF.toInt()
    /** The visible disc; the window around it leaves room for its shadow and badge. */
    private const val PUCK_DP = 54
    private const val PUCK_PAD_DP = 7
    private const val EDGE_DP = 4
    private const val TRAY_DP = 232
    private const val DIM_AFTER_MS = 4200L
    private const val DIM_ALPHA = 0.58f

    /**
     * The three palettes the app can resolve to. Every value mirrors
     * `src/theme/palettes.ts`: dark, paper and white. There is no fourth,
     * hardcoded dark panel hiding anywhere below.
     */
    private val DARK = Palette(
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
    private val PAPER = Palette(
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
    private val WHITE = Palette(
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

    /** English, used until the JS side sends its translated labels. */
    private val DEFAULT_LABELS: Map<String, String> = linkedMapOf(
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
      "notificationText" to "Tap the floating bubble to scan one screen when you choose.",
      "stopSharing" to "Stop screen sharing",
      "channelName" to "Floating screen scan",
      "channelDescription" to "Shows when Kriko's user-started floating scan session is active.",
      "queueEmpty" to "Scan a product page. Each scan joins the queue here.",
      "answerEmpty" to "Scan a product page to see its answer and sources here.",
      "captureFailed" to "Could not read that screen. Try scanning again.",
      "sourceFailed" to "Could not open that source.",
    )

    private fun paletteFor(name: String?): Palette = when (name) {
      "paper" -> PAPER
      "white" -> WHITE
      else -> DARK
    }

    @Volatile var isActive: Boolean = false
      private set
  }

  private lateinit var windowManager: WindowManager
  private var projection: MediaProjection? = null
  private var display: VirtualDisplay? = null
  private var reader: ImageReader? = null
  private var captureThread: HandlerThread? = null
  private var captureHandler: Handler? = null
  @Volatile private var capturePending = false
  @Volatile private var scanGeneration = 0
  private var shuttingDown = false
  private var jobs = JSONArray()
  private var selectedJob = ""
  /** Finished answers the reader has already looked at; the rest wear a badge. */
  private val seen = mutableSetOf<String>()

  // The puck.
  private var puck: FrameLayout? = null
  private var puckParams: WindowManager.LayoutParams? = null
  private var puckRing: RingView? = null
  private var puckBadge: TextView? = null
  private var puckSnap: ValueAnimator? = null
  private var puckYBeforeSheet: Int? = null

  // The tray.
  private var tray: View? = null
  private var trayParams: WindowManager.LayoutParams? = null
  private var trayClosedAt = 0L
  private var trayBadge: TextView? = null

  // The sheet.
  private var sheet: View? = null
  private var sheetParams: WindowManager.LayoutParams? = null
  private var sheetTitle: TextView? = null
  private var sheetStatus: TextView? = null
  private var sheetBar: View? = null
  private var sheetScroll: ScrollView? = null
  private var sheetBody: LinearLayout? = null
  private var sheetChips: LinearLayout? = null
  private var sheetChipsScroll: View? = null
  private var sheetActions: LinearLayout? = null
  private var siteUrlInput: EditText? = null
  private var siteSection: View? = null
  private var siteOpen = false
  private var answerView: TextView? = null
  private var stepView: TextView? = null
  private var renderedSignature: String? = null

  /** A UI update arrived mid-capture; apply it when the windows come back. */
  private var uiDirty = false

  /**
   * Whether Kriko's own screen is in front. The scanner floats over the reader's
   * page, so while the app itself is showing it stands down instead of sitting on
   * the app's tabs. True until JS says otherwise: a session starts from the app.
   */
  private var appForeground = true
  /** The first-run hint (the tray, open once) waits for the reader to leave the app. */
  private var hintPending = false
  private var palette: Palette = DARK
  private val labels: MutableMap<String, String> = LinkedHashMap(DEFAULT_LABELS)
  private val activeMotion = WeakHashMap<View, ValueAnimator>()
  private val gentleSpring = TimeInterpolator { input ->
    val t = input.coerceIn(0f, 1f).toDouble()
    (1.0 - exp(-8.2 * t) * cos(10.5 * t)).coerceIn(0.0, 1.08).toFloat()
  }
  private val geistRegular by lazy { runCatching { Typeface.createFromAsset(assets, "fonts/KrikoGeist-Regular.ttf") }.getOrDefault(Typeface.DEFAULT) }
  private val geistMedium by lazy { runCatching { Typeface.createFromAsset(assets, "fonts/KrikoGeist-Medium.ttf") }.getOrDefault(Typeface.DEFAULT) }
  private val geistSemiBold by lazy { runCatching { Typeface.createFromAsset(assets, "fonts/KrikoGeist-SemiBold.ttf") }.getOrDefault(Typeface.DEFAULT_BOLD) }
  @Volatile private var captureMode = "research"
  @Volatile private var reviewSite = ""
  private val mainHandler = Handler(android.os.Looper.getMainLooper())
  private val dimRunnable = Runnable { dimPuck() }
  private val projectionCallback = object : MediaProjection.Callback() {
    override fun onStop() {
      if (!shuttingDown) {
        shuttingDown = true
        releaseResources(stopProjection = false)
        isActive = false
        stopForeground(STOP_FOREGROUND_REMOVE)
        sendSession(false)
        KrikoOverlayModule.finishHeadlessSession()
        stopSelf()
      }
    }
  }

  override fun onCreate() {
    super.onCreate()
    windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
    createNotificationChannel()
  }

  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    when (intent?.action) {
      ACTION_STOP -> {
        stopSession()
        return START_NOT_STICKY
      }
      ACTION_UI -> {
        intent.getStringExtra(EXTRA_UI)?.let { applyUi(it) }
        return START_NOT_STICKY
      }
      ACTION_APP -> {
        setAppForeground(intent.getBooleanExtra(EXTRA_FOREGROUND, true))
        return START_NOT_STICKY
      }
      ACTION_UPDATE -> {
        val json = intent.getStringExtra(EXTRA_JOBS)
        if (json != null) {
          jobs = try { JSONArray(json) } catch (_: Exception) { JSONArray() }
          renderAll()
        }
        return START_NOT_STICKY
      }
      ACTION_START -> startProjection(intent)
    }
    return START_NOT_STICKY
  }

  private fun startProjection(intent: Intent) {
    if (isActive) return
    // Carry the reader's last palette and words into the very first puck.
    intent.getStringExtra(EXTRA_UI)?.let { readUi(it) }
    val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, 0)
    val data = intent.getParcelableExtra<Intent>(EXTRA_RESULT_DATA)
    if (data == null || resultCode == 0) {
      failStart("Screen capture permission data is missing. Start the session again.")
      return
    }
    try {
      startForeground(NOTIFICATION_ID, buildNotification())
      val manager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
      val currentProjection = manager.getMediaProjection(resultCode, data)
        ?: throw IllegalStateException("Android could not start the screen capture session.")
      projection = currentProjection
      currentProjection.registerCallback(projectionCallback, mainHandler)

      val bounds = displayBounds()
      val density = resources.configuration.densityDpi
      val imageReader = ImageReader.newInstance(bounds.width(), bounds.height(), PixelFormat.RGBA_8888, 2)
      reader = imageReader
      captureThread = HandlerThread("KrikoOverlayCapture").also { it.start() }
      captureHandler = Handler(captureThread!!.looper)
      imageReader.setOnImageAvailableListener({ source -> onFrameAvailable(source) }, captureHandler)

      // The surface stays detached between user scans. The projection token and
      // virtual display remain alive, but no frames are delivered or retained.
      display = currentProjection.createVirtualDisplay(
        "KrikoOnDemandScreenScan", bounds.width(), bounds.height(), density,
        DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, null, null, mainHandler,
      )
      if (!Settings.canDrawOverlays(this)) throw IllegalStateException("Overlay permission was revoked.")
      isActive = true
      showPuck()
      sendSession(true)
      KrikoOverlayModule.serviceReady()
      // Once the reader has left the app for their own page, show what to do a
      // single time, so the first thing on that screen is the button that matters.
      hintPending = true
    } catch (error: Exception) {
      failStart(error.message ?: "Could not start the screen scan session.")
    }
  }

  private fun displayBounds(): Rect {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
      return windowManager.maximumWindowMetrics.bounds
    }
    @Suppress("DEPRECATION")
    val display: Display = windowManager.defaultDisplay
    val metrics = DisplayMetrics()
    @Suppress("DEPRECATION")
    display.getRealMetrics(metrics)
    return Rect(0, 0, metrics.widthPixels, metrics.heightPixels)
  }

  private fun failStart(message: String) {
    shuttingDown = true
    releaseResources(stopProjection = true)
    isActive = false
    stopForeground(STOP_FOREGROUND_REMOVE)
    stopSelf()
    KrikoOverlayModule.serviceFailed(message)
  }

  /** One translated word, or its English default. */
  private fun L(key: String): String = labels[key] ?: DEFAULT_LABELS[key] ?: key

  // ------------------------------------------------------------------ UI feed --

  /**
   * Read `{ theme, labels }` without touching views. Called before the first
   * puck exists, so the window is built in the right palette already.
   */
  private fun readUi(json: String) {
    val parsed = try { JSONObject(json) } catch (_: Exception) { return }
    if (parsed.has("theme")) palette = paletteFor(parsed.optString("theme"))
    val incoming = parsed.optJSONObject("labels") ?: return
    for (key in DEFAULT_LABELS.keys) {
      val value = incoming.optString(key)
      if (value.isNotBlank()) labels[key] = value
    }
    // The channel is visible in Android settings; keep its name and
    // description in the reader's language as well.
    createNotificationChannel()
  }

  /** Apply a UI update to live windows, or leave it for the end of a capture. */
  private fun applyUi(json: String) {
    readUi(json)
    if (!isActive || shuttingDown) return
    if (capturePending) {
      uiDirty = true
      updateNotification()
      return
    }
    refreshUi()
  }

  /**
   * Rebuild the puck and whatever is open in the current palette and language,
   * keeping where they were and what the reader had typed.
   */
  private fun refreshUi() {
    if (!isActive || shuttingDown) return
    val trayWasOpen = tray != null
    val sheetWasOpen = sheet != null
    val keepSite = siteUrlInput?.text?.toString().orEmpty()
    val keepScroll = sheetScroll?.scrollY ?: 0
    val keepX = puckParams?.x
    val keepY = puckParams?.y
    removeTray(animated = false)
    removeSheet()
    removePuck()
    showPuck()
    val params = puckParams
    if (params != null && keepX != null && keepY != null) {
      params.x = keepX
      params.y = keepY
      try { puck?.let { windowManager.updateViewLayout(it, params) } } catch (_: Exception) { }
    }
    if (sheetWasOpen) {
      openSheet()
      siteUrlInput?.setText(keepSite)
      sheetScroll?.post { sheetScroll?.scrollTo(0, keepScroll) }
    } else if (trayWasOpen && !appForeground) {
      showTray()
    }
    hideWhileInApp()
    updateNotification()
  }

  /** Stand down while Kriko's own screen is showing; come back when it is not. */
  private fun setAppForeground(value: Boolean) {
    if (appForeground == value) return
    appForeground = value
    if (!isActive || shuttingDown) return
    if (value) {
      removeTray(animated = false)
      puck?.visibility = View.GONE
      sheet?.visibility = View.GONE
    } else if (!capturePending) {
      restoreWindows()
      if (hintPending && tray == null && sheet == null) {
        hintPending = false
        mainHandler.postDelayed({
          if (isActive && !shuttingDown && !appForeground && tray == null && sheet == null) showTray()
        }, 450)
      }
    }
  }

  /** Bring the puck (and an open sheet) back after a capture or after leaving the app. */
  private fun restoreWindows() {
    if (appForeground) return
    puck?.let { animateIn(it, 0.9f, 220L) }
    sheet?.let { animateIn(it, 0.96f, 200L) }
  }

  /** Hide whatever a rebuild just created if Kriko's own screen is in front. */
  private fun hideWhileInApp() {
    if (!appForeground) return
    puck?.visibility = View.GONE
    sheet?.visibility = View.GONE
  }

  /** Replace the ongoing notification's words and colour without touching capture. */
  private fun updateNotification() {
    if (!isActive || shuttingDown) return
    try { startForeground(NOTIFICATION_ID, buildNotification()) } catch (_: Exception) { }
  }

  private fun buildNotification(): Notification {
    val stopIntent = Intent(this, KrikoOverlayService::class.java).apply { action = ACTION_STOP }
    val pending = PendingIntent.getService(this, 7407, stopIntent,
      PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      Notification.Builder(this, CHANNEL_ID)
    } else {
      @Suppress("DEPRECATION")
      Notification.Builder(this)
    }
    return builder
      .setSmallIcon(android.R.drawable.ic_menu_camera)
      .setContentTitle(L("notificationTitle"))
      .setContentText(L("notificationText"))
      .setColor(palette.accent)
      .setOngoing(true)
      .addAction(android.R.drawable.ic_menu_close_clear_cancel, L("stopSharing"), pending)
      .build()
  }

  private fun createNotificationChannel() {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
    val channel = NotificationChannel(CHANNEL_ID, L("channelName"),
      NotificationManager.IMPORTANCE_LOW).apply {
      description = L("channelDescription")
      setShowBadge(false)
    }
    (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(channel)
  }

  // ---------------------------------------------------------------- job state --

  private fun statusOf(index: Int): String = jobs.optJSONObject(index)?.optString("status") ?: ""

  private fun isActiveStatus(status: String) =
    status == "queued" || status == "running" || status == "reading"

  private fun activeCount(): Int = (0 until jobs.length()).count { isActiveStatus(statusOf(it)) }

  private fun hasRunningJob(): Boolean = (0 until jobs.length()).any {
    val status = statusOf(it)
    status == "running" || status == "reading"
  }

  /** Finished answers nobody has opened yet. */
  private fun readyCount(): Int = (0 until jobs.length()).count { index ->
    val item = jobs.optJSONObject(index)
    item != null && item.optString("status") == "done" && !seen.contains(item.optString("id"))
  }

  /** The job the sheet shows: the reader's pick, else what is running, else the newest. */
  private fun currentJob(): JSONObject? {
    val items = (0 until jobs.length()).mapNotNull { jobs.optJSONObject(it) }
    return items.firstOrNull { it.optString("id") == selectedJob }
      ?: items.firstOrNull { isActiveStatus(it.optString("status")) }
      ?: items.firstOrNull()
  }

  /** Everything that reflects job state, refreshed whenever the jobs change. */
  private fun renderAll() {
    syncPuck()
    syncTray()
    renderSheet()
  }

  // --------------------------------------------------------------------- puck --

  /**
   * One round K. The window is the disc plus a little air for its shadow and
   * badge; the reader drags it anywhere and it settles on the nearest edge.
   */
  private fun showPuck() {
    if (puck != null || !Settings.canDrawOverlays(this)) return
    val p = palette
    val disc = FrameLayout(this).apply {
      background = puckBackground(p)
      elevation = dp(8).toFloat()
      outlineProvider = roundOutline(PUCK_DP / 2)
    }
    disc.addView(TextView(this).apply {
      text = "K"
      setTextColor(ON_ACCENT)
      textSize = 21f
      typeface = geistSemiBold
      includeFontPadding = false
      gravity = Gravity.CENTER
    }, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
    val ring = RingView(this)
    puckRing = ring
    disc.addView(ring, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))

    val root = FrameLayout(this).apply {
      clipChildren = false
      clipToPadding = false
      contentDescription = L("dragHint")
    }
    root.addView(disc, FrameLayout.LayoutParams(dp(PUCK_DP), dp(PUCK_DP)).apply {
      setMargins(dp(PUCK_PAD_DP), dp(PUCK_PAD_DP), dp(PUCK_PAD_DP), dp(PUCK_PAD_DP))
    })
    val badge = TextView(this).apply {
      setTextColor(ON_ACCENT)
      textSize = 10.5f
      typeface = geistSemiBold
      includeFontPadding = false
      gravity = Gravity.CENTER
      background = capsule(p.ok, 9, p.panel)
      minWidth = dp(18)
      setPadding(dp(5), dp(1), dp(5), dp(1))
      visibility = View.GONE
      elevation = dp(10).toFloat()
    }
    puckBadge = badge
    root.addView(badge, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(18),
      Gravity.TOP or Gravity.END).apply { setMargins(0, dp(1), dp(1), 0) })

    puck = root
    val size = dp(PUCK_DP + PUCK_PAD_DP * 2)
    val bounds = displayBounds()
    puckParams = overlayParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
      Gravity.TOP or Gravity.START).apply {
      x = bounds.width() - size - dp(EDGE_DP)
      y = dp(210)
    }
    root.alpha = 0f
    root.scaleX = 0.8f
    root.scaleY = 0.8f
    installPuckTouch(root)
    windowManager.addView(root, puckParams)
    if (appForeground) root.visibility = View.GONE else animateIn(root, 0.8f, 260L)
    syncPuck()
    scheduleDim()
  }

  private fun puckBackground(p: Palette): Drawable = GradientDrawable(
    GradientDrawable.Orientation.TOP_BOTTOM,
    intArrayOf(mix(p.accent, ON_ACCENT, 0.2f), p.accent),
  ).apply {
    shape = GradientDrawable.OVAL
    setStroke(dp(1), tint(ON_ACCENT, 0.26f))
  }

  /** Spinner ring while research runs, green count when answers are waiting. */
  private fun syncPuck() {
    val running = activeCount() > 0
    puckRing?.setRunning(running)
    val ready = readyCount()
    puckBadge?.let { badge ->
      badge.text = ready.toString()
      badge.visibility = if (ready > 0) View.VISIBLE else View.GONE
      badge.background = capsule(palette.ok, 9, palette.panel)
    }
    puck?.contentDescription = when {
      ready > 0 -> "${L("dragHint")} · ${L("results")} $ready"
      running -> "${L("dragHint")} · ${L("running")}"
      else -> L("dragHint")
    }
    if (running || ready > 0) wakePuck() else scheduleDim()
  }

  private fun wakePuck() {
    mainHandler.removeCallbacks(dimRunnable)
    val view = puck ?: return
    if (view.visibility == View.VISIBLE && view.alpha < 1f) animateView(view, 1f, 1f, 0f, 160L, spring = false)
  }

  private fun scheduleDim() {
    mainHandler.removeCallbacks(dimRunnable)
    mainHandler.postDelayed(dimRunnable, DIM_AFTER_MS)
  }

  private fun dimPuck() {
    val view = puck ?: return
    // Idle means nothing is open, nothing is running and nothing is waiting.
    if (tray != null || sheet != null || activeCount() > 0 || readyCount() > 0) return
    if (view.visibility == View.VISIBLE) animateView(view, DIM_ALPHA, 1f, 0f, 320L, spring = false)
  }

  /** Slide the puck to the nearer screen edge once the finger lets go. */
  private fun snapPuck() {
    val view = puck ?: return
    val params = puckParams ?: return
    val bounds = displayBounds()
    val width = if (view.width > 0) view.width else dp(PUCK_DP + PUCK_PAD_DP * 2)
    val left = dp(EDGE_DP)
    val right = (bounds.width() - width - dp(EDGE_DP)).coerceAtLeast(left)
    val target = if (params.x + width / 2 < bounds.width() / 2) left else right
    puckSnap?.cancel()
    if (!animationsEnabled() || target == params.x) {
      params.x = target
      try { windowManager.updateViewLayout(view, params) } catch (_: Exception) { }
      return
    }
    val from = params.x
    puckSnap = ValueAnimator.ofFloat(0f, 1f).apply {
      duration = 260
      interpolator = gentleSpring
      addUpdateListener { animation ->
        if (puck !== view) return@addUpdateListener
        params.x = (from + (target - from) * (animation.animatedValue as Float)).roundToInt()
        try { windowManager.updateViewLayout(view, params) } catch (_: Exception) { }
      }
      start()
    }
  }

  private fun installPuckTouch(view: View) {
    var downX = 0f
    var downY = 0f
    var startX = 0
    var startY = 0
    var moved = false
    val touchSlop = ViewConfiguration.get(this).scaledTouchSlop
    view.setOnTouchListener { _, event ->
      val params = puckParams ?: return@setOnTouchListener false
      when (event.actionMasked) {
        MotionEvent.ACTION_DOWN -> {
          puckSnap?.cancel()
          downX = event.rawX; downY = event.rawY
          startX = params.x; startY = params.y
          moved = false
          mainHandler.removeCallbacks(dimRunnable)
          view.alpha = 1f
          animateView(view, 1f, 0.94f, 0f, 90L, spring = true)
          true
        }
        MotionEvent.ACTION_MOVE -> {
          val dx = (event.rawX - downX).roundToInt()
          val dy = (event.rawY - downY).roundToInt()
          if (kotlin.math.abs(dx) + kotlin.math.abs(dy) > touchSlop) moved = true
          if (moved) {
            val bounds = displayBounds()
            params.x = (startX + dx).coerceIn(0, (bounds.width() - view.width).coerceAtLeast(0))
            params.y = (startY + dy).coerceIn(0, (bounds.height() - view.height).coerceAtLeast(0))
            try { windowManager.updateViewLayout(view, params) } catch (_: Exception) { }
            // A tray that stays behind while the puck moves points at nothing.
            if (tray != null) removeTray(animated = false)
          }
          true
        }
        MotionEvent.ACTION_UP -> {
          animateView(view, 1f, 1f, 0f, 160L, spring = true)
          if (moved) {
            snapPuck()
            scheduleDim()
          } else {
            view.performClick()
            onPuckTap()
          }
          true
        }
        MotionEvent.ACTION_CANCEL -> {
          animateView(view, 1f, 1f, 0f, 160L, spring = true)
          scheduleDim()
          true
        }
        else -> true
      }
    }
  }

  /** Tap: a closed tray opens; an open one closes; a sheet folds away first. */
  private fun onPuckTap() {
    if (capturePending) return
    if (sheet != null) {
      hideSheetAnimated()
      return
    }
    if (tray != null) {
      removeTray(animated = true)
      return
    }
    // The same touch that closed the tray (a tap outside it) must not reopen it.
    if (SystemClock.uptimeMillis() - trayClosedAt < 600) return
    showTray()
  }

  // --------------------------------------------------------------------- tray --

  private fun showTray() {
    val anchor = puck ?: return
    if (tray != null || appForeground) return
    val p = palette
    val width = dp(TRAY_DP)
    val card = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      background = capsule(p.panel, 22, p.edge)
      elevation = dp(16).toFloat()
      outlineProvider = roundOutline(22)
      clipToOutline = true
      setPadding(dp(10), dp(10), dp(10), dp(6))
    }
    card.addView(
      actionRow("scan", L("scanPage"), p.accent, ON_ACCENT, tint(ON_ACCENT, 0.24f), Color.TRANSPARENT, 52, 15f) {
        removeTray(animated = false)
        requestCapture("research")
      },
      LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(52)),
    )

    val results = actionRow("list", L("results"), p.raised, p.ink, tint(p.ink, 0.08f), p.edge, 46, 13.5f) {
      removeTray(animated = false)
      openSheet()
    }
    val badge = TextView(this).apply {
      setTextColor(ON_ACCENT)
      textSize = 10.5f
      typeface = geistSemiBold
      includeFontPadding = false
      gravity = Gravity.CENTER
      setPadding(dp(6), dp(1), dp(6), dp(1))
      visibility = View.GONE
    }
    trayBadge = badge
    results.addView(badge, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(18)).apply {
      marginStart = dp(8)
    })
    card.addView(results, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(46)).apply {
      topMargin = dp(8)
    })

    // Stop sits apart and quiet: ending the session is never one slip away from Scan.
    card.addView(View(this).apply { setBackgroundColor(p.edge) },
      LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 1).apply {
        topMargin = dp(10)
        marginStart = dp(4); marginEnd = dp(4)
      })
    card.addView(
      actionRow("stop", L("stopSharing"), Color.TRANSPARENT, p.risk, tint(p.risk, 0.14f), Color.TRANSPARENT, 42, 12.5f) {
        stopSession()
      },
      LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(42)).apply { topMargin = dp(2) },
    )

    val bounds = displayBounds()
    card.measure(
      View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY),
      View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED),
    )
    val height = card.measuredHeight
    val params = puckParams
    val puckWidth = if (anchor.width > 0) anchor.width else dp(PUCK_DP + PUCK_PAD_DP * 2)
    val puckCenterX = (params?.x ?: 0) + puckWidth / 2
    val opensRight = puckCenterX < bounds.width() / 2
    val gap = dp(6)
    val x = if (opensRight) (params?.x ?: 0) + puckWidth + gap
    else ((params?.x ?: 0) - width - gap).coerceAtLeast(dp(6))
    val y = ((params?.y ?: 0) - dp(8)).coerceIn(dp(24), (bounds.height() - height - dp(48)).coerceAtLeast(dp(24)))

    trayParams = overlayParams(width, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP or Gravity.START,
      WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH).apply {
      this.x = x
      this.y = y
    }
    card.setOnTouchListener { _, event ->
      if (event.action == MotionEvent.ACTION_OUTSIDE) {
        removeTray(animated = true)
        true
      } else false
    }
    card.alpha = 0f
    card.scaleX = 0.92f
    card.scaleY = 0.92f
    card.pivotX = if (opensRight) 0f else width.toFloat()
    card.pivotY = dp(26).toFloat()
    tray = card
    windowManager.addView(card, trayParams)
    animateIn(card, 0.92f, 220L)
    wakePuck()
    syncTray()
  }

  private fun syncTray() {
    val badge = trayBadge ?: return
    val ready = readyCount()
    val active = activeCount()
    val count = if (ready > 0) ready else active
    badge.visibility = if (count > 0) View.VISIBLE else View.GONE
    badge.text = count.toString()
    badge.background = capsule(if (ready > 0) palette.ok else palette.accent, 9, Color.TRANSPARENT)
  }

  private fun removeTray(animated: Boolean) {
    val view = tray ?: return
    tray = null
    trayParams = null
    trayBadge = null
    trayClosedAt = SystemClock.uptimeMillis()
    val dispose = {
      activeMotion.remove(view)?.cancel()
      try { windowManager.removeView(view) } catch (_: Exception) { }
    }
    if (animated && animationsEnabled()) {
      animateView(view, 0f, 0.94f, 0f, 140L, spring = false) { dispose() }
    } else {
      dispose()
    }
    scheduleDim()
  }

  // -------------------------------------------------------------------- sheet --

  private fun openSheet() {
    if (sheet != null) {
      renderSheet()
      return
    }
    removeTray(animated = false)
    val p = palette
    val bounds = displayBounds()
    val density = resources.displayMetrics.density
    val screenWidthDp = (bounds.width() / density).roundToInt()
    val screenHeightDp = (bounds.height() / density).roundToInt()
    val sheetWidthDp = minOf(404, screenWidthDp - 16).coerceAtLeast(240)
    // The body gives way first; header, chips and buttons always stay in reach.
    val bodyCapDp = (screenHeightDp * 0.5 - 150).toInt().coerceIn(96, 400)

    val root = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      background = capsule(p.panel, 26, p.edge)
      elevation = dp(20).toFloat()
      outlineProvider = roundOutline(26)
      clipToOutline = true
      setPadding(dp(16), dp(8), dp(16), dp(12))
    }
    root.addView(View(this).apply { background = capsule(tint(p.ink, 0.2f), 2, Color.TRANSPARENT) },
      LinearLayout.LayoutParams(dp(34), dp(4)).apply {
        gravity = Gravity.CENTER_HORIZONTAL
        bottomMargin = dp(8)
      })

    val header = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    val title = TextView(this).apply {
      setTextColor(p.ink)
      textSize = 16f
      typeface = geistSemiBold
      maxLines = 2
      ellipsize = android.text.TextUtils.TruncateAt.END
    }
    sheetTitle = title
    header.addView(title, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
    val status = TextView(this).apply {
      textSize = 11f
      typeface = geistMedium
      includeFontPadding = false
      gravity = Gravity.CENTER
      setPadding(dp(9), dp(4), dp(9), dp(4))
      visibility = View.GONE
    }
    sheetStatus = status
    header.addView(status, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
      marginStart = dp(8)
    })
    val close = TextView(this).apply {
      text = "×"
      setTextColor(p.ink2)
      textSize = 26f
      typeface = geistRegular
      includeFontPadding = false
      gravity = Gravity.CENTER
      contentDescription = L("close")
      background = capsule(Color.TRANSPARENT, 22, Color.TRANSPARENT, tint(p.ink, 0.10f))
      installPressMotion(this)
      setOnClickListener { hideSheetAnimated() }
    }
    header.addView(close, LinearLayout.LayoutParams(dp(44), dp(44)).apply { marginStart = dp(4); marginEnd = -dp(8) })
    root.addView(header)

    val bar = IndeterminateBar(this, tint(p.ink, 0.08f), p.accentHi)
    bar.visibility = View.GONE
    sheetBar = bar
    root.addView(bar, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(3)).apply {
      topMargin = dp(4)
      bottomMargin = dp(2)
    })

    val scroll = CappedScroll(this, dp(bodyCapDp)).apply {
      isFillViewport = false
      overScrollMode = View.OVER_SCROLL_NEVER
      isVerticalScrollBarEnabled = false
    }
    sheetScroll = scroll
    val body = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      setPadding(0, dp(2), 0, dp(4))
    }
    sheetBody = body
    scroll.addView(body)
    root.addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))

    val chipsRow = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    sheetChips = chipsRow
    val chipsScroll = HorizontalScrollView(this).apply {
      isHorizontalScrollBarEnabled = false
      overScrollMode = View.OVER_SCROLL_NEVER
      addView(chipsRow)
      visibility = View.GONE
    }
    sheetChipsScroll = chipsScroll
    root.addView(chipsScroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(34)).apply {
      topMargin = dp(6)
    })

    val actions = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    sheetActions = actions
    root.addView(actions, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
      topMargin = dp(8)
    })

    root.addView(buildSiteSection(p), LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))

    sheet = root
    sheetParams = overlayParams(dp(sheetWidthDp), ViewGroup.LayoutParams.WRAP_CONTENT,
      Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL).apply {
      y = dp(26)
      softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
    }
    root.alpha = 0f
    root.scaleX = 0.96f
    root.scaleY = 0.96f
    root.pivotX = (dp(sheetWidthDp) / 2).toFloat()
    root.pivotY = Float.MAX_VALUE
    windowManager.addView(root, sheetParams)
    if (appForeground) root.visibility = View.GONE else animateIn(root, 0.96f, 240L)
    keepPuckAboveSheet(screenHeightDp, bodyCapDp)
    wakePuck()
    renderedSignature = null
    renderSheet()
  }

  /** If the sheet would cover the puck, lift the puck above it until the sheet closes. */
  private fun keepPuckAboveSheet(screenHeightDp: Int, bodyCapDp: Int) {
    val params = puckParams ?: return
    val view = puck ?: return
    val bounds = displayBounds()
    // The sheet is at most its body cap plus about 250 dp of header and buttons.
    val sheetTop = bounds.height() - dp(bodyCapDp + 250 + 26)
    val puckHeight = if (view.height > 0) view.height else dp(PUCK_DP + PUCK_PAD_DP * 2)
    if (params.y + puckHeight > sheetTop) {
      puckYBeforeSheet = params.y
      params.y = (sheetTop - puckHeight - dp(6)).coerceAtLeast(dp(24))
      try { windowManager.updateViewLayout(view, params) } catch (_: Exception) { }
    }
  }

  private fun restorePuckHeight() {
    val before = puckYBeforeSheet ?: return
    puckYBeforeSheet = null
    val params = puckParams ?: return
    val view = puck ?: return
    params.y = before
    try { windowManager.updateViewLayout(view, params) } catch (_: Exception) { }
  }

  /** The quiet "Site comments" disclosure: a URL field and one button. */
  private fun buildSiteSection(p: Palette): View {
    val wrap = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    val field = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      visibility = if (siteOpen) View.VISIBLE else View.GONE
    }
    siteSection = field
    val input = EditText(this).apply {
      hint = L("siteUrlHint")
      setHintTextColor(p.ink3)
      setTextColor(p.ink)
      textSize = 13.5f
      typeface = geistRegular
      setSingleLine(true)
      inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
      background = capsule(p.raised, 12, p.edge)
      setPadding(dp(12), dp(6), dp(12), dp(6))
      isFocusable = true
      isFocusableInTouchMode = true
      setOnTouchListener { _, event ->
        if (event.action == MotionEvent.ACTION_DOWN) enableInputWindow(this)
        false
      }
      setOnClickListener { enableInputWindow(this) }
      onFocusChangeListener = View.OnFocusChangeListener { _, focused ->
        val params = sheetParams ?: return@OnFocusChangeListener
        params.flags = if (focused) {
          params.flags and WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE.inv()
        } else {
          params.flags or WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
        }
        try { sheet?.let { windowManager.updateViewLayout(it, params) } } catch (_: Exception) { }
        if (focused) post { (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager)
          .showSoftInput(this, InputMethodManager.SHOW_IMPLICIT) }
      }
    }
    siteUrlInput = input
    field.addView(input, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(44)).apply { topMargin = dp(6) })
    field.addView(
      actionRow(null, L("readSiteComments"), p.raised, p.ink, tint(p.ink, 0.08f), p.edge, 42, 13f) {
        reviewSite = siteUrlInput?.text?.toString()?.trim().orEmpty()
        clearInputFocus()
        requestCapture("site_reviews", reviewSite)
      },
      LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(42)).apply { topMargin = dp(6) },
    )

    val toggle = TextView(this).apply {
      text = "${L("siteComments")}  ${if (siteOpen) "▴" else "▾"}"
      setTextColor(p.ink3)
      textSize = 12f
      typeface = geistMedium
      includeFontPadding = false
      gravity = Gravity.CENTER_VERTICAL
      setPadding(dp(2), 0, dp(2), 0)
      background = capsule(Color.TRANSPARENT, 10, Color.TRANSPARENT, tint(p.ink, 0.08f))
      isClickable = true
      setOnClickListener {
        siteOpen = !siteOpen
        text = "${L("siteComments")}  ${if (siteOpen) "▴" else "▾"}"
        field.visibility = if (siteOpen) View.VISIBLE else View.GONE
      }
    }
    wrap.addView(toggle, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(38)).apply { topMargin = dp(4) })
    wrap.addView(field)
    return wrap
  }

  private fun renderSheet() {
    val body = sheetBody ?: return
    val item = currentJob()
    val id = item?.optString("id").orEmpty()
    val status = item?.optString("status").orEmpty()
    // Looking at a finished answer is what clears its badge.
    if (item != null && status == "done" && seen.add(id)) syncPuck()

    val signature = buildString {
      append(id).append('|').append(status).append('|')
      append(item?.optString("title").orEmpty()).append('|')
      append(item?.optString("error").orEmpty()).append('|')
      append(item?.optJSONArray("sources")?.length() ?: 0).append('|')
      append(item?.optString("text").orEmpty().isNotBlank()).append('|')
      append(item?.optJSONArray("steps")?.length()?.let { it > 0 } ?: false).append('|')
      for (index in 0 until jobs.length()) {
        val other = jobs.optJSONObject(index) ?: continue
        append(other.optString("id")).append(':').append(other.optString("status")).append(':')
          .append(other.optString("title")).append(';')
      }
    }
    if (signature == renderedSignature) {
      updateLiveViews(item)
      return
    }
    renderedSignature = signature
    val p = palette
    val priorScroll = sheetScroll?.scrollY ?: 0

    sheetTitle?.text = item?.optString("title")?.ifBlank { L("productScan") } ?: "Kriko"
    val active = isActiveStatus(status)
    sheetBar?.visibility = if (active) View.VISIBLE else View.GONE
    sheetStatus?.let { chip ->
      if (status.isBlank()) {
        chip.visibility = View.GONE
      } else {
        val color = when (status) {
          "done" -> p.ok
          "error", "cancelled" -> p.risk
          else -> p.accentHi
        }
        chip.text = statusLabel(status)
        chip.setTextColor(color)
        chip.background = capsule(tint(color, 0.14f), 11, Color.TRANSPARENT)
        chip.visibility = View.VISIBLE
      }
    }

    body.removeAllViews()
    answerView = null
    stepView = null
    if (item == null) {
      body.addView(bodyText(L("answerEmpty"), 13.5f, p.ink2))
    } else {
      val steps = item.optJSONArray("steps") ?: JSONArray()
      val latestStep = if (steps.length() > 0) steps.optJSONObject(steps.length() - 1) else null
      if (latestStep != null && (status == "running" || status == "reading")) {
        val view = bodyText(latestStep.optString("text"), 12.5f, p.ink2)
        stepView = view
        body.addView(view)
      }
      val error = item.optString("error")
      if (error.isNotBlank()) body.addView(errorText(error))
      val answer = item.optString("text")
      if (answer.isNotBlank()) {
        val view = answerText(answer, item.optJSONArray("sources") ?: JSONArray())
        answerView = view
        body.addView(view)
      }
      addSources(body, item.optJSONArray("sources") ?: JSONArray())
    }

    renderChips()
    renderActions(active, id)
    sheetScroll?.post { sheetScroll?.scrollTo(0, priorScroll) }
  }

  /** Streaming text and the latest step change far more often than the layout does. */
  private fun updateLiveViews(item: JSONObject?) {
    if (item == null) return
    answerView?.let { view ->
      view.text = Html.fromHtml(
        markdownHtml(item.optString("text"), item.optJSONArray("sources") ?: JSONArray()),
        Html.FROM_HTML_MODE_COMPACT,
      )
    }
    val steps = item.optJSONArray("steps") ?: JSONArray()
    val latest = if (steps.length() > 0) steps.optJSONObject(steps.length() - 1) else null
    stepView?.let { view -> setProgressText(view, latest?.optString("text").orEmpty()) }
  }

  private fun setProgressText(view: TextView, text: String) {
    if (view.text.toString() == text) return
    view.text = text
    if (!animationsEnabled()) return
    view.alpha = minOf(view.alpha, 0.84f)
    animateView(view, 1f, 1f, 0f, 135L, spring = false)
  }

  /** Other scans, as chips; hidden while there is only one. */
  private fun renderChips() {
    val row = sheetChips ?: return
    row.removeAllViews()
    val items = (0 until minOf(jobs.length(), 12)).mapNotNull { jobs.optJSONObject(it) }
    sheetChipsScroll?.visibility = if (items.size > 1) View.VISIBLE else View.GONE
    if (items.size <= 1) return
    val current = currentJob()?.optString("id").orEmpty()
    for (item in items) row.addView(jobChip(item, item.optString("id") == current))
  }

  private fun jobChip(item: JSONObject, selected: Boolean): View {
    val p = palette
    val id = item.optString("id")
    val dot = when (item.optString("status")) {
      "done" -> p.ok
      "error", "cancelled" -> p.risk
      else -> p.accentHi
    }
    val raw = item.optString("title").ifBlank { L("productScan") }
    val label = if (raw.length > 24) raw.take(23).trimEnd() + "…" else raw
    return LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
      background = capsule(if (selected) p.raised else Color.TRANSPARENT, 17,
        if (selected) p.accent else p.edge, tint(p.ink, 0.08f))
      setPadding(dp(11), 0, dp(13), 0)
      contentDescription = raw
      isClickable = true
      installPressMotion(this)
      setOnClickListener {
        selectedJob = id
        renderedSignature = null
        renderSheet()
      }
      addView(View(this@KrikoOverlayService).apply { background = circle(dot) },
        LinearLayout.LayoutParams(dp(7), dp(7)).apply { marginEnd = dp(7) })
      addView(TextView(this@KrikoOverlayService).apply {
        text = label
        setTextColor(if (selected) p.ink else p.ink2)
        textSize = 12.5f
        typeface = geistMedium
        includeFontPadding = false
        maxLines = 1
      })
      layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(34)).apply { marginEnd = dp(6) }
    }
  }

  private fun renderActions(active: Boolean, id: String) {
    val row = sheetActions ?: return
    val p = palette
    row.removeAllViews()
    row.addView(
      actionRow("scan", L(if (jobs.length() == 0) "scanPage" else "scanAgain"), p.accent, ON_ACCENT,
        tint(ON_ACCENT, 0.24f), Color.TRANSPARENT, 46, 14f) {
        requestCapture("research")
      },
      LinearLayout.LayoutParams(0, dp(46), 1f),
    )
    if (active && id.isNotBlank()) {
      row.addView(
        actionRow(null, L("cancel"), p.riskWash, p.risk, tint(p.risk, 0.16f), Color.TRANSPARENT, 46, 13.5f) {
          emitAction("cancel", id)
        },
        LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(46)).apply { marginStart = dp(8) },
      )
    }
  }

  /** The clickable sources under an answer, headed by the translated word. */
  private fun addSources(card: LinearLayout, sources: JSONArray) {
    val rows = mutableListOf<Pair<String, String>>()
    for (index in 0 until minOf(sources.length(), 5)) {
      val source = sources.optJSONObject(index) ?: continue
      val url = safeHttpUrl(source.optString("url"))
      if (url.isBlank()) continue
      val label = source.optString("title").ifBlank { source.optString("host").ifBlank { url } }
      rows.add(url to label)
    }
    if (rows.isEmpty()) return
    card.addView(sectionText(L("sources")))
    for ((url, label) in rows) card.addView(sourceRow(label, url))
  }

  private fun hideSheetAnimated() {
    val target = sheet ?: return
    cancelSheetFocus()
    animateView(target, 0f, 0.96f, dp(6).toFloat(), 170L, spring = false) {
      if (sheet === target) removeSheet()
    }
    restorePuckHeight()
    scheduleDim()
  }

  private fun cancelSheetFocus() {
    if (siteUrlInput?.hasFocus() == true) clearInputFocus()
  }

  private fun removeSheet() {
    val view = sheet
    if (view != null) {
      activeMotion.remove(view)?.cancel()
      try { windowManager.removeView(view) } catch (_: Exception) { }
    }
    sheet = null
    sheetParams = null
    sheetTitle = null
    sheetStatus = null
    sheetBar = null
    sheetScroll = null
    sheetBody = null
    sheetChips = null
    sheetChipsScroll = null
    sheetActions = null
    siteUrlInput = null
    siteSection = null
    answerView = null
    stepView = null
    renderedSignature = null
    restorePuckHeight()
  }

  private fun removePuck() {
    puckSnap?.cancel()
    puckSnap = null
    mainHandler.removeCallbacks(dimRunnable)
    puckRing?.setRunning(false)
    puck?.let {
      activeMotion.remove(it)?.cancel()
      try { windowManager.removeView(it) } catch (_: Exception) { }
    }
    puck = null
    puckParams = null
    puckRing = null
    puckBadge = null
  }

  // ------------------------------------------------------------------ capture --

  private fun requestCapture(mode: String = "research", siteUrl: String = "") {
    if (!isActive || capturePending) return
    capturePending = true
    scanGeneration += 1
    val thisScan = scanGeneration
    captureMode = mode
    reviewSite = siteUrl
    cancelSheetFocus()
    removeTray(animated = false)
    puck?.visibility = View.GONE
    sheet?.visibility = View.GONE
    // Allow the OS compositor to remove our translucent windows before one
    // requested frame is routed to ImageReader.
    mainHandler.postDelayed({
      if (!capturePending || display == null || reader == null) return@postDelayed
      try {
        display?.setSurface(reader?.surface)
        mainHandler.postDelayed({
          if (capturePending && thisScan == scanGeneration) finishCapture(null)
        }, 2500)
      } catch (_: Exception) {
        if (thisScan == scanGeneration) finishCapture(null)
      }
    }, if (mode == "site_reviews") 550 else 300)
  }

  private fun onFrameAvailable(source: ImageReader) {
    val image = try { source.acquireLatestImage() } catch (_: Exception) { null }
    if (image == null) return
    if (!capturePending) {
      image.close()
      return
    }
    capturePending = false
    display?.setSurface(null)
    try {
      val encoded = encode(image)
      image.close()
      mainHandler.post { afterCapture() }
      if (encoded != null) {
        val body = Arguments.createMap().apply {
          putString("base64", encoded)
          putString("mime", "image/jpeg")
          putString("uri", "")
          putString("mode", captureMode)
          if (captureMode == "site_reviews") putString("reviewSite", reviewSite)
        }
        KrikoOverlayModule.emit("onScan", body)
      } else {
        showToast(L("captureFailed"))
      }
    } catch (_: Exception) {
      image.close()
      mainHandler.post { afterCapture() }
      showToast(L("captureFailed"))
    }
  }

  /** Bring the puck back and show the new scan's progress where a thumb reaches it. */
  private fun afterCapture() {
    if (uiDirty) {
      uiDirty = false
      refreshUi()
    }
    puck?.let { if (!appForeground) animateIn(it, 0.9f, 200L) }
    // A new scan is what the reader is waiting on: show it, not an older pick.
    selectedJob = ""
    renderedSignature = null
    openSheet()
    sheet?.let { if (!appForeground) animateIn(it, 0.96f, 230L) }
  }

  private fun encode(image: Image): String? {
    val plane = image.planes.firstOrNull() ?: return null
    val pixelStride = plane.pixelStride
    val rowStride = plane.rowStride
    val paddedWidth = rowStride / pixelStride
    val raw = Bitmap.createBitmap(paddedWidth, image.height, Bitmap.Config.ARGB_8888)
    val bytes = ByteArray(rowStride * image.height)
    val buffer = plane.buffer
    buffer.get(bytes, 0, minOf(buffer.remaining(), bytes.size))
    raw.copyPixelsFromBuffer(ByteBuffer.wrap(bytes))
    val cropped = if (paddedWidth != image.width) Bitmap.createBitmap(raw, 0, 0, image.width, image.height) else raw
    val out = ByteArrayOutputStream()
    cropped.compress(Bitmap.CompressFormat.JPEG, 86, out)
    if (cropped !== raw) cropped.recycle()
    raw.recycle()
    return Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
  }

  private fun finishCapture(image: Image?) {
    image?.close()
    capturePending = false
    display?.setSurface(null)
    if (uiDirty) {
      uiDirty = false
      refreshUi()
    }
    restoreWindows()
  }

  // ------------------------------------------------------------------- motion --

  private fun animationsEnabled(): Boolean = Build.VERSION.SDK_INT < 26 || ValueAnimator.areAnimatorsEnabled()

  private fun animateIn(view: View, initialScale: Float, duration: Long) {
    if (view.visibility != View.VISIBLE) {
      view.alpha = 0f
      view.scaleX = initialScale
      view.scaleY = initialScale
    }
    view.visibility = View.VISIBLE
    animateView(view, 1f, 1f, 0f, duration, spring = true)
  }

  private fun animateView(
    view: View,
    alpha: Float,
    scale: Float,
    translationY: Float,
    duration: Long,
    spring: Boolean,
    onEnd: (() -> Unit)? = null,
  ) {
    activeMotion.remove(view)?.cancel()
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
      interpolator = if (spring) gentleSpring else DecelerateInterpolator()
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
          if (cancelled || activeMotion[view] !== animator) return
          activeMotion.remove(view)
          view.alpha = alpha.coerceIn(0f, 1f)
          view.scaleX = scale
          view.scaleY = scale
          view.translationY = translationY
          onEnd?.invoke()
        }
      })
    }
    activeMotion[view] = animator
    animator.start()
  }

  private fun openSource(url: String) {
    try {
      startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (_: Exception) {
      showToast(L("sourceFailed"))
    }
  }

  // ------------------------------------------------------------------ widgets --

  /**
   * A full-width pill: an optional glyph, then the label, centred as a pair.
   * The ripple clips to the pill's own radius.
   */
  private fun actionRow(
    glyph: String?,
    label: String,
    backgroundColor: Int,
    foregroundColor: Int,
    rippleColor: Int,
    strokeColor: Int,
    heightDp: Int,
    textSp: Float,
    onClick: () -> Unit,
  ): LinearLayout = LinearLayout(this).apply {
    orientation = LinearLayout.HORIZONTAL
    gravity = Gravity.CENTER
    background = capsule(backgroundColor, heightDp / 2, strokeColor, rippleColor)
    setPadding(dp(14), 0, dp(14), 0)
    isClickable = true
    contentDescription = label
    installPressMotion(this)
    setOnClickListener { onClick() }
    if (glyph != null) {
      addView(GlyphView(this@KrikoOverlayService, glyph, foregroundColor),
        LinearLayout.LayoutParams(dp(20), dp(20)).apply { marginEnd = dp(9) })
    }
    addView(TextView(this@KrikoOverlayService).apply {
      text = label
      setTextColor(foregroundColor)
      textSize = textSp
      typeface = geistSemiBold
      includeFontPadding = false
      maxLines = 1
      gravity = Gravity.CENTER
    })
  }

  /** A short scale on press; the ripple comes from the background drawable. */
  private fun installPressMotion(view: View) {
    view.setOnTouchListener { pressedView, event ->
      when (event.actionMasked) {
        MotionEvent.ACTION_DOWN -> animateView(pressedView, 1f, 0.97f, 0f, 90L, spring = true)
        MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> animateView(pressedView, 1f, 1f, 0f, 150L, spring = true)
      }
      false
    }
  }

  private fun bodyText(text: String, size: Float, color: Int) = TextView(this).apply {
    this.text = text
    setTextColor(color)
    textSize = size
    typeface = geistRegular
    setLineSpacing(dp(2).toFloat(), 1f)
    setPadding(0, dp(4), 0, dp(2))
  }

  private fun sectionText(label: String) = TextView(this).apply {
    text = label
    setTextColor(palette.ink3)
    textSize = 11f
    typeface = geistSemiBold
    letterSpacing = 0.05f
    setPadding(0, dp(10), 0, dp(3))
  }

  private fun errorText(message: String) = TextView(this).apply {
    text = message
    setTextColor(palette.risk)
    textSize = 12.5f
    typeface = geistRegular
    setLineSpacing(dp(2).toFloat(), 1f)
    background = capsule(palette.riskWash, 12, Color.TRANSPARENT)
    setPadding(dp(11), dp(8), dp(11), dp(8))
    layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
      .apply { topMargin = dp(5) }
  }

  private fun sourceRow(label: String, url: String) = TextView(this).apply {
    text = label
    setTextColor(palette.accentHi)
    textSize = 12.5f
    typeface = geistMedium
    maxLines = 2
    ellipsize = android.text.TextUtils.TruncateAt.END
    contentDescription = label
    setPadding(dp(8), dp(6), dp(8), dp(6))
    background = capsule(Color.TRANSPARENT, 8, Color.TRANSPARENT, tint(palette.accentHi, 0.12f))
    isClickable = true
    setOnClickListener { openSource(url) }
    layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
      .apply { bottomMargin = dp(2) }
  }

  private fun statusLabel(status: String): String = when (status) {
    "queued" -> L("queued")
    "reading" -> L("reading")
    "running" -> L("running")
    "done" -> L("done")
    "error" -> L("error")
    "cancelled" -> L("cancelled")
    else -> status
  }

  private fun answerText(markdown: String, sources: JSONArray): TextView {
    val answer = TextView(this).apply {
      setTextColor(palette.ink)
      textSize = 14f
      typeface = geistRegular
      setLineSpacing(dp(3).toFloat(), 1f)
      setPadding(0, dp(6), 0, dp(4))
      setTextIsSelectable(true)
      setLinkTextColor(palette.accentHi)
      movementMethod = LinkMovementMethod.getInstance()
    }
    answer.text = Html.fromHtml(markdownHtml(markdown, sources), Html.FROM_HTML_MODE_COMPACT)
    return answer
  }

  private fun markdownHtml(markdown: String, sources: JSONArray): String {
    val sourceUrls = mutableMapOf<String, String>()
    for (index in 0 until sources.length()) {
      val source = sources.optJSONObject(index) ?: continue
      val number = source.optString("n")
      val url = safeHttpUrl(source.optString("url"))
      if (number.isNotBlank() && url.isNotBlank()) sourceUrls[number] = url
    }
    val out = StringBuilder()
    for (raw in markdown.replace("\r\n", "\n").split("\n")) {
      val line = raw.trim()
      if (line.isEmpty()) {
        out.append("<br/>")
        continue
      }
      val heading = Regex("^(#{1,3})\\s+(.+)$").matchEntire(line)
      val bullet = Regex("^[-*]\\s+(.+)$").matchEntire(line)
      val numbered = Regex("^\\d+[.)]\\s+(.+)$").matchEntire(line)
      when {
        heading != null -> out.append("<br/><b>").append(inlineHtml(heading.groupValues[2], sourceUrls)).append("</b><br/>")
        bullet != null -> out.append("&#8226;&nbsp; ").append(inlineHtml(bullet.groupValues[1], sourceUrls)).append("<br/>")
        numbered != null -> out.append("&#8226;&nbsp; ").append(inlineHtml(numbered.groupValues[1], sourceUrls)).append("<br/>")
        else -> out.append(inlineHtml(line, sourceUrls)).append("<br/>")
      }
    }
    return out.toString()
  }

  private fun inlineHtml(line: String, sourceUrls: Map<String, String>): String {
    var html = escapeHtml(line)
    val markdownLink = Regex("\\[([^\\]]+)\\]\\((https?://[^\\s)]+)\\)")
    html = markdownLink.replace(html) { match ->
      val url = safeHttpUrl(match.groupValues[2].replace("&amp;", "&"))
      if (url.isBlank()) match.groupValues[1]
      else "<a href=\"" + escapeHtml(url) + "\">" + match.groupValues[1] + "</a>"
    }
    html = Regex("\\*\\*(.+?)\\*\\*").replace(html) { "<b>${it.groupValues[1]}</b>" }
    html = Regex("(?<!\\*)\\*([^*]+)\\*(?!\\*)").replace(html) { "<i>${it.groupValues[1]}</i>" }
    html = Regex("`([^`]+)`").replace(html) { "<tt>${it.groupValues[1]}</tt>" }
    html = Regex("\\[(\\d+)]").replace(html) { match ->
      val url = sourceUrls[match.groupValues[1]]
      if (url == null) match.value else "<a href=\"" + escapeHtml(url) + "\">" + match.value + "</a>"
    }
    return html
  }

  private fun escapeHtml(value: String): String = value
    .replace("&", "&amp;")
    .replace("<", "&lt;")
    .replace(">", "&gt;")
    .replace("\"", "&quot;")

  private fun safeHttpUrl(value: String): String {
    val url = Uri.parse(value.trim())
    val scheme = url.scheme?.lowercase()
    if (scheme != "http" && scheme != "https") return ""
    if (url.host.isNullOrBlank() || !url.userInfo.isNullOrBlank()) return ""
    return url.toString()
  }

  @Suppress("DEPRECATION")
  private fun overlayParams(width: Int, height: Int, gravity: Int, extraFlags: Int = 0): WindowManager.LayoutParams {
    val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
    } else {
      WindowManager.LayoutParams.TYPE_PHONE
    }
    return WindowManager.LayoutParams(
      width, height, type,
      WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
        or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
        or extraFlags,
      PixelFormat.TRANSLUCENT,
    ).apply {
      this.gravity = gravity
      alpha = 1f
    }
  }

  // --------------------------------------------------------------- drawables --

  private fun shape(color: Int, radiusDp: Int, strokeColor: Int = Color.TRANSPARENT): GradientDrawable =
    GradientDrawable().apply {
      shape = GradientDrawable.RECTANGLE
      setColor(color)
      cornerRadius = dp(radiusDp).toFloat()
      if (Color.alpha(strokeColor) > 0) setStroke(dp(1), strokeColor)
    }

  /** A hairline-edged rounded fill, optionally wrapped in a clipping press ripple. */
  private fun capsule(color: Int, radiusDp: Int, strokeColor: Int, rippleColor: Int? = null): Drawable {
    val content = shape(color, radiusDp, strokeColor)
    if (rippleColor == null) return content
    return RippleDrawable(ColorStateList.valueOf(rippleColor), content, shape(Color.WHITE, radiusDp))
  }

  private fun circle(color: Int): GradientDrawable = GradientDrawable().apply {
    shape = GradientDrawable.OVAL
    setColor(color)
  }

  private fun roundOutline(radiusDp: Int): ViewOutlineProvider = object : ViewOutlineProvider() {
    override fun getOutline(view: View, outline: Outline) {
      outline.setRoundRect(0, 0, view.width, view.height, dp(radiusDp).toFloat())
    }
  }

  private fun tint(color: Int, fraction: Float): Int = Color.argb(
    (255 * fraction).roundToInt().coerceIn(0, 255),
    Color.red(color),
    Color.green(color),
    Color.blue(color),
  )

  private fun mix(color: Int, other: Int, fraction: Float): Int = Color.argb(
    Color.alpha(color),
    (Color.red(color) + (Color.red(other) - Color.red(color)) * fraction).roundToInt(),
    (Color.green(color) + (Color.green(other) - Color.green(color)) * fraction).roundToInt(),
    (Color.blue(color) + (Color.blue(other) - Color.blue(color)) * fraction).roundToInt(),
  )

  // ----------------------------------------------------------- custom views --

  /** A scroll view that stops growing at a cap, so the buttons below it stay on screen. */
  private inner class CappedScroll(context: Context, private val capPx: Int) : ScrollView(context) {
    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
      super.onMeasure(widthMeasureSpec, View.MeasureSpec.makeMeasureSpec(capPx, View.MeasureSpec.AT_MOST))
    }
  }

  /** The action glyphs, drawn in the app's own line weight so no icon font is needed. */
  private inner class GlyphView(context: Context, private val kind: String, private val color: Int) : View(context) {
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
      }
    }
  }

  /** The thin ring that turns around the puck while research runs. */
  private inner class RingView(context: Context) : View(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
      style = Paint.Style.STROKE
      strokeCap = Paint.Cap.ROUND
      color = tint(ON_ACCENT, 0.92f)
    }
    private val box = RectF()
    private var running = false
    private var angle = 0f
    private var spinner: ValueAnimator? = null

    fun setRunning(value: Boolean) {
      if (value == running) return
      running = value
      spinner?.cancel()
      spinner = null
      if (running && animationsEnabled()) {
        spinner = ValueAnimator.ofFloat(0f, 360f).apply {
          duration = 1100
          repeatCount = ValueAnimator.INFINITE
          interpolator = android.view.animation.LinearInterpolator()
          addUpdateListener { animation ->
            angle = animation.animatedValue as Float
            invalidate()
          }
          start()
        }
      }
      invalidate()
    }

    override fun onDetachedFromWindow() {
      spinner?.cancel()
      spinner = null
      super.onDetachedFromWindow()
    }

    override fun onDraw(canvas: Canvas) {
      if (!running) return
      val inset = dp(4).toFloat()
      paint.strokeWidth = dp(2).toFloat()
      box.set(inset, inset, width - inset, height - inset)
      canvas.drawArc(box, angle - 90f, 96f, false, paint)
    }
  }

  /** A thin sliding highlight: "working" without a percentage nobody can know. */
  private inner class IndeterminateBar(
    context: Context,
    track: Int,
    private val fill: Int,
  ) : FrameLayout(context) {
    private val runner = View(context)
    private var animator: ValueAnimator? = null

    init {
      background = shape(track, 2)
      clipChildren = true
      clipToOutline = true
      outlineProvider = roundOutline(2)
      runner.background = shape(fill, 2)
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

  // ----------------------------------------------------------------- plumbing --

  private fun emitAction(action: String, id: String) {
    val body = Arguments.createMap().apply {
      putString("action", action)
      putString("id", id)
    }
    KrikoOverlayModule.emit("onAction", body)
  }

  private fun sendSession(active: Boolean) {
    val body = Arguments.createMap().apply { putBoolean("active", active) }
    KrikoOverlayModule.emit("onSession", body)
  }

  private fun showToast(message: String) = mainHandler.post {
    Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
  }

  private fun clearInputFocus() {
    siteUrlInput?.let { input ->
      try {
        (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager)
          .hideSoftInputFromWindow(input.windowToken, 0)
        input.clearFocus()
      } catch (_: Exception) { }
    }
  }

  private fun enableInputWindow(input: EditText) {
    val params = sheetParams ?: return
    params.flags = params.flags and WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE.inv()
    params.softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
    try { sheet?.let { windowManager.updateViewLayout(it, params) } } catch (_: Exception) { }
    input.requestFocus()
    input.post { (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager)
      .showSoftInput(input, InputMethodManager.SHOW_IMPLICIT) }
  }

  private fun stopSession() {
    if (shuttingDown) return
    shuttingDown = true
    releaseResources(stopProjection = true)
    isActive = false
    stopForeground(STOP_FOREGROUND_REMOVE)
    sendSession(false)
    KrikoOverlayModule.finishHeadlessSession()
    stopSelf()
  }

  private fun releaseResources(stopProjection: Boolean) {
    capturePending = false
    uiDirty = false
    try { display?.setSurface(null) } catch (_: Exception) { }
    try { display?.release() } catch (_: Exception) { }
    display = null
    try { reader?.setOnImageAvailableListener(null, null) } catch (_: Exception) { }
    try { reader?.close() } catch (_: Exception) { }
    reader = null
    captureThread?.quitSafely()
    captureThread = null
    captureHandler = null
    mainHandler.removeCallbacksAndMessages(null)
    removeTray(animated = false)
    removeSheet()
    removePuck()
    projection?.let { current ->
      try { current.unregisterCallback(projectionCallback) } catch (_: Exception) { }
      if (stopProjection) try { current.stop() } catch (_: Exception) { }
    }
    projection = null
  }

  override fun onDestroy() {
    if (isActive) {
      shuttingDown = true
      releaseResources(stopProjection = true)
      isActive = false
      sendSession(false)
      KrikoOverlayModule.finishHeadlessSession()
    }
    super.onDestroy()
  }

  override fun onBind(intent: Intent?): IBinder? = null

  private fun dp(value: Int): Int = (value * resources.displayMetrics.density).roundToInt()
}

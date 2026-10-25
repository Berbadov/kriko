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
import android.graphics.Color
import android.graphics.Outline
import android.graphics.PixelFormat
import android.graphics.Rect
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
import android.widget.LinearLayout
import android.widget.ProgressBar
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

class KrikoOverlayService : Service() {
  companion object {
    const val ACTION_START = "__PACKAGE__.overlay.START"
    const val ACTION_STOP = "__PACKAGE__.overlay.STOP"
    const val ACTION_UPDATE = "__PACKAGE__.overlay.UPDATE"
    const val ACTION_UI = "__PACKAGE__.overlay.UI"
    const val EXTRA_RESULT_CODE = "resultCode"
    const val EXTRA_RESULT_DATA = "resultData"
    const val EXTRA_JOBS = "jobs"
    const val EXTRA_UI = "ui"
    private const val CHANNEL_ID = "kriko_screen_scan"
    private const val NOTIFICATION_ID = 7406
    private const val ON_ACCENT = 0xFFFFFFFF.toInt()

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
  private var bubble: View? = null
  private var panel: View? = null
  private var bubbleParams: WindowManager.LayoutParams? = null
  private var panelParams: WindowManager.LayoutParams? = null
  private var panelScroll: ScrollView? = null
  @Volatile private var capturePending = false
  @Volatile private var scanGeneration = 0
  private var shuttingDown = false
  private var jobs = JSONArray()
  private var selectedJob = ""
  private var siteUrlInput: EditText? = null
  private var jobList: LinearLayout? = null
  private var panelMode = "queue"
  private var currentTab: TextView? = null
  private var queueTab: TextView? = null
  private var siteActionView: View? = null
  private var bubbleHandle: View? = null
  private var bubbleScanView: TextView? = null
  private var bubbleQueueChip: View? = null
  private var bubbleQueueLabel: TextView? = null
  private var bubbleQueueBadge: TextView? = null
  private var bubbleDot: View? = null
  private var bubbleStopView: TextView? = null
  private var dotAnimator: ValueAnimator? = null
  /** A UI update arrived mid-capture; apply it when the windows come back. */
  private var uiDirty = false
  private var palette: Palette = DARK
  private val labels: MutableMap<String, String> = LinkedHashMap(DEFAULT_LABELS)
  private var panelCloseGeneration = 0
  private var panelIsClosing = false
  private var panelTransitionGeneration = 0
  private var panelSwitching = false
  private var pendingPanelMode: String? = null
  private val activeMotion = WeakHashMap<View, ValueAnimator>()
  private val gentleSpring = TimeInterpolator { input ->
    val t = input.coerceIn(0f, 1f).toDouble()
    (1.0 - exp(-8.2 * t) * cos(10.5 * t)).coerceIn(0.0, 1.08).toFloat()
  }
  private val geistRegular by lazy { runCatching { Typeface.createFromAsset(assets, "fonts/KrikoGeist-Regular.ttf") }.getOrDefault(Typeface.DEFAULT) }
  private val geistMedium by lazy { runCatching { Typeface.createFromAsset(assets, "fonts/KrikoGeist-Medium.ttf") }.getOrDefault(Typeface.DEFAULT) }
  private val geistSemiBold by lazy { runCatching { Typeface.createFromAsset(assets, "fonts/KrikoGeist-SemiBold.ttf") }.getOrDefault(Typeface.DEFAULT_BOLD) }
  private var renderedSignature: String? = null
  private val answerViews = mutableMapOf<String, TextView>()
  private val stepViews = mutableMapOf<String, TextView>()
  private val statusViews = mutableMapOf<String, TextView>()
  @Volatile private var captureMode = "research"
  @Volatile private var reviewSite = ""
  private val mainHandler = Handler(android.os.Looper.getMainLooper())
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
      ACTION_UPDATE -> {
        val json = intent.getStringExtra(EXTRA_JOBS)
        if (json != null) {
          jobs = try { JSONArray(json) } catch (_: Exception) { JSONArray() }
          renderPanel()
        }
        return START_NOT_STICKY
      }
      ACTION_START -> startProjection(intent)
    }
    return START_NOT_STICKY
  }

  private fun startProjection(intent: Intent) {
    if (isActive) return
    // Carry the reader's last palette and words into the very first bubble.
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
      showBubble()
      sendSession(true)
      KrikoOverlayModule.serviceReady()
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

  /** One translated bubble/panel word, or its English default. */
  private fun L(key: String): String = labels[key] ?: DEFAULT_LABELS[key] ?: key

  // ------------------------------------------------------------------ UI feed --

  /**
   * Read `{ theme, labels }` without touching views. Called before the first
   * bubble exists, so the window is built in the right palette already.
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
   * Rebuild the bubble and, when open, the panel in the current palette and
   * language while keeping where they were and what the reader had typed.
   */
  private fun refreshUi() {
    if (!isActive || shuttingDown) return
    val panelWasOpen = panel?.visibility == View.VISIBLE
    val keepMode = panelMode
    val keepSite = siteUrlInput?.text?.toString().orEmpty()
    val keepScroll = panelScroll?.scrollY ?: 0
    val keepX = bubbleParams?.x
    val keepY = bubbleParams?.y
    removePanel()
    bubble?.let { view ->
      stopDot()
      activeMotion.remove(view)?.cancel()
      try { windowManager.removeView(view) } catch (_: Exception) { }
    }
    bubble = null
    bubbleParams = null
    showBubble()
    val params = bubbleParams
    if (params != null && keepX != null && keepY != null) {
      params.x = keepX
      params.y = keepY
      try { bubble?.let { windowManager.updateViewLayout(it, params) } } catch (_: Exception) { }
    }
    // A translated label can change the capsule's width, so clamp the restored
    // position once the new window has measured itself.
    val moved = bubble
    if (moved != null) {
      moved.post {
        if (bubble !== moved || shuttingDown) return@post
        val bounds = displayBounds()
        val current = bubbleParams ?: return@post
        current.x = current.x.coerceIn(0, (bounds.width() - moved.width).coerceAtLeast(0))
        current.y = current.y.coerceIn(0, (bounds.height() - moved.height).coerceAtLeast(0))
        try { windowManager.updateViewLayout(moved, current) } catch (_: Exception) { }
      }
    }
    if (panelWasOpen) {
      togglePanel(keepMode)
      siteUrlInput?.setText(keepSite)
      panelScroll?.post { panelScroll?.scrollTo(0, keepScroll) }
    }
    updateNotification()
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

  // ------------------------------------------------------------------- bubble --

  /**
   * A compact capsule: a blue K grip, Scan, the queue chip with its active
   * count, a running dot, and a quiet Stop. The window stays
   * WRAP_CONTENT x 52dp and is dragged and clamped by the K grip.
   */
  private fun showBubble() {
    if (bubble != null || !Settings.canDrawOverlays(this)) return
    val p = palette
    val root = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
      background = capsule(p.panel, 26, p.edge)
      setPadding(dp(6), dp(6), dp(8), dp(6))
      elevation = dp(12).toFloat()
      outlineProvider = roundOutline(26)
      // Keep the K grip's soft shadow visible inside the capsule's padding.
      clipChildren = false
    }

    val handle = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      gravity = Gravity.CENTER
      background = handleBackground(p)
      contentDescription = L("dragHint")
      elevation = dp(2).toFloat()
      outlineProvider = roundOutline(15)
      layoutParams = LinearLayout.LayoutParams(dp(40), dp(40))
    }
    handle.addView(TextView(this).apply {
      text = "K"
      setTextColor(ON_ACCENT)
      textSize = 14f
      typeface = geistSemiBold
      includeFontPadding = false
      gravity = Gravity.CENTER
    })
    handle.addView(View(this).apply {
      // The grip line: a small drag affordance under the mark.
      background = capsule(tint(ON_ACCENT, 0.5f), 1, Color.TRANSPARENT)
      layoutParams = LinearLayout.LayoutParams(dp(9), dp(2)).apply { topMargin = dp(2) }
    })

    val scan = button(L("scan"), p.accent, ON_ACCENT, tint(ON_ACCENT, 0.24f), Color.TRANSPARENT, 34) {
      requestCapture("research")
    }

    val chip = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER
      background = capsule(p.raised, 16, p.edge, tint(p.ink, 0.08f))
      setPadding(dp(9), 0, dp(9), 0)
      isClickable = true
      contentDescription = L("queue")
      installPressMotion(this)
      setOnClickListener { togglePanel("queue") }
      layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(32)).apply { marginStart = dp(8) }
    }
    val chipLabel = TextView(this).apply {
      text = L("queue")
      setTextColor(p.ink)
      textSize = 12f
      typeface = geistMedium
      includeFontPadding = false
      gravity = Gravity.CENTER
    }
    val badge = TextView(this).apply {
      text = activeCount().toString()
      setTextColor(ON_ACCENT)
      textSize = 10f
      typeface = geistSemiBold
      includeFontPadding = false
      gravity = Gravity.CENTER
      background = capsule(p.accent, 9, Color.TRANSPARENT)
      setPadding(dp(5), dp(1), dp(5), dp(1))
      visibility = if (activeCount() > 0) View.VISIBLE else View.GONE
      layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(18)).apply { marginStart = dp(5) }
    }
    chip.addView(chipLabel)
    chip.addView(badge)

    val dot = View(this).apply {
      background = circle(p.accent)
      layoutParams = LinearLayout.LayoutParams(dp(8), dp(8)).apply { marginStart = dp(8) }
      visibility = View.GONE
    }

    val stop = TextView(this).apply {
      text = L("stop")
      setTextColor(p.ink3)
      textSize = 12f
      typeface = geistMedium
      includeFontPadding = false
      gravity = Gravity.CENTER
      contentDescription = L("stopSharing")
      setPadding(dp(10), 0, dp(10), 0)
      background = capsule(Color.TRANSPARENT, 16, Color.TRANSPARENT, tint(p.ink, 0.08f))
      installPressMotion(this)
      setOnClickListener { stopSession() }
      layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(32)).apply { marginStart = dp(8) }
    }

    root.addView(handle)
    root.addView(scan)
    root.addView(chip)
    root.addView(dot)
    root.addView(stop)

    bubble = root
    bubbleHandle = handle
    bubbleScanView = scan
    bubbleQueueChip = chip
    bubbleQueueLabel = chipLabel
    bubbleQueueBadge = badge
    bubbleDot = dot
    bubbleStopView = stop
    bubbleParams = overlayParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(52), Gravity.TOP or Gravity.START).apply {
      x = dp(18)
      y = dp(190)
    }
    root.alpha = 0f
    root.scaleX = 0.94f
    root.scaleY = 0.94f
    // The K grip owns the touch stream so the window can be dragged; sibling
    // actions stay tappable.
    installDrag(handle, bubbleParams!!, root)
    windowManager.addView(root, bubbleParams)
    animateIn(root, 0.94f, 240L)
    syncBubble()
  }

  /** Bubble text, badge and running dot, refreshed whenever job state changes. */
  private fun syncBubble() {
    val active = activeCount()
    bubbleQueueLabel?.text = L("queue")
    bubbleQueueChip?.contentDescription = if (active > 0) "${L("queue")} $active" else L("queue")
    bubbleQueueBadge?.let { badge ->
      badge.text = active.toString()
      badge.visibility = if (active > 0) View.VISIBLE else View.GONE
    }
    bubbleScanView?.let { scan ->
      scan.text = L("scan")
      scan.contentDescription = L("scan")
    }
    bubbleStopView?.let { stop ->
      stop.text = L("stop")
      stop.contentDescription = L("stopSharing")
    }
    bubbleHandle?.contentDescription = L("dragHint")
    setDotRunning(hasRunningJob())
  }

  /** The small dot breathes while research runs; static when motion is off. */
  private fun setDotRunning(running: Boolean) {
    val dot = bubbleDot ?: return
    dot.visibility = if (running) View.VISIBLE else View.GONE
    dot.contentDescription = if (running) L("running") else null
    if (!running) {
      stopDot()
      return
    }
    if (dotAnimator != null) return
    if (!animationsEnabled()) {
      dot.alpha = 1f
      return
    }
    dotAnimator = ValueAnimator.ofFloat(0.32f, 1f).apply {
      duration = 850
      repeatCount = ValueAnimator.INFINITE
      repeatMode = ValueAnimator.REVERSE
      interpolator = DecelerateInterpolator()
      addUpdateListener { animation -> dot.alpha = animation.animatedValue as Float }
      start()
    }
  }

  private fun stopDot() {
    dotAnimator?.cancel()
    dotAnimator = null
    bubbleDot?.alpha = 1f
  }

  private fun activeCount(): Int = (0 until jobs.length()).count { index ->
    val status = jobs.optJSONObject(index)?.optString("status") ?: ""
    status == "queued" || status == "running" || status == "reading"
  }

  private fun tabQueueLabel(): String {
    val active = activeCount()
    return if (active == 0) L("all") else "${L("all")} · $active"
  }

  private fun hasRunningJob(): Boolean = (0 until jobs.length()).any { index ->
    val status = jobs.optJSONObject(index)?.optString("status") ?: ""
    status == "running" || status == "reading"
  }

  // -------------------------------------------------------------------- panel --

  private fun togglePanel(mode: String = "queue") {
    if (panel != null) {
      if (panelIsClosing || panel?.visibility != View.VISIBLE) {
        panelCloseGeneration += 1
        panelIsClosing = false
        panel?.let { animateIn(it, 0.95f, 230L) }
      }
      switchPanelMode(mode)
      return
    }
    val p = palette
    val container = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      background = capsule(p.panel, 20, p.edge)
      elevation = dp(20).toFloat()
      outlineProvider = roundOutline(20)
      clipToOutline = true
      setPadding(dp(12), dp(10), dp(12), dp(10))
    }
    val header = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    val title = TextView(this).apply {
      text = "Kriko"
      setTextColor(p.ink)
      textSize = 16f
      typeface = geistSemiBold
      letterSpacing = 0.035f
      layoutParams = LinearLayout.LayoutParams(0, dp(36), 1f)
      gravity = Gravity.CENTER_VERTICAL
    }
    header.addView(title)
    header.addView(button(L("scan"), p.accent, ON_ACCENT, tint(ON_ACCENT, 0.24f)) {
      requestCapture("research")
    })
    header.addView(button(L("close"), p.raised, p.ink2, tint(p.ink, 0.10f), p.edge) {
      hidePanelAnimated()
    })
    container.addView(header)

    val tabs = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
      background = capsule(p.ground, 12, p.edge)
      setPadding(dp(3), dp(3), dp(3), dp(3))
    }
    val nowTab = tabButton(L("now")) { switchPanelMode("current") }
    val allTab = tabButton(tabQueueLabel()) { switchPanelMode("queue") }
    currentTab = nowTab
    queueTab = allTab
    tabs.addView(nowTab, LinearLayout.LayoutParams(0, dp(34), 1f))
    tabs.addView(allTab, LinearLayout.LayoutParams(0, dp(34), 1f))
    container.addView(tabs, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(40)).apply {
      topMargin = dp(7)
      bottomMargin = dp(8)
    })

    val siteUrl = EditText(this).apply {
      hint = L("siteUrlHint")
      setHintTextColor(p.ink3)
      setTextColor(p.ink)
      textSize = 13f
      setSingleLine(true)
      inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
      background = capsule(p.ground, 10, p.edge)
      setPadding(dp(11), dp(5), dp(11), dp(5))
      isFocusable = true
      isFocusableInTouchMode = true
      setOnTouchListener { _, event ->
        if (event.action == MotionEvent.ACTION_DOWN) enableInputWindow(this)
        false
      }
      setOnClickListener { enableInputWindow(this) }
      onFocusChangeListener = View.OnFocusChangeListener { _, focused ->
        val params = panelParams ?: return@OnFocusChangeListener
        params.flags = if (focused) {
          params.flags and WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE.inv()
        } else {
          params.flags or WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
        }
        try { panel?.let { windowManager.updateViewLayout(it, params) } } catch (_: Exception) { }
        if (focused) post { (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager)
          .showSoftInput(this, InputMethodManager.SHOW_IMPLICIT) }
      }
    }
    siteUrlInput = siteUrl
    container.addView(siteUrl, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(40)))
    val siteAction = button(L("readSiteComments"), p.accent, ON_ACCENT, tint(ON_ACCENT, 0.24f), Color.TRANSPARENT, 38) {
      reviewSite = siteUrlInput?.text?.toString()?.trim().orEmpty()
      clearInputFocus()
      requestCapture("site_reviews", reviewSite)
    }
    siteActionView = siteAction
    container.addView(siteAction, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(38)).apply {
      topMargin = dp(6)
      bottomMargin = dp(8)
    })

    val bounds = displayBounds()
    val density = resources.displayMetrics.density
    val screenWidthDp = (bounds.width() / density).roundToInt()
    val screenHeightDp = (bounds.height() / density).roundToInt()
    val panelWidthDp = minOf(360, screenWidthDp - 20).coerceAtLeast(200)
    val scrollHeight = minOf(360, screenHeightDp - 290).coerceAtLeast(72)
    val scroll = ScrollView(this).apply {
      isFillViewport = false
      overScrollMode = View.OVER_SCROLL_NEVER
    }
    panelScroll = scroll
    val list = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      setPadding(0, dp(2), 0, dp(2))
    }
    jobList = list
    scroll.addView(list)
    container.addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(scrollHeight)))
    panel = container
    panelMode = mode
    panelParams = overlayParams(dp(panelWidthDp), WindowManager.LayoutParams.WRAP_CONTENT, Gravity.TOP or Gravity.END).apply {
      x = dp(10)
      y = dp(minOf(64, (screenHeightDp - 20 - 221 - scrollHeight).coerceAtLeast(8)))
    }
    container.alpha = 0f
    container.scaleX = 0.96f
    container.scaleY = 0.96f
    windowManager.addView(container, panelParams)
    animateIn(container, 0.96f, 230L)
    renderPanel()
  }

  private fun renderPanel() {
    syncBubble()
    styleTabs()
    siteUrlInput?.visibility = if (panelMode == "current") View.VISIBLE else View.GONE
    siteActionView?.visibility = if (panelMode == "current") View.VISIBLE else View.GONE
    val list = jobList ?: return
    if (panelSwitching) return
    val signature = buildString {
      append(panelMode).append('|').append(selectedJob).append('|')
      for (index in 0 until jobs.length()) {
        val item = jobs.optJSONObject(index) ?: continue
        val steps = item.optJSONArray("steps") ?: JSONArray()
        append(item.optString("id")).append(':')
          .append(item.optString("status")).append(':')
          .append(item.optString("title")).append(':')
          .append(item.optString("error")).append(':')
          .append(steps.length() > 0)
          .append(':').append(item.optJSONArray("sources")?.length() ?: 0)
          .append(':').append(item.optString("text").isNotBlank()).append(';')
      }
    }
    if (signature == renderedSignature) {
      updateAnswerViews()
      return
    }
    renderedSignature = signature
    val priorScroll = panelScroll?.scrollY ?: 0
    if (panelMode == "queue") renderQueue(list) else renderCurrent(list)
    panelScroll?.post { panelScroll?.scrollTo(0, priorScroll) }
  }

  /** Selected/unselected tab pills, in the current palette. */
  private fun styleTabs() {
    val p = palette
    val nowSelected = panelMode == "current"
    currentTab?.let { tab ->
      tab.background = capsule(
        if (nowSelected) p.raised else Color.TRANSPARENT,
        9,
        if (nowSelected) p.edge else Color.TRANSPARENT,
        tint(p.ink, 0.08f),
      )
      tab.setTextColor(if (nowSelected) p.ink else p.ink2)
    }
    val allSelected = panelMode == "queue"
    queueTab?.let { tab ->
      tab.text = tabQueueLabel()
      tab.background = capsule(
        if (allSelected) p.raised else Color.TRANSPARENT,
        9,
        if (allSelected) p.edge else Color.TRANSPARENT,
        tint(p.ink, 0.08f),
      )
      tab.setTextColor(if (allSelected) p.ink else p.ink2)
    }
  }

  private fun switchPanelMode(mode: String) {
    if (!panelSwitching && mode == panelMode) {
      renderPanel()
      return
    }
    if (panelSwitching && pendingPanelMode == mode) return
    val list = jobList
    if (!animationsEnabled() || list == null) {
      panelTransitionGeneration += 1
      panelSwitching = false
      pendingPanelMode = null
      panelMode = mode
      renderedSignature = null
      renderPanel()
      return
    }

    panelTransitionGeneration += 1
    val generation = panelTransitionGeneration
    pendingPanelMode = mode
    panelSwitching = true
    animateView(list, 0f, 0.99f, dp(4).toFloat(), 90L, spring = false) {
      if (generation != panelTransitionGeneration || panel == null || list.parent?.parent !== panel) return@animateView
      panelMode = mode
      pendingPanelMode = null
      panelSwitching = false
      renderedSignature = null
      list.alpha = 0f
      list.scaleX = 0.99f
      list.scaleY = 0.99f
      list.translationY = -dp(3).toFloat()
      renderPanel()
      animateView(list, 1f, 1f, 0f, 210L, spring = true)
    }
  }

  private fun updateAnswerViews() {
    for (index in 0 until jobs.length()) {
      val item = jobs.optJSONObject(index) ?: continue
      val answer = answerViews[item.optString("id")] ?: continue
      answer.text = Html.fromHtml(
        markdownHtml(item.optString("text"), item.optJSONArray("sources") ?: JSONArray()),
        Html.FROM_HTML_MODE_COMPACT,
      )
    }
    for (index in 0 until jobs.length()) {
      val item = jobs.optJSONObject(index) ?: continue
      val stepView = stepViews[item.optString("id")] ?: continue
      val steps = item.optJSONArray("steps") ?: JSONArray()
      val latestStep = if (steps.length() > 0) steps.optJSONObject(steps.length() - 1) else null
      setProgressText(stepView, latestStep?.optString("text").orEmpty())
    }
    for (index in 0 until jobs.length()) {
      val item = jobs.optJSONObject(index) ?: continue
      statusViews[item.optString("id")]?.text = statusLabel(item.optString("status"))
    }
  }

  private fun setProgressText(view: TextView, text: String) {
    if (view.text.toString() == text) return
    view.text = text
    if (!animationsEnabled()) return
    view.alpha = minOf(view.alpha, 0.84f)
    animateView(view, 1f, 1f, 0f, 135L, spring = false)
  }

  private fun renderCurrent(list: LinearLayout) {
    list.removeAllViews()
    answerViews.clear()
    stepViews.clear()
    statusViews.clear()
    val items = (0 until jobs.length()).mapNotNull { jobs.optJSONObject(it) }
    val current = items.firstOrNull { it.optString("status") == "running" || it.optString("status") == "reading" }
      ?: items.firstOrNull { it.optString("id") == selectedJob }
      ?: items.firstOrNull()
    if (current == null) {
      list.addView(bodyText(L("answerEmpty"), 13f, palette.ink2))
      return
    }
    renderJobCard(list, current)
  }

  private fun renderQueue(list: LinearLayout) {
    list.removeAllViews()
    answerViews.clear()
    stepViews.clear()
    statusViews.clear()
    if (jobs.length() == 0) {
      list.addView(bodyText(L("queueEmpty"), 13f, palette.ink2))
      return
    }
    for (index in 0 until minOf(jobs.length(), 16)) {
      val item = jobs.optJSONObject(index) ?: continue
      renderJobCard(list, item)
    }
  }

  private fun renderJobCard(list: LinearLayout, item: JSONObject) {
    val p = palette
    val id = item.optString("id")
    val status = item.optString("status")
    val card = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      background = capsule(p.raised, 14, p.edge, tint(p.ink, 0.05f))
      setPadding(dp(11), dp(9), dp(11), dp(9))
      isClickable = true
      layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        .apply { bottomMargin = dp(7) }
      setOnClickListener {
        selectedJob = id
        if (panelMode == "queue") switchPanelMode("current")
      }
    }
    val top = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    val title = TextView(this).apply {
      text = item.optString("title").ifBlank { L("productScan") }
      setTextColor(p.ink)
      textSize = 14f
      typeface = geistSemiBold
      maxLines = 2
      layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
    }
    top.addView(title)
    val active = status == "queued" || status == "running" || status == "reading"
    if (active) top.addView(ProgressBar(this).apply {
      isIndeterminate = true
      indeterminateTintList = ColorStateList.valueOf(p.accentHi)
      layoutParams = LinearLayout.LayoutParams(dp(18), dp(18)).apply { marginStart = dp(8) }
    })
    card.addView(top)
    val statusColor = when (status) {
      "done" -> p.ok
      "error", "cancelled" -> p.risk
      else -> p.accentHi
    }
    if (status.isNotBlank()) {
      val statusView = bodyText(statusLabel(status), 11f, statusColor)
      statusViews[id] = statusView
      card.addView(statusView)
    }
    val steps = item.optJSONArray("steps") ?: JSONArray()
    val latestStep = if (steps.length() > 0) steps.optJSONObject(steps.length() - 1) else null
    if (latestStep != null && (status == "running" || status == "reading")) {
      val stepView = bodyText(latestStep.optString("text"), 11f, p.ink2)
      stepViews[id] = stepView
      card.addView(stepView)
    }
    val error = item.optString("error")
    val answer = item.optString("text")
    if (error.isNotBlank()) card.addView(errorText(error))
    if (answer.isNotBlank()) {
      val answerView = answerText(answer, item.optJSONArray("sources") ?: JSONArray())
      answerViews[id] = answerView
      card.addView(answerView)
    }
    addSources(card, item.optJSONArray("sources") ?: JSONArray())
    list.addView(card)
    if (active) card.addView(
      button(L("cancel"), p.riskWash, p.risk, tint(p.risk, 0.16f)) { emitAction("cancel", id) },
      LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(34)).apply { topMargin = dp(6) },
    )
  }

  /** The clickable sources under an answer, headed by the translated word. */
  private fun addSources(card: LinearLayout, sources: JSONArray) {
    val rows = mutableListOf<Pair<String, String>>()
    for (index in 0 until minOf(sources.length(), 4)) {
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

  private fun requestCapture(mode: String = "research", siteUrl: String = "") {
    if (!isActive || capturePending) return
    cancelPanelTransition()
    capturePending = true
    scanGeneration += 1
    val thisScan = scanGeneration
    captureMode = mode
    reviewSite = siteUrl
    bubble?.visibility = View.GONE
    panel?.visibility = View.GONE
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
      mainHandler.post {
        if (uiDirty) {
          uiDirty = false
          refreshUi()
        }
        bubble?.let { it.visibility = View.VISIBLE; animateIn(it, 0.96f, 180L) }
        showResultPanel()
      }
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
      mainHandler.post {
        if (uiDirty) {
          uiDirty = false
          refreshUi()
        }
        bubble?.let { it.visibility = View.VISIBLE; animateIn(it, 0.96f, 180L) }
        showResultPanel()
      }
      showToast(L("captureFailed"))
    }
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
    val restorePanel = panel != null
    val mode = panelMode
    if (uiDirty) {
      uiDirty = false
      refreshUi()
      if (restorePanel && panel == null) togglePanel(mode)
    }
    bubble?.let { animateIn(it, 0.92f, 210L) }
    panel?.let { animateIn(it, 0.95f, 210L) }
  }

  private fun showResultPanel() {
    if (panel == null) {
      togglePanel("current")
      return
    }
    panelCloseGeneration += 1
    panelIsClosing = false
    panelTransitionGeneration += 1
    panelSwitching = false
    pendingPanelMode = null
    panelMode = "current"
    renderedSignature = null
    renderPanel()
    panel?.let { animateIn(it, 0.95f, 230L) }
  }

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
        val nextScale = fromScaleX + (scale - fromScaleX) * fraction
        view.scaleX = nextScale
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

  private fun hidePanelAnimated() {
    val target = panel ?: return
    panelCloseGeneration += 1
    val generation = panelCloseGeneration
    panelIsClosing = true
    cancelPanelTransition()
    animateView(target, 0f, 0.96f, -dp(3).toFloat(), 180L, spring = false) {
      if (generation == panelCloseGeneration && panel === target) removePanel()
    }
  }

  private fun cancelPanelTransition() {
    panelTransitionGeneration += 1
    panelSwitching = false
    pendingPanelMode = null
    jobList?.let {
      activeMotion.remove(it)?.cancel()
      it.alpha = 1f
      it.scaleX = 1f
      it.scaleY = 1f
      it.translationY = 0f
    }
  }

  private fun openSource(url: String) {
    try {
      startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (_: Exception) {
      showToast(L("sourceFailed"))
    }
  }

  /** A pill button with a ripple that clips to its own radius. */
  private fun button(
    label: String,
    backgroundColor: Int,
    foregroundColor: Int,
    rippleColor: Int,
    strokeColor: Int = Color.TRANSPARENT,
    heightDp: Int = 34,
    onClick: () -> Unit,
  ): TextView = TextView(this).apply {
    text = label
    setTextColor(foregroundColor)
    textSize = 12f
    typeface = geistMedium
    gravity = Gravity.CENTER
    includeFontPadding = false
    contentDescription = label
    setPadding(dp(12), 0, dp(12), 0)
    background = capsule(backgroundColor, 17, strokeColor, rippleColor)
    installPressMotion(this)
    setOnClickListener { onClick() }
    layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(heightDp))
      .apply { marginStart = dp(8) }
  }

  private fun tabButton(label: String, onClick: () -> Unit): TextView = TextView(this).apply {
    text = label
    textSize = 12f
    typeface = geistMedium
    gravity = Gravity.CENTER
    includeFontPadding = false
    setTextColor(palette.ink2)
    setPadding(dp(8), 0, dp(8), 0)
    installPressMotion(this)
    setOnClickListener { onClick() }
  }

  /** A short scale on press; the ripple comes from the background drawable. */
  private fun installPressMotion(view: View) {
    view.setOnTouchListener { pressedView, event ->
      when (event.actionMasked) {
        MotionEvent.ACTION_DOWN -> animateView(pressedView, 1f, 0.96f, 0f, 90L, spring = true)
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
    textSize = 10.5f
    typeface = geistSemiBold
    letterSpacing = 0.06f
    setPadding(0, dp(9), 0, dp(3))
  }

  private fun errorText(message: String) = TextView(this).apply {
    text = message
    setTextColor(palette.risk)
    textSize = 12f
    typeface = geistRegular
    setLineSpacing(dp(2).toFloat(), 1f)
    background = capsule(palette.riskWash, 10, Color.TRANSPARENT)
    setPadding(dp(9), dp(7), dp(9), dp(7))
    layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
      .apply { topMargin = dp(5) }
  }

  private fun sourceRow(label: String, url: String) = TextView(this).apply {
    text = label
    setTextColor(palette.accentHi)
    textSize = 12f
    typeface = geistMedium
    maxLines = 2
    contentDescription = label
    setPadding(dp(8), dp(5), dp(8), dp(5))
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
      textSize = 13.5f
      typeface = geistRegular
      setLineSpacing(dp(3).toFloat(), 1f)
      setPadding(0, dp(7), 0, dp(5))
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
  private fun overlayParams(width: Int, height: Int, gravity: Int): WindowManager.LayoutParams {
    val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
    } else {
      WindowManager.LayoutParams.TYPE_PHONE
    }
    return WindowManager.LayoutParams(
      width, height, type,
      WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
        or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
      PixelFormat.TRANSLUCENT,
    ).apply {
      this.gravity = gravity
    alpha = 1f
    }
  }

  private fun installDrag(view: View, params: WindowManager.LayoutParams, windowView: View = view) {
    var downX = 0f
    var downY = 0f
    var startX = 0
    var startY = 0
    var moved = false
    val touchSlop = ViewConfiguration.get(this).scaledTouchSlop
    view.setOnTouchListener { _, event ->
      when (event.action) {
        MotionEvent.ACTION_DOWN -> {
          downX = event.rawX; downY = event.rawY
          startX = params.x; startY = params.y
          moved = false
          animateView(view, 1f, 0.96f, 0f, 90L, spring = true)
          true
        }
        MotionEvent.ACTION_MOVE -> {
          val dx = (event.rawX - downX).roundToInt()
          val dy = (event.rawY - downY).roundToInt()
          if (kotlin.math.abs(dx) + kotlin.math.abs(dy) > touchSlop) moved = true
          if (moved) {
            val bounds = displayBounds()
            params.x = (startX + dx).coerceIn(0, (bounds.width() - windowView.width).coerceAtLeast(0))
            params.y = (startY + dy).coerceIn(0, (bounds.height() - windowView.height).coerceAtLeast(0))
            try { windowManager.updateViewLayout(windowView, params) } catch (_: Exception) { }
          }
          true
        }
        MotionEvent.ACTION_UP -> {
          animateView(view, 1f, 1f, 0f, 150L, spring = true)
          if (!moved) view.performClick()
          true
        }
        MotionEvent.ACTION_CANCEL -> {
          animateView(view, 1f, 1f, 0f, 150L, spring = true)
          true
        }
        else -> true
      }
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

  /**
   * The K grip: a top-lit blue gradient, a hairline inner highlight and a small
   * grip line under the mark. The drag owns the touch stream, so press feedback
   * is the scale in `installDrag`, not a ripple.
   */
  private fun handleBackground(p: Palette): Drawable = GradientDrawable(
    GradientDrawable.Orientation.TOP_BOTTOM,
    intArrayOf(mix(p.accent, ON_ACCENT, 0.18f), p.accent),
  ).apply {
    shape = GradientDrawable.RECTANGLE
    cornerRadius = dp(15).toFloat()
    setStroke(dp(1), tint(ON_ACCENT, 0.22f))
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

  private fun removePanel() {
    panelCloseGeneration += 1
    panelIsClosing = false
    cancelPanelTransition()
    panel?.let {
      activeMotion.remove(it)?.cancel()
      try { windowManager.removeView(it) } catch (_: Exception) { }
    }
    panel = null
    panelParams = null
    siteUrlInput = null
    jobList = null
    panelScroll = null
    renderedSignature = null
    answerViews.clear()
    stepViews.clear()
    currentTab = null
    queueTab = null
    siteActionView = null
    statusViews.clear()
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
    val params = panelParams ?: return
    params.flags = params.flags and WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE.inv()
    params.softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
    try { panel?.let { windowManager.updateViewLayout(it, params) } } catch (_: Exception) { }
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
    removePanel()
    stopDot()
    bubble?.let {
      activeMotion.remove(it)?.cancel()
      try { windowManager.removeView(it) } catch (_: Exception) { }
    }
    bubble = null
    bubbleHandle = null
    bubbleScanView = null
    bubbleQueueChip = null
    bubbleQueueLabel = null
    bubbleQueueBadge = null
    bubbleDot = null
    bubbleStopView = null
    bubbleParams = null
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

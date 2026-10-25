package __PACKAGE__.overlay

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Rect
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
import android.text.InputType
import android.text.TextUtils
import android.util.Base64
import android.util.DisplayMetrics
import android.view.Display
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowManager
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import com.facebook.react.bridge.Arguments
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.util.concurrent.Executors
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * The floating scanner, in three pieces that never cover each other:
 *
 *  - the **puck**: a small page with a K on it that the reader drags anywhere.
 *    It snaps to the nearest screen edge, rests half-transparent (the reader
 *    sets how much), sweeps a band of light while research runs, turns over
 *    when an answer is ready and shows a green count for the ones waiting;
 *  - the **tray**: tap the puck and a small card opens beside it with one big
 *    action (Scan this page), the results, and, deliberately apart, Stop;
 *  - the **sheet**: the answer, pinned to the top of the screen under the
 *    status bar, with the picture of the scanned page beside its title, the
 *    answer set as short blocks and the other scans as chips under it.
 *
 * The scanner outlives everything but the reader's own Stop. When Android ends
 * the screen capture (it does so when the phone locks) the puck stays, goes
 * grey, and asks for capture again the next time the reader presses Scan.
 */
class KrikoOverlayService : Service() {
  companion object {
    const val ACTION_START = "__PACKAGE__.overlay.START"
    const val ACTION_STOP = "__PACKAGE__.overlay.STOP"
    const val ACTION_UPDATE = "__PACKAGE__.overlay.UPDATE"
    const val ACTION_UI = "__PACKAGE__.overlay.UI"
    const val ACTION_APP = "__PACKAGE__.overlay.APP"
    /** Capture consent arrived from the re-arm screen (see [KrikoCaptureActivity]). */
    const val ACTION_PROJECTION = "__PACKAGE__.overlay.PROJECTION"
    const val ACTION_PROJECTION_DENIED = "__PACKAGE__.overlay.PROJECTION_DENIED"
    const val EXTRA_FOREGROUND = "foreground"
    const val EXTRA_RESULT_CODE = "resultCode"
    const val EXTRA_RESULT_DATA = "resultData"
    const val EXTRA_JOBS = "jobs"
    const val EXTRA_UI = "ui"
    private const val CHANNEL_ID = "kriko_screen_scan"
    private const val NOTIFICATION_ID = 7406
    private const val PUCK_PAD_DP = 7
    private const val EDGE_DP = 4
    private const val TRAY_DP = 232
    private const val SETTLE_AFTER_MS = 4200L
    private const val CAPTURE_WATCHDOG_MS = 6500L

    /** A scanner session exists: the puck is up, whether or not capture is live. */
    @Volatile var isActive: Boolean = false
      private set

    /** Android's screen-capture grant is held, so Scan can answer without asking. */
    @Volatile var captureLive: Boolean = false
      private set
  }

  private lateinit var windowManager: WindowManager
  private lateinit var ui: KrikoUi
  private lateinit var fonts: KrikoFonts
  private lateinit var answer: KrikoAnswer
  private val motion = KrikoMotion()
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
  private var lastReady = 0
  /** A scan the reader asked for while capture was paused; it runs once consent returns. */
  private var pendingResume: Pair<String, String>? = null
  private val imageWorker = Executors.newSingleThreadExecutor()
  private var thumbPath = ""
  private var thumbBitmap: Bitmap? = null

  private val palette: Palette get() = ui.palette

  // The puck.
  private var puck: FrameLayout? = null
  private var puckView: KrikoPuckView? = null
  private var puckParams: WindowManager.LayoutParams? = null
  private var puckBadge: TextView? = null
  private var puckSnap: android.animation.ValueAnimator? = null
  private var puckYBeforeSheet: Int? = null

  // The tray.
  private var tray: View? = null
  private var trayParams: WindowManager.LayoutParams? = null
  private var trayClosedAt = 0L
  private var trayBadge: TextView? = null

  // The sheet.
  private var sheet: View? = null
  private var sheetParams: WindowManager.LayoutParams? = null
  private var sheetThumb: ScanThumb? = null
  private var sheetTitle: TextView? = null
  private var sheetStatus: TextView? = null
  private var sheetBar: View? = null
  private var sheetScroll: CappedScroll? = null
  private var sheetBody: LinearLayout? = null
  private var sheetChips: LinearLayout? = null
  private var sheetChipsScroll: View? = null
  private var sheetActions: LinearLayout? = null
  private var siteUrlInput: EditText? = null
  private var siteSection: View? = null
  private var siteOpen = false
  private var answerBox: LinearLayout? = null
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
  @Volatile private var captureMode = "research"
  @Volatile private var reviewSite = ""
  private val mainHandler = Handler(android.os.Looper.getMainLooper())
  private val settleRunnable = Runnable { settlePuck() }
  private val captureWatchdog = Runnable {
    if (capturePending) {
      finishCapture(null)
      showToast(L("captureFailed"))
    }
  }
  private val projectionCallback = object : MediaProjection.Callback() {
    override fun onStop() = onProjectionStopped()
  }

  override fun onCreate() {
    super.onCreate()
    windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
    ui = KrikoUi(this).loadSaved()
    fonts = KrikoFonts(this)
    answer = KrikoAnswer(this, ui, fonts) { openSource(it) }
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
      ACTION_START, ACTION_PROJECTION -> {
        if (isActive && !shuttingDown) {
          if (!captureLive) attachProjection(intent)
        } else {
          startProjection(intent)
        }
      }
      ACTION_PROJECTION_DENIED -> {
        pendingResume = null
        showToast(L("resumeFailed"))
      }
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
      val current = manager.getMediaProjection(resultCode, data)
        ?: throw IllegalStateException("Android could not start the screen capture session.")
      setupCapture(current)
      if (!Settings.canDrawOverlays(this)) throw IllegalStateException("Overlay permission was revoked.")
      isActive = true
      showPuck()
      sendSession(true, paused = false)
      KrikoOverlayModule.serviceReady()
      // Once the reader has left the app for their own page, show what to do a
      // single time, so the first thing on that screen is the button that matters.
      hintPending = true
    } catch (error: Exception) {
      failStart(error.message ?: "Could not start the screen scan session.")
    }
  }

  /**
   * Capture consent came back to a session that survived the last grant (the
   * phone locked, or the system's own cast control stopped it). Reuse the
   * windows already on screen and carry on with the scan that asked for it.
   */
  private fun attachProjection(intent: Intent) {
    val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, 0)
    val data = intent.getParcelableExtra<Intent>(EXTRA_RESULT_DATA)
    if (data == null || resultCode == 0) {
      pendingResume = null
      showToast(L("resumeFailed"))
      KrikoOverlayModule.startRejected("Screen capture permission data is missing. Start the session again.")
      return
    }
    try {
      startForeground(NOTIFICATION_ID, buildNotification())
      val manager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
      val current = manager.getMediaProjection(resultCode, data)
        ?: throw IllegalStateException("Android could not start the screen capture session.")
      setupCapture(current)
      syncPuck()
      updateNotification()
      sendSession(true, paused = false)
      KrikoOverlayModule.serviceReady()
      val resume = pendingResume
      pendingResume = null
      if (resume != null) {
        // Let the permission dialog finish leaving before the screen is read.
        mainHandler.postDelayed({
          if (isActive && !shuttingDown) requestCapture(resume.first, resume.second)
        }, 750)
      }
    } catch (error: Exception) {
      tearDownCapture(stopProjection = true)
      pendingResume = null
      syncPuck()
      showToast(L("resumeFailed"))
      KrikoOverlayModule.startRejected(error.message ?: "Could not start the screen scan session.")
    }
  }

  /** The projection, its reader and the display that feeds it. */
  private fun setupCapture(current: MediaProjection) {
    projection = current
    current.registerCallback(projectionCallback, mainHandler)
    val bounds = displayBounds()
    val density = resources.configuration.densityDpi
    val imageReader = ImageReader.newInstance(bounds.width(), bounds.height(), PixelFormat.RGBA_8888, 2)
    reader = imageReader
    captureThread = HandlerThread("KrikoOverlayCapture").also { it.start() }
    captureHandler = Handler(captureThread!!.looper)
    imageReader.setOnImageAvailableListener({ source -> onFrameAvailable(source) }, captureHandler)
    // The surface stays detached between user scans. The projection token and
    // virtual display remain alive, but no frames are delivered or retained.
    display = current.createVirtualDisplay(
      "KrikoOnDemandScreenScan", bounds.width(), bounds.height(), density,
      DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, null, null, mainHandler,
    )
    captureLive = true
  }

  private fun tearDownCapture(stopProjection: Boolean) {
    captureLive = false
    capturePending = false
    mainHandler.removeCallbacks(captureWatchdog)
    try { display?.setSurface(null) } catch (_: Exception) { }
    try { display?.release() } catch (_: Exception) { }
    display = null
    try { reader?.setOnImageAvailableListener(null, null) } catch (_: Exception) { }
    try { reader?.close() } catch (_: Exception) { }
    reader = null
    captureThread?.quitSafely()
    captureThread = null
    captureHandler = null
    projection?.let { current ->
      try { current.unregisterCallback(projectionCallback) } catch (_: Exception) { }
      if (stopProjection) try { current.stop() } catch (_: Exception) { }
    }
    projection = null
  }

  /**
   * Android ended the capture grant: the phone locked, the reader pressed the
   * system's own stop control, or the system reclaimed it. The scanner is not
   * over. The puck stays, shows it is paused, and the next Scan asks again.
   */
  private fun onProjectionStopped() {
    if (shuttingDown || !isActive) return
    tearDownCapture(stopProjection = false)
    restoreWindows()
    syncPuck()
    updateNotification()
    sendSession(true, paused = true)
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

  /** The height of the status bar (and any cut-out), so the sheet starts below it. */
  private fun statusBarInset(): Int {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
      try {
        val insets = windowManager.currentWindowMetrics.windowInsets.getInsetsIgnoringVisibility(
          WindowInsets.Type.statusBars() or WindowInsets.Type.displayCutout())
        if (insets.top > 0) return insets.top
      } catch (_: Exception) { }
    }
    val id = resources.getIdentifier("status_bar_height", "dimen", "android")
    return if (id > 0) resources.getDimensionPixelSize(id) else dp(26)
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
  private fun L(key: String): String = ui.label(key)

  // ------------------------------------------------------------------ UI feed --

  /**
   * Read `{ theme, labels, puckOpacity }` without touching views. Called before
   * the first puck exists, so the window is built in the right palette already.
   */
  private fun readUi(json: String) {
    if (!ui.apply(json)) return
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
    puck?.let { motion.animateIn(it, 0.9f, 220L) }
    sheet?.let { motion.animateIn(it, 0.97f, 200L, fromTranslationY = -dp(10).toFloat()) }
  }

  /** Hide whatever a rebuild just created if Kriko's own screen is in front. */
  private fun hideWhileInApp() {
    if (!appForeground) return
    puck?.visibility = View.GONE
    sheet?.visibility = View.GONE
  }

  /**
   * Replace the ongoing notification's words without touching the foreground
   * state: re-declaring the capture type needs a live grant, which a paused
   * session does not have.
   */
  private fun updateNotification() {
    if (!isActive || shuttingDown) return
    try {
      (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).notify(NOTIFICATION_ID, buildNotification())
    } catch (_: Exception) { }
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
      .setContentText(if (captureLive || !isActive) L("notificationText") else L("notificationPausedText"))
      .setColor(palette.accent)
      .setOngoing(true)
      .addAction(android.R.drawable.ic_menu_close_clear_cancel, L("stopSharing"), pending)
      .build()
  }

  private fun createNotificationChannel() {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O || !::ui.isInitialized) return
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
   * One page-shaped K. The window is the page plus a little air for the badge;
   * the reader drags it anywhere and it settles on the nearest edge.
   */
  private fun showPuck() {
    if (puck != null || !Settings.canDrawOverlays(this)) return
    val p = palette
    val view = KrikoPuckView(this, ui, fonts)
    puckView = view
    val root = FrameLayout(this).apply {
      clipChildren = false
      clipToPadding = false
      contentDescription = L("dragHint")
    }
    root.addView(view, FrameLayout.LayoutParams(dp(KrikoPuckView.PAGE_W_DP), dp(KrikoPuckView.PAGE_H_DP)).apply {
      setMargins(dp(PUCK_PAD_DP), dp(PUCK_PAD_DP), dp(PUCK_PAD_DP), dp(PUCK_PAD_DP))
    })
    val badge = TextView(this).apply {
      setTextColor(KrikoTheme.ON_ACCENT)
      textSize = 10.5f
      typeface = fonts.semiBold
      includeFontPadding = false
      gravity = Gravity.CENTER
      background = capsule(p.ok, 9, p.panel)
      minWidth = dp(18)
      setPadding(dp(5), dp(1), dp(5), dp(1))
      visibility = View.GONE
    }
    puckBadge = badge
    root.addView(badge, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(18),
      Gravity.TOP or Gravity.END).apply { setMargins(0, dp(1), dp(1), 0) })

    puck = root
    val width = dp(KrikoPuckView.PAGE_W_DP + PUCK_PAD_DP * 2)
    val bounds = displayBounds()
    puckParams = overlayParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
      Gravity.TOP or Gravity.START).apply {
      x = bounds.width() - width - dp(EDGE_DP)
      y = dp(210)
    }
    root.alpha = 0f
    root.scaleX = 0.8f
    root.scaleY = 0.8f
    installPuckTouch(root)
    windowManager.addView(root, puckParams)
    if (appForeground) root.visibility = View.GONE else motion.animateIn(root, 0.8f, 260L)
    lastReady = readyCount()
    syncPuck()
    scheduleSettle()
  }

  /** Scanning sweep while research runs, a grey page while capture is paused. */
  private fun syncPuck() {
    val running = activeCount() > 0
    val view = puckView
    view?.setMode(when {
      running -> KrikoPuckView.Mode.SCANNING
      !captureLive -> KrikoPuckView.Mode.PAUSED
      else -> KrikoPuckView.Mode.IDLE
    })
    val ready = readyCount()
    puckBadge?.let { badge ->
      badge.text = ready.toString()
      badge.visibility = if (ready > 0) View.VISIBLE else View.GONE
      badge.background = capsule(palette.ok, 9, palette.panel)
    }
    // An answer arriving is the one thing worth turning the page over for.
    if (ready > lastReady && puck?.visibility == View.VISIBLE) view?.flip()
    lastReady = ready
    puck?.contentDescription = when {
      ready > 0 -> "${L("dragHint")} · ${L("results")} $ready"
      running -> "${L("dragHint")} · ${L("running")}"
      !captureLive -> "${L("dragHint")} · ${L("paused")}"
      else -> L("dragHint")
    }
    if (running || ready > 0) wakePuck() else scheduleSettle()
  }

  private fun wakePuck() {
    mainHandler.removeCallbacks(settleRunnable)
    puckView?.awaken()
  }

  private fun scheduleSettle() {
    mainHandler.removeCallbacks(settleRunnable)
    mainHandler.postDelayed(settleRunnable, SETTLE_AFTER_MS)
  }

  /** Back to the reader's chosen opacity once nothing wants their attention. */
  private fun settlePuck() {
    // Idle means nothing is open, nothing is running and nothing is waiting.
    if (tray != null || sheet != null || activeCount() > 0 || readyCount() > 0) return
    if (puck?.visibility == View.VISIBLE) puckView?.settle()
  }

  /** Slide the puck to the nearer screen edge once the finger lets go. */
  private fun snapPuck() {
    val view = puck ?: return
    val params = puckParams ?: return
    val bounds = displayBounds()
    val width = if (view.width > 0) view.width else dp(KrikoPuckView.PAGE_W_DP + PUCK_PAD_DP * 2)
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
    puckSnap = android.animation.ValueAnimator.ofFloat(0f, 1f).apply {
      duration = 260
      interpolator = motion.spring
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
          mainHandler.removeCallbacks(settleRunnable)
          puckView?.awaken()
          puckView?.setPress(true)
          true
        }
        MotionEvent.ACTION_MOVE -> {
          val dx = (event.rawX - downX).roundToInt()
          val dy = (event.rawY - downY).roundToInt()
          if (abs(dx) + abs(dy) > touchSlop) moved = true
          if (moved) {
            val bounds = displayBounds()
            params.x = (startX + dx).coerceIn(0, (bounds.width() - view.width).coerceAtLeast(0))
            params.y = (startY + dy).coerceIn(0, (bounds.height() - view.height).coerceAtLeast(0))
            try { windowManager.updateViewLayout(view, params) } catch (_: Exception) { }
            // The reader chose this spot; do not put the puck back when the sheet closes.
            puckYBeforeSheet = null
            // A tray that stays behind while the puck moves points at nothing.
            if (tray != null) removeTray(animated = false)
          }
          true
        }
        MotionEvent.ACTION_UP -> {
          puckView?.setPress(false)
          if (moved) {
            snapPuck()
            scheduleSettle()
          } else {
            view.performClick()
            onPuckTap()
          }
          true
        }
        MotionEvent.ACTION_CANCEL -> {
          puckView?.setPress(false)
          scheduleSettle()
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
      outlineProvider = KrikoDraw.roundOutline(this@KrikoOverlayService, 22)
      clipToOutline = true
      setPadding(dp(10), dp(10), dp(10), dp(6))
    }
    if (!captureLive) {
      card.addView(TextView(this).apply {
        text = L("paused")
        setTextColor(p.ink3)
        textSize = 11.5f
        typeface = fonts.medium
        includeFontPadding = false
        gravity = Gravity.CENTER_VERTICAL
        setPadding(dp(6), 0, dp(6), 0)
      }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(24)).apply { bottomMargin = dp(4) })
    }
    card.addView(
      actionRow("scan", L("scanPage"), p.accent, KrikoTheme.ON_ACCENT, tint(KrikoTheme.ON_ACCENT, 0.24f), Color.TRANSPARENT, 52, 15f) {
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
      setTextColor(KrikoTheme.ON_ACCENT)
      textSize = 10.5f
      typeface = fonts.semiBold
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
    val puckWidth = if (anchor.width > 0) anchor.width else dp(KrikoPuckView.PAGE_W_DP + PUCK_PAD_DP * 2)
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
    motion.animateIn(card, 0.92f, 220L)
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
      motion.cancel(view)
      try { windowManager.removeView(view) } catch (_: Exception) { }
    }
    if (animated && animationsEnabled()) {
      motion.animate(view, 0f, 0.94f, 0f, 140L, spring = false) { dispose() }
    } else {
      dispose()
    }
    scheduleSettle()
  }

  // -------------------------------------------------------------------- sheet --

  /**
   * The answer sheet. It hangs from the top of the screen, under the status bar,
   * where a glance finds it and the reader's own page stays visible below.
   */
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
    val bodyCapDp = (screenHeightDp * 0.62 - 205).toInt().coerceIn(110, 470)

    val root = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      background = capsule(p.panel, 26, p.edge)
      elevation = dp(20).toFloat()
      outlineProvider = KrikoDraw.roundOutline(this@KrikoOverlayService, 26)
      clipToOutline = true
      setPadding(dp(16), dp(14), dp(16), dp(12))
    }

    val header = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    val thumb = ScanThumb(this, ui, fonts)
    sheetThumb = thumb
    header.addView(thumb, LinearLayout.LayoutParams(dp(46), dp(58)).apply { marginEnd = dp(12) })
    val titleColumn = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    val title = TextView(this).apply {
      setTextColor(p.ink)
      textSize = 16f
      typeface = fonts.semiBold
      maxLines = 2
      ellipsize = TextUtils.TruncateAt.END
    }
    sheetTitle = title
    titleColumn.addView(title, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
    val status = TextView(this).apply {
      textSize = 11f
      typeface = fonts.medium
      includeFontPadding = false
      gravity = Gravity.CENTER
      setPadding(dp(9), dp(4), dp(9), dp(4))
      visibility = View.GONE
    }
    sheetStatus = status
    titleColumn.addView(status, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
      topMargin = dp(6)
    })
    header.addView(titleColumn, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
    val close = TextView(this).apply {
      text = "×"
      setTextColor(p.ink2)
      textSize = 26f
      typeface = fonts.regular
      includeFontPadding = false
      gravity = Gravity.CENTER
      contentDescription = L("close")
      background = capsule(Color.TRANSPARENT, 22, Color.TRANSPARENT, tint(p.ink, 0.10f))
      motion.pressMotion(this)
      setOnClickListener { hideSheetAnimated() }
    }
    header.addView(close, LinearLayout.LayoutParams(dp(44), dp(44)).apply { marginStart = dp(4); marginEnd = -dp(8) })
    root.addView(header)
    installSheetDrag(header, root)

    val bar = IndeterminateBar(this, tint(p.ink, 0.08f), p.accentHi)
    bar.visibility = View.GONE
    sheetBar = bar
    root.addView(bar, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(3)).apply {
      topMargin = dp(10)
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
      setPadding(0, dp(4), 0, dp(4))
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
      Gravity.TOP or Gravity.CENTER_HORIZONTAL).apply {
      y = statusBarInset() + dp(8)
      softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
    }
    root.alpha = 0f
    root.scaleX = 0.97f
    root.scaleY = 0.97f
    root.translationY = -dp(26).toFloat()
    root.pivotX = (dp(sheetWidthDp) / 2).toFloat()
    root.pivotY = 0f
    windowManager.addView(root, sheetParams)
    if (appForeground) root.visibility = View.GONE
    else motion.animateIn(root, 0.97f, 260L, fromTranslationY = -dp(26).toFloat())
    root.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> keepPuckClearOfSheet() }
    wakePuck()
    renderedSignature = null
    renderSheet()
  }

  /** Dragging the header upward folds the sheet away, the way a notification goes. */
  private fun installSheetDrag(handle: View, target: View) {
    var downY = 0f
    var dragging = false
    val slop = ViewConfiguration.get(this).scaledTouchSlop
    handle.setOnTouchListener { _, event ->
      when (event.actionMasked) {
        MotionEvent.ACTION_DOWN -> {
          downY = event.rawY
          dragging = false
          true
        }
        MotionEvent.ACTION_MOVE -> {
          val dy = event.rawY - downY
          if (!dragging && dy < -slop) dragging = true
          if (dragging) {
            motion.cancel(target)
            target.translationY = dy.coerceAtMost(0f)
            target.alpha = (1f + dy / dp(220)).coerceIn(0.35f, 1f)
          }
          true
        }
        MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
          if (dragging && target.translationY < -dp(54)) {
            hideSheetAnimated()
          } else if (dragging) {
            motion.animate(target, 1f, 1f, 0f, 220L, spring = true)
          }
          dragging = false
          true
        }
        else -> true
      }
    }
  }

  /** If the sheet would cover the puck, move the puck just below it until the sheet closes. */
  private fun keepPuckClearOfSheet() {
    val params = puckParams ?: return
    val view = puck ?: return
    val shown = sheet ?: return
    val sheetTop = sheetParams?.y ?: return
    val bounds = displayBounds()
    val sheetBottom = sheetTop + shown.height + dp(8)
    val puckHeight = if (view.height > 0) view.height else dp(KrikoPuckView.PAGE_H_DP + PUCK_PAD_DP * 2)
    val overlaps = params.y < sheetBottom && params.y + puckHeight > sheetTop
    if (!overlaps) return
    if (puckYBeforeSheet == null) puckYBeforeSheet = params.y
    val target = sheetBottom.coerceAtMost((bounds.height() - puckHeight - dp(24)).coerceAtLeast(dp(24)))
    if (target == params.y) return
    params.y = target
    try { windowManager.updateViewLayout(view, params) } catch (_: Exception) { }
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
      typeface = fonts.regular
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
      typeface = fonts.medium
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
      append(item?.optString("image").orEmpty()).append('|')
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

    sheetTitle?.text = item?.optString("title")?.ifBlank { L("productScan") } ?: L("assistTitle")
    val active = isActiveStatus(status)
    sheetBar?.visibility = if (active) View.VISIBLE else View.GONE
    sheetThumb?.setActive(active)
    showJobImage(item)
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
    answerBox = null
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
      val text = item.optString("text")
      if (text.isNotBlank()) {
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        answerBox = box
        body.addView(box, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        answer.render(box, text, item.optJSONArray("sources") ?: JSONArray())
      } else if (active) {
        // Nothing has arrived yet: show where the words will go.
        body.addView(SkeletonView(this, tint(p.ink, 0.07f), tint(p.ink, 0.12f)),
          LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
            topMargin = dp(10)
            bottomMargin = dp(4)
          })
      }
      addSources(body, item.optJSONArray("sources") ?: JSONArray())
    }

    renderChips()
    renderActions(active, id, item?.optString("text").orEmpty())
    sheetScroll?.post { sheetScroll?.scrollTo(0, priorScroll) }
  }

  /** Streaming text and the latest step change far more often than the layout does. */
  private fun updateLiveViews(item: JSONObject?) {
    if (item == null) return
    answerBox?.let { box ->
      answer.render(box, item.optString("text"), item.optJSONArray("sources") ?: JSONArray())
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
    motion.animate(view, 1f, 1f, 0f, 135L, spring = false)
  }

  /** The scanned page's picture beside the title, decoded off the main thread. */
  private fun showJobImage(item: JSONObject?) {
    val thumb = sheetThumb ?: return
    val raw = item?.optString("image").orEmpty()
    val path = if (raw.startsWith("file:")) Uri.parse(raw).path.orEmpty() else raw
    if (path.isBlank()) {
      thumb.setBitmap(null)
      return
    }
    val cached = thumbBitmap
    if (path == thumbPath && cached != null) {
      thumb.setBitmap(cached)
      return
    }
    thumb.setBitmap(null)
    val width = dp(92)
    val height = dp(116)
    imageWorker.execute {
      val decoded = decodeThumb(path, width, height)
      mainHandler.post {
        if (decoded != null) {
          thumbPath = path
          thumbBitmap = decoded
        }
        val stillThis = currentJob()?.optString("image").orEmpty().let {
          (if (it.startsWith("file:")) Uri.parse(it).path.orEmpty() else it) == path
        }
        if (stillThis) sheetThumb?.setBitmap(decoded)
      }
    }
  }

  private fun decodeThumb(path: String, wantWidth: Int, wantHeight: Int): Bitmap? = try {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeFile(path, bounds)
    var sample = 1
    while (bounds.outWidth / (sample * 2) >= wantWidth && bounds.outHeight / (sample * 2) >= wantHeight) sample *= 2
    BitmapFactory.decodeFile(path, BitmapFactory.Options().apply { inSampleSize = sample })
  } catch (_: Exception) {
    null
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
      motion.pressMotion(this)
      setOnClickListener {
        selectedJob = id
        renderedSignature = null
        renderSheet()
      }
      addView(View(this@KrikoOverlayService).apply { background = KrikoDraw.circle(dot) },
        LinearLayout.LayoutParams(dp(7), dp(7)).apply { marginEnd = dp(7) })
      addView(TextView(this@KrikoOverlayService).apply {
        text = label
        setTextColor(if (selected) p.ink else p.ink2)
        textSize = 12.5f
        typeface = fonts.medium
        includeFontPadding = false
        maxLines = 1
      })
      layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(34)).apply { marginEnd = dp(6) }
    }
  }

  private fun renderActions(active: Boolean, id: String, answerText: String) {
    val row = sheetActions ?: return
    val p = palette
    row.removeAllViews()
    row.addView(
      actionRow("scan", L(if (jobs.length() == 0) "scanPage" else "scanAgain"), p.accent, KrikoTheme.ON_ACCENT,
        tint(KrikoTheme.ON_ACCENT, 0.24f), Color.TRANSPARENT, 46, 14f) {
        requestCapture("research")
      },
      LinearLayout.LayoutParams(0, dp(46), 1f),
    )
    if (answerText.isNotBlank()) {
      row.addView(
        iconButton("copy", L("copy")) { copyAnswer(answerText) },
        LinearLayout.LayoutParams(dp(46), dp(46)).apply { marginStart = dp(8) },
      )
    }
    if (active && id.isNotBlank()) {
      row.addView(
        actionRow(null, L("cancel"), p.riskWash, p.risk, tint(p.risk, 0.16f), Color.TRANSPARENT, 46, 13.5f) {
          emitAction("cancel", id)
        },
        LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(46)).apply { marginStart = dp(8) },
      )
    }
  }

  private fun copyAnswer(markdown: String) {
    try {
      val clipboard = getSystemService(CLIPBOARD_SERVICE) as ClipboardManager
      clipboard.setPrimaryClip(ClipData.newPlainText("Kriko", KrikoMarkdown.plain(markdown)))
      showToast(L("copied"))
    } catch (_: Exception) { }
  }

  /** The clickable sources under an answer, each a numbered row with its site. */
  private fun addSources(card: LinearLayout, sources: JSONArray) {
    val rows = mutableListOf<Triple<String, String, String>>()
    for (index in 0 until minOf(sources.length(), 6)) {
      val source = sources.optJSONObject(index) ?: continue
      val url = safeHttpUrl(source.optString("url"))
      if (url.isBlank()) continue
      val host = (Uri.parse(url).host ?: "").removePrefix("www.")
      val label = source.optString("title").ifBlank { host.ifBlank { url } }
      val number = source.optString("n").ifBlank { (index + 1).toString() }
      rows.add(Triple(number, label, url))
    }
    if (rows.isEmpty()) return
    card.addView(sectionText(L("sources")))
    for ((number, label, url) in rows) card.addView(sourceRow(number, label, url))
  }

  private fun hideSheetAnimated() {
    val target = sheet ?: return
    cancelSheetFocus()
    motion.animate(target, 0f, 0.97f, -dp(14).toFloat(), 170L, spring = false) {
      if (sheet === target) removeSheet()
    }
    restorePuckHeight()
    scheduleSettle()
  }

  private fun cancelSheetFocus() {
    if (siteUrlInput?.hasFocus() == true) clearInputFocus()
  }

  private fun removeSheet() {
    val view = sheet
    if (view != null) {
      motion.cancel(view)
      try { windowManager.removeView(view) } catch (_: Exception) { }
    }
    sheet = null
    sheetParams = null
    sheetThumb = null
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
    answerBox = null
    stepView = null
    renderedSignature = null
    restorePuckHeight()
  }

  private fun removePuck() {
    puckSnap?.cancel()
    puckSnap = null
    mainHandler.removeCallbacks(settleRunnable)
    puck?.let {
      motion.cancel(it)
      try { windowManager.removeView(it) } catch (_: Exception) { }
    }
    puck = null
    puckView = null
    puckParams = null
    puckBadge = null
  }

  // ------------------------------------------------------------------ capture --

  private fun requestCapture(mode: String = "research", siteUrl: String = "") {
    if (!isActive || capturePending) return
    if (!captureLive || projection == null || display == null || reader == null) {
      resumeCapture(mode, siteUrl)
      return
    }
    capturePending = true
    scanGeneration += 1
    val thisScan = scanGeneration
    captureMode = mode
    reviewSite = siteUrl
    cancelSheetFocus()
    removeTray(animated = false)
    puck?.visibility = View.GONE
    sheet?.visibility = View.GONE
    // Whatever happens below, the windows come back: a scan that stalls must not
    // leave the reader with a scanner that has vanished.
    mainHandler.removeCallbacks(captureWatchdog)
    mainHandler.postDelayed(captureWatchdog, CAPTURE_WATCHDOG_MS)
    // Allow the OS compositor to remove our translucent windows before one
    // requested frame is routed to ImageReader.
    mainHandler.postDelayed({
      if (!capturePending || thisScan != scanGeneration) return@postDelayed
      if (display == null || reader == null) {
        finishCapture(null)
        return@postDelayed
      }
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

  /**
   * Capture was ended by the system. Ask for it again, then carry on with the
   * scan the reader pressed: one short permission screen, no trip into the app.
   */
  private fun resumeCapture(mode: String, siteUrl: String) {
    pendingResume = mode to siteUrl
    removeTray(animated = false)
    try {
      startActivity(Intent(this, KrikoCaptureActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (_: Exception) {
      pendingResume = null
      showToast(L("resumeFailed"))
    }
  }

  private fun onFrameAvailable(source: ImageReader) {
    val image = try { source.acquireLatestImage() } catch (_: Exception) { null }
    if (image == null) return
    if (!capturePending) {
      image.close()
      return
    }
    capturePending = false
    mainHandler.removeCallbacks(captureWatchdog)
    display?.setSurface(null)
    try {
      val jpeg = encode(image)
      image.close()
      if (jpeg == null) {
        mainHandler.post { afterCapture(openSheet = false) }
        showToast(L("captureFailed"))
        return
      }
      val uri = KrikoHandoff.writeFrame(this, jpeg)
      val mode = captureMode
      val site = reviewSite
      if (KrikoOverlayModule.jsReady) {
        mainHandler.post { afterCapture(openSheet = true) }
        val body = Arguments.createMap().apply {
          putString("base64", Base64.encodeToString(jpeg, Base64.NO_WRAP))
          putString("mime", "image/jpeg")
          putString("uri", uri ?: "")
          putString("mode", mode)
          if (mode == "site_reviews") putString("reviewSite", site)
        }
        KrikoOverlayModule.emit("onScan", body)
      } else {
        // Kriko's screen is gone (swiped away, or reclaimed). The scan is not
        // lost: it opens the app on a fresh chat that reads it.
        mainHandler.post {
          afterCapture(openSheet = false)
          if (uri == null) showToast(L("captureFailed")) else openApp(uri, mode, site)
        }
      }
    } catch (_: Exception) {
      image.close()
      mainHandler.post { afterCapture(openSheet = false) }
      showToast(L("captureFailed"))
    }
  }

  private fun openApp(uri: String, mode: String, site: String) {
    try {
      startActivity(KrikoHandoff.intent(this, uri, mode = mode, site = site))
    } catch (_: Exception) {
      showToast(L("resumeFailed"))
    }
  }

  /** Bring the puck back and show the new scan's progress where a thumb reaches it. */
  private fun afterCapture(openSheet: Boolean) {
    if (uiDirty) {
      uiDirty = false
      refreshUi()
    }
    puck?.let { if (!appForeground) motion.animateIn(it, 0.9f, 200L) }
    if (!openSheet) return
    // A new scan is what the reader is waiting on: show it, not an older pick.
    selectedJob = ""
    renderedSignature = null
    openSheet()
    sheet?.let { if (!appForeground) motion.animateIn(it, 0.97f, 240L, fromTranslationY = -dp(26).toFloat()) }
  }

  private fun encode(image: Image): ByteArray? {
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
    return out.toByteArray()
  }

  private fun finishCapture(image: Image?) {
    image?.close()
    capturePending = false
    mainHandler.removeCallbacks(captureWatchdog)
    try { display?.setSurface(null) } catch (_: Exception) { }
    if (uiDirty) {
      uiDirty = false
      refreshUi()
    }
    restoreWindows()
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
    motion.pressMotion(this)
    setOnClickListener { onClick() }
    if (glyph != null) {
      addView(GlyphView(this@KrikoOverlayService, glyph, foregroundColor),
        LinearLayout.LayoutParams(dp(20), dp(20)).apply { marginEnd = dp(9) })
    }
    addView(TextView(this@KrikoOverlayService).apply {
      text = label
      setTextColor(foregroundColor)
      textSize = textSp
      typeface = fonts.semiBold
      includeFontPadding = false
      maxLines = 1
      gravity = Gravity.CENTER
    })
  }

  /** A square-ish round button holding one glyph. */
  private fun iconButton(glyph: String, description: String, onClick: () -> Unit): View {
    val p = palette
    return FrameLayout(this).apply {
      background = capsule(p.raised, 23, p.edge, tint(p.ink, 0.08f))
      isClickable = true
      contentDescription = description
      motion.pressMotion(this)
      setOnClickListener { onClick() }
      addView(GlyphView(this@KrikoOverlayService, glyph, p.ink2),
        FrameLayout.LayoutParams(dp(20), dp(20), Gravity.CENTER))
    }
  }

  private fun bodyText(text: String, size: Float, color: Int) = TextView(this).apply {
    this.text = text
    setTextColor(color)
    textSize = size
    typeface = fonts.regular
    setLineSpacing(dp(2).toFloat(), 1f)
    setPadding(0, dp(4), 0, dp(2))
  }

  private fun sectionText(label: String) = TextView(this).apply {
    text = label.uppercase()
    setTextColor(palette.ink3)
    textSize = 11f
    typeface = fonts.semiBold
    letterSpacing = 0.08f
    setPadding(0, dp(18), 0, dp(4))
  }

  private fun errorText(message: String) = TextView(this).apply {
    text = message
    setTextColor(palette.risk)
    textSize = 12.5f
    typeface = fonts.regular
    setLineSpacing(dp(2).toFloat(), 1f)
    background = capsule(palette.riskWash, 12, Color.TRANSPARENT)
    setPadding(dp(11), dp(8), dp(11), dp(8))
    layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
      .apply { topMargin = dp(5) }
  }

  /** One source: its number, its title and the site it came from. */
  private fun sourceRow(number: String, label: String, url: String): View {
    val p = palette
    val host = (Uri.parse(url).host ?: "").removePrefix("www.")
    return LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
      setPadding(dp(6), dp(6), dp(8), dp(6))
      background = capsule(Color.TRANSPARENT, 10, Color.TRANSPARENT, tint(p.accentHi, 0.12f))
      isClickable = true
      contentDescription = label
      motion.pressMotion(this)
      setOnClickListener { openSource(url) }
      addView(TextView(this@KrikoOverlayService).apply {
        text = number
        setTextColor(p.accentHi)
        textSize = 11.5f
        typeface = fonts.semiBold
        includeFontPadding = false
        gravity = Gravity.CENTER
        background = capsule(tint(p.accent, if (p === KrikoTheme.DARK) 0.26f else 0.12f), 7, Color.TRANSPARENT)
      }, LinearLayout.LayoutParams(dp(22), dp(22)).apply { marginEnd = dp(10) })
      val column = LinearLayout(this@KrikoOverlayService).apply { orientation = LinearLayout.VERTICAL }
      column.addView(TextView(this@KrikoOverlayService).apply {
        text = label
        setTextColor(p.ink)
        textSize = 13f
        typeface = fonts.medium
        includeFontPadding = false
        maxLines = 1
        ellipsize = TextUtils.TruncateAt.END
      })
      if (host.isNotBlank() && host != label) {
        column.addView(TextView(this@KrikoOverlayService).apply {
          text = host
          setTextColor(p.ink3)
          textSize = 11f
          typeface = fonts.regular
          includeFontPadding = false
          maxLines = 1
          ellipsize = TextUtils.TruncateAt.END
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(3) })
      }
      addView(column, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
      layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        .apply { bottomMargin = dp(2) }
    }
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

  private fun capsule(color: Int, radiusDp: Int, strokeColor: Int, rippleColor: Int? = null) =
    KrikoDraw.capsule(this, color, radiusDp, strokeColor, rippleColor)

  private fun tint(color: Int, fraction: Float): Int = KrikoColor.tint(color, fraction)

  // ----------------------------------------------------------------- plumbing --

  private fun emitAction(action: String, id: String) {
    val body = Arguments.createMap().apply {
      putString("action", action)
      putString("id", id)
    }
    KrikoOverlayModule.emit("onAction", body)
  }

  private fun sendSession(active: Boolean, paused: Boolean = false) {
    val body = Arguments.createMap().apply {
      putBoolean("active", active)
      putBoolean("paused", paused)
    }
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

  /** The reader's own Stop, from the tray or the notification: the one way a session ends. */
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
    uiDirty = false
    pendingResume = null
    mainHandler.removeCallbacksAndMessages(null)
    tearDownCapture(stopProjection)
    removeTray(animated = false)
    removeSheet()
    removePuck()
  }

  override fun onDestroy() {
    if (isActive) {
      shuttingDown = true
      releaseResources(stopProjection = true)
      isActive = false
      sendSession(false)
      KrikoOverlayModule.finishHeadlessSession()
    }
    imageWorker.shutdown()
    super.onDestroy()
  }

  override fun onBind(intent: Intent?): IBinder? = null

  private fun dp(value: Int): Int = (value * resources.displayMetrics.density).roundToInt()
}

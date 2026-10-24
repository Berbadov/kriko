package __PACKAGE__.overlay

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
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
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.view.inputmethod.InputMethodManager
import android.text.InputType
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import android.util.Base64
import android.util.DisplayMetrics
import android.view.Display
import android.graphics.Rect
import android.graphics.Color
import android.content.res.ColorStateList
import android.animation.ValueAnimator
import android.view.animation.DecelerateInterpolator
import android.text.Html
import android.text.method.LinkMovementMethod
import com.facebook.react.bridge.Arguments
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import kotlin.math.roundToInt
import android.view.ViewConfiguration
import android.widget.ProgressBar
import android.view.ViewGroup

class KrikoOverlayService : Service() {
  companion object {
    const val ACTION_START = "__PACKAGE__.overlay.START"
    const val ACTION_STOP = "__PACKAGE__.overlay.STOP"
    const val ACTION_UPDATE = "__PACKAGE__.overlay.UPDATE"
    const val EXTRA_RESULT_CODE = "resultCode"
    const val EXTRA_RESULT_DATA = "resultData"
    const val EXTRA_JOBS = "jobs"
    private const val CHANNEL_ID = "kriko_screen_scan"
    private const val NOTIFICATION_ID = 7406
    private const val INK = 0xFF24231F.toInt()
    private const val INK_SECONDARY = 0xFF4C4942.toInt()
    private const val INK_MUTED = 0xFF78756D.toInt()
    private const val ACCENT = 0xFF2E5BEF.toInt()
    private const val ACCENT_HI = 0xFF2E5BEF.toInt()
    private const val RISK = 0xFF9B4439.toInt()
    private const val OK = 0xFF32704A.toInt()
    private const val GROUND = 0xF7FFFDF7.toInt()
    private const val PANEL = 0xF4F4F0E6.toInt()
    private const val PANEL_RAISED = 0xFFFFFDF7.toInt()
    private const val EDGE = 0xFFDED8CC.toInt()
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
  private var panelBody: LinearLayout? = null
  private var panelMode = "queue"
  private var bubbleQueue: TextView? = null
  private var bubbleProgress: ProgressBar? = null
  private var currentTab: TextView? = null
  private var queueTab: TextView? = null
  private var siteActionView: View? = null
  private var panelCloseGeneration = 0
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
      .setContentTitle("Kriko screen scan is active")
      .setContentText("Tap the floating bubble to scan one screen when you choose.")
      .setOngoing(true)
      .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Stop session", pending)
      .build()
  }

  private fun createNotificationChannel() {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
    val channel = NotificationChannel(CHANNEL_ID, "Floating screen scan",
      NotificationManager.IMPORTANCE_LOW).apply {
      description = "Shows when Kriko's user-started floating scan session is active."
      setShowBadge(false)
    }
    (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(channel)
  }

  private fun showBubble() {
    if (bubble != null || !Settings.canDrawOverlays(this)) return
    val root = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
      background = rounded(GROUND, 24, EDGE)
      elevation = dp(12).toFloat()
      setPadding(dp(6), dp(6), dp(6), dp(6))
    }
    val logo = TextView(this).apply {
      text = "K"
      setTextColor(Color.WHITE)
      textSize = 15f
      typeface = geistSemiBold
      gravity = Gravity.CENTER
      background = rounded(ACCENT, 20, ACCENT)
      contentDescription = "Drag Kriko or open scan panel"
      layoutParams = LinearLayout.LayoutParams(dp(34), dp(34)).apply { marginEnd = dp(5) }
      setOnClickListener { togglePanel("queue") }
    }
    val scan = actionButton("Scan", ACCENT, Color.WHITE) { requestCapture("research") }
    val activity = ProgressBar(this).apply {
      isIndeterminate = true
      indeterminateTintList = ColorStateList.valueOf(ACCENT)
      visibility = if (hasRunningJob()) View.VISIBLE else View.GONE
      layoutParams = LinearLayout.LayoutParams(dp(16), dp(16)).apply {
        marginStart = dp(4)
        marginEnd = dp(1)
      }
    }
    val queue = actionButton(queueLabel(), PANEL_RAISED, INK) { togglePanel("queue") }
    queue.contentDescription = "Open scan queue"
    val stop = actionButton("Stop", PANEL_RAISED, INK_SECONDARY) { stopSession() }
    stop.contentDescription = "Stop screen sharing"
    root.addView(logo)
    root.addView(activity)
    root.addView(scan)
    root.addView(queue)
    root.addView(stop)
    bubble = root
    bubbleQueue = queue
    bubbleProgress = activity
    bubbleParams = overlayParams(WindowManager.LayoutParams.WRAP_CONTENT, dp(52), Gravity.TOP or Gravity.START).apply {
      x = dp(18)
      y = dp(190)
    }
    // Drag the actual window from the blue mark; sibling actions remain tappable.
    installDrag(logo, bubbleParams!!, root)
    windowManager.addView(root, bubbleParams)
    animateIn(root, 0.88f, 240L)
  }

  private fun queueLabel(): String {
    val active = (0 until jobs.length()).count { index ->
      val status = jobs.optJSONObject(index)?.optString("status") ?: ""
      status == "queued" || status == "running" || status == "reading"
    }
    return if (active == 0) "Queue" else "Queue $active"
  }

  private fun hasRunningJob(): Boolean = (0 until jobs.length()).any { index ->
    val status = jobs.optJSONObject(index)?.optString("status") ?: ""
    status == "running" || status == "reading"
  }

  private fun togglePanel(mode: String = "queue") {
    if (panel != null) {
      panelCloseGeneration += 1
      panel?.animate()?.cancel()
      panel?.apply { alpha = 1f; scaleX = 1f; scaleY = 1f; visibility = View.VISIBLE }
      panelMode = mode
      renderPanel()
      return
    }
    val container = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      background = rounded(GROUND, 22, EDGE)
      elevation = dp(18).toFloat()
      setPadding(dp(12), dp(10), dp(12), dp(10))
      clipToOutline = true
    }
    val header = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    val title = TextView(this).apply {
      text = "Kriko"
      setTextColor(INK)
      textSize = 18f
      typeface = Typeface.create(Typeface.SERIF, Typeface.BOLD)
      layoutParams = LinearLayout.LayoutParams(0, dp(36), 1f)
      gravity = Gravity.CENTER_VERTICAL
    }
    header.addView(title)
    header.addView(actionButton("Scan", ACCENT, Color.WHITE) { requestCapture("research") })
    header.addView(actionButton("Close", PANEL_RAISED, INK_SECONDARY) { hidePanelAnimated() })
    container.addView(header)

    val tabs = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
      background = rounded(PANEL, 12, EDGE)
      setPadding(dp(3), dp(3), dp(3), dp(3))
    }
    currentTab = tabButton("Answer") { panelMode = "current"; renderPanel() }
    queueTab = tabButton(queueLabel()) { panelMode = "queue"; renderPanel() }
    tabs.addView(currentTab, LinearLayout.LayoutParams(0, dp(34), 1f))
    tabs.addView(queueTab, LinearLayout.LayoutParams(0, dp(34), 1f))
    container.addView(tabs, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(40)).apply {
      topMargin = dp(7)
      bottomMargin = dp(8)
    })

    val siteUrl = EditText(this).apply {
      hint = "Review site (optional)"
      setHintTextColor(INK_MUTED)
      setTextColor(INK)
      textSize = 13f
      setSingleLine(true)
      inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
      background = rounded(PANEL_RAISED, 10, EDGE)
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
    siteActionView = actionButton("Read site comments", ACCENT, Color.WHITE) {
      reviewSite = siteUrlInput?.text?.toString()?.trim().orEmpty()
      clearInputFocus()
      requestCapture("site_reviews", reviewSite)
    }
    container.addView(siteActionView, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(38)).apply {
      topMargin = dp(5)
      bottomMargin = dp(7)
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
    panelBody = list
    scroll.addView(list)
    container.addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(scrollHeight)))
    panel = container
    panelMode = mode
    panelParams = overlayParams(dp(panelWidthDp), WindowManager.LayoutParams.WRAP_CONTENT, Gravity.TOP or Gravity.END).apply {
      x = dp(10)
      y = dp(minOf(64, (screenHeightDp - 20 - 221 - scrollHeight).coerceAtLeast(8)))
    }
    windowManager.addView(container, panelParams)
    animateIn(container, 0.97f, 190L)
    renderPanel()
  }

  private fun renderPanel() {
    bubbleQueue?.text = queueLabel()
    bubbleProgress?.visibility = if (hasRunningJob()) View.VISIBLE else View.GONE
    queueTab?.let { tab ->
      tab.text = queueLabel()
      tab.background = rounded(if (panelMode == "queue") PANEL_RAISED else Color.TRANSPARENT, 9,
        if (panelMode == "queue") EDGE else Color.TRANSPARENT)
      tab.setTextColor(if (panelMode == "queue") INK else INK_SECONDARY)
    }
    currentTab?.let { tab ->
      tab.background = rounded(if (panelMode == "current") PANEL_RAISED else Color.TRANSPARENT, 9,
        if (panelMode == "current") EDGE else Color.TRANSPARENT)
      tab.setTextColor(if (panelMode == "current") INK else INK_SECONDARY)
    }
    siteUrlInput?.visibility = if (panelMode == "current") View.VISIBLE else View.GONE
    siteActionView?.visibility = if (panelMode == "current") View.VISIBLE else View.GONE
    val list = jobList ?: return
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
      stepView.text = latestStep?.optString("text").orEmpty()
    }
    for (index in 0 until jobs.length()) {
      val item = jobs.optJSONObject(index) ?: continue
      statusViews[item.optString("id")]?.text = statusLabel(item.optString("status"))
    }
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
      list.addView(bodyText("Scan a product page to see its answer and sources here.", 13f, INK_SECONDARY))
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
      list.addView(bodyText("No products yet. Tap Scan to add one to the queue.", 13f, INK_SECONDARY))
      return
    }
    for (index in 0 until minOf(jobs.length(), 16)) {
      val item = jobs.optJSONObject(index) ?: continue
      renderJobCard(list, item)
    }
  }

  private fun renderJobCard(list: LinearLayout, item: JSONObject) {
    val id = item.optString("id")
    val status = item.optString("status")
    val card = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      background = rounded(PANEL_RAISED, 14, EDGE)
      setPadding(dp(11), dp(9), dp(11), dp(9))
      layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
        .apply { bottomMargin = dp(7) }
      setOnClickListener {
        selectedJob = id
        if (panelMode == "queue") {
          panelMode = "current"
          renderPanel()
        }
      }
    }
    val top = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    val title = TextView(this).apply {
      text = item.optString("title", "Scan result")
      setTextColor(INK)
      textSize = 14f
      typeface = geistSemiBold
      maxLines = 2
      layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
    }
    top.addView(title)
    val active = status == "queued" || status == "running" || status == "reading"
    if (active) top.addView(ProgressBar(this).apply {
      isIndeterminate = true
      indeterminateTintList = ColorStateList.valueOf(ACCENT_HI)
      layoutParams = LinearLayout.LayoutParams(dp(18), dp(18)).apply { marginStart = dp(8) }
    })
    card.addView(top)
    val statusColor = when (status) {
      "done" -> OK
      "error", "cancelled" -> RISK
      else -> ACCENT_HI
    }
    if (status.isNotBlank()) {
      val statusView = bodyText(statusLabel(status), 11f, statusColor)
      statusViews[id] = statusView
      card.addView(statusView)
    }
    val steps = item.optJSONArray("steps") ?: JSONArray()
    val latestStep = if (steps.length() > 0) steps.optJSONObject(steps.length() - 1) else null
    if (latestStep != null && (status == "running" || status == "reading")) {
      val stepView = bodyText(latestStep.optString("text"), 11f, INK_SECONDARY)
      stepViews[id] = stepView
      card.addView(stepView)
    }
    val error = item.optString("error")
    val answer = item.optString("text")
    if (error.isNotBlank()) card.addView(bodyText(error, 12f, RISK))
    if (answer.isNotBlank()) {
      val answerView = answerText(answer, item.optJSONArray("sources") ?: JSONArray())
      answerViews[id] = answerView
      card.addView(answerView)
    }
    val sources = item.optJSONArray("sources") ?: JSONArray()
    for (sourceIndex in 0 until minOf(sources.length(), 4)) {
      val source = sources.optJSONObject(sourceIndex) ?: continue
      val url = source.optString("url")
      if (!url.startsWith("https://") && !url.startsWith("http://")) continue
      val label = source.optString("title").ifBlank { source.optString("host").ifBlank { "Source" } }
      card.addView(TextView(this).apply {
        text = "Source: $label"
        setTextColor(ACCENT_HI)
        textSize = 12f
        typeface = geistMedium
        setPadding(0, dp(4), 0, dp(4))
        setOnClickListener { openSource(url) }
      })
    }
    list.addView(card)
    if (active) card.addView(actionButton("Cancel", PANEL, RISK) {
      emitAction("cancel", id)
    }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(34)).apply {
      topMargin = dp(6)
    })
  }

  private fun requestCapture(mode: String = "research", siteUrl: String = "") {
    if (!isActive || capturePending) return
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
        showToast("Could not read that screen. Try scanning again.")
      }
    } catch (_: Exception) {
      image.close()
      mainHandler.post {
        bubble?.let { it.visibility = View.VISIBLE; animateIn(it, 0.96f, 180L) }
        showResultPanel()
      }
      showToast("Could not capture that screen. Try scanning again.")
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
    bubble?.let { it.visibility = View.VISIBLE; animateIn(it, 0.96f, 180L) }
    panel?.let { it.visibility = View.VISIBLE; it.alpha = 1f; it.scaleX = 1f; it.scaleY = 1f }
  }

  private fun showResultPanel() {
    if (panel == null) {
      togglePanel("current")
      return
    }
    panelMode = "current"
    renderPanel()
    panel?.let { it.visibility = View.VISIBLE; animateIn(it, 0.97f, 190L) }
  }

  private fun animationsEnabled(): Boolean = Build.VERSION.SDK_INT < 26 || ValueAnimator.areAnimatorsEnabled()

  private fun animateIn(view: View, initialScale: Float, duration: Long) {
    view.animate().cancel()
    if (!animationsEnabled()) {
      view.alpha = 1f
      view.scaleX = 1f
      view.scaleY = 1f
      return
    }
    view.alpha = 0f
    view.scaleX = initialScale
    view.scaleY = initialScale
    view.animate().alpha(1f).scaleX(1f).scaleY(1f)
      .setDuration(duration).setInterpolator(DecelerateInterpolator()).start()
  }

  private fun hidePanelAnimated() {
    val target = panel ?: return
    panelCloseGeneration += 1
    val generation = panelCloseGeneration
    target.animate().cancel()
    if (!animationsEnabled()) {
      removePanel()
      return
    }
    target.animate().alpha(0f).scaleX(0.98f).scaleY(0.98f)
      .setDuration(150L).setInterpolator(DecelerateInterpolator())
      .withEndAction { if (generation == panelCloseGeneration && panel === target) removePanel() }
      .start()
  }

  private fun openSource(url: String) {
    try {
      startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (_: Exception) {
      showToast("Could not open that source.")
    }
  }

  private fun actionButton(label: String, onClick: () -> Unit): TextView =
    actionButton(label, PANEL_RAISED, INK, onClick)

  private fun actionButton(
    label: String,
    backgroundColor: Int,
    foregroundColor: Int = INK,
    onClick: () -> Unit,
  ): TextView = TextView(this).apply {
    text = label
    setTextColor(foregroundColor)
    textSize = 12f
    typeface = geistMedium
    gravity = Gravity.CENTER
    background = rounded(backgroundColor, 11, EDGE)
    setPadding(dp(11), dp(5), dp(11), dp(5))
    setOnClickListener { onClick() }
    layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(34))
      .apply { marginStart = dp(6) }
  }

  private fun tabButton(label: String, onClick: () -> Unit): TextView = TextView(this).apply {
    text = label
    textSize = 12f
    typeface = geistMedium
    gravity = Gravity.CENTER
    setTextColor(INK_SECONDARY)
    setPadding(dp(8), 0, dp(8), 0)
    setOnClickListener { onClick() }
  }

  private fun bodyText(text: String, size: Float, color: Int) = TextView(this).apply {
    this.text = text
    setTextColor(color)
    textSize = size
    typeface = geistRegular
    setLineSpacing(dp(2).toFloat(), 1f)
    setPadding(0, dp(4), 0, dp(2))
  }

  private fun statusLabel(status: String): String = when (status) {
    "queued" -> "Waiting"
    "reading" -> "Reading product"
    "running" -> "Researching"
    "done" -> "Complete"
    "error" -> "Could not finish"
    "cancelled" -> "Cancelled"
    else -> status
  }

  private fun answerText(markdown: String, sources: JSONArray): TextView {
    val answer = TextView(this).apply {
      setTextColor(INK)
      textSize = 13.5f
      typeface = geistRegular
      setLineSpacing(dp(3).toFloat(), 1f)
      setPadding(0, dp(7), 0, dp(5))
      setTextIsSelectable(true)
      setLinkTextColor(ACCENT_HI)
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
          if (!moved) view.performClick()
          true
        }
        else -> true
      }
    }
  }

  private fun rounded(color: Int, radius: Int, strokeColor: Int = EDGE) = GradientDrawable().apply {
    setColor(color)
    cornerRadius = dp(radius).toFloat()
    setStroke(dp(1), strokeColor)
  }

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
    panel?.let { try { windowManager.removeView(it) } catch (_: Exception) { } }
    panel = null
    panelParams = null
    siteUrlInput = null
    jobList = null
    panelBody = null
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
    bubble?.let { try { windowManager.removeView(it) } catch (_: Exception) { } }
    bubble = null
    bubbleProgress = null
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

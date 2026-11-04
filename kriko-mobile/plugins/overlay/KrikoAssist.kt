package __PACKAGE__.overlay

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.media.projection.MediaProjectionConfig
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.service.voice.VoiceInteractionService
import android.service.voice.VoiceInteractionSession
import android.service.voice.VoiceInteractionSessionService
import android.speech.RecognitionService
import android.speech.SpeechRecognizer
import android.text.TextUtils
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.Executors
import kotlin.math.min

/**
 * How a scan reaches the app when the scanner cannot hand it to JavaScript
 * directly: as a picture in the cache and a link that opens Kriko on a fresh
 * chat that reads it (`kriko://assist?shot=<file uri>`). The assistant screen
 * uses the same door, so both routes start the same way.
 */
internal object KrikoHandoff {
  private const val FOLDER = "kriko-frames"
  private const val KEEP_MS = 30L * 60L * 1000L

  fun intent(
    context: Context,
    shotUri: String?,
    mode: String = "research",
    site: String = "",
    error: String? = null,
  ): Intent {
    val link = Uri.Builder().scheme("kriko").authority("assist").apply {
      if (shotUri != null) appendQueryParameter("shot", shotUri)
      if (error != null) appendQueryParameter("error", error)
      if (mode != "research") appendQueryParameter("mode", mode)
      if (site.isNotBlank()) appendQueryParameter("site", site)
    }.build()
    return Intent(Intent.ACTION_VIEW, link).apply {
      setPackage(context.packageName)
      addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
    }
  }

  private fun framesDir(context: Context): File = File(context.cacheDir, FOLDER).apply { mkdirs() }

  /** Delete frames nobody has picked up; the app removes the ones it reads. */
  private fun sweep(context: Context) {
    val cutoff = System.currentTimeMillis() - KEEP_MS
    framesDir(context).listFiles()?.filter { it.lastModified() < cutoff }?.forEach { it.delete() }
  }

  fun writeFrame(context: Context, jpeg: ByteArray): String? = try {
    sweep(context)
    val file = File(framesDir(context), "frame-${System.currentTimeMillis()}.jpg")
    file.writeBytes(jpeg)
    Uri.fromFile(file).toString()
  } catch (_: Exception) {
    null
  }

  fun writeBitmap(context: Context, bitmap: Bitmap): String? = try {
    sweep(context)
    val file = File(framesDir(context), "frame-${System.currentTimeMillis()}.jpg")
    FileOutputStream(file).use { bitmap.compress(Bitmap.CompressFormat.JPEG, 86, it) }
    Uri.fromFile(file).toString()
  } catch (_: Exception) {
    null
  }
}

/**
 * A see-through screen whose only job is to ask Android for screen capture
 * again. The floating scanner starts it when Scan is pressed after the system
 * ended the last grant (it does so when the phone locks), so the reader answers
 * one dialog over their own page instead of being sent back into the app.
 */
class KrikoCaptureActivity : Activity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    if (savedInstanceState != null) return
    try {
      val manager = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
      val intent = if (Build.VERSION.SDK_INT >= 34) {
        manager.createScreenCaptureIntent(MediaProjectionConfig.createConfigForDefaultDisplay())
      } else {
        manager.createScreenCaptureIntent()
      }
      startActivityForResult(intent, REQUEST)
    } catch (_: Exception) {
      deny()
    }
  }

  @Deprecated("Deprecated in Java")
  override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
    super.onActivityResult(requestCode, resultCode, data)
    if (requestCode != REQUEST) return
    if (resultCode == RESULT_OK && data != null) {
      try {
        startService(Intent(this, KrikoOverlayService::class.java).apply {
          action = KrikoOverlayService.ACTION_PROJECTION
          putExtra(KrikoOverlayService.EXTRA_RESULT_CODE, resultCode)
          putExtra(KrikoOverlayService.EXTRA_RESULT_DATA, data)
        })
      } catch (_: Exception) {
        deny()
        return
      }
    } else {
      deny()
      return
    }
    finishQuietly()
  }

  private fun deny() {
    try {
      startService(Intent(this, KrikoOverlayService::class.java).apply {
        action = KrikoOverlayService.ACTION_PROJECTION_DENIED
      })
    } catch (_: Exception) { }
    finishQuietly()
  }

  private fun finishQuietly() {
    finish()
    @Suppress("DEPRECATION")
    overridePendingTransition(0, 0)
  }

  private companion object {
    const val REQUEST = 8412
  }
}

/**
 * Kriko as the phone's digital assistant. Android lists an app under Default
 * apps → Digital assistant when it declares this service, and starts a session
 * when the reader long-presses the power or home button (or says the gesture
 * their phone uses). The service itself does nothing; the session is the work.
 */
class KrikoAssistService : VoiceInteractionService() {
  override fun onReady() {
    super.onReady()
    instance = this
  }

  override fun onShutdown() {
    if (instance === this) instance = null
    super.onShutdown()
  }

  companion object {
    @Volatile private var instance: KrikoAssistService? = null

    /**
     * Summon the assistant again from inside Kriko (the answer sheet's Scan
     * again). False when Kriko is not the phone's chosen assistant right now.
     */
    fun rescan(): Boolean {
      val service = instance ?: return false
      return try {
        service.showSession(
          Bundle(),
          VoiceInteractionSession.SHOW_WITH_ASSIST or VoiceInteractionSession.SHOW_WITH_SCREENSHOT,
        )
        true
      } catch (_: Exception) {
        false
      }
    }
  }
}

/** Hands Android a fresh session each time the assistant is summoned. */
class KrikoAssistSessionService : VoiceInteractionSessionService() {
  override fun onNewSession(args: Bundle?): VoiceInteractionSession = KrikoAssistSession(this)
}

/**
 * Android requires every assistant to name a speech recogniser. Kriko does not
 * listen, so this one declines every request; it exists to satisfy the contract.
 */
class KrikoRecognitionService : RecognitionService() {
  override fun onStartListening(recognizerIntent: Intent?, listener: RecognitionService.Callback?) {
    try { listener?.error(SpeechRecognizer.ERROR_CLIENT) } catch (_: Exception) { }
  }

  override fun onCancel(listener: RecognitionService.Callback?) = Unit

  override fun onStopListening(listener: RecognitionService.Callback?) = Unit
}

/**
 * One summoning of the assistant. It answers the press at once, with a small
 * scanning card on the reader's own screen, saves the screenshot Android hands
 * it, and opens Kriko on a fresh chat that reads that picture.
 *
 * Android only sends the screenshot when the reader has "Use screenshot" on for
 * their assistant; if it did not come, the card says where that switch is.
 */
internal class KrikoAssistSession(private val host: Context) : VoiceInteractionSession(host) {
  private val ui = KrikoUi(host).loadSaved()
  private val fonts = KrikoFonts(host)
  private val motion = KrikoMotion()
  private val main = Handler(Looper.getMainLooper())
  private val worker = Executors.newSingleThreadExecutor()
  private var card: View? = null
  private var puck: KrikoPuckView? = null
  private var bar: View? = null
  private var message: TextView? = null
  private var launched = false
  private val noShot = Runnable { showNoShot() }

  override fun onCreateContentView(): View {
    val p = ui.palette
    val root = FrameLayout(host).apply {
      setBackgroundColor(Color.TRANSPARENT)
      setOnClickListener { hide() }
    }
    val widthPx = min(host.dp(404), host.resources.displayMetrics.widthPixels - host.dp(16))
    val column = LinearLayout(host).apply {
      orientation = LinearLayout.VERTICAL
      outlineProvider = android.view.ViewOutlineProvider.BACKGROUND
      clipToOutline = true
      setPadding(host.dp(16), host.dp(14), host.dp(16), host.dp(14))
      isClickable = true
    }
    column.background = GlassDrawable(
      host, 28f, { KrikoGlassLevel.body(p) }, { KrikoGlassLevel.sheet(ui) },
      { KrikoGlassLevel.isDark(p) }, frosted = false,
    ).attach(column)
    val row = LinearLayout(host).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    val chip = KrikoPuckView(host, ui, fonts)
    puck = chip
    row.addView(chip, LinearLayout.LayoutParams(host.dp(KrikoPuckView.SIZE_DP), host.dp(KrikoPuckView.SIZE_DP)).apply {
      marginEnd = host.dp(14)
    })
    val texts = LinearLayout(host).apply { orientation = LinearLayout.VERTICAL }
    texts.addView(TextView(host).apply {
      text = ui.label("assistTitle")
      setTextColor(p.ink)
      setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
      typeface = fonts.semiBold
      includeFontPadding = false
    })
    val line = TextView(host).apply {
      setTextColor(p.ink2)
      setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
      typeface = fonts.regular
      setLineSpacing(host.dpf(2f), 1f)
      ellipsize = TextUtils.TruncateAt.END
      maxLines = 4
    }
    message = line
    texts.addView(line, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
      topMargin = host.dp(5)
    })
    row.addView(texts, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
    column.addView(row)
    val progress = IndeterminateBar(host, KrikoColor.tint(p.ink, 0.08f), p.accentHi)
    bar = progress
    column.addView(progress, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, host.dp(3)).apply {
      topMargin = host.dp(14)
    })
    card = column
    val id = host.resources.getIdentifier("status_bar_height", "dimen", "android")
    val statusBar = if (id > 0) host.resources.getDimensionPixelSize(id) else host.dp(26)
    root.addView(column, FrameLayout.LayoutParams(widthPx, ViewGroup.LayoutParams.WRAP_CONTENT,
      Gravity.TOP or Gravity.CENTER_HORIZONTAL).apply { topMargin = statusBar + host.dp(8) })
    return root
  }

  override fun onShow(args: Bundle?, showFlags: Int) {
    super.onShow(args, showFlags)
    main.removeCallbacksAndMessages(null)
    launched = false
    message?.text = ui.label("assistScanning")
    bar?.visibility = View.VISIBLE
    puck?.setMode(KrikoPuckView.Mode.SCANNING)
    puck?.awaken()
    card?.let {
      it.visibility = View.INVISIBLE
      it.pivotY = 0f
      motion.animateIn(it, 0.97f, 260L, fromTranslationY = -host.dp(26).toFloat())
    }
    val withScreenshot = (showFlags and SHOW_WITH_SCREENSHOT) != 0
    // Without the flag no screenshot is coming; with it, give Android a moment.
    main.postDelayed(noShot, if (withScreenshot) 4500L else 800L)
  }

  override fun onHandleScreenshot(screenshot: Bitmap?) {
    main.removeCallbacks(noShot)
    if (screenshot == null) {
      showNoShot()
      return
    }
    worker.execute {
      // Frost the page for the glass of the answer that is about to sit over it.
      KrikoBackdrop.update(screenshot)
      val uri = KrikoHandoff.writeBitmap(host, screenshot)
      main.post { if (uri == null) showNoShot() else handOff(uri) }
    }
  }

  /**
   * The answer belongs over the reader's own page. With permission to draw there,
   * the overlay service takes the picture, ripples a wave of pixels across the
   * page and hangs the answer sheet where this card is; this card then leaves.
   * Without it (or with Kriko itself in front) the picture opens in the app.
   */
  private fun handOff(uri: String) {
    if (launched) return
    val over = Settings.canDrawOverlays(host) && !KrikoOverlayModule.appInForeground
    if (over) {
      try {
        host.startService(Intent(host, KrikoOverlayService::class.java).apply {
          action = KrikoOverlayService.ACTION_ASSIST
          putExtra(KrikoOverlayService.EXTRA_SHOT, uri)
        })
        launched = true
        main.postDelayed({ hide() }, 240L)
        return
      } catch (_: Exception) {
        // Fall through to the app.
      }
    }
    message?.text = ui.label("openingKriko")
    open(uri)
  }

  private fun open(uri: String) {
    if (launched) return
    launched = true
    val intent = KrikoHandoff.intent(host, uri)
    try {
      host.startActivity(intent)
    } catch (_: Exception) {
      try { startAssistantActivity(intent) } catch (_: Exception) {
        showNoShot()
        return
      }
    }
    main.postDelayed({ hide() }, 650L)
  }

  private fun showNoShot() {
    if (launched) return
    message?.text = ui.label("assistNoShot")
    bar?.visibility = View.GONE
    puck?.setMode(KrikoPuckView.Mode.PAUSED)
  }

  override fun onHide() {
    main.removeCallbacksAndMessages(null)
    super.onHide()
  }

  override fun onDestroy() {
    main.removeCallbacksAndMessages(null)
    worker.shutdown()
    super.onDestroy()
  }
}

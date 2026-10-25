package __PACKAGE__.overlay

import android.app.Activity
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.media.projection.MediaProjectionConfig
import android.media.projection.MediaProjectionManager
import com.facebook.react.bridge.ActivityEventListener
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.bridge.UiThreadUtil
import com.facebook.react.modules.core.DeviceEventManagerModule
import com.facebook.react.jstasks.HeadlessJsTaskConfig
import com.facebook.react.jstasks.HeadlessJsTaskContext
import java.lang.ref.WeakReference

class KrikoOverlayModule(private val appContext: ReactApplicationContext) :
  ReactContextBaseJavaModule(appContext), ActivityEventListener {

  companion object {
    const val REQUEST_OVERLAY = 8410
    const val REQUEST_CAPTURE = 8411
    @Volatile private var reactContextRef: WeakReference<ReactApplicationContext>? = null
    @Volatile private var startPromise: Promise? = null
    @Volatile private var headlessTaskId: Int? = null
    /** The last palette and labels JS sent, kept so a session starts already themed. */
    @Volatile private var uiJson: String? = null
    /**
     * Whether Kriko's screen is mounted and listening for scans. The scanner
     * outlives the screen; when nobody is listening it opens the app with the
     * picture instead of emitting an event no one would hear.
     */
    @Volatile var jsReady: Boolean = false

    fun emit(name: String, body: com.facebook.react.bridge.WritableMap) {
      val context = reactContextRef?.get() ?: return
      if (!context.hasActiveReactInstance()) return
      context.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
        .emit(name, body)
    }

    fun serviceReady() {
      val body = Arguments.createMap().apply { putBoolean("active", true) }
      emit("onSession", body)
      startHeadlessSession()
      startPromise?.resolve(true)
      startPromise = null
    }

    /** A re-grant for a session that already exists failed; the session itself carries on. */
    fun startRejected(message: String) {
      startPromise?.reject("PROJECTION_START_FAILED", message)
      startPromise = null
    }

    fun serviceFailed(message: String) {
      startPromise?.reject("PROJECTION_START_FAILED", message)
      startPromise = null
      val body = Arguments.createMap().apply { putBoolean("active", false) }
      emit("onSession", body)
      finishHeadlessSession()
    }

    fun startHeadlessSession() {
      val context = reactContextRef?.get() ?: return
      UiThreadUtil.runOnUiThread {
        if (!KrikoOverlayService.isActive || !context.hasActiveReactInstance() || headlessTaskId != null) return@runOnUiThread
        headlessTaskId = HeadlessJsTaskContext.getInstance(context).startTask(
          HeadlessJsTaskConfig("KrikoOverlaySession", Arguments.createMap(), 0L, true),
        )
      }
    }

    fun finishHeadlessSession() {
      val context = reactContextRef?.get() ?: return
      val id = headlessTaskId ?: return
      headlessTaskId = null
      UiThreadUtil.runOnUiThread {
        HeadlessJsTaskContext.getInstance(context).finishTask(id)
      }
    }
  }

  init {
    reactContextRef = WeakReference(appContext)
    appContext.addActivityEventListener(this)
  }

  override fun getName() = "KrikoOverlay"

  @ReactMethod
  fun startSession(promise: Promise) {
    // A session whose capture was ended by the system is still "active"; asking
    // to start it again is how the reader grants capture again from Settings.
    if (KrikoOverlayService.isActive && KrikoOverlayService.captureLive) {
      promise.resolve(true)
      return
    }
    val activity = getCurrentActivity()
    if (activity == null) {
      promise.reject("NO_ACTIVITY", "Open Kriko before starting the floating scan session.")
      return
    }
    if (startPromise != null) {
      promise.reject("SESSION_START_IN_PROGRESS", "The scan session permission flow is already open.")
      return
    }
    if (!Settings.canDrawOverlays(activity)) {
      val settings = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
        Uri.parse("package:${activity.packageName}"))
      activity.startActivityForResult(settings, REQUEST_OVERLAY)
      promise.reject("OVERLAY_PERMISSION_REQUIRED",
        "Allow Kriko to display over other apps, return here, then start the floating scan again.")
      return
    }

    val manager = activity.getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
    val captureIntent = if (Build.VERSION.SDK_INT >= 34) {
      manager.createScreenCaptureIntent(MediaProjectionConfig.createConfigForDefaultDisplay())
    } else {
      manager.createScreenCaptureIntent()
    }
    startPromise = promise
    try {
      activity.startActivityForResult(captureIntent, REQUEST_CAPTURE)
    } catch (error: Exception) {
      startPromise = null
      promise.reject("CAPTURE_PERMISSION_FAILED", error.message ?: "Could not open screen capture permission.")
    }
  }

  override fun onActivityResult(activity: Activity, requestCode: Int, resultCode: Int, data: Intent?) {
    if (requestCode == REQUEST_OVERLAY) return
    if (requestCode != REQUEST_CAPTURE) return
    val promise = startPromise
    if (resultCode != Activity.RESULT_OK || data == null) {
      startPromise = null
      promise?.reject("CAPTURE_PERMISSION_DENIED", "Screen capture permission was not granted.")
      return
    }
    try {
      val service = Intent(appContext, KrikoOverlayService::class.java).apply {
        action = KrikoOverlayService.ACTION_START
        putExtra(KrikoOverlayService.EXTRA_RESULT_CODE, resultCode)
        putExtra(KrikoOverlayService.EXTRA_RESULT_DATA, data)
        uiJson?.let { putExtra(KrikoOverlayService.EXTRA_UI, it) }
      }
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) appContext.startForegroundService(service)
      else appContext.startService(service)
    } catch (error: Exception) {
      startPromise = null
      promise?.reject("PROJECTION_START_FAILED", error.message ?: "Could not start screen capture.")
    }
  }

  override fun onNewIntent(intent: Intent) = Unit

  override fun invalidate() {
    startPromise?.reject("MODULE_RELOADED", "The screen scan permission flow was interrupted. Start the session again.")
    startPromise = null
    jsReady = false
    finishHeadlessSession()
    super.invalidate()
  }

  /** Called by the session provider as it mounts (true) and unmounts (false). */
  @ReactMethod
  fun setUiReady(ready: Boolean) {
    jsReady = ready
  }

  /** Whether Kriko is the phone's chosen digital assistant right now. */
  @ReactMethod
  fun isDefaultAssistant(promise: Promise) {
    promise.resolve(try {
      val resolver = appContext.contentResolver
      val chosen = Settings.Secure.getString(resolver, "assistant")
        ?: Settings.Secure.getString(resolver, "voice_interaction_service")
      val component = chosen?.let { ComponentName.unflattenFromString(it) }
      component?.packageName == appContext.packageName
    } catch (_: Exception) {
      false
    })
  }

  /**
   * Open the phone's own page for choosing the digital assistant. Android does
   * not let an app pick itself, so the reader makes the choice there.
   */
  @ReactMethod
  fun openAssistantSettings(promise: Promise) {
    val candidates = listOf(
      Intent(Settings.ACTION_VOICE_INPUT_SETTINGS),
      Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS),
      Intent(Settings.ACTION_SETTINGS),
    )
    for (candidate in candidates) {
      try {
        candidate.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        appContext.startActivity(candidate)
        promise.resolve(true)
        return
      } catch (_: Exception) {
        // Try the next, broader screen.
      }
    }
    promise.resolve(false)
  }

  @ReactMethod
  fun stopSession(promise: Promise) {
    if (!KrikoOverlayService.isActive) {
      promise.resolve(true)
      return
    }
    appContext.startService(Intent(appContext, KrikoOverlayService::class.java).apply {
      action = KrikoOverlayService.ACTION_STOP
    })
    promise.resolve(true)
  }

  @ReactMethod
  fun isActive(promise: Promise) {
    promise.resolve(KrikoOverlayService.isActive)
  }

  @ReactMethod
  fun ensureHeadlessSession() {
    startHeadlessSession()
  }

  /**
   * Put Kriko's own task behind the page the reader came from. The scanner is
   * its own window and stays on top, so this is what turns "start" into
   * "now scan the page" without a manual trip to the home screen.
   */
  @ReactMethod
  fun moveToBack(promise: Promise) {
    val activity = getCurrentActivity()
    if (activity == null) {
      promise.resolve(false)
      return
    }
    UiThreadUtil.runOnUiThread {
      promise.resolve(try { activity.moveTaskToBack(true) } catch (_: Exception) { false })
    }
  }

  /**
   * Whether Kriko's own screen is in front. The scanner stands down while it is
   * and returns the moment the reader moves to another page.
   */
  @ReactMethod
  fun setAppForeground(foreground: Boolean) {
    if (!KrikoOverlayService.isActive) return
    appContext.startService(Intent(appContext, KrikoOverlayService::class.java).apply {
      action = KrikoOverlayService.ACTION_APP
      putExtra(KrikoOverlayService.EXTRA_FOREGROUND, foreground)
    })
  }

  @ReactMethod
  fun updateJobs(json: String) {
    if (!KrikoOverlayService.isActive) return
    appContext.startService(Intent(appContext, KrikoOverlayService::class.java).apply {
      action = KrikoOverlayService.ACTION_UPDATE
      putExtra(KrikoOverlayService.EXTRA_JOBS, json)
    })
  }

  /**
   * The reader's palette and translated words for the floating bubble and panel.
   * Cached even with no session running, so the bubble appears in that theme and
   * language on the first frame rather than after an English, dark flash.
   */
  @ReactMethod
  fun updateUi(json: String) {
    uiJson = json
    // Also kept on disk: the assistant starts without this module being awake.
    KrikoUi(appContext).save(json)
    if (!KrikoOverlayService.isActive) return
    appContext.startService(Intent(appContext, KrikoOverlayService::class.java).apply {
      action = KrikoOverlayService.ACTION_UI
      putExtra(KrikoOverlayService.EXTRA_UI, json)
    })
  }

  @ReactMethod
  fun addListener(eventName: String) = Unit

  @ReactMethod
  fun removeListeners(count: Int) = Unit
}

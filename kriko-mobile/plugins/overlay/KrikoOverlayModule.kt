package __PACKAGE__.overlay

import android.app.Activity
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
    if (KrikoOverlayService.isActive) {
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
    finishHeadlessSession()
    super.invalidate()
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

  @ReactMethod
  fun updateJobs(json: String) {
    if (!KrikoOverlayService.isActive) return
    appContext.startService(Intent(appContext, KrikoOverlayService::class.java).apply {
      action = KrikoOverlayService.ACTION_UPDATE
      putExtra(KrikoOverlayService.EXTRA_JOBS, json)
    })
  }

  @ReactMethod
  fun addListener(eventName: String) = Unit

  @ReactMethod
  fun removeListeners(count: Int) = Unit
}

package __PACKAGE__.overlay

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.speech.RecognitionListener
import android.speech.RecognitionService
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.modules.core.DeviceEventManagerModule

/** One short, foreground voice-typing session. Audio is only handed to Android's recognizer. */
internal class KrikoVoice(private val context: ReactApplicationContext) {
  private val main = Handler(Looper.getMainLooper())
  private var recognizer: SpeechRecognizer? = null
  private var sessionId: String? = null
  private var generation = 0L
  private var terminal = false
  private var timeout: Runnable? = null

  fun available(): Boolean = try {
    SpeechRecognizer.isRecognitionAvailable(context) && selectService() != null
  } catch (_: Exception) { false }

  fun start(locale: String, id: String, done: (Boolean) -> Unit) {
    main.post {
      if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
        done(false)
        emit(id, "error", code = "permission")
        return@post
      }
      if (sessionId != null) {
        done(false)
        emit(id, "error", code = "busy")
        return@post
      }
      val component = selectService()
      if (component == null || !SpeechRecognizer.isRecognitionAvailable(context)) {
        done(false)
        emit(id, "error", code = "unavailable")
        return@post
      }
      val currentGeneration = ++generation
      sessionId = id
      terminal = false
      try {
        val speech = SpeechRecognizer.createSpeechRecognizer(context, component)
        recognizer = speech
        speech.setRecognitionListener(listener(currentGeneration, id))
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
          putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
          putExtra(RecognizerIntent.EXTRA_LANGUAGE, locale.ifBlank { java.util.Locale.getDefault().toLanguageTag() })
          putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
          putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
          putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, context.packageName)
        }
        speech.startListening(intent)
        emit(id, "listening")
        val timeoutTask = Runnable {
          if (isCurrent(currentGeneration, id)) {
            emit(id, "error", code = "timeout")
            end(currentGeneration, id)
          }
        }
        timeout = timeoutTask
        main.postDelayed(timeoutTask, SESSION_TIMEOUT_MS)
        done(true)
      } catch (_: Exception) {
        emit(id, "error", code = "unavailable")
        end(currentGeneration, id)
        done(false)
      }
    }
  }

  fun stop(id: String) = main.post {
    if (sessionId != id || terminal) return@post
    try { recognizer?.stopListening() } catch (_: Exception) {
      finishError(generation, id, "failed")
    }
  }

  fun cancel(id: String) = main.post {
    if (sessionId != id || terminal) return@post
    terminal = true
    emit(id, "cancelled")
    release()
  }

  fun destroy() = main.post {
    sessionId?.let { emit(it, "cancelled") }
    generation++
    timeout?.let(main::removeCallbacks)
    timeout = null
    terminal = true
    release()
  }

  private fun listener(expectedGeneration: Long, expectedId: String) = object : RecognitionListener {
    private fun current() = isCurrent(expectedGeneration, expectedId)
    override fun onReadyForSpeech(params: Bundle?) { if (current()) emit(expectedId, "listening") }
    override fun onBeginningOfSpeech() { if (current()) emit(expectedId, "listening") }
    override fun onRmsChanged(rmsdB: Float) = Unit
    override fun onBufferReceived(buffer: ByteArray?) = Unit
    override fun onEndOfSpeech() { if (current()) emit(expectedId, "processing") }
    override fun onError(error: Int) { if (current()) finishError(expectedGeneration, expectedId, mapError(error)) }
    override fun onResults(results: Bundle?) {
      if (!current()) return
      val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
      if (text.isBlank()) finishError(expectedGeneration, expectedId, "no_match")
      else {
        terminal = true
        emit(expectedId, "result", text = text, final = true)
        end(expectedGeneration, expectedId)
      }
    }
    override fun onPartialResults(results: Bundle?) {
      if (!current()) return
      val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull() ?: return
      emit(expectedId, "result", text = text, final = false)
    }
    override fun onEvent(eventType: Int, params: Bundle?) = Unit
  }

  private fun finishError(expectedGeneration: Long, id: String, code: String) {
    if (!isCurrent(expectedGeneration, id)) return
    terminal = true
    emit(id, "error", code = code)
    end(expectedGeneration, id)
  }

  private fun end(expectedGeneration: Long, id: String) {
    if (generation != expectedGeneration || sessionId != id) return
    release()
  }

  private fun release() {
    timeout?.let(main::removeCallbacks)
    timeout = null
    val old = recognizer
    recognizer = null
    sessionId = null
    try { old?.cancel() } catch (_: Exception) { }
    try { old?.destroy() } catch (_: Exception) { }
  }

  private fun isCurrent(expectedGeneration: Long, id: String) =
    generation == expectedGeneration && sessionId == id && !terminal

  private fun emit(id: String, status: String, text: String? = null, final: Boolean? = null, code: String? = null) {
    if (!context.hasActiveReactInstance()) return
    val body = Arguments.createMap().apply {
      putString("sessionId", id)
      putString("status", status)
      text?.let { putString("text", it) }
      final?.let { putBoolean("final", it) }
      code?.let { putString("code", it) }
    }
    context.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java).emit("onVoiceTyping", body)
  }

  private fun mapError(error: Int): String = when (error) {
    SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "permission"
    SpeechRecognizer.ERROR_NO_MATCH -> "no_match"
    SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT,
    SpeechRecognizer.ERROR_SERVER, SpeechRecognizer.ERROR_SERVER_DISCONNECTED -> "network"
    SpeechRecognizer.ERROR_RECOGNIZER_BUSY, SpeechRecognizer.ERROR_TOO_MANY_REQUESTS -> "busy"
    SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "timeout"
    SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED, SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE -> "language"
    else -> "failed"
  }

  /** Never route to KrikoRecognitionService, which is only the assistant's required stub. */
  @Suppress("DEPRECATION")
  private fun selectService(): ComponentName? {
    val intent = Intent(RecognitionService.SERVICE_INTERFACE)
    val matches = try {
      @Suppress("DEPRECATION")
      context.packageManager.queryIntentServices(intent, 0)
    } catch (_: Exception) { emptyList() }
    val candidates = matches.mapNotNull { resolveInfo ->
      val info = resolveInfo.serviceInfo ?: return@mapNotNull null
      if (info.packageName == context.packageName) return@mapNotNull null
      ComponentName(info.packageName, info.name)
    }
    if (candidates.isEmpty()) return null
    val preferredSetting = try { Settings.Secure.getString(context.contentResolver, "voice_recognition_service") } catch (_: Exception) { null }
    val preferred = preferredSetting?.let(ComponentName::unflattenFromString)
    if (preferred != null && preferred.packageName != context.packageName && candidates.contains(preferred)) return preferred
    val systemCandidates = candidates.filter { component ->
      try {
        val app = context.packageManager.getApplicationInfo(component.packageName, 0)
        (app.flags and android.content.pm.ApplicationInfo.FLAG_SYSTEM != 0) ||
          (app.flags and android.content.pm.ApplicationInfo.FLAG_UPDATED_SYSTEM_APP != 0)
      } catch (_: Exception) { false }
    }
    return systemCandidates.firstOrNull() ?: candidates.firstOrNull()
  }

  companion object { private const val SESSION_TIMEOUT_MS = 60_000L }
}

package __PACKAGE__.overlay

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.content.pm.PackageInfo
import android.os.Build
import android.os.SystemClock
import androidx.core.content.ContextCompat
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Fetches a newer build of this app and hands it to Android's own installer.
 *
 * Nothing here starts by itself: the reader pressed Update. The file is checked
 * three times before the installer sees it (its size and checksum as GitHub
 * states them; that it is this app; that it is signed with the key already on
 * the phone), and Android then asks the reader once more. A build signed with
 * another key could never replace this one, so that is said plainly instead of
 * left to a failed install.
 */
object KrikoUpdater {
  const val RESULT_ACTION = "__PACKAGE__.overlay.UPDATE_RESULT"
  private const val MAX_BYTES = 400L * 1024L * 1024L
  private val VERSION = Regex("[0-9]{1,4}\\.[0-9]{1,4}\\.[0-9]{1,4}")

  private val downloading = AtomicBoolean(false)
  @Volatile private var cancelled = false
  @Volatile private var receiver: BroadcastReceiver? = null

  /** `kind` is a short word JavaScript maps to the reader's language. */
  class Failure(val kind: String, message: String) : Exception(message)

  class Fetched(val sha256: String, val bytes: Long)

  private fun folder(context: Context): File = File(context.cacheDir, "kriko-updates").also { it.mkdirs() }

  private fun apkFile(context: Context, version: String): File {
    if (!VERSION.matches(version)) throw Failure("invalid", "That is not a version number.")
    return File(folder(context), "kriko-agent-$version.apk")
  }

  fun cancel() {
    cancelled = true
  }

  private fun hex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it) }

  private fun digestOf(file: File): String {
    val sha = MessageDigest.getInstance("SHA-256")
    file.inputStream().use { input ->
      val buffer = ByteArray(64 * 1024)
      while (true) {
        val read = input.read(buffer)
        if (read < 0) break
        sha.update(buffer, 0, read)
      }
    }
    return hex(sha.digest())
  }

  /**
   * Download one version into the app's own cache. Blocking: call it off the
   * main thread. A finished file whose checksum already matches is reused, so
   * a trip to the phone's "install unknown apps" page does not cost a second
   * download.
   */
  fun download(
    context: Context,
    version: String,
    url: String,
    expectedSha: String,
    expectedBytes: Long,
    progress: (Long, Long) -> Unit,
  ): Fetched {
    val target = apkFile(context, version)
    if (!downloading.compareAndSet(false, true)) throw Failure("busy", "An update is already downloading.")
    cancelled = false
    val part = File(target.path + ".part")
    var connection: HttpURLConnection? = null
    try {
      folder(context).listFiles()?.forEach { if (it != target) it.delete() }
      if (target.exists()) {
        val have = digestOf(target)
        if (expectedSha.isNotEmpty() && have == expectedSha && (expectedBytes <= 0L || target.length() == expectedBytes)) {
          progress(target.length(), target.length())
          return Fetched(have, target.length())
        }
        target.delete()
      }

      connection = (URL(url).openConnection() as HttpURLConnection).apply {
        connectTimeout = 15_000
        readTimeout = 30_000
        instanceFollowRedirects = true
        setRequestProperty("Accept", "application/octet-stream")
        setRequestProperty("User-Agent", "Kriko-Agent-Android")
      }
      val code = connection.responseCode
      if (code != 200) throw Failure("network", "The download server answered $code.")
      val total = connection.contentLengthLong.takeIf { it > 0L } ?: expectedBytes

      val sha = MessageDigest.getInstance("SHA-256")
      var received = 0L
      var lastReport = 0L
      connection.inputStream.use { input ->
        part.outputStream().use { output ->
          val buffer = ByteArray(64 * 1024)
          while (true) {
            if (cancelled) throw Failure("cancelled", "The download was cancelled.")
            val read = input.read(buffer)
            if (read < 0) break
            output.write(buffer, 0, read)
            sha.update(buffer, 0, read)
            received += read
            if (received > MAX_BYTES) throw Failure("size", "The download is larger than an app should be.")
            val now = SystemClock.elapsedRealtime()
            if (now - lastReport >= 200L) {
              lastReport = now
              progress(received, total)
            }
          }
        }
      }
      progress(received, total)
      if (expectedBytes > 0L && received != expectedBytes) {
        throw Failure("size", "The download stopped early ($received of $expectedBytes bytes).")
      }
      val got = hex(sha.digest())
      if (expectedSha.isNotEmpty() && got != expectedSha) {
        throw Failure("checksum", "The download does not match the checksum GitHub states for it.")
      }
      if (!part.renameTo(target)) throw Failure("storage", "The download could not be saved.")
      return Fetched(got, received)
    } catch (failure: Failure) {
      part.delete()
      throw failure
    } catch (error: IOException) {
      part.delete()
      val full = error.message?.contains("ENOSPC") == true
      throw Failure(if (full) "storage" else "network", error.message ?: "The download failed.")
    } finally {
      connection?.disconnect()
      downloading.set(false)
    }
  }

  @Suppress("DEPRECATION")
  private fun signersOf(info: PackageInfo): Set<String> {
    val signatures = if (Build.VERSION.SDK_INT >= 28) {
      val signing = info.signingInfo ?: return emptySet()
      if (signing.hasMultipleSigners()) signing.apkContentsSigners else signing.signingCertificateHistory
    } else {
      info.signatures
    }
    return signatures?.map { hex(MessageDigest.getInstance("SHA-256").digest(it.toByteArray())) }?.toSet() ?: emptySet()
  }

  @Suppress("DEPRECATION")
  private fun codeOf(info: PackageInfo): Long =
    if (Build.VERSION.SDK_INT >= 28) info.longVersionCode else info.versionCode.toLong()

  /** Is this file a build of this app that the phone will accept over the one it has? */
  private fun check(context: Context, file: File) {
    val manager = context.packageManager
    @Suppress("DEPRECATION")
    val flags = if (Build.VERSION.SDK_INT >= 28) PackageManager.GET_SIGNING_CERTIFICATES else PackageManager.GET_SIGNATURES
    val archive = manager.getPackageArchiveInfo(file.path, flags)
      ?: throw Failure("invalid", "The download is not an app package.")
    if (archive.packageName != context.packageName) throw Failure("invalid", "The download is a different app.")
    val installed = manager.getPackageInfo(context.packageName, flags)
    if (codeOf(archive) < codeOf(installed)) throw Failure("older", "The download is older than the installed app.")
    val offered = signersOf(archive)
    val current = signersOf(installed)
    // An archive that does not reveal its signers is left to the installer to judge.
    if (offered.isNotEmpty() && current.isNotEmpty() && offered.intersect(current).isEmpty()) {
      throw Failure("signature", "The download is signed with a different key than the installed app.")
    }
  }

  /**
   * Hand the downloaded version to the system installer. `notify` hears what
   * the system says next: "confirm" (its screen is open), "installed",
   * "cancelled", or "failed" with a reason. A successful install replaces this
   * very process, so "installed" may never be heard; the next start simply
   * finds the new version.
   */
  fun install(context: Context, version: String, notify: (String, String) -> Unit) {
    val file = apkFile(context, version)
    if (!file.exists()) throw Failure("missing", "The download is gone. Download it again.")
    if (Build.VERSION.SDK_INT >= 26 && !context.packageManager.canRequestPackageInstalls()) {
      throw Failure("permission", "Allow Kriko to install apps first.")
    }
    check(context, file)

    val installer = context.packageManager.packageInstaller
    val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
    params.setAppPackageName(context.packageName)
    params.setSize(file.length())
    if (Build.VERSION.SDK_INT >= 31) {
      params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
    }
    val id = try {
      installer.createSession(params)
    } catch (error: IOException) {
      throw Failure("storage", error.message ?: "The installer could not start.")
    }

    listen(context, notify)
    try {
      installer.openSession(id).use { session ->
        file.inputStream().use { input ->
          session.openWrite("kriko-agent.apk", 0L, file.length()).use { output ->
            input.copyTo(output)
            session.fsync(output)
          }
        }
        val intent = Intent(RESULT_ACTION).setPackage(context.packageName)
        // The system fills the result into this intent, so it must be mutable.
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or
          (if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0)
        session.commit(PendingIntent.getBroadcast(context, id, intent, flags).intentSender)
      }
    } catch (error: Exception) {
      stopListening(context)
      try { installer.abandonSession(id) } catch (_: Exception) { }
      throw Failure("storage", error.message ?: "The installer could not take the file.")
    }
  }

  private fun listen(context: Context, notify: (String, String) -> Unit) {
    stopListening(context)
    val created = object : BroadcastReceiver() {
      override fun onReceive(received: Context, intent: Intent) {
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
        val message = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE) ?: ""
        when (status) {
          PackageInstaller.STATUS_PENDING_USER_ACTION -> {
            @Suppress("DEPRECATION")
            val confirm = if (Build.VERSION.SDK_INT >= 33) {
              intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
            } else {
              intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
            }
            if (confirm == null) {
              finish(received, notify, "failed", "The installer asked for a screen it did not give.")
              return
            }
            try {
              confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
              received.startActivity(confirm)
              notify("confirm", "")
            } catch (error: Exception) {
              finish(received, notify, "failed", error.message ?: "The installer's screen would not open.")
            }
          }
          PackageInstaller.STATUS_SUCCESS -> finish(received, notify, "installed", "")
          PackageInstaller.STATUS_FAILURE_ABORTED -> finish(received, notify, "cancelled", message)
          PackageInstaller.STATUS_FAILURE_BLOCKED -> finish(received, notify, "blocked", message)
          PackageInstaller.STATUS_FAILURE_INCOMPATIBLE -> finish(received, notify, "signature", message)
          PackageInstaller.STATUS_FAILURE_STORAGE -> finish(received, notify, "storage", message)
          else -> finish(received, notify, "failed", message)
        }
      }
    }
    receiver = created
    ContextCompat.registerReceiver(context, created, IntentFilter(RESULT_ACTION), ContextCompat.RECEIVER_NOT_EXPORTED)
  }

  private fun finish(context: Context, notify: (String, String) -> Unit, state: String, message: String) {
    stopListening(context)
    notify(state, message)
  }

  private fun stopListening(context: Context) {
    val current = receiver ?: return
    receiver = null
    try { context.unregisterReceiver(current) } catch (_: Exception) { }
  }
}

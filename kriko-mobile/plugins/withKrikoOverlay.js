const fs = require('fs');
const path = require('path');
const {
  withAndroidManifest,
  withDangerousMod,
  withMainApplication,
} = require('@expo/config-plugins');

const PACKAGE_CLASS = 'KrikoOverlayPackage';
const TEMPLATE_FILES = [
  'KrikoOverlayModule.kt',
  'KrikoOverlayPackage.kt',
  'KrikoOverlayService.kt',
  'KrikoTheme.kt',
  'KrikoWidgets.kt',
  'KrikoPuckView.kt',
  'KrikoGlass.kt',
  'KrikoScanFx.kt',
  'KrikoMarkdown.kt',
  'KrikoAssist.kt',
  'KrikoUpdater.kt',
];

/**
 * The file Android reads to learn that Kriko is a digital assistant. Both the
 * session service and a recognition service are required by the platform; the
 * names are written out in full because Android does not expand a leading dot
 * in this file the way it does in the manifest.
 */
function voiceInteractionXml(appPackage) {
  return `<?xml version="1.0" encoding="utf-8"?>
<voice-interaction-service xmlns:android="http://schemas.android.com/apk/res/android"
    android:sessionService="${appPackage}.overlay.KrikoAssistSessionService"
    android:recognitionService="${appPackage}.overlay.KrikoRecognitionService"
    android:supportsAssist="true"
    android:supportsLaunchVoiceAssistFromKeyguard="true" />
`;
}

async function syncNativeSources(projectRoot, platformProjectRoot, appPackage) {
  if (!/^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$/.test(appPackage)) {
    throw new Error('The Android application package must be a valid Java package name.');
  }
  const packagePath = appPackage.replace(/\./g, path.sep);
  const destination = path.join(
    platformProjectRoot,
    'app', 'src', 'main', 'java', packagePath, 'overlay',
  );
  const templateRoot = path.join(projectRoot, 'plugins', 'overlay');
  await fs.promises.mkdir(destination, { recursive: true });
  for (const file of TEMPLATE_FILES) {
    const template = await fs.promises.readFile(path.join(templateRoot, file), 'utf8');
    await fs.promises.writeFile(
      path.join(destination, file),
      template.replaceAll('__PACKAGE__', appPackage),
      'utf8',
    );
  }
  const xmlDirectory = path.join(platformProjectRoot, 'app', 'src', 'main', 'res', 'xml');
  await fs.promises.mkdir(xmlDirectory, { recursive: true });
  await fs.promises.writeFile(
    path.join(xmlDirectory, 'kriko_voice_interaction.xml'),
    voiceInteractionXml(appPackage),
    'utf8',
  );
  const fontDirectory = path.join(platformProjectRoot, 'app', 'src', 'main', 'assets', 'fonts');
  await fs.promises.mkdir(fontDirectory, { recursive: true });
  for (const [weight, face] of [['400Regular', 'Regular'], ['500Medium', 'Medium'], ['600SemiBold', 'SemiBold']]) {
    const font = require.resolve(`@expo-google-fonts/geist/${weight}/Geist_${weight}.ttf`, { paths: [projectRoot] });
    await fs.promises.copyFile(font, path.join(fontDirectory, `KrikoGeist-${face}.ttf`));
  }
}

function withKrikoOverlay(config) {
  const appPackage = config.android?.package;
  if (!appPackage || !/^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$/.test(appPackage)) {
    throw new Error('withKrikoOverlay requires android.package to be a valid Java package name.');
  }

  config = withAndroidManifest(config, (mod) => {
    const application = mod.modResults.manifest.application?.[0];
    if (!application) throw new Error('Kriko overlay could not locate the Android application manifest.');
    const serviceName = `${appPackage}.overlay.KrikoOverlayService`;
    application.service = application.service || [];
    const service = application.service.find((row) => row.$?.['android:name'] === serviceName);
    const entry = service || { $: { 'android:name': serviceName } };
    entry.$ = {
      ...entry.$,
      'android:exported': 'false',
      'android:foregroundServiceType': 'mediaProjection',
      'android:stopWithTask': 'false',
    };
    if (!service) application.service.push(entry);

    // Kriko as a digital assistant: listed under Default apps → Digital assistant,
    // started by a long press of the power or home button.
    const upsertService = (name, attributes, extras = {}) => {
      const full = `${appPackage}.overlay.${name}`;
      const existing = application.service.find((row) => row.$?.['android:name'] === full);
      const row = existing || { $: { 'android:name': full } };
      row.$ = { ...row.$, ...attributes };
      Object.assign(row, extras);
      if (!existing) application.service.push(row);
    };
    upsertService('KrikoAssistService', {
      'android:permission': 'android.permission.BIND_VOICE_INTERACTION',
      'android:exported': 'true',
    }, {
      'meta-data': [{ $: {
        'android:name': 'android.voice_interaction',
        'android:resource': '@xml/kriko_voice_interaction',
      } }],
      'intent-filter': [{ action: [{ $: { 'android:name': 'android.service.voice.VoiceInteractionService' } }] }],
    });
    upsertService('KrikoAssistSessionService', {
      'android:permission': 'android.permission.BIND_VOICE_INTERACTION',
      'android:exported': 'true',
    });
    upsertService('KrikoRecognitionService', {
      'android:exported': 'true',
    }, {
      'intent-filter': [{
        action: [{ $: { 'android:name': 'android.speech.RecognitionService' } }],
        category: [{ $: { 'android:name': 'android.intent.category.DEFAULT' } }],
      }],
    });

    // The see-through screen that asks for screen capture again when Scan is
    // pressed after the system ended the previous grant.
    application.activity = application.activity || [];
    const captureName = `${appPackage}.overlay.KrikoCaptureActivity`;
    const capture = application.activity.find((row) => row.$?.['android:name'] === captureName);
    const captureEntry = capture || { $: { 'android:name': captureName } };
    captureEntry.$ = {
      ...captureEntry.$,
      'android:exported': 'false',
      'android:theme': '@android:style/Theme.Translucent.NoTitleBar',
      'android:excludeFromRecents': 'true',
      'android:taskAffinity': '',
    };
    if (!capture) application.activity.push(captureEntry);
    return mod;
  });

  config = withMainApplication(config, (mod) => {
    let source = mod.modResults.contents;
    const call = `add(${appPackage}.overlay.${PACKAGE_CLASS}())`;
    if (!source.includes(call)) {
      const marker = 'PackageList(this).packages.apply {';
      if (!source.includes(marker)) {
        throw new Error('Kriko overlay could not find PackageList(this).packages.apply in MainApplication.kt.');
      }
      source = source.replace(marker, `${marker}\n          ${call}`);
    }
    mod.modResults.contents = source;
    return mod;
  });

  return withDangerousMod(config, ['android', async (mod) => {
    await syncNativeSources(
      mod.modRequest.projectRoot,
      mod.modRequest.platformProjectRoot,
      appPackage,
    );
    return mod;
  }]);
}

module.exports = withKrikoOverlay;
module.exports.syncNativeSources = syncNativeSources;

async function syncAndroidCli() {
  const targetArgument = process.argv[3];
  if (!targetArgument) throw new Error('Pass the generated android project path after --sync-android.');
  const projectRoot = path.resolve(__dirname, '..');
  const expectedRoot = path.resolve(projectRoot, 'android');
  const platformProjectRoot = path.resolve(targetArgument);
  if (platformProjectRoot !== expectedRoot) {
    throw new Error(`Refusing to sync outside this project's generated android directory: ${expectedRoot}`);
  }
  const manifest = path.join(platformProjectRoot, 'app', 'src', 'main', 'AndroidManifest.xml');
  if (!fs.existsSync(manifest)) {
    throw new Error(`Generated Android manifest not found at the expected CNG path: ${manifest}`);
  }
  const appConfig = JSON.parse(await fs.promises.readFile(path.join(projectRoot, 'app.json'), 'utf8'));
  const appPackage = appConfig?.expo?.android?.package;
  if (!appPackage) throw new Error('app.json does not declare expo.android.package.');
  await syncNativeSources(projectRoot, platformProjectRoot, appPackage);
  // Keep generated release metadata aligned without clearing Gradle outputs.
  const gradlePath = path.join(platformProjectRoot, 'app', 'build.gradle');
  const version = appConfig.expo.version;
  const versionCode = appConfig.expo.android.versionCode;
  if (!/^[0-9A-Za-z.+-]+$/.test(version) || !Number.isSafeInteger(versionCode) || versionCode < 1) {
    throw new Error('app.json contains invalid Android release version metadata.');
  }
  const gradle = await fs.promises.readFile(gradlePath, 'utf8');
  if (!/\bversionCode\s+\d+/.test(gradle) || !/\bversionName\s+['"][^'"]+['"]/.test(gradle)) {
    throw new Error('Generated app/build.gradle version fields could not be located.');
  }
  const updated = gradle.replace(/\bversionCode\s+\d+/, `versionCode ${versionCode}`)
    .replace(/\bversionName\s+['"][^'"]+['"]/, `versionName "${version}"`);
  if (updated !== gradle) await fs.promises.writeFile(gradlePath, updated, 'utf8');
}

if (require.main === module && process.argv[2] === '--sync-android') {
  syncAndroidCli().catch((error) => {
    console.error(error.message || String(error));
    process.exitCode = 1;
  });
}

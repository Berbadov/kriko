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
];

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

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const ts = require('typescript');

const root = path.resolve(__dirname, '..');
const output = fs.mkdtempSync(path.join(os.tmpdir(), 'kriko-mobile-tests-'));
try {
  const program = ts.createProgram({
    rootNames: [
      path.join(__dirname, 'test-adaptive-turn.ts'),
      path.join(__dirname, 'test-screen.ts'),
      path.join(__dirname, 'test-queue.ts'),
      path.join(__dirname, 'test-history.ts'),
      path.join(__dirname, 'test-fresh-chat.ts'),
      path.join(__dirname, 'test-thumbs.ts'),
      path.join(__dirname, 'test-vision.ts'),
      path.join(__dirname, 'test-i18n.ts'),
      path.join(__dirname, 'test-theme.ts'),
    ],
    options: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
      moduleResolution: ts.ModuleResolutionKind.Node10,
      esModuleInterop: true,
      skipLibCheck: true,
      noCheck: true,
      types: ['node'],
      outDir: output,
    },
  });
  const emitted = program.emit();
  if (emitted.emitSkipped) throw new Error('TypeScript could not emit the offline test files.');

  for (const file of [
    'tools/test-adaptive-turn.js',
    'tools/test-screen.js',
    'tools/test-queue.js',
    'tools/test-history.js',
    'tools/test-fresh-chat.js',
    'tools/test-thumbs.js',
    'tools/test-vision.js',
    'tools/test-i18n.js',
    'tools/test-theme.js',
  ]) {
    const result = spawnSync(process.execPath, [path.join(output, file)], {
      cwd: root,
      // The emitted tests live under the OS temp directory, so a test that
      // imports a dev dependency (the i18n audit uses the TypeScript parser)
      // must find this project's node_modules rather than walking up from temp.
      env: {
        ...process.env,
        NODE_PATH: path.join(root, 'node_modules'),
        KRIKO_MOBILE_ROOT: root,
      },
      stdio: 'inherit',
    });
    if (result.error) throw result.error;
    if (result.status !== 0) process.exitCode = result.status || 1;
    if (process.exitCode) break;
  }
} finally {
  fs.rmSync(output, { recursive: true, force: true });
}

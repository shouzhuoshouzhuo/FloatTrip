'use strict';

// React Native 0.86.2 invokes `find` through a shell without quoting the app
// path. Keep native Codegen working when a repository directory contains
// spaces. Remove this after upgrading to a release that fixes it upstream.
const fs = require('fs');
const path = require('path');

const target = path.join(
  __dirname,
  '..',
  'node_modules',
  'react-native',
  'scripts',
  'codegen',
  'generate-artifacts-executor',
  'generateReactCodegenPodspec.js',
);

let source = fs.readFileSync(target, 'utf8');
const replacements = [
  [
    'execSync(`find ${resolvedAppPath} -type d -name "*.xcodeproj"`)',
    'execSync(`find "${resolvedAppPath}" -type d -name "*.xcodeproj"`)',
  ],
  [
    'const findCommand = `find ${path.join(resolvedAppPath, jsSrcsDir)} -type f',
    'const findCommand = `find "${path.join(resolvedAppPath, jsSrcsDir)}" -type f',
  ],
];

let changed = false;
for (const [before, after] of replacements) {
  if (source.includes(after)) {continue;}
  if (!source.includes(before)) {
    throw new Error(`React Native Codegen patch target changed: ${before}`);
  }
  source = source.replace(before, after);
  changed = true;
}

if (changed) {fs.writeFileSync(target, source);}

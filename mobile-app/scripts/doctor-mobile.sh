#!/bin/sh

set -u

status=0

check_command() {
  label="$1"
  command_name="$2"
  if command -v "$command_name" >/dev/null 2>&1; then
    printf 'ok   %-18s %s\n' "$label" "$(command -v "$command_name")"
  else
    printf 'miss %-18s %s\n' "$label" "$command_name"
    status=1
  fi
}

check_command "Node.js" node
check_command "npm" npm
if command -v java >/dev/null 2>&1 && java -version >/dev/null 2>&1; then
  printf 'ok   %-18s %s\n' "JDK" "$(command -v java)"
else
  printf 'miss %-18s install JDK 17\n' "JDK"
  status=1
fi
check_command "Android adb" adb
check_command "Xcode" xcodebuild
check_command "CocoaPods" pod
check_command "Watchman" watchman

if command -v xcodebuild >/dev/null 2>&1 && ! xcodebuild -version >/dev/null 2>&1; then
  printf 'miss %-18s command line tools are selected; choose full Xcode\n' "Full Xcode"
  status=1
fi

if [ "$status" -ne 0 ]; then
  printf '\nInstall the missing native toolchain before Android/iOS builds. JS checks can still run.\n'
fi

exit "$status"

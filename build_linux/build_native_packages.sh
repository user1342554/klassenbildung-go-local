#!/usr/bin/env bash
# Baut eine vollstaendige Linux-App und verpackt sie als RPM und DEB.
# Standardmaessig entsteht das Bundle in einem manylinux_2_28-Container, damit
# es auch auf aelteren glibc-basierten Distributionen startet.

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
VERSION="${KB_VERSION:-1.0.0}"
BUILD_DIR="$PROJECT_DIR/build_linux/build"
NATIVE_DIST="$PROJECT_DIR/build_linux/native-dist"
PACKAGES_DIR="$PROJECT_DIR/build_linux/packages"
RPM_TOP="$PROJECT_DIR/build_linux/rpmbuild"

case "$(uname -m)" in
  x86_64|amd64)
    RPM_ARCH="x86_64"
    DEB_ARCH="amd64"
    CONTAINER_ARCH="x86_64"
    ;;
  aarch64|arm64)
    RPM_ARCH="aarch64"
    DEB_ARCH="arm64"
    CONTAINER_ARCH="aarch64"
    ;;
  *)
    printf 'Nicht unterstuetzte Architektur: %s\n' "$(uname -m)" >&2
    exit 1
    ;;
esac

if [[ "${KB_NATIVE_REUSE_BUNDLE:-0}" == "1" ]]; then
  rm -rf -- "$PACKAGES_DIR" "$RPM_TOP"
else
  rm -rf -- "$BUILD_DIR" "$NATIVE_DIST" "$PACKAGES_DIR" "$RPM_TOP"
fi
mkdir -p "$BUILD_DIR" "$NATIVE_DIST" "$PACKAGES_DIR" "$RPM_TOP"

build_bundle_in_container() {
  local image="quay.io/pypa/manylinux_2_28_${CONTAINER_ARCH}:latest"
  command -v podman >/dev/null 2>&1 || {
    printf 'Podman fehlt. Fuer einen lokalen Build KB_NATIVE_LOCAL=1 setzen.\n' >&2
    exit 1
  }
  podman run --rm \
    --userns=keep-id \
    --security-opt label=disable \
    --env HOME=/tmp/klassenbildung-home \
    --env PIP_CACHE_DIR=/src/build_linux/cache/pip \
    --env UV_PYTHON_INSTALL_DIR=/src/build_linux/cache/python \
    --volume "$PROJECT_DIR:/src" \
    --workdir /src \
    "$image" \
    /bin/bash -lc '
      set -euo pipefail
      mkdir -p "$HOME"
      if [[ ! -x build_linux/cache/uv/uv ]]; then
        /opt/python/cp312-cp312/bin/python - <<"PY"
import pathlib
import urllib.request

url = "https://astral.sh/uv/0.12.5/install.sh"
target = pathlib.Path("build_linux/cache/uv-installer.sh")
target.parent.mkdir(parents=True, exist_ok=True)
request = urllib.request.Request(url, headers={"User-Agent": "Klassenbildung-Builder"})
with urllib.request.urlopen(request, timeout=180) as response:
    target.write_bytes(response.read())
PY
        UV_UNMANAGED_INSTALL=/src/build_linux/cache/uv \
          sh build_linux/cache/uv-installer.sh
      fi
      build_linux/cache/uv/uv venv --clear --seed --managed-python --python 3.12 \
        build_linux/build/venv
      for attempt in 1 2 3; do
        if build_linux/build/venv/bin/python -m pip install \
          --disable-pip-version-check --timeout 180 --retries 10 \
          --requirement requirements.txt "pyinstaller==6.22.2"; then
          break
        fi
        if [[ "$attempt" == "3" ]]; then
          exit 1
        fi
        sleep 2
      done
      build_linux/build/venv/bin/python -m PyInstaller \
        --noconfirm --clean \
        --workpath build_linux/build/pyinstaller \
        --distpath build_linux/native-dist \
        build_linux/Klassenbildung.spec
    '
}

build_bundle_locally() {
  local python="${KB_NATIVE_PYTHON:-$PROJECT_DIR/.venv/bin/python}"
  [[ -x "$python" ]] || {
    printf 'Python-Umgebung fehlt: %s\n' "$python" >&2
    exit 1
  }
  "$python" -m pip install --disable-pip-version-check --upgrade "pyinstaller==6.22.2"
  "$python" -m PyInstaller \
    --noconfirm --clean \
    --workpath "$BUILD_DIR/pyinstaller" \
    --distpath "$NATIVE_DIST" \
    "$PROJECT_DIR/build_linux/Klassenbildung.spec"
}

if [[ "${KB_NATIVE_REUSE_BUNDLE:-0}" != "1" ]]; then
  if [[ "${KB_NATIVE_LOCAL:-0}" == "1" ]]; then
    build_bundle_locally
  else
    build_bundle_in_container
  fi
fi

BUNDLE_DIR="$NATIVE_DIST/Klassenbildung"
BUNDLE_EXECUTABLE="$BUNDLE_DIR/Klassenbildung"
[[ -x "$BUNDLE_EXECUTABLE" ]] || {
  printf 'PyInstaller-Ausgabe fehlt: %s\n' "$BUNDLE_EXECUTABLE" >&2
  exit 1
}

KLASSENBILDUNG_SELFTEST=1 "$BUNDLE_EXECUTABLE"
desktop-file-validate "$PROJECT_DIR/build_linux/klassenbildung.desktop"
appstreamcli validate --no-net "$PROJECT_DIR/build_linux/de.klassenbildung.local.metainfo.xml"

STAGING_ROOT="$(mktemp -d -t klassenbildung-native-package.XXXXXX)"
cleanup() {
  rm -rf -- "$STAGING_ROOT"
}
trap cleanup EXIT

PACKAGE_ROOT="$STAGING_ROOT/root"
mkdir -p \
  "$PACKAGE_ROOT/usr/bin" \
  "$PACKAGE_ROOT/usr/lib" \
  "$PACKAGE_ROOT/usr/share/applications" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps" \
  "$PACKAGE_ROOT/usr/share/metainfo"

cp -a "$BUNDLE_DIR" "$PACKAGE_ROOT/usr/lib/klassenbildung"
install -m 0755 "$PROJECT_DIR/build_linux/native_wrapper.sh" "$PACKAGE_ROOT/usr/bin/klassenbildung"
install -m 0644 "$PROJECT_DIR/build_linux/klassenbildung.desktop" \
  "$PACKAGE_ROOT/usr/share/applications/klassenbildung.desktop"
install -m 0644 "$PROJECT_DIR/assets/klassenbildung.svg" \
  "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/klassenbildung.svg"
install -m 0644 "$PROJECT_DIR/build_linux/de.klassenbildung.local.metainfo.xml" \
  "$PACKAGE_ROOT/usr/share/metainfo/de.klassenbildung.local.metainfo.xml"

mkdir -p "$RPM_TOP/BUILD" "$RPM_TOP/BUILDROOT" "$RPM_TOP/RPMS" "$RPM_TOP/SOURCES" "$RPM_TOP/SPECS" "$RPM_TOP/SRPMS"
QA_RPATHS=0x0010 rpmbuild -bb "$PROJECT_DIR/build_linux/Klassenbildung.rpm.spec" \
  --define "_topdir $RPM_TOP" \
  --define "_kb_root $PACKAGE_ROOT" \
  --define "_kb_version $VERSION" \
  --define "dist .linux" \
  --define "__brp_strip %{nil}" \
  --define "__brp_strip_comment_note %{nil}" \
  --define "__brp_strip_lto %{nil}" \
  --define "__brp_strip_static_archive %{nil}"

RPM_SOURCE="$(find "$RPM_TOP/RPMS" -type f -name '*.rpm' -print -quit)"
[[ -n "$RPM_SOURCE" ]] || {
  printf 'RPM-Ausgabe fehlt.\n' >&2
  exit 1
}
RPM_PACKAGE="$PACKAGES_DIR/Klassenbildung-${VERSION}-1.${RPM_ARCH}.rpm"
install -m 0644 "$RPM_SOURCE" "$RPM_PACKAGE"

DEB_ROOT="$STAGING_ROOT/deb"
cp -a "$PACKAGE_ROOT" "$DEB_ROOT"
mkdir -p "$DEB_ROOT/DEBIAN"
INSTALLED_SIZE="$(du -sk "$DEB_ROOT/usr" | cut -f1)"
cat >"$DEB_ROOT/DEBIAN/control" <<EOF
Package: klassenbildung
Version: $VERSION-1
Section: education
Priority: optional
Architecture: $DEB_ARCH
Installed-Size: $INSTALLED_SIZE
Maintainer: Klassenbildung <noreply@example.invalid>
Depends: libc6 (>= 2.28), libstdc++6, xdg-utils
Homepage: https://github.com/user1342554/klassenbildung-go-local
Description: Lokale Anwendung zur Klassenbildung
 Importiert Excel-Daten, prueft Regeln und erstellt mit OR-Tools
 Klasseneinteilungen. Python und alle Module sind enthalten.
EOF

DEB_PACKAGE="$PACKAGES_DIR/Klassenbildung_${VERSION}-1_${DEB_ARCH}.deb"
dpkg-deb --root-owner-group --build "$DEB_ROOT" "$DEB_PACKAGE"

(
  cd -- "$PACKAGES_DIR"
  sha256sum "$(basename "$RPM_PACKAGE")" "$(basename "$DEB_PACKAGE")" >SHA256SUMS
)

printf '\nFertige Pakete:\n'
printf '  %s\n' "$RPM_PACKAGE"
printf '  %s\n' "$DEB_PACKAGE"
printf '  %s\n' "$PACKAGES_DIR/SHA256SUMS"

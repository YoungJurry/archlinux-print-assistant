# Maintainer: youngshine
pkgname=archlinux-print-assistant
pkgver=0.5.0
pkgrel=1
pkgdesc='Arch Linux GTK4 print assistant with preview, clipboard images, and reliable duplex printing'
arch=('any')
url='https://github.com/YoungJurry/archlinux-print-assistant'
license=('MIT')
provides=('pi-print-assistant')
conflicts=('pi-print-assistant')
replaces=('pi-print-assistant')
depends=(
  'python'
  'python-gobject'
  'python-cairo'
  'gtk4'
  'poppler-glib'
  'python-pillow'
  'python-reportlab'
  'python-pypdf'
  'cups'
  'cups-filters'
  'libreoffice-fresh'
  'desktop-file-utils'
)
source=(
  'archlinux-print-assistant.py'
  'com.youngshine.ArchlinuxPrintAssistant.desktop'
  'archlinux-print-assistant.svg'
  'README.md'
  'CHANGELOG.md'
  'LICENSE'
)
sha256sums=('e27ba834a05669cecf7cb2d81f3879ee8b14733ff4e3436f9878d97c59bb2544'
            'd2e7d6f0c800affa80a0aebbc88d37741ece7630bd1b8c46f31c8a1ffef95ab1'
            '59466f947822761b667c7d17f8d378a5891ded91cdc085074cb073219d60fb9a'
            '21902e005e3538676e5bb4bcf83f387f6e94f87d123a8c37b403d38278ba6cc3'
            '1bcd2715c1b4c04b5b8d446725a4616cfd9203e91ef57368aab95d060bac103a'
            'a6ce45fafbc8cffc9b31a0ff49eda39ffbaf11f0e8b41e333f3fc9c472467237')

package() {
  install -Dm755 "$srcdir/archlinux-print-assistant.py" \
    "$pkgdir/usr/bin/archlinux-print-assistant"
  install -Dm644 "$srcdir/com.youngshine.ArchlinuxPrintAssistant.desktop" \
    "$pkgdir/usr/share/applications/com.youngshine.ArchlinuxPrintAssistant.desktop"
  install -Dm644 "$srcdir/archlinux-print-assistant.svg" \
    "$pkgdir/usr/share/icons/hicolor/scalable/apps/archlinux-print-assistant.svg"
  install -Dm644 "$srcdir/README.md" \
    "$pkgdir/usr/share/doc/archlinux-print-assistant/README.md"
  install -Dm644 "$srcdir/CHANGELOG.md" \
    "$pkgdir/usr/share/doc/archlinux-print-assistant/CHANGELOG.md"
  install -Dm644 "$srcdir/LICENSE" \
    "$pkgdir/usr/share/licenses/archlinux-print-assistant/LICENSE"
}

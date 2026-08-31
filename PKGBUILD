# Maintainer: youngshine
pkgname=pi-print-assistant
pkgver=0.3.0
pkgrel=1
pkgdesc='GTK4 print assistant with PDF preview, clipboard images, and reliable duplex printing'
arch=('any')
url='https://github.com/YoungJurry/pi-print-assistant'
license=('MIT')
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
  'pi-print-assistant.py'
  'com.youngshine.PiPrintAssistant.desktop'
  'pi-print-assistant.svg'
  'README.md'
  'CHANGELOG.md'
  'LICENSE'
)
sha256sums=('d6990f608290157a63054af8d5ebdcfbfad0130fd53f12f230d8ab597d5e0ca2'
            '48cf909ad5013c45797e987e70836ea2165894ac331f321f854f5ec334e95bf9'
            '59466f947822761b667c7d17f8d378a5891ded91cdc085074cb073219d60fb9a'
            '5212a9f8528871ba6f9b68845796dc95dc4323569e7879f921aec58220af87f4'
            '12264c3d8412f71df00e37028dfba85ad5d244a7203731bd5f4f9a3e11c56058'
            'a6ce45fafbc8cffc9b31a0ff49eda39ffbaf11f0e8b41e333f3fc9c472467237')

package() {
  install -Dm755 "$srcdir/pi-print-assistant.py" \
    "$pkgdir/usr/bin/pi-print-assistant"
  install -Dm644 "$srcdir/com.youngshine.PiPrintAssistant.desktop" \
    "$pkgdir/usr/share/applications/com.youngshine.PiPrintAssistant.desktop"
  install -Dm644 "$srcdir/pi-print-assistant.svg" \
    "$pkgdir/usr/share/icons/hicolor/scalable/apps/pi-print-assistant.svg"
  install -Dm644 "$srcdir/README.md" \
    "$pkgdir/usr/share/doc/pi-print-assistant/README.md"
  install -Dm644 "$srcdir/CHANGELOG.md" \
    "$pkgdir/usr/share/doc/pi-print-assistant/CHANGELOG.md"
  install -Dm644 "$srcdir/LICENSE" \
    "$pkgdir/usr/share/licenses/pi-print-assistant/LICENSE"
}

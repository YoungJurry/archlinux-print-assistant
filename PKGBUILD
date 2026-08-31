# Maintainer: youngshine
pkgname=pi-print-assistant
pkgver=0.2.0
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
sha256sums=('a95d623ecb221071e20870eac0394e1ac4cfcb93543811c74317a989e80ca0be'
            '48cf909ad5013c45797e987e70836ea2165894ac331f321f854f5ec334e95bf9'
            '59466f947822761b667c7d17f8d378a5891ded91cdc085074cb073219d60fb9a'
            '38710f61f815d97e67319c702f250382b44f1d0de6818f53748411efbe6a55f9'
            '887dc9a80773603fbfb10f2e58eb90a91e14ed730331dca04739a2d4ea30a779'
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

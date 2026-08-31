#!/usr/bin/python
from __future__ import annotations

import argparse
import io
import math
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Poppler", "0.18")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Graphene, Gtk, Poppler

import cairo
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf._page import PageObject
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

APP_ID = "com.youngshine.ArchlinuxPrintAssistant"
APP_NAME = "arch打印助手"
DEFAULT_PRINTER = "HP_LaserJet_M403dn"
TMP_ROOT = Path(f"/tmp/archlinux-print-assistant-{os.getuid()}")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
PDF_SUFFIXES = {".pdf"}
OFFICE_SUFFIXES = {
    ".doc", ".docx", ".odt", ".rtf",
    ".ppt", ".pptx", ".odp",
    ".xls", ".xlsx", ".ods",
}
SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | PDF_SUFFIXES | OFFICE_SUFFIXES

MM = 72.0 / 25.4
IN = 72.0
PAPER_SIZES: dict[str, tuple[float, float]] = {
    "A4": (210 * MM, 297 * MM),
    "A5": (148 * MM, 210 * MM),
    "A6": (105 * MM, 148 * MM),
    "B5": (182 * MM, 257 * MM),
    "B6": (128 * MM, 182 * MM),
    "Letter": (8.5 * IN, 11 * IN),
    "Legal": (8.5 * IN, 14 * IN),
    "Executive": (7.25 * IN, 10.5 * IN),
    "Statement": (5.5 * IN, 8.5 * IN),
    "FanFoldGermanLegal": (8.5 * IN, 13 * IN),
    "4x6": (4 * IN, 6 * IN),
    "5x8": (5 * IN, 8 * IN),
    "Env4x6": (4 * IN, 6 * IN),
    "Oficio": (8.5 * IN, 13 * IN),
    "195x270mm": (195 * MM, 270 * MM),
    "184x260mm": (184 * MM, 260 * MM),
    "7.75x10.75": (7.75 * IN, 10.75 * IN),
    "Postcard": (100 * MM, 148 * MM),
    "DoublePostcardRotated": (200 * MM, 148 * MM),
    "Env10": (9.5 * IN, 4.125 * IN),
    "EnvMonarch": (7.5 * IN, 3.875 * IN),
    "EnvISOB5": (176 * MM, 250 * MM),
    "EnvC5": (162 * MM, 229 * MM),
    "EnvDL": (110 * MM, 220 * MM),
}
PAPER_LABELS = {
    "A4": "A4（默认）", "A5": "A5", "A6": "A6", "B5": "B5", "B6": "B6",
    "Letter": "Letter", "Legal": "Legal", "Executive": "Executive",
    "Statement": "Statement", "4x6": "4 × 6 英寸", "5x8": "5 × 8 英寸",
    "Postcard": "明信片", "Env10": "10号信封", "EnvC5": "C5信封", "EnvDL": "DL信封",
}


@dataclass
class PrintItem:
    path: Path
    source: str = "file"

    @property
    def display_name(self) -> str:
        return self.path.name

    @property
    def kind(self) -> str:
        suffix = self.path.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            return "图片"
        if suffix in PDF_SUFFIXES:
            return "PDF"
        if suffix in OFFICE_SUFFIXES:
            return "Office"
        return "文件"


@dataclass(frozen=True)
class PrintSettings:
    printer: str
    paper: str
    copies: int
    duplex: str
    scaling: str
    orientation: str
    input_slot: str | None
    media_type: str | None


@dataclass
class PrinterCapabilities:
    printer: str
    options: dict[str, list[str]]
    defaults: dict[str, str]

    @classmethod
    def read(cls, printer: str) -> "PrinterCapabilities":
        env = {**os.environ, "LC_ALL": "C"}
        result = subprocess.run(
            ["lpoptions", "-p", printer, "-l"],
            text=True, capture_output=True, env=env, check=True,
        )
        options: dict[str, list[str]] = {}
        defaults: dict[str, str] = {}
        for raw in result.stdout.splitlines():
            if ":" not in raw or "/" not in raw.split(":", 1)[0]:
                continue
            left, values_raw = raw.split(":", 1)
            key = left.split("/", 1)[0].strip()
            values: list[str] = []
            for token in values_raw.split():
                default = token.startswith("*")
                value = token.removeprefix("*")
                values.append(value)
                if default:
                    defaults[key] = value
            options[key] = values
        return cls(printer, options, defaults)

    def values(self, *keys: str) -> list[str]:
        for key in keys:
            if key in self.options:
                return self.options[key]
        return []


class DocumentBuilder:
    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.office_cache: dict[tuple[str, int], Path] = {}

    @staticmethod
    def paper_size(keyword: str) -> tuple[float, float]:
        return PAPER_SIZES.get(keyword, PAPER_SIZES["A4"])

    def convert_office(self, path: Path) -> Path:
        key = (str(path.resolve()), path.stat().st_mtime_ns)
        cached = self.office_cache.get(key)
        if cached and cached.exists():
            return cached
        out_dir = self.session_dir / f"office-{uuid.uuid4().hex}"
        out_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "SAL_USE_VCLPLUGIN": "svp"}
        result = subprocess.run(
            ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(path)],
            text=True, capture_output=True, env=env,
        )
        expected = out_dir / f"{path.stem}.pdf"
        if result.returncode != 0 or not expected.exists():
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"无法转换 {path.name}")
        self.office_cache[key] = expected
        return expected

    @staticmethod
    def _oriented_size(base: tuple[float, float], orientation: str, source_landscape: bool) -> tuple[float, float]:
        width, height = base
        if orientation == "landscape" or (orientation == "auto" and source_landscape):
            return max(width, height), min(width, height)
        return min(width, height), max(width, height)

    def image_pdf(self, image_path: Path, settings: PrintSettings, output: Path) -> Path:
        with Image.open(image_path) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
            source_landscape = image.width > image.height
            page_w, page_h = self._oriented_size(self.paper_size(settings.paper), settings.orientation, source_landscape)
            c = canvas.Canvas(str(output), pagesize=(page_w, page_h))
            dpi = raw.info.get("dpi", (96, 96))
            try:
                dpi_x, dpi_y = float(dpi[0]), float(dpi[1])
                if dpi_x <= 1 or dpi_y <= 1:
                    raise ValueError
            except Exception:
                dpi_x = dpi_y = 96.0
            if settings.scaling == "fit":
                margin = 12.0
                scale = min((page_w - 2 * margin) / image.width, (page_h - 2 * margin) / image.height)
                draw_w, draw_h = image.width * scale, image.height * scale
            else:
                draw_w, draw_h = image.width / dpi_x * IN, image.height / dpi_y * IN
            x, y = (page_w - draw_w) / 2, (page_h - draw_h) / 2
            c.drawImage(ImageReader(image), x, y, draw_w, draw_h, preserveAspectRatio=True, mask="auto")
            c.showPage()
            c.save()
        return output

    def normalize_pdf(self, input_pdf: Path, settings: PrintSettings, writer: PdfWriter) -> None:
        reader = PdfReader(str(input_pdf))
        for source in reader.pages:
            if source.rotation:
                source.transfer_rotation_to_content()
            src_w = float(source.mediabox.width)
            src_h = float(source.mediabox.height)
            page_w, page_h = self._oriented_size(
                self.paper_size(settings.paper), settings.orientation, src_w > src_h,
            )
            target = PageObject.create_blank_page(width=page_w, height=page_h)
            if settings.scaling == "fit":
                margin = 12.0
                scale = min((page_w - 2 * margin) / src_w, (page_h - 2 * margin) / src_h)
            else:
                scale = 1.0
            tx = (page_w - src_w * scale) / 2
            ty = (page_h - src_h * scale) / 2
            target.merge_transformed_page(source, Transformation().scale(scale).translate(tx, ty))
            writer.add_page(target)

    def build(
        self, items: list[PrintItem], settings: PrintSettings, output: Path,
    ) -> tuple[Path, int, list[tuple[int, int]]]:
        writer = PdfWriter()
        page_ranges: list[tuple[int, int]] = []
        work_dir = self.session_dir / f"build-{uuid.uuid4().hex}"
        work_dir.mkdir(parents=True, exist_ok=True)
        for index, item in enumerate(items):
            start_page = len(writer.pages)
            suffix = item.path.suffix.lower()
            if suffix in IMAGE_SUFFIXES:
                item_pdf = work_dir / f"image-{index}.pdf"
                self.image_pdf(item.path, settings, item_pdf)
                self.normalize_pdf(item_pdf, settings, writer)
            elif suffix in PDF_SUFFIXES:
                self.normalize_pdf(item.path, settings, writer)
            elif suffix in OFFICE_SUFFIXES:
                self.normalize_pdf(self.convert_office(item.path), settings, writer)
            else:
                raise RuntimeError(f"不支持的文件类型：{item.path.name}")
            page_ranges.append((start_page, len(writer.pages) - start_page))
        if len(writer.pages) == 0:
            raise RuntimeError("没有可预览的页面")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("wb") as fh:
            writer.write(fh)
        return output, len(writer.pages), page_ranges


class PreviewRenderer:
    def __init__(self):
        self.document: Poppler.Document | None = None
        self.path: Path | None = None

    def load(self, path: Path) -> int:
        self.path = path
        self.document = Poppler.Document.new_from_file(path.resolve().as_uri(), None)
        return self.document.get_n_pages()

    def render(self, index: int, max_width: int = 720, max_height: int = 820) -> GdkPixbuf.Pixbuf:
        if not self.document:
            raise RuntimeError("预览尚未生成")
        page = self.document.get_page(index)
        width, height = page.get_size()
        scale = min(max_width / width, max_height / height)
        pixel_w = max(1, int(width * scale))
        pixel_h = max(1, int(height * scale))
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, pixel_w, pixel_h)
        context = cairo.Context(surface)
        context.set_source_rgb(1, 1, 1)
        context.paint()
        context.scale(scale, scale)
        page.render(context)
        buffer = io.BytesIO()
        surface.write_to_png(buffer)
        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.write(buffer.getvalue())
        loader.close()
        pixbuf = loader.get_pixbuf()
        if pixbuf is None:
            raise RuntimeError("无法渲染预览")
        return pixbuf.copy()


class FileRow(Gtk.ListBoxRow):
    def __init__(
        self,
        item: PrintItem,
        remove_cb: Callable[["FileRow"], None],
        drag_begin_cb: Callable[["FileRow"], None],
        drag_update_cb: Callable[["FileRow", float], None],
        drag_end_cb: Callable[["FileRow", float], None],
    ):
        super().__init__()
        self.item = item
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(7); box.set_margin_bottom(7); box.set_margin_start(8); box.set_margin_end(8)
        handle = Gtk.Image.new_from_icon_name("list-drag-handle-symbolic")
        handle.set_tooltip_text("拖动调整顺序")
        icon_name = "image-x-generic-symbolic" if item.kind == "图片" else (
            "application-pdf-symbolic" if item.kind == "PDF" else "x-office-document-symbolic"
        )
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(32)
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        name = Gtk.Label(label=item.display_name, xalign=0)
        name.set_ellipsize(3)
        detail = Gtk.Label(label=f"{item.kind} · {item.path}", xalign=0)
        detail.add_css_class("dim-label")
        detail.set_ellipsize(3)
        text_box.append(name); text_box.append(detail)
        text_box.set_hexpand(True)
        remove = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        remove.set_tooltip_text("从列表移除")
        remove.add_css_class("flat")
        remove.connect("clicked", lambda _b: remove_cb(self))
        box.append(handle); box.append(icon); box.append(text_box); box.append(remove)
        self.set_child(box)

        handle.set_cursor_from_name("grab")
        drag_gesture = Gtk.GestureDrag()
        drag_gesture.set_button(Gdk.BUTTON_PRIMARY)

        def on_drag_begin(_gesture, _x, _y):
            self.add_css_class("drag-placeholder")
            handle.set_cursor_from_name("grabbing")
            drag_begin_cb(self)

        def on_drag_update(_gesture, _offset_x, offset_y):
            drag_update_cb(self, offset_y)

        def on_drag_end(_gesture, _offset_x, offset_y):
            self.remove_css_class("drag-placeholder")
            handle.set_cursor_from_name("grab")
            drag_end_cb(self, offset_y)

        drag_gesture.connect("drag-begin", on_drag_begin)
        drag_gesture.connect("drag-update", on_drag_update)
        drag_gesture.connect("drag-end", on_drag_end)
        handle.add_controller(drag_gesture)


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title=APP_NAME)
        self.set_default_size(1280, 800)
        self.set_size_request(980, 640)
        self.items: list[PrintItem] = []
        self.rows: list[FileRow] = []
        self.session_dir = TMP_ROOT / f"session-{uuid.uuid4().hex}"
        self.session_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        TMP_ROOT.chmod(0o700)
        self.builder = DocumentBuilder(self.session_dir)
        self.preview = PreviewRenderer()
        self.preview_path: Path | None = None
        self.preview_pages = 0
        self.preview_index = 0
        self.preview_item_ranges: list[tuple[int, int]] = []
        self.preview_dirty = True
        self.building = False
        self.rebuild_again = False
        self.rebuild_source: int | None = None
        self.capabilities: PrinterCapabilities | None = None
        self.last_job_id: str | None = None
        self.drag_state: dict | None = None
        self._build_ui()
        self._load_printers()
        self._install_controllers()

    def _build_ui(self) -> None:
        # 不使用 Gtk.HeaderBar 客户端装饰，交给 XFWM 绘制紧凑且与系统一致的标题栏。
        self.set_decorated(True)
        self.set_title(APP_NAME)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        paned_left = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        paned_right = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        files_panel = self._build_files_panel()
        paned_left.set_start_child(files_panel)
        paned_left.set_end_child(paned_right)
        paned_left.set_resize_start_child(False)
        paned_left.set_shrink_start_child(False)
        paned_right.set_start_child(self._build_preview_panel())
        paned_right.set_end_child(self._build_settings_panel())
        paned_left.set_position(340)
        paned_right.set_position(650)
        paned_left.set_vexpand(True)
        root.append(paned_left)
        self.status = Gtk.Label(label="添加文件或按 Ctrl+V 粘贴剪贴板图片", xalign=0)
        self.status.set_margin_start(10); self.status.set_margin_end(10)
        self.status.set_margin_top(6); self.status.set_margin_bottom(6)
        self.status.add_css_class("dim-label")
        root.append(self.status)
        self.set_child(root)

    def _panel_title(self, text: str) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0)
        label.add_css_class("heading")
        label.set_margin_top(10); label.set_margin_bottom(8); label.set_margin_start(10); label.set_margin_end(10)
        return label

    def _build_files_panel(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_size_request(300, -1)
        box.set_margin_start(8); box.set_margin_end(8)
        box.append(self._panel_title("待打印文件"))
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        toolbar.set_margin_start(8); toolbar.set_margin_end(8); toolbar.set_margin_bottom(8)
        add = Gtk.Button(label="添加文件")
        add.connect("clicked", self._on_add_clicked)
        paste = Gtk.Button(label="粘贴图片")
        paste.connect("clicked", lambda _b: self.paste_clipboard())
        clear = Gtk.Button.new_from_icon_name("edit-clear-all-symbolic")
        clear.set_tooltip_text("清空")
        clear.connect("clicked", lambda _b: self.clear_items())
        toolbar.append(add); toolbar.append(paste); toolbar.append(clear)
        box.append(toolbar)
        self.file_list = Gtk.ListBox()
        self.file_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.file_list.connect("row-selected", self._on_file_selected)
        self.file_list.add_css_class("boxed-list")
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(self.file_list)
        scroll.set_vexpand(True)
        self.file_overlay = Gtk.Overlay()
        self.file_overlay.set_child(scroll)
        self.file_overlay.set_vexpand(True)
        box.append(self.file_overlay)
        hint = Gtk.Label(label="拖动列表项目可调整打印顺序\n支持右键打开方式和 Ctrl+V", justify=Gtk.Justification.CENTER)
        hint.add_css_class("dim-label")
        hint.set_margin_top(8); hint.set_margin_bottom(10)
        box.append(hint)
        return box

    def _build_preview_panel(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_hexpand(True); box.set_vexpand(True)
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.set_margin_start(10); top.set_margin_end(10); top.set_margin_top(8); top.set_margin_bottom(8)
        title = Gtk.Label(label="打印预览", xalign=0)
        title.add_css_class("heading"); title.set_hexpand(True)
        self.sheet_toggle = Gtk.ToggleButton(label="纸张视图")
        self.sheet_toggle.set_sensitive(False)
        self.sheet_toggle.connect("toggled", lambda _b: self._render_current())
        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh.set_tooltip_text("重新生成预览")
        refresh.connect("clicked", lambda _b: self.schedule_preview(immediate=True))
        top.append(title); top.append(self.sheet_toggle); top.append(refresh)
        box.append(top)
        self.preview_stack = Gtk.Stack()
        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        placeholder.set_valign(Gtk.Align.CENTER); placeholder.set_halign(Gtk.Align.CENTER)
        placeholder.append(Gtk.Image.new_from_icon_name("document-print-preview-symbolic"))
        placeholder.append(Gtk.Label(label="添加文件后将在这里显示最终打印效果"))
        self.preview_stack.add_named(placeholder, "empty")
        preview_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        preview_box.set_margin_start(10); preview_box.set_margin_end(10)
        preview_box.set_margin_top(5); preview_box.set_margin_bottom(5)
        self.front_frame = Gtk.Frame(label="页面")
        self.front_picture = Gtk.Picture()
        self.front_picture.set_can_shrink(True)
        self.front_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.front_frame.set_child(self.front_picture)
        self.front_frame.set_hexpand(True); self.front_frame.set_vexpand(True)
        self.back_frame = Gtk.Frame(label="背面")
        self.back_picture = Gtk.Picture()
        self.back_picture.set_can_shrink(True)
        self.back_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.back_frame.set_child(self.back_picture)
        self.back_frame.set_hexpand(True); self.back_frame.set_vexpand(True)
        preview_box.append(self.front_frame); preview_box.append(self.back_frame)
        self.preview_stack.add_named(preview_box, "preview")
        self.preview_stack.set_visible_child_name("empty")
        self.preview_stack.set_vexpand(True)
        box.append(self.preview_stack)
        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        nav.set_halign(Gtk.Align.CENTER); nav.set_margin_top(8); nav.set_margin_bottom(10)
        self.prev_button = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        self.prev_button.connect("clicked", lambda _b: self.change_preview(-1))
        self.page_label = Gtk.Label(label="0 / 0")
        self.next_button = Gtk.Button.new_from_icon_name("go-next-symbolic")
        self.next_button.connect("clicked", lambda _b: self.change_preview(1))
        nav.append(self.prev_button); nav.append(self.page_label); nav.append(self.next_button)
        box.append(nav)
        return box

    def _setting_row(self, label_text: str, widget: Gtk.Widget) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        row.set_margin_start(10); row.set_margin_end(10); row.set_margin_bottom(9)
        label = Gtk.Label(label=label_text, xalign=0)
        label.add_css_class("dim-label")
        row.append(label); row.append(widget)
        return row

    def _build_settings_panel(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.set_size_request(280, -1)
        outer.append(self._panel_title("打印设置"))
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.printer_combo = Gtk.ComboBoxText()
        self.printer_combo.connect("changed", self._on_printer_changed)
        content.append(self._setting_row("打印机", self.printer_combo))
        self.paper_combo = Gtk.ComboBoxText()
        self.paper_combo.connect("changed", self._on_setting_changed)
        content.append(self._setting_row("纸张尺寸（默认 A4）", self.paper_combo))
        self.copies_spin = Gtk.SpinButton.new_with_range(1, 999, 1)
        self.copies_spin.set_value(1)
        self.copies_spin.connect("value-changed", lambda _w: self._update_summary(self.current_settings()))
        content.append(self._setting_row("份数", self.copies_spin))
        self.duplex_combo = Gtk.ComboBoxText()
        self.duplex_combo.append("single", "单面（默认）")
        self.duplex_combo.append("long", "双面 · 长边翻转")
        self.duplex_combo.append("short", "双面 · 短边翻转")
        self.duplex_combo.set_active_id("single")
        self.duplex_combo.connect("changed", self._on_setting_changed)
        content.append(self._setting_row("打印方式", self.duplex_combo))
        self.scaling_combo = Gtk.ComboBoxText()
        self.scaling_combo.append("fit", "适应页面（默认）")
        self.scaling_combo.append("original", "原始尺寸")
        self.scaling_combo.set_active_id("fit")
        self.scaling_combo.connect("changed", self._on_setting_changed)
        content.append(self._setting_row("缩放", self.scaling_combo))
        self.orientation_combo = Gtk.ComboBoxText()
        self.orientation_combo.append("auto", "自动")
        self.orientation_combo.append("portrait", "纵向")
        self.orientation_combo.append("landscape", "横向")
        self.orientation_combo.set_active_id("auto")
        self.orientation_combo.connect("changed", self._on_setting_changed)
        content.append(self._setting_row("方向", self.orientation_combo))
        self.input_combo = Gtk.ComboBoxText()
        content.append(self._setting_row("进纸来源", self.input_combo))
        self.media_combo = Gtk.ComboBoxText()
        content.append(self._setting_row("纸张类型", self.media_combo))
        color = Gtk.Label(label="黑白（当前打印机固定）", xalign=0)
        color.set_sensitive(False)
        content.append(self._setting_row("颜色", color))
        self.summary = Gtk.Label(label="尚未生成预览", xalign=0)
        self.summary.set_wrap(True)
        summary_frame = Gtk.Frame(label="预计结果")
        summary_frame.set_margin_start(10); summary_frame.set_margin_end(10); summary_frame.set_margin_top(4)
        summary_frame.set_child(self.summary)
        self.summary.set_margin_top(8); self.summary.set_margin_bottom(8); self.summary.set_margin_start(8); self.summary.set_margin_end(8)
        content.append(summary_frame)
        scroll.set_child(content); scroll.set_vexpand(True)
        outer.append(scroll)
        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        self.print_button = Gtk.Button(label="打印")
        self.print_button.add_css_class("suggested-action")
        self.print_button.set_sensitive(False)
        self.print_button.connect("clicked", self._on_print_clicked)
        self.stop_button = Gtk.Button(label="紧急停止上个任务")
        self.stop_button.add_css_class("destructive-action")
        self.stop_button.set_visible(False)
        self.stop_button.connect("clicked", self._on_emergency_stop)
        action = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        action.set_margin_top(8); action.set_margin_bottom(10); action.set_margin_start(10); action.set_margin_end(10)
        action.append(self.spinner); action.append(self.print_button); action.append(self.stop_button)
        outer.append(action)
        return outer

    def _install_controllers(self) -> None:
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key)
        try:
            drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
            drop.connect("drop", self._on_files_dropped)
            self.add_controller(drop)
        except Exception:
            pass

    def _on_key_pressed(self, _controller, keyval, _keycode, state) -> bool:
        if keyval in (Gdk.KEY_v, Gdk.KEY_V) and state & Gdk.ModifierType.CONTROL_MASK:
            self.paste_clipboard()
            return True
        return False

    def _on_files_dropped(self, _target, value, _x, _y) -> bool:
        try:
            self.add_paths([Path(file.get_path()) for file in value.get_files() if file.get_path()])
            return True
        except Exception as exc:
            self.show_error(str(exc))
            return False

    @staticmethod
    def _available_printers() -> list[str]:
        env = {**os.environ, "LC_ALL": "C"}
        result = subprocess.run(["lpstat", "-p"], text=True, capture_output=True, env=env)
        printers: list[str] = []
        for line in result.stdout.splitlines():
            if line.startswith("printer "):
                printers.append(line.split()[1])
        return printers

    def _load_printers(self) -> None:
        printers = self._available_printers()
        for printer in printers:
            self.printer_combo.append(printer, printer)
        selected = DEFAULT_PRINTER if DEFAULT_PRINTER in printers else (printers[0] if printers else None)
        if selected:
            self.printer_combo.set_active_id(selected)
        else:
            self.status.set_text("没有发现可用打印机")
            self.print_button.set_sensitive(False)

    def _fill_combo(self, combo: Gtk.ComboBoxText, values: list[str], default: str | None, labels=None) -> None:
        combo.remove_all()
        labels = labels or {}
        filtered = [value for value in values if not value.startswith("Custom.")]
        for value in filtered:
            combo.append(value, labels.get(value, value))
        wanted = default if default in filtered else (filtered[0] if filtered else None)
        if wanted:
            combo.set_active_id(wanted)

    def _on_printer_changed(self, _combo) -> None:
        printer = self.printer_combo.get_active_id()
        if not printer:
            return
        try:
            self.capabilities = PrinterCapabilities.read(printer)
            papers = [p for p in self.capabilities.values("PageSize") if p in PAPER_SIZES]
            self._fill_combo(self.paper_combo, papers or ["A4"], "A4", PAPER_LABELS)
            self._fill_combo(
                self.input_combo,
                self.capabilities.values("InputSlot"),
                self.capabilities.defaults.get("InputSlot"),
                {"Auto": "自动", "Tray1": "纸盒1", "Tray2": "纸盒2", "Tray3": "纸盒3", "ManualFeed": "手动进纸"},
            )
            self._fill_combo(
                self.media_combo,
                self.capabilities.values("MediaType"),
                self.capabilities.defaults.get("MediaType"),
                {"Unspecified": "自动/未指定", "Plain": "普通纸", "Recycled": "再生纸", "Labels": "标签", "Envelope": "信封"},
            )
            duplex_values = self.capabilities.values("Duplex")
            self.duplex_combo.set_sensitive("DuplexNoTumble" in duplex_values and "DuplexTumble" in duplex_values)
            if not self.duplex_combo.get_sensitive():
                self.duplex_combo.set_active_id("single")
            self.schedule_preview()
        except Exception as exc:
            self.show_error(f"读取打印机能力失败：{exc}")

    def _on_setting_changed(self, _widget) -> None:
        duplex_enabled = self.duplex_combo.get_active_id() != "single"
        self.sheet_toggle.set_sensitive(duplex_enabled)
        # 选择双面后默认切换到正反面配对视图，直接显示每张纸的两面。
        self.sheet_toggle.set_active(duplex_enabled)
        self.schedule_preview()

    def current_settings(self) -> PrintSettings:
        return PrintSettings(
            printer=self.printer_combo.get_active_id() or DEFAULT_PRINTER,
            paper=self.paper_combo.get_active_id() or "A4",
            copies=int(self.copies_spin.get_value()),
            duplex=self.duplex_combo.get_active_id() or "single",
            scaling=self.scaling_combo.get_active_id() or "fit",
            orientation=self.orientation_combo.get_active_id() or "auto",
            input_slot=self.input_combo.get_active_id(),
            media_type=self.media_combo.get_active_id(),
        )

    def _on_add_clicked(self, _button) -> None:
        dialog = Gtk.FileDialog(title="添加待打印文件")
        dialog.open_multiple(self, None, self._on_files_selected)

    def _on_files_selected(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            model = dialog.open_multiple_finish(result)
            paths = []
            for index in range(model.get_n_items()):
                file = model.get_item(index)
                if file and file.get_path():
                    paths.append(Path(file.get_path()))
            self.add_paths(paths)
        except GLib.Error as exc:
            if not exc.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED):
                self.show_error(str(exc))
        except Exception as exc:
            self.show_error(str(exc))

    def add_paths(self, paths: list[Path], source: str = "file") -> None:
        rejected: list[str] = []
        for path in paths:
            path = path.expanduser().resolve()
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                rejected.append(path.name)
                continue
            item = PrintItem(path, source)
            row = FileRow(
                item,
                self.remove_row,
                self.begin_live_drag,
                self.update_live_drag,
                self.end_live_drag,
            )
            self.items.append(item); self.rows.append(row); self.file_list.append(row)
        if rejected:
            self.show_error("暂不支持：" + "、".join(rejected))
        if paths and self.items:
            self.status.set_text(f"已添加 {len(self.items)} 个文件")
            self.schedule_preview()

    def remove_row(self, row: FileRow) -> None:
        if row not in self.rows:
            return
        index = self.rows.index(row)
        self.rows.pop(index); self.items.pop(index); self.file_list.remove(row)
        self.schedule_preview()

    def clear_items(self) -> None:
        for row in self.rows:
            self.file_list.remove(row)
        self.rows.clear(); self.items.clear()
        self.preview_path = None; self.preview_pages = 0; self.preview_item_ranges = []; self.preview_dirty = True
        self.preview_stack.set_visible_child_name("empty")
        self.summary.set_text("尚未生成预览")
        self.print_button.set_sensitive(False)
        self.status.set_text("添加文件或按 Ctrl+V 粘贴剪贴板图片")

    def _make_drag_preview(self, row: FileRow) -> Gtk.Widget:
        frame = Gtk.Frame()
        frame.add_css_class("drag-floating")
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content.set_margin_top(8); content.set_margin_bottom(8)
        content.set_margin_start(10); content.set_margin_end(10)
        icon_name = "image-x-generic-symbolic" if row.item.kind == "图片" else (
            "application-pdf-symbolic" if row.item.kind == "PDF" else "x-office-document-symbolic"
        )
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(32)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        name = Gtk.Label(label=row.item.display_name, xalign=0)
        name.set_ellipsize(3)
        detail = Gtk.Label(label=row.item.kind, xalign=0)
        detail.add_css_class("dim-label")
        labels.append(name); labels.append(detail)
        labels.set_hexpand(True)
        content.append(icon); content.append(labels)
        frame.set_child(content)
        frame.set_halign(Gtk.Align.START); frame.set_valign(Gtk.Align.START)
        frame.set_can_target(False)
        return frame

    def begin_live_drag(self, row: FileRow) -> None:
        if row not in self.rows or self.drag_state is not None:
            return
        ok, point = row.compute_point(self.file_overlay, Graphene.Point().init(0, 0))
        if not ok:
            point = Graphene.Point().init(0, 0)
        floating = self._make_drag_preview(row)
        floating.set_size_request(max(220, row.get_width()), max(1, row.get_height()))
        floating.set_margin_start(max(0, int(point.x)))
        floating.set_margin_top(max(0, int(point.y)))
        self.file_overlay.add_overlay(floating)
        start_top = float(point.y)
        self.drag_state = {
            "row": row,
            "origin_index": self.rows.index(row),
            "start_top": start_top,
            "desired_top": start_top,
            "display_top": start_top,
            "last_frame_time": None,
            "row_height": max(1, row.get_height()),
            "floating": floating,
            "changed": False,
        }
        self.drag_state["tick_id"] = self.file_overlay.add_tick_callback(self._tick_live_drag)
        self.file_list.select_row(row)
        self.status.set_text(f"正在拖动：{row.item.display_name}")

    def _tick_live_drag(self, _widget, frame_clock) -> bool:
        state = self.drag_state
        if not state:
            return False
        now = frame_clock.get_frame_time() / 1_000_000.0
        last = state["last_frame_time"]
        state["last_frame_time"] = now
        if last is None:
            alpha = 1.0
        else:
            # 约 45ms 的平滑跟随，既能紧跟鼠标，也能滤掉细小抖动。
            delta_time = max(0.001, min(0.05, now - last))
            alpha = 1.0 - math.exp(-delta_time / 0.045)
        state["display_top"] += (state["desired_top"] - state["display_top"]) * alpha
        state["floating"].set_margin_top(int(round(state["display_top"])))
        return True

    def _move_dragged_row_live(self, row: FileRow, target_index: int) -> None:
        current_index = self.rows.index(row)
        while current_index < target_index:
            crossing_index = current_index + 1
            crossing_row = self.rows[crossing_index]
            crossing_item = self.items[crossing_index]
            self.rows.pop(crossing_index); self.items.pop(crossing_index)
            self.rows.insert(current_index, crossing_row); self.items.insert(current_index, crossing_item)
            self.file_list.remove(crossing_row)
            self.file_list.insert(crossing_row, current_index)
            current_index += 1
        while current_index > target_index:
            crossing_index = current_index - 1
            crossing_row = self.rows[crossing_index]
            crossing_item = self.items[crossing_index]
            self.rows.pop(crossing_index); self.items.pop(crossing_index)
            self.rows.insert(current_index, crossing_row); self.items.insert(current_index, crossing_item)
            self.file_list.remove(crossing_row)
            self.file_list.insert(crossing_row, current_index)
            current_index -= 1

    def update_live_drag(self, row: FileRow, offset_y: float) -> None:
        state = self.drag_state
        if not state or state["row"] is not row:
            return
        current_index = self.rows.index(row)
        # GestureDrag 的 offset 是相对被拖控件计算的；列表换位后，控件本身
        # 也移动了一行，GTK 会把这段位移反向计入 offset，造成浮层突然跳回。
        # 加回控件相对起点移动的行数，得到相对窗口稳定的鼠标位移。
        stable_offset_y = offset_y + (
            current_index - state["origin_index"]
        ) * state["row_height"]
        max_top = max(0, self.file_overlay.get_height() - state["row_height"])
        state["desired_top"] = max(0, min(max_top, state["start_top"] + stable_offset_y))

        # 使用带滞回区间的换位阈值：向下越过 62% 才换位，换位后必须
        # 反向退回到 38% 才恢复，避免鼠标停在中线附近时来回闪烁。
        pointer_position = state["origin_index"] + stable_offset_y / state["row_height"]
        target_index = current_index
        while target_index < len(self.rows) - 1 and pointer_position > target_index + 0.62:
            target_index += 1
        while target_index > 0 and pointer_position < target_index - 0.62:
            target_index -= 1
        current_index = self.rows.index(row)
        if target_index != current_index:
            self._move_dragged_row_live(row, target_index)
            state["changed"] = True
            self.preview_dirty = True
            self.print_button.set_sensitive(False)
            self.status.set_text(f"移动到第 {target_index + 1} 位：{row.item.display_name}")

    def end_live_drag(self, row: FileRow, _offset_y: float) -> None:
        state = self.drag_state
        if not state or state["row"] is not row:
            return
        self.file_overlay.remove_tick_callback(state["tick_id"])
        self.file_overlay.remove_overlay(state["floating"])
        changed = state["changed"]
        self.drag_state = None
        self.file_list.select_row(row)
        if changed:
            self.status.set_text(f"已调整到第 {self.rows.index(row) + 1} 位：{row.item.display_name}")
            self.schedule_preview(immediate=True)
        else:
            self.status.set_text(f"顺序未改变：{row.item.display_name}")

    def _on_file_selected(self, _list_box, row: FileRow | None) -> None:
        if self.drag_state is not None or row is None or row not in self.rows or self.preview_dirty:
            return
        self._jump_to_row(row)

    def _jump_to_row(self, row: FileRow) -> None:
        index = self.rows.index(row)
        if index >= len(self.preview_item_ranges):
            return
        first_page, page_count = self.preview_item_ranges[index]
        if page_count <= 0:
            return
        self.preview_index = first_page // 2 if self._sheet_mode() else first_page
        self._render_current()
        self.status.set_text(f"已跳到：{row.item.display_name}（第 {first_page + 1} 页）")

    def paste_clipboard(self) -> None:
        clipboard = Gdk.Display.get_default().get_clipboard()
        # 微信和 QQ 在 X11 下通常公开 image/png 等 MIME，而不一定公开
        # Gdk.Texture GType；直接尝试 read_texture_async 最可靠。
        clipboard.read_texture_async(None, self._on_clipboard_texture)

    def _on_clipboard_texture(self, clipboard, result) -> None:
        try:
            texture = clipboard.read_texture_finish(result)
            if texture is None:
                raise RuntimeError("no texture")
            path = TMP_ROOT / f"clipboard-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.png"
            TMP_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
            texture.save_to_png(str(path))
            self.add_paths([path], source="clipboard")
            self.status.set_text(f"剪贴板图片已保存：{path}")
        except Exception:
            # 若剪贴板保存的是文件 URI 或路径，再尝试文本读取。
            clipboard.read_text_async(None, self._on_clipboard_text)

    def _on_clipboard_text(self, clipboard, result) -> None:
        try:
            text = clipboard.read_text_finish(result) or ""
            paths: list[Path] = []
            for line in text.splitlines():
                value = line.strip()
                if value.startswith("file://"):
                    file = Gio.File.new_for_uri(value)
                    if file.get_path():
                        paths.append(Path(file.get_path()))
                elif Path(value).is_file():
                    paths.append(Path(value))
            if not paths:
                raise RuntimeError("剪贴板中没有图片或文件")
            self.add_paths(paths, source="clipboard")
        except Exception as exc:
            self.show_error(str(exc))

    def schedule_preview(self, immediate: bool = False) -> None:
        self.preview_dirty = True
        self.print_button.set_sensitive(False)
        if not self.items:
            return
        if self.rebuild_source:
            GLib.source_remove(self.rebuild_source)
        self.rebuild_source = GLib.timeout_add(1 if immediate else 450, self._start_preview_build)

    def _start_preview_build(self) -> bool:
        self.rebuild_source = None
        if self.building:
            self.rebuild_again = True
            return False
        items = list(self.items)
        settings = self.current_settings()
        output = self.session_dir / f"preview-{uuid.uuid4().hex}.pdf"
        self.building = True; self.preview_dirty = True
        self.spinner.set_visible(True); self.spinner.start()
        self.status.set_text("正在生成最终 PDF 预览……")

        def worker():
            try:
                result = self.builder.build(items, settings, output)
                GLib.idle_add(self._preview_built, result[0], result[1], result[2], settings, None)
            except Exception as exc:
                GLib.idle_add(self._preview_built, None, 0, [], settings, str(exc))
        threading.Thread(target=worker, daemon=True).start()
        return False

    def _preview_built(
        self,
        path: Path | None,
        pages: int,
        item_ranges: list[tuple[int, int]],
        settings: PrintSettings,
        error: str | None,
    ) -> bool:
        self.building = False; self.spinner.stop(); self.spinner.set_visible(False)
        if error or path is None:
            self.preview_dirty = True
            self.print_button.set_sensitive(False)
            self.show_error(f"生成预览失败：{error}")
        else:
            try:
                self.preview.load(path)
                self.preview_path = path; self.preview_pages = pages; self.preview_index = 0
                self.preview_item_ranges = item_ranges
                self.preview_dirty = False
                self.preview_stack.set_visible_child_name("preview")
                self.print_button.set_sensitive(True)
                self._update_summary(settings)
                selected = self.file_list.get_selected_row()
                if selected in self.rows:
                    self._jump_to_row(selected)
                else:
                    self._render_current()
                    self.status.set_text(f"预览已生成：{pages} 页 · {path}")
            except Exception as exc:
                self.preview_dirty = True
                self.show_error(f"载入预览失败：{exc}")
        if self.rebuild_again:
            self.rebuild_again = False
            self.schedule_preview(immediate=True)
        return False

    def _sheet_mode(self) -> bool:
        return self.sheet_toggle.get_active() and self.duplex_combo.get_active_id() != "single"

    def _render_current(self) -> None:
        if not self.preview_path or self.preview_pages == 0:
            return
        sheet = self._sheet_mode()
        unit_count = math.ceil(self.preview_pages / 2) if sheet else self.preview_pages
        self.preview_index = max(0, min(self.preview_index, unit_count - 1))
        try:
            if sheet:
                front_idx = self.preview_index * 2
                back_idx = front_idx + 1
                self.front_frame.set_label(f"正面 · 第 {front_idx + 1} 页")
                self.front_picture.set_pixbuf(self.preview.render(front_idx, 460, 700))
                self.back_frame.set_visible(True)
                if back_idx < self.preview_pages:
                    self.back_frame.set_label(f"背面 · 第 {back_idx + 1} 页")
                    self.back_picture.set_pixbuf(self.preview.render(back_idx, 460, 700))
                else:
                    self.back_frame.set_label("背面 · 空白")
                    self.back_picture.set_pixbuf(None)
                flip = "长边" if self.duplex_combo.get_active_id() == "long" else "短边"
                self.page_label.set_text(f"第 {self.preview_index + 1} / {unit_count} 张纸 · {flip}翻转")
            else:
                self.front_frame.set_label(f"第 {self.preview_index + 1} 页")
                self.front_picture.set_pixbuf(self.preview.render(self.preview_index, 720, 820))
                self.back_frame.set_visible(False)
                self.page_label.set_text(f"第 {self.preview_index + 1} / {unit_count} 页")
            self.prev_button.set_sensitive(self.preview_index > 0)
            self.next_button.set_sensitive(self.preview_index + 1 < unit_count)
            self._update_summary(self.current_settings())
        except Exception as exc:
            self.show_error(f"渲染预览失败：{exc}")

    def change_preview(self, delta: int) -> None:
        self.preview_index += delta
        self._render_current()

    def _expected_sheets(self, settings: PrintSettings) -> int:
        per_copy = self.preview_pages if settings.duplex == "single" else math.ceil(self.preview_pages / 2)
        return per_copy * settings.copies

    def _update_summary(self, settings: PrintSettings) -> None:
        if self.preview_pages == 0:
            return
        mode = {"single": "单面", "long": "双面长边", "short": "双面短边"}[settings.duplex]
        self.summary.set_text(
            f"内容：{self.preview_pages}页\n"
            f"预计：{self._expected_sheets(settings)}张纸\n"
            f"纸张：{settings.paper}\n份数：{settings.copies}\n"
            f"方式：{mode}\n缩放：{'自适应' if settings.scaling == 'fit' else '原始尺寸'}"
        )

    def _print_command(self, settings: PrintSettings) -> list[str]:
        if not self.preview_path:
            raise RuntimeError("没有可打印的最终 PDF")
        command = ["lp", "-d", settings.printer, "-n", str(settings.copies), "-o", f"media={settings.paper}"]
        duplex_value = {"single": "None", "long": "DuplexNoTumble", "short": "DuplexTumble"}[settings.duplex]
        if self.capabilities and "Duplex" in self.capabilities.options:
            command += ["-o", f"Duplex={duplex_value}"]
        else:
            sides = {"single": "one-sided", "long": "two-sided-long-edge", "short": "two-sided-short-edge"}[settings.duplex]
            command += ["-o", f"sides={sides}"]
        if settings.scaling == "fit":
            command += ["-o", "fit-to-page"]
        if settings.input_slot and settings.input_slot != "Auto":
            command += ["-o", f"InputSlot={settings.input_slot}"]
        if settings.media_type and settings.media_type != "Unspecified":
            command += ["-o", f"MediaType={settings.media_type}"]
        if settings.copies > 1:
            command += ["-o", "Collate=True"]
        command.append(str(self.preview_path))
        return command

    def _on_print_clicked(self, _button) -> None:
        if self.preview_dirty or not self.preview_path:
            self.show_error("预览尚未更新，不能打印")
            return
        settings = self.current_settings()
        mode = {"single": "单面", "long": "双面长边翻转", "short": "双面短边翻转"}[settings.duplex]
        message = (
            f"打印机：{settings.printer}\n文件：{len(self.items)}个\n内容：{self.preview_pages}页\n"
            f"预计用纸：{self._expected_sheets(settings)}张\n纸张：{settings.paper}\n"
            f"份数：{settings.copies}\n颜色：黑白\n方式：{mode}\n"
            f"缩放：{'适应页面' if settings.scaling == 'fit' else '原始尺寸'}"
        )
        dialog = Gtk.AlertDialog(message="确认打印？", detail=message)
        dialog.set_buttons(["取消", "打印"])
        dialog.set_cancel_button(0); dialog.set_default_button(1)
        dialog.choose(self, None, lambda d, result: self._on_print_confirmed(d, result, settings))

    def _on_print_confirmed(self, dialog: Gtk.AlertDialog, result, settings: PrintSettings) -> None:
        try:
            if dialog.choose_finish(result) != 1:
                return
            if settings.duplex != "single":
                values = self.capabilities.values("Duplex") if self.capabilities else []
                required = "DuplexNoTumble" if settings.duplex == "long" else "DuplexTumble"
                if required not in values:
                    raise RuntimeError("当前驱动未公开所选双面功能，任务已阻止")
            command = self._print_command(settings)
            env = {**os.environ, "LC_ALL": "C"}
            result = subprocess.run(command, text=True, capture_output=True, env=env)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "lp 提交失败")
            output = result.stdout.strip()
            match = re.search(r"request id is (\S+)", output)
            self.last_job_id = match.group(1) if match else None
            self.stop_button.set_visible(bool(self.last_job_id))
            self.status.set_text(f"打印任务已提交：{output}")
            done = Gtk.AlertDialog(message="打印任务已提交", detail=f"{output}\n请核对实际出纸结果。")
            done.show(self)
        except Exception as exc:
            self.show_error(str(exc))

    def _on_emergency_stop(self, _button) -> None:
        if not self.last_job_id:
            return
        subprocess.run(["cupsdisable", self.current_settings().printer], capture_output=True)
        subprocess.run(["cancel", self.last_job_id], capture_output=True)
        self.status.set_text(f"已暂停打印机并尝试取消任务 {self.last_job_id}；如仍出纸，请按打印机面板取消键")

    def show_error(self, message: str) -> None:
        self.status.set_text(message)
        dialog = Gtk.AlertDialog(message="操作失败", detail=message)
        dialog.show(self)


class PrintApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.window: MainWindow | None = None

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        TMP_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            .heading { font-weight: 700; font-size: 1.1em; }
            .dim-label { opacity: 0.68; font-size: 0.9em; }
            .drag-placeholder { opacity: 0.20; }
            .drag-floating {
                background-color: @theme_bg_color;
                border: 2px solid #7aa2f7;
                border-radius: 8px;
                box-shadow: 0 8px 20px rgba(0, 0, 0, 0.38);
                opacity: 0.96;
            }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def ensure_window(self) -> MainWindow:
        if self.window is None:
            self.window = MainWindow(self)
        return self.window

    def do_activate(self) -> None:
        self.ensure_window().present()

    def do_open(self, files, _n_files, _hint) -> None:
        window = self.ensure_window()
        paths = [Path(file.get_path()) for file in files if file.get_path()]
        window.add_paths(paths)
        window.present()


def self_test(files: list[str], output: str) -> int:
    TMP_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    session = TMP_ROOT / f"self-test-{uuid.uuid4().hex}"
    session.mkdir(parents=True)
    settings = PrintSettings(DEFAULT_PRINTER, "A4", 1, "long", "fit", "auto", None, None)
    items = [PrintItem(Path(path).resolve()) for path in files]
    result, pages, item_ranges = DocumentBuilder(session).build(items, settings, Path(output))
    print(f"output={result}")
    print(f"pages={pages}")
    print(f"item_ranges={item_ranges}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", default="/tmp/archlinux-print-assistant-self-test.pdf")
    parser.add_argument("files", nargs="*")
    known, _unknown = parser.parse_known_args()
    if known.self_test:
        return self_test(known.files, known.output)
    app = PrintApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())

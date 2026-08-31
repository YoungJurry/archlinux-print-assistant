# arch打印助手

本机 GTK4 图形化打印程序。所有输入先转换并合并为一个最终 PDF，预览确认后再通过 CUPS `lp` 提交。

## 功能

- 默认 A4、1份、黑白、单面、自适应页面
- 单面、双面长边、双面短边
- 多图片自动合并为一个多页 PDF，双面时正确打印在同一张纸正反面
- 图片、PDF、Word、PowerPoint、Excel、OpenDocument 文件
- 最终 PDF 页面预览及双面正反面纸张预览
- 微信/QQ 剪贴板图片通过 Ctrl+V 保存至 `/tmp/archlinux-print-assistant-<UID>/` 并添加
- 文件拖放和 Thunar“打开方式”集成
- 待打印列表支持带实时动画和平滑跟随的拖动排序
- 选中列表项目时，预览自动跳转到该文件首页
- 使用 XFWM 原生标题栏，与 XFCE 窗口按钮和主题一致
- 打印前显示内容页数和预计用纸数

## 构建安装

```bash
git clone https://github.com/YoungJurry/archlinux-print-assistant.git
cd archlinux-print-assistant
makepkg -si
```

安装后可从 XFCE 应用菜单启动“arch打印助手”，或在 Thunar 中右键文件选择“打开方式”。

## 卸载

```bash
sudo pacman -Rns archlinux-print-assistant
```

# VF PDF Helper

![VF PDF Helper 图标](assets/vf-pdf-helper.png)

VF PDF Helper 是一款完全免费、开源的 Windows PDF 浏览、页面整理、表单填写、签名与文本层编辑工具。

项目主页：<https://github.com/FFeederR10/vf-pdf-helper>

## 功能

- 打开、浏览 PDF，支持缩放、适合宽度、前后翻页
- 左侧缩略图拖拽排序，以及多选删除、左转或右转页面
- 插入另一份 PDF，可选择来源页码范围和插入位置
- 单击选择文本块，Delete/Backspace 删除，按住拖动调整位置
- 双击已有文字原位修改；Enter 或点击别处保存，Esc 取消
- 点击页面位置直接输入新增文字
- 浮动工具条设置字体、字号、颜色、加粗、斜体和下划线
- 填写 AcroForm 文本框、复选框、单选框、下拉框和列表框
- 简易签名画笔，颜色和粗细可调，保存为标准 PDF Ink 注释
- 12 步撤销/重做，导出时原子写入并重新打开校验
- 支持从命令行传入 PDF，可设为 Windows 默认 PDF 打开程序

## 系统要求

- Windows 10/11 64 位
- 从源码运行或构建时需要 Python 3.12

## 从源码运行

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## 测试

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q
```

## 构建 Windows 版本

```powershell
.\build.ps1
```

构建产物为：

- `dist\VF PDF Helper\VF PDF Helper.exe`
- `dist\VF-PDF-Helper-windows-x64.zip`

程序采用 PyInstaller `onedir` 方式打包，运行库放在可见目录中，方便用户检查、替换和重新构建依赖。压缩包会同时包含开源许可、第三方声明和源码提供说明。

## 文字与字体说明

文字修改针对 PDF 的真实文本层。扫描件、截图或已转曲的 CAD 文字没有可编辑文本层，仍可浏览、管理页面并叠加新文字，但不能直接选中原文字。

VF PDF Helper 不随程序分发 Windows 字体文件。使用系统字体写入 PDF 前，程序会检查 OpenType/TrueType 的嵌入权限，仅允许适合可编辑文档嵌入的字体。项目图标是由 `scripts/make_icon.py` 生成的位图资源。

## 开源许可

VF PDF Helper 按 [GNU Affero General Public License v3](LICENSE) 发布。任何人都可以免费使用、研究、修改和再分发，但分发修改版或提供网络服务时必须遵守 AGPL v3 的源码公开等条件。

依赖组件、所选许可和版权声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。官方二进制发布的对应源码安排见 [SOURCE_OFFER.md](SOURCE_OFFER.md)。

## 隐私

PDF 文件仅在本机处理，程序不上传文档，也不包含遥测或账户系统。提交问题时请勿上传含有私人、商业机密或无权公开的 PDF。

## 参与贡献

请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请按照 [SECURITY.md](SECURITY.md) 报告。


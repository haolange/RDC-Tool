---
kind: frontend_style
name: 内嵌 HTML 报告与原生预览窗口的轻量前端样式体系
category: frontend_style
scope:
    - '**'
source_files:
    - rdc_tool/core/report_builder.py
    - rdc_tool/preview_window.py
---

## 1. 使用的系统/方法

本仓库没有传统的前端工程（无 package.json、无 CSS/SCSS 文件、无 Tailwind/PostCSS/Webpack）。前端样式以两种互补的方式实现：

- **自包含 HTML 报告**：通过 Python 字符串常量中的 Jinja2 模板渲染出单文件 index.html，所有 CSS 使用 <style> 内联，不依赖任何外部样式表或框架。
- **Windows 原生预览窗口**：通过 ctypes.windll.user32 / kernel32 直接调用 Win32 API 创建顶层窗口，不使用 Tkinter、Webview 或第三方 GUI 库；视觉外观由 Windows 系统主题决定，仅做最小化的尺寸适配。

因此，该仓库的“前端风格”本质上是 Python 侧生成的静态 HTML + 原生 Win32 窗口的组合。

## 2. 关键文件

- rdc_tool/core/report_builder.py：定义 _HTML_TEMPLATE（约 450 行），包含完整的 CSS 变量、布局、交互脚本，并通过 ReportBuilder.build_bundle() 输出 bundle/index.html、report.json、report.md。
- rdc_tool/preview_window.py：基于 ctypes 的 Win32 预览窗口宿主，负责窗口类注册、消息循环、自动缩放与用户拖拽调整大小。
- binaries/windows/x64/python/Lib/pydoc_data/_pydoc.css：随附 Python 发行版自带的 pydoc CSS，仅在 Python 内置工具链中作为第三方资源存在，不属于项目自身样式体系。

## 3. 架构与约定

### 3.1 HTML 报告（dark theme）

- **设计令牌集中化**：在 :root 中声明一组 CSS 自定义属性（--bg-primary、--accent-blue、--accent-red 等），颜色采用 Tokyo Night 风格的深色系（背景 #1a1b26，强调色蓝/青/绿/黄/橙/红/洋红），并通过 var(--*) 全局复用。
- **布局基于 CSS Grid**：.app 使用 grid-template-areas 划分 header/sidebar/viewer/inspector/timeline 五个区域，形成固定的四栏三行网格。
- **组件式命名空间**：通过 BEM 风格前缀组织样式——.app-*、.sidebar、.viewer-*、.inspector-*、.timeline、.exp-card、.fix-banner、.empty-state 等，每个模块职责清晰。
- **字体策略**：优先使用 'Inter' 无衬线字体族，回退到系统栈；代码块使用 'JetBrains Mono' / 'Fira Code' / 'Cascadia Code' monospace。
- **交互逻辑内联**：Tab 切换、比较滑块拖拽、事件树高亮等全部以 IIFE 包裹的原生 JS 写在模板末尾，不引入 jQuery 或框架。
- **响应式基础**：通过 <meta name="viewport"> 启用移动端缩放，但整体布局为桌面端固定宽度网格（sidebar 260px、inspector 320px），未提供断点媒体查询。

### 3.2 原生预览窗口

- 通过 WNDCLASSW 注册名为 RdcToolPreviewWindow 的窗口类，使用 WS_OVERLAPPEDWINDOW | WS_EX_CLIENTEDGE 风格。
- 窗口背景色使用系统 COLOR_WINDOW + 1，光标使用 IDC_ARROW，不注入自定义图标或菜单。
- 尺寸计算集中在 fit_size_within_bounds 与 fit_content_rect：根据屏幕工作区面积乘以 screen_cap_ratio（默认 0.5）限制最大显示尺寸，并居中放置内容。
- 支持用户手动拖拽调整窗口大小，并在拖拽结束后记录 manual_size_override 状态，避免后续自动 resize 覆盖用户操作。

## 4. 约定与约束

- **禁止外部样式依赖**：报告生成器注释明确说明“确保输出为单个自包含文件，无外部依赖”，所有 CSS/JS 均内嵌于 Python 字符串模板中。
- **暗色主题强制**：模板根级 background: var(--bg-primary) 与全局文本颜色统一为浅色文字，不存在亮色主题切换逻辑。
- **Jinja2 模板即唯一 UI 源**：报告界面完全由 _HTML_TEMPLATE 驱动，新增视图区域应遵循现有 .app-header/.sidebar/.viewer/.inspector/.timeline 网格区域扩展，而非新建独立页面。
- **Win32 窗口保持极简**：预览窗口不加载 HTML/CSS，仅作为图像展示容器；任何视觉定制应通过上层渲染层（如图像缩放、叠加）完成，而非修改 Win32 样式。
- **无构建/打包步骤**：样式不是独立资产，而是 Python 源码的一部分，修改后直接随 wheel 发布，无需额外编译管线。

## 5. 适用范围说明

该样式体系仅服务于两个用途：(1) 调试报告 HTML viewer；(2) 本地预览窗口宿主。仓库中没有面向最终用户的 Web 前端、组件库或设计系统，因此 frontend_style 在此仓库中属于局部且非典型的前端关注点。
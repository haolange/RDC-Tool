## 概述

本仓库是 rdx-tools 的 Python CLI/服务端聚合项目，**没有独立的 Web 前端工程、CSS 构建管线或样式框架**。唯一的用户可见 UI 是一个由 `rdc_tool/core/report_builder.py` 生成的单文件 HTML 调试报告（`index.html`），其样式完全以内嵌 `<style>` 块的形式写在 Python 字符串常量 `_HTML_TEMPLATE` 中，并通过 Jinja2 模板渲染。

因此不存在 CSS 文件、SCSS、Tailwind 配置或设计令牌文件；样式策略是“一个 Python 源文件 + 内联 CSS”。

## 样式系统与方法论

- **CSS 方法论**：使用原生 CSS + CSS Custom Properties（`:root` 变量）。无预处理器、无 PostCSS、无 Tailwind。
- **主题模型**：基于暗色主题，所有颜色通过 CSS 变量集中声明在 `:root`，包括背景层级（`--bg-primary/secondary/tertiary/hover`）、文字层级（`--text-primary/secondary/muted`）、强调色（蓝/青/绿/黄/橙/红/紫）和边框圆角 `--radius`。
- **布局**：使用 CSS Grid 定义三栏 + 底部时间线的固定网格区域（`.app` → `grid-template-areas`），侧边栏（事件树）、中间图像查看器、右侧检查面板、底部时间线。字体采用 Inter / -apple-system / Cascadia Code 等现代无衬线 + 等宽字体栈。
- **交互**：纯 CSS hover 状态 + 少量内联 JS（用于树节点展开、标签页切换、对比滑块拖拽），JS 逻辑与 HTML 模板位于同一 Python 文件中，未分离为独立脚本。
- **响应式**：仅通过 `<meta name="viewport" content="width=device-width, initial-scale=1">` 启用移动端缩放，无媒体查询——报告以桌面端为主。

## 关键文件

- `rdc_tool/core/report_builder.py`：唯一包含样式逻辑的文件。包含 Jinja2 HTML 模板（含 `<style>`）、报告生成入口、以及把 mask/diff/final 图片作为 base64 资源注入的机制。
- `binaries/windows/x64/python/Lib/pydoc_data/_pydoc.css`：随 Python 二进制分发的 pydoc 样式表，属于第三方依赖，非本项目样式。

## 约定与约束

- **样式位置约束**：所有 UI 样式必须放在 `report_builder.py` 的 `_HTML_TEMPLATE` 字符串内；仓库中没有其他 `.css`/`.scss`/`.html` 文件（除第三方产物外）。
- **主题扩展约束**：新增视觉元素应复用已声明的 CSS 变量（`--bg-*`、`--text-*`、`--accent-*`、`--border-color`、`--radius`、`--font-mono`、`--font-sans`），以保持与既有暗色主题一致。
- **无外部样式依赖**：不引入任何 CDN 样式库；字体引用（Inter、JetBrains Mono、Fira Code、Cascadia Code）为本地回退字体栈，不强制下载。
- **模板渲染方式**：HTML 模板通过 Jinja2 渲染，动态内容（如 confidence 百分比、任务 ID、资产路径）通过 `{{ ... }}` 插值，但样式本身不使用 Jinja2 变量——颜色与尺寸全部硬编码在 CSS 变量中。

## 置信度说明

由于该仓库本质上是 Python CLI/服务端工具，前端 UI 仅为一个内嵌样式的调试报告 HTML，不存在通用的“前端风格体系”，故本卡片描述范围严格限定于 `report_builder.py` 中的内联样式。
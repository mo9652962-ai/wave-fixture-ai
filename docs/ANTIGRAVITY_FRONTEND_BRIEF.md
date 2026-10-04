# WAVE FIXTURE AI · 前端精修任务书（Antigravity 版）

> 本文档是交给 agentic IDE（Google Antigravity）执行的自包含任务书。
> 目标：把 `web/index.html` 从「功能完整」提升到「工业 SaaS 质感」。
> 执行前必读：第 1 节红线、第 6 节验收。任何一条违反即视为失败。

---

## 0. 项目一句话

波峰焊治具 AI 设计助手：拖入 Gerber → 自动生成治具 DXF/CNC G 代码/生产工单，
含 3D 预览、元件干涉分析、可疑元件高度交互表、自然语言参数调整。
后端 FastAPI（`web_server.py`），前端**单文件** `web/index.html`（内联 CSS/JS）。

## 1. 红线（不可违反）

1. **单文件架构不动**：所有 CSS/JS 保留在 `index.html` 内联；three.js 经
   `<script type="importmap">`（CDN r160）动态 import，勿改为 npm/打包器。
2. **元素 ID 是 API**：以下 ID 被内联 JS 与 pytest（`tests/test_packaging_layout.py`
   等 244 项）依赖，禁止改名/删除：
   `dropzone fileInput fileList fileItems generateBtn result statsBody status
   downloadDxf downloadPng downloadGcode downloadReport gen3dBtn resetBtn
   preview3dPanel threeContainer interfBtn interfResult interf3dPanel
   interfContainer suspTableContainer suspTableBody applyOverridesBtn
   resetOverridesBtn materialSelect machineSelect palletThickness panelCols
   panelRows panelGap adjustInput adjustBtn adjustResult`
   允许：新增 class/包裹层/新元素；不允许：删除或语义变更。
3. **API 响应契约不动**：前端消费的 `data.job_id / gcode_url / report_url /
   material.{name,sheet_thickness,weight_kg,cost.total,sink_depth} / stats.panel /
   drc.{allowed,counts,issues} / interference_boxes / suspicious_components` 等字段
   由 `web_server.py` 生成——前端只做展示层适配，不改后端。
4. **XSS 安全模式**：元件表数据（ref/name 来自用户上传文件）必须用
   `textContent`/DOM API 构建，已有 `escapeHtml()` 助手——精修时不得退化为
   innerHTML 拼接用户数据。
5. **已知坑必须保留修复**：`display:none → block` 后立即读容器尺寸会得到 0×0，
   现用 rAF 双帧（见 `renderInterference3D`）——任何重构保留该模式或等价方案。
6. **提交门槛**：完成后 `pytest tests` 244 项全绿（`test_doc_consistency.py` 会核对
   README 徽章与实际数字）；走 PR 流，CI 必需检查 4 项全绿方可合入。

## 2. 现状盘点（实测快照，2026-10-04）

页面区块（自上而下）：
1. Header（logo + GitHub 链接）——朴素，无导航锚点
2. 拖拽上传区 Dropzone（支持 .gbr/.zip 等，去重入列）
3. 生产参数栏 `prod-params`（材料/机台/板厚/拼版列行/片间距）——裸 flex，分组感弱
4. 结果区：2D 预览（matplotlib PNG）+ 生成统计（DRC 门禁徽章、DRC 发现清单、
   沉板深度依据行）+ 下载条（DXF/PNG/G 代码/生产报告/3D/重传）——按钮色彩杂
5. 自然语言调整（输入 + 示例 chips 未做成可点击）
6. 干涉分析：运行按钮 + 3D 视图（three.js GLB + 干涉红盒/可疑黄盒/选中青色）+
   **高度可疑与干涉元件交互列表**（状态徽章/可编辑高度/聚焦按钮）
7. 全局 status toast（3s 自动消失，单条，无堆叠）

已知视觉/交互短板：
- 色彩与字号无 token 体系（:root 变量有但使用不彻底）；间距不成 8px 网格
- 下载条四色按钮无主次；徽章风格不统一（DRC 门禁 vs 元件状态徽章）
- 3D 视图无工具条（重置视角/俯视/截图/线框切换都没有），只有自动旋转
- 生成期间无进度感（仅按钮 spinner + 底部 toast）；无骨架屏
- 示例指令是纯文本，未做成点击填入的 chips
- toast 3s 过快且单条；错误详情（DRC issues）藏在统计卡内
- 768px 单断点，参数栏/表格在窄屏挤压
- 对比度未系统核查（--dim #8b90a0 on #1a1d27 约 4.6:1，勉强 AA）

## 3. 设计方向：工业 SaaS 质感（参考 Linear / Vercel / Grafana 暗色系）

- **Token 化**：颜色（背景 4 层：#0b0d12 / #11141c / #161b26 / #1c2230）、
  文本 3 级、语义色（success/warn/error/info/accent）全部进 `:root`；
  字号阶梯 12/13/14/16/20/28；间距 4/8/12/16/24/32；圆角 6/10/14；
  阴影只用两层（sm/md），发光只给 accent 焦点态
- **主次明确**：主操作唯一（生成治具），下载条改为「主 DXF + 其余次级 ghost」，
  G 代码/报告用 icon+文字的紧凑次级样式，不再各配一色
- **工业感细节**：等宽数字（tabular-nums）用于所有 mm/kg/¥ 数值；
  表格行 hover 扫描线；卡片 1px 边框 + 内阴影替代大面积阴影；节点/连线的
  工程图气质（细线、直角、坐标网格背景 3% 透明度）
- **状态系统**：toast 分级（info/success/warn/error 图标+左边框色）+ 堆叠
  （最多 3 条，5s）；按钮三态（default/hover/loading 带 spinner 常宽防跳动）
- **动效纪律**：所有过渡 150-250ms ease-out；页面区块进场 8px 上移淡入
  （stagger 60ms，尊重 prefers-reduced-motion）；禁止持续循环动画（3D 自动旋转
  保留但提供暂停）

## 4. 任务分解（按此顺序做，每阶段独立可验收）

### P0 设计系统与布局骨架（先立地基）
- [ ] `:root` token 全面替换硬编码色值/间距/圆角/阴影
- [ ] Header 加导航锚点（上传/预览/3D/干涉/调整）+ 版本号徽标（读 pyproject 同步 0.2.4）
- [ ] 生产参数栏重构：分组卡片（材料 / 机台 / 拼版），label 与控件对齐，
      禁用态联动（拼版列行=1 时片间距置灰）
- [ ] 下载条按钮主次重构（见上）
- [ ] 验收：改动前后 DOM 截图对比无功能回归；244 tests 绿

### P1 核心流程反馈
- [ ] 生成流程进度条：顶部细进度条 + 结果区骨架屏（2D 预览/统计卡/下载条占位）
- [ ] toast 堆叠系统（替换现单条 status）：
      success ⏱5s / error 需手动关闭 + 「查看详情」展开 DRC/接口错误
- [ ] DRC 发现清单卡片化：四级严重度左侧色条 + 可折叠 + 每条带出处来源行
- [ ] 自然语言示例做成可点击 chips（点击填入 adjustInput）
- [ ] 验收：拖入 `cases/case_003_stm32_4layer` 全流程走通（含 DRC 未过的
      case_001 水印路径），toast/骨架屏无闪烁

### P2 3D 体验（重点）
- [ ] 3D 工具条（悬浮右上）：重置视角 / 俯视 / 暂停自旋 / 线框模式 / 截图 PNG
- [ ] OrbitControls 保留阻尼；双击元件盒 = 聚焦（与表格点击联动已有）
- [ ] 聚焦动画：镜头用 lerp 平滑过渡（300ms）而非瞬移；选中盒脉冲发光一次
- [ ] 干涉/可疑图例（红=干涉 黄=可疑 青=选中）常驻左下角
- [ ] 尺寸标注：GLB 场景加外形包围盒尺寸线（150×120 类数字标注）可选实现
- [ ] 验收：case_003 干涉分析后点击 FB1 聚焦动画流畅；截图功能输出含时间戳文件

### P3 可疑元件交互表
- [ ] 表头吸顶已有，补：状态筛选 chips（全部/干涉/可疑/已修改）+ 计数徽章
- [ ] 高度输入微交互：改动后行尾出现「↺」单行重置按钮；Enter 行为不变
- [ ] 「应用并重新分析」按钮在无修改时禁用；修改后出现脉冲提示
- [ ] 位号列加元件类型 icon（R/C/U/J 色点）
- [ ] 验收：改 FB1 高度 1.5→0.5 应用后干涉体积实时变化（528→176mm³ 基准）

### P4 响应式与可访问性
- [ ] 断点：1440（双栏）/ 1024（参数栏两行）/ 768（单栏）/ 480（表格横滚）
- [ ] 焦点可见性：全部可交互元素 :focus-visible accent 环
- [ ] 对比度过 AA：正文 ≥4.5:1，次要文字允许 ≥3:1（18px+）
- [ ] 表格 th scope、按钮 aria-label、3D 容器 role="img" + aria-label
- [ ] 验收：Lighthouse a11y ≥ 90；键盘可完成完整生成流程

## 5. 验证协议（每阶段结束执行）

```bash
# 1. 测试门禁
.venv/Scripts/python.exe -m pytest tests -q          # 244 passed

# 2. 起服务
.venv/Scripts/python.exe web_server.py --port 8899

# 3. 浏览器实测（Chrome DevTools MCP 或 Antigravity browser tool）
#    - 打开 http://127.0.0.1:8899
#    - 用 fetch('/dl/case_003_test.zip') 灌入真实板（先打包 cases/case_003_stm32_4layer
#      除 .json 外全部文件为 zip 放 output/）
#    - 全流程：生成 → 3D → 干涉分析 → 改高度 → 应用 → 截图
#    - 每阶段存 before/after 全页截图到 output/ui-shots/
```

截图命名：`{phase}-{panel}-before.png` / `-after.png`，PR 描述里贴关键对比。

## 6. 完成定义（DoD）

- [ ] 244 tests 全绿 + ruff clean（前端虽无 lint，保持 PR 模板通过）
- [ ] 四阶段全部完成且各有 before/after 截图证据
- [ ] 无新增依赖（仍单文件 + three.js CDN）
- [ ] PR 描述含：改动清单、截图对比、测试结果
- [ ] 合并后 tag v0.2.5 触发 PyPI 自动发布（wheel 内 index.html 同步更新，
      `test_packaging_layout.py` 会验证）

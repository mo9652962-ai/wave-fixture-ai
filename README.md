<div align="center">

  <img src="docs/images/brand-mark.png" alt="Wave Fixture AI" width="110">

  # WAVE FIXTURE AI

  **Gerber 进 · 治具工程图出 · 13 项自动化 · 会听人话的 CAD 助手**

  **wave-fixture-ai 把波峰焊治具设计从手工描图变成一条命令：拖入 PCB Gerber 文件，自动生成沉板区、取手位、避位区、上锡区、压扣孔、定位销与治具外形，输出 DXF/STL/GLB；支持 3D 预览、元件干涉分析与自然语言参数调整（「避位区外扩1mm」等 23 参数确定性解析）。**

  <p>
    <a href="README.en.md">English</a>
    ·
    <a href="#-命令行方式">⌨️ 命令行</a>
    ·
    <a href="#-api-端点">🔌 API</a>
    ·
    <a href="LICENSE">MIT</a>
  </p>

  <p>
    <a href="https://github.com/mo9652962-ai/wave-fixture-ai/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mo9652962-ai/wave-fixture-ai/ci.yml?style=flat-square&label=CI" alt="CI"></a>
    <img src="https://img.shields.io/badge/features-13-2563EB?style=flat-square" alt="features">
    <img src="https://img.shields.io/badge/KiCad-10%20兼容-314CE0?style=flat-square&logo=kicad&logoColor=white" alt="KiCad 10">
    <img src="https://img.shields.io/badge/tests-22%20passed-success?style=flat-square" alt="tests">
    <a href="LICENSE"><img src="https://img.shields.io/github/license/mo9652962-ai/wave-fixture-ai?style=flat-square" alt="MIT"></a>
  </p>
</div>

<div align="center">
  <img src="docs/images/banner-1200x630.png" alt="WAVE FIXTURE AI · 波峰焊治具 AI 设计助手" width="100%">
</div>

<div align="center">
  <img src="docs/images/demo.gif" alt="wave-fixture-ai 能力清单：Gerber 识别 / 沉板区 / 避位区 / 3D 预览 / 干涉分析 / 自然语言调整" width="92%">
  <p><sub>▲ 13 项自动化 · DXF / STL / GLB 交付 · Web 界面或命令行</sub></p>
</div>

<div align="center">

### ⭐ 如果 wave-fixture-ai 对你有帮助，点个 Star 就是最大的支持

[![GitHub stars](https://img.shields.io/github/stars/mo9652962-ai/wave-fixture-ai?style=social)](https://github.com/mo9652962-ai/wave-fixture-ai/stargazers)
[![GitHub License](https://img.shields.io/github/license/mo9652962-ai/wave-fixture-ai?style=flat-square)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/mo9652962-ai/wave-fixture-ai/ci.yml?style=flat-square)](https://github.com/mo9652962-ai/wave-fixture-ai/actions)

[![Star History Chart](https://api.star-history.com/svg?repos=mo9652962-ai/wave-fixture-ai&type=Date)](https://star-history.com/#mo9652962-ai/wave-fixture-ai&Date)

</div>

## ✨ 13 项自动化

| 步骤 | 功能 | 状态 |
|:---|:---|:---|
| 1 | Gerber 上传识别（KiCad 10 兼容）| ✅ gerbonara + 正则回退 |
| 2 | 沉板区（外形外扩 0.2mm + R1.85 清角）| ✅ |
| 3 | 取手位（左右 20×40mm，重叠 1mm，R2 倒角）| ✅ |
| 4 | 压扣螺丝孔（Φ3.4，四角，距边 10mm）| ✅ |
| 5 | 定位销（DRL 钻孔内缩 0.1mm）| ✅ |
| 6 | 避位区（BOT+TOP 双面贴片包围 + 自动合并）| ✅ ESP32 板实测 |
| 7 | 上锡区（TOP 插件焊脚包围 + R2）| ✅ |
| 8 | 盖板弹力柱孔（丝印中心 Φ2.45）| ✅ |
| 9 | 治具外形（外扩整数化 + R5 + 轨道虚线 + 挡锡条）| ✅ |
| 10 | 输出治具 DXF（8 图层）| ✅ |
| 11 | **3D 预览**（STL/GLB 导出 + 浏览器旋转查看）| ✅ |
| 12 | **干涉分析**（元件 vs 治具：2D 覆盖 + 3D 布尔双层判定）| ✅ |
| 13 | **自然语言调整**（「避位区外扩1mm」等 23 参数）| ✅ |
| 14 | **DRC 生产安全门禁**（16 规则 · 四级严重度 · 每条带出处；未过 → 只出水印预览）| ✅ |
| 15 | **Golden Sample 回归验证**（IoU≥0.9 · Hausdorff≤0.5mm · 圆孔双向 best-match）| ✅ |
| 16 | **人工 Review 闭环**（缺数据/低置信度挂起 → 工程师确认 → SHA 绑定 + 审计日志）| ✅ |
| 17 | **定位销打分选点**（孔径窗口 / NPTH / 靠边权重 + 对角最大跨距）| ✅ |

## 🚦 DRC 生产安全门禁（工业级核心）

治具出图前跑 16 条设计规则检查，**存在 blocking / error 时导出的 DXF 自动打水印**（`PREVIEW`），
禁止直接送 CNC 生产——这是"设计稿"与"生产件"之间的最后防线。

| 级别 | 含义 | 例 |
|:---|:---|:---|
| `blocking` | 几何无效，不能生产 | 沉板区超出治具外框、外形自交 |
| `error` | 工艺冲突，需修正 | 定位销落入避位区、压扣孔压到板边元件、治具超传送带极限（508×762mm）|
| `warning` | 建议优化 | 定位销/压扣少于 2 个、避位区与上锡区重叠 |
| `info` | 提示 | — |

每条规则都带 **出处**（竞品逆向框架 + Macaos / AGICORP / APTPCB / PCBSync / MB Manufacturing 的 DFM 指南），
不是拍脑袋的阈值。QA 闭环配套：

- **Golden Sample 回归**：`golden.py` 支持导出几何基准并断言 IoU ≥0.9、Hausdorff ≤0.5mm、圆孔位置/半径误差；
- **人工 Review**：缺层/低置信度**不自动猜**，挂起 mandatory review；工程师确认后写入
  `layer_mapping.json`（绑定 geometry SHA256——几何一变确认自动过期），pending 状态阻断生产放行。

## 🚀 快速开始（Web 界面，推荐）

```bash
# 安装（或 pip install -e . 后用 wave-fixture-ai 命令）
pip install -e .

wave-fixture-ai --port 8000
```

浏览器打开 **http://localhost:8000**，使用流程：

```
1. 拖入 Gerber 文件（.gbs/.gts/.gbl/.gtl/.gm1/.drl 等，可多选）
   建议包含：B_Mask + F_Mask + Edge_Cuts + B_Cu + F_Cu + .drl
2. 点「🚀 生成治具」→ 预览 2D + 下载 DXF/PNG
3. 点「🧊 生成 3D」→ 3D 旋转预览 + 下载 STL/GLB
4. （可选）干涉分析：再拖入 KiCad 工程文件 .kicad_pcb → 报告避位不足的元件
5. （可选）自然语言调整：输入如「避位区外扩1mm」→ 重新生成
```

## ⌨️ 命令行方式

```bash
# Phase 1（沉板区/取手位/压扣孔/定位销）
python fixture_phase1.py <gerber_dir> -o output/fixture.dxf

# Phase 2 完整（+避位区/上锡区/盖板/治具外形）
python fixture_phase2.py <gerber_dir> -o output/fixture-full.dxf

# 干涉分析（需 .kicad_pcb）
python -c "
from interference import parse_kicad_pcb, analyze_interference
comps = parse_kicad_pcb('board.kicad_pcb')
reports = analyze_interference('output/fixture.stl', comps)
"
```

## 🔌 API 端点

| 端点 | 功能 |
|:---|:---|
| `POST /api/generate` | 上传 Gerber → DXF + PNG |
| `POST /api/generate3d` | 上传 Gerber → 3D 治具（STL + GLB）|
| `POST /api/adjust` | 自然语言调整 → 重新生成 |
| `POST /api/interference` | 干涉分析（需含 .kicad_pcb）|
| `GET /dl/{file}` | 下载生成的文件 |

## 🔬 干涉分析说明

- 需要 **.kicad_pcb** 文件（Gerber 只有焊盘几何，无元件高度信息）
- 判定规则：元件盒在避位区覆盖 <85% 或 与治具 3D 重叠 >5mm³ → 报干涉
- 插件（PinHeader/Connector/USB 等）自动跳过（贯穿治具由「上锡区」处理）

## 💬 自然语言调整示例

```
避位区外扩1mm           → avoid_pad_extra: 0.3 → 1.3
沉板区外扩0.5mm          → sink_expand_mm: 0.2 → 0.7
盖板孔径改3mm            → cap_hole_r: 2.45 → 3.0
左右外扩加大20mm         → ext_left_right: 20.0 → 40.0
```

> 规则解析（确定性，不用 LLM）——工程参数调整要精确可复现。

## 🧰 技术栈

- **gerbonara** — Gerber/Excellon 解析（层自动识别 + KiCad10 G85 正则回退）
- **shapely** — 几何运算（外扩/倒角/凸包包围/坐标变换）
- **ezdxf** — DXF 输出
- **trimesh + manifold** — 3D 拉伸/布尔
- **fastapi + uvicorn** — Web 服务
- **three.js** — 前端 3D 渲染（ES module）

## 🧪 真实板验证（Golden Cases）

两类**真实生产板**的端到端回归基准（`cases/`）：

| Case | 来源 | 规格 | 覆盖 |
|:---|:---|:---|:---|
| `case_001_espmh` | EasyEDA 双排插针板（竞品 production sample + 人工基准） | 25.654×48.26mm · 31 钻孔 · 仅外形层 | 格式兼容（GBR/GER/GKO 三份等价外形）、微缺口闭合、无焊盘层时不凭空生成上锡区 |
| `case_002_aircon_kicad` | KiCad 空调板（含 B_Cu/B_Mask/Edge_Cuts 全层） | 100×80mm · 169 钻孔 · 5 种孔径 | KiCad 命名规范、大规模钻孔、真实避位/上锡区（20/24 个）、销径告警 |

```bash
uv run pytest tests/test_golden_case001.py tests/test_golden_case002_kicad.py -v   # 18 项黄金断言
```

| 断言类别 | 内容 |
|:---|:---|
| 几何精确性 | 板尺寸/面积/钻孔数与人工基准**精确匹配**（偏差 0.000） |
| 设计规则 | 治具外形 =(板+2×外扩) 向上取整 5mm；压扣孔必在沉板区**外**；销径 ≥1.5mm |
| 工程约束 | 在传送带极限内；治具完整包含沉板区 |
| 门禁语义 | 无 blocking/error 才放行；无焊盘层不凭空生成上锡区 |

> 端到端跑通的过程修掉了 **11 个真实缺陷**（层名兼容 / overrides 语义 / 同层多文件 /
> 微缺口闭合 / 压扣孔位置 / 定位销未筛选 / 销径规则 / matplotlib 依赖 / 前端门禁未渲染 /
> **干涉判定 OR→AND 误报** / **板框 gr_line 解析**）——**单测 52 全绿时仍未被发现，
> 只有真实数据、真实浏览器与黄金对比能暴露**。方法论已沉淀为 `real-world-validation` 技能。
>
> 3D 干涉分析在真实板（36 元件）上的输出：报出的大体积元件（继电器 1886–2260mm³、
> 数码管 3163mm³）避位覆盖仅 0.04–0.60，是**真实设计缺陷**（大件落在避位区外会被治具压到）。

## License

MIT

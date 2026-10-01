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

## License

MIT

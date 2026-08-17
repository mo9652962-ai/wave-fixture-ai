# 波峰焊治具 AI 设计助手 (Wave Fixture AI)

输入 PCB Gerber 文件 → 自动生成波峰焊治具二维工程图（DXF），替代传统重复性 CAD 手工画图。

## 功能（PDF 10 步规则，Phase 1+2 已实现）

| 步骤 | 功能 | 状态 |
|:---|:---|:---|
| 1 | Gerber 上传识别 | ✅ gerbonara 解析 |
| 2 | 沉板区（外形外扩 0.2mm + R1.85 清角）| ✅ |
| 3 | 取手位（左右 20×40mm，重叠 1mm，R2 倒角）| ✅ |
| 4 | 压扣螺丝孔（Φ3.4，四角，距边 10mm）| ✅ |
| 5 | 定位销（DRL 钻孔内缩 0.1mm）| ✅ |
| 6 | 避位区（BOT 贴片丝印包围 + R1.5）| ✅ 算法就绪（待贴片板实测）|
| 7 | 上锡区（TOP 插件焊脚包围 + R2）| ✅ |
| 8 | 盖板弹力柱孔（丝印中心 Φ2.45）| ✅ |
| 9 | 治具外形（外扩整数化 + R5 + 轨道虚线 + 挡锡条）| ✅ |
| 10 | 输出治具 DXF | ✅ 8 图层 |

## 技术栈

- **gerbonara** — Gerber/Excellon 解析（层自动识别）
- **shapely** — 几何运算（外扩/倒角/凸包包围）
- **ezdxf** — DXF 输出

## 快速开始

```bash
# Phase 1（沉板区/取手位/压扣孔/定位销）
python fixture_phase1.py <gerber_dir> -o output/fixture.dxf

# Phase 2 完整（+避位区/上锡区/盖板/治具外形）
python fixture_phase2.py <gerber_dir> -o output/fixture-full.dxf
```

## 验证

- 实测板：空调板 demo（80×80mm，68 钻孔）
- 视觉验证：AI 读图确认治具布局正确（沉板区/取手位/压扣孔/定位销/上锡区/治具外形）

## 后续计划

- [ ] 前端界面（拖 Gerber → 预览 → 下载 DXF）
- [ ] 贴片板实测步骤 6 避位区
- [ ] 3D 预览 + 干涉分析（PDF 后期功能）
- [ ] 自然语言对话调整（PDF 后期功能）

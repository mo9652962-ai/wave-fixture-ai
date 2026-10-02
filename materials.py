"""治具材料预设库——工业级材料选型、重量与成本估算。

材料数据来源（每项带出处，可参数化覆盖）：
- Durostone（Röchling 合成石）：GFRP 矿物填充聚酯板，波峰焊治具行业事实标准；
  常规板材厚度 2/3/4/5/6/8/10/12/15mm（Noves-China 供货规格），
  静电耗散（ESD）、耐温 280°C 级（Röchling Durostone PCB Solder Pallets 产品页）。
- Ricocel：同类合成石竞品（S&M / Chuxin SMT 指南推荐），参数近似 Durostone。
- 高 Tg FR-4：低成本替代，玻璃化温度 ~170-180°C（PCBSync 材料对比）。
- 铝合金 6061：重载/高导热治具，耐温高但波峰焊应用较少（需防挂锡）。

切削参数（cnc_gcode 使用）：合成石粉尘磨蚀性强 → 低进给、高转速、分层少切；
数值为安全默认值，供 Φ3.7 平底铣刀试切基准（Bee-Plastic Durostone CNC 加工服务页：
±0.03mm 精度），实际机台按刀具/机床刚性微调。
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

log = logging.getLogger("fixture-materials")


@dataclass
class MaterialPreset:
    """单一材料预设：物理参数 + 成本 + 推荐切削参数。"""

    key: str
    name_cn: str
    name_en: str
    density_g_cm3: float          # 密度 g/cm³
    max_service_temp_c: float     # 长期使用温度上限 °C
    thickness_options_mm: tuple   # 常规板材厚度档位
    price_per_kg: float           # 参考材料价（元/kg，可按采购价覆盖）
    esd_safe: bool                # 是否静电耗散
    color: str                    # 常见颜色
    source: str                   # 数据出处
    # 推荐切削参数（Φ3.7 平底铣刀基准）
    feed_xy_mm_min: float = 600.0     # XY 进给
    feed_plunge_mm_min: float = 150.0 # Z 向下刀
    spindle_rpm: float = 18000.0      # 主轴转速
    stepdown_mm: float = 1.5          # 每层切深
    stepover_pct: float = 45.0        # 行距占刀具直径百分比
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["thickness_options_mm"] = list(self.thickness_options_mm)
        return d


MATERIALS: dict[str, MaterialPreset] = {
    "durostone": MaterialPreset(
        key="durostone",
        name_cn="Durostone 合成石",
        name_en="Durostone (Rochling C253/C151)",
        density_g_cm3=1.90,
        max_service_temp_c=280.0,
        thickness_options_mm=(2, 3, 4, 5, 6, 8, 10, 12, 15),
        price_per_kg=420.0,
        esd_safe=True,
        color="黑色 / 蓝色",
        source="Rochling Durostone PCB Solder Pallets 产品页 + Noves-China 板厚规格",
        feed_xy_mm_min=600.0,
        feed_plunge_mm_min=150.0,
        spindle_rpm=18000.0,
        stepdown_mm=1.5,
        stepover_pct=45.0,
        note="波峰焊治具行业事实标准；静电耗散、低热传导、波峰挂锡少。",
    ),
    "ricocel": MaterialPreset(
        key="ricocel",
        name_cn="Ricocel 合成石",
        name_en="Ricocel synthetic stone",
        density_g_cm3=1.85,
        max_service_temp_c=280.0,
        thickness_options_mm=(3, 5, 8, 10, 12),
        price_per_kg=380.0,
        esd_safe=True,
        color="黑色",
        source="S&M / Chuxin SMT 波峰焊治具设计指南（Durostone/Ricocel 推荐）",
        feed_xy_mm_min=600.0,
        feed_plunge_mm_min=150.0,
        spindle_rpm=18000.0,
        stepdown_mm=1.5,
        stepover_pct=45.0,
        note="Durostone 同类竞品，性价比路线。",
    ),
    "fr4_high_tg": MaterialPreset(
        key="fr4_high_tg",
        name_cn="高 Tg FR-4 玻纤板",
        name_en="High-Tg FR-4",
        density_g_cm3=2.10,
        max_service_temp_c=180.0,
        thickness_options_mm=(2, 3, 5, 8, 10, 12),
        price_per_kg=90.0,
        esd_safe=False,
        color="黄绿色",
        source="PCBSync《Wave Solder Pallet Design》材料对比",
        feed_xy_mm_min=800.0,
        feed_plunge_mm_min=200.0,
        spindle_rpm=20000.0,
        stepdown_mm=2.0,
        stepover_pct=50.0,
        note="低成本打样/小批量；高温长期使用易分层，双波工艺慎选。",
    ),
    "aluminum": MaterialPreset(
        key="aluminum",
        name_cn="铝合金 6061",
        name_en="Aluminum 6061-T6",
        density_g_cm3=2.70,
        max_service_temp_c=400.0,
        thickness_options_mm=(6, 8, 10, 12, 15, 20),
        price_per_kg=60.0,
        esd_safe=False,
        color="银白（阳极黑可选）",
        source="PCBSync 材料对比（titanium/aluminum 重载治具路线）",
        feed_xy_mm_min=1000.0,
        feed_plunge_mm_min=250.0,
        spindle_rpm=12000.0,
        stepdown_mm=1.0,
        stepover_pct=40.0,
        note="导热高、寿命长；波峰焊需防挂锡涂层，重量大（传送带载荷注意）。",
    ),
}

DEFAULT_MATERIAL = "durostone"


def get_material(key: str | None) -> MaterialPreset:
    """按 key 取材料预设；未知/缺省回退 Durostone（不抛异常，保住生产流程）。"""
    if not key:
        return MATERIALS[DEFAULT_MATERIAL]
    m = MATERIALS.get(key.lower().strip())
    if m is None:
        log.warning(f"  未知材料 '{key}'，回退 {DEFAULT_MATERIAL}")
        return MATERIALS[DEFAULT_MATERIAL]
    return m


def nearest_sheet_thickness(thickness_mm: float, material: MaterialPreset) -> float:
    """把任意设计厚度吸附到该材料的常规板材档位（向上取档，保证毛坯够厚）。"""
    opts = sorted(material.thickness_options_mm)
    for t in opts:
        if t >= thickness_mm - 1e-6:
            return float(t)
    return float(opts[-1])


def estimate_weight(area_mm2: float, thickness_mm: float, material: MaterialPreset,
                    openings_area_mm2: float = 0.0) -> float:
    """估算治具毛坯净重 kg：体积 = (面积 - 开孔面积) × 厚度。"""
    net_area = max(area_mm2 - openings_area_mm2, 0.0)
    vol_cm3 = net_area * thickness_mm / 1000.0
    return round(vol_cm3 * material.density_g_cm3 / 1000.0, 3)


def estimate_cost(weight_kg: float, material: MaterialPreset,
                  machining_minutes: float = 0.0, labor_per_hour: float = 120.0) -> dict:
    """估算治具成本（材料 + 机加工时），返回分项 dict（报价参考，非定价）。"""
    material_cost = weight_kg * material.price_per_kg
    machining_cost = machining_minutes / 60.0 * labor_per_hour
    return {
        "material_cost": round(material_cost, 1),
        "machining_cost": round(machining_cost, 1),
        "total": round(material_cost + machining_cost, 1),
        "currency": "CNY",
        "note": "按参考价与工时估算，仅作报价参考；实际以采购价与机台费率校准。",
    }


def blank_area(bounds_wh: tuple[float, float], margin_mm: float = 10.0) -> float:
    """毛坯面积（含装夹边距）。"""
    return (bounds_wh[0] + 2 * margin_mm) * (bounds_wh[1] + 2 * margin_mm)


if __name__ == "__main__":
    for k, m in MATERIALS.items():
        print(f"{k:12s} {m.name_cn:14s} ρ={m.density_g_cm3} T={m.max_service_temp_c}°C "
              f"板厚{m.thickness_options_mm}")
    demo_w = estimate_weight(blank_area((120.0, 85.0)), 10.0, MATERIALS["durostone"])
    print(f"120×85 治具 10mm Durostone 毛坯重 ≈ {demo_w} kg")

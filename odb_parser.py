"""ODB++ (Open Database++) 复合工程数据解析器。

工业定位（对标商业软件 Macaos Solder Pallet Designer / CAM350）：
工业级 CAM 不仅接受离散的 Gerber/DRL，更把 ODB++ 视为首选输入格式（Valor / Siemens 工业标准）。
ODB++ 将层叠矩阵 (matrix)、板框多边形 (profile)、钻孔 (drill) 及包含元件位号/尺寸/高度的
EDA 数据 (eda/data) 打包为单一结构化归档（.tgz / .tar.gz / .zip 或解压目录），消除了 Gerber
文件名猜测、层名混乱及与 KiCad .kicad_pcb 分离的缺陷。

本模块提供轻量、自包含、纯 Python 的 ODB++ 读取引擎：
  1. 解包与目录结构遍历（支持 .tgz / .tar.gz / .zip 及解压目录）
  2. 矩阵层定义识别 (`matrix/matrix`)
  3. 板框轮廓解析 (`steps/<step>/profile` 或 `outline/features` 提取封闭 Polygon)
  4. 钻孔图元提取 (`layers/<drill>/features` 提取坐标与孔径)
  5. EDA 贴片与插装元件元数据解析 (`eda/data` 提取位号、坐标、旋转角、封装与 3D 高度)
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union

log = logging.getLogger("fixture-odb")


@dataclass
class ODBComponent:
    ref: str
    part_name: str
    pkg_name: str
    x: float
    y: float
    rotation: float = 0.0
    side: str = "FSide"  # "FSide" | "BSide"
    w: float = 2.0
    h: float = 2.0
    height: float = 1.5
    source: str = "odb"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "name": self.pkg_name or self.part_name,
            "part_name": self.part_name,
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "w": round(self.w, 2),
            "h": round(self.h, 2),
            "height": round(self.height, 2),
            "side": self.side,
            "fp_key": self.pkg_name.lower(),
            "source": self.source,
            "is_suspicious": self.height >= 10.0 or self.height <= 0.2,
            "suspicious_reason": (
                f"高大立件 ({self.height}mm)"
                if self.height >= 10.0
                else f"超薄器件 ({self.height}mm)"
                if self.height <= 0.2
                else ""
            ),
        }


@dataclass
class ODBData:
    step_name: str = "pcb"
    board_poly: Polygon | None = None
    drills: list[tuple[float, float, float]] = field(default_factory=list)  # (x, y, dia_mm)
    components: list[ODBComponent] = field(default_factory=list)
    matrix_layers: dict[str, str] = field(default_factory=dict)  # layer_name -> layer_type
    unit: str = "MM"  # "MM" | "INCH"

    @property
    def has_outline(self) -> bool:
        return self.board_poly is not None and not self.board_poly.is_empty


def is_odb_archive(path: str | Path) -> bool:
    """检测输入文件或目录是否为 ODB++ 归档/工程。"""
    p = Path(path)
    if p.is_dir():
        return (p / "matrix" / "matrix").is_file() or any((p / "steps").glob("*"))
    name = p.name.lower()
    return name.endswith((".tgz", ".tar.gz", ".zip", ".odb", ".xml.tgz"))


def extract_odb_archive(archive_path: str | Path, target_dir: str | Path) -> Path:
    """解压 ODB++ 归档到指定临时目录，返回包含 matrix/steps 的根路径。"""
    src = Path(archive_path)
    dst = Path(target_dir)
    dst.mkdir(parents=True, exist_ok=True)

    if src.is_dir():
        return src

    if src.name.lower().endswith((".tgz", ".tar.gz")):
        with tarfile.open(src, "r:*") as tar:
            # 路径安全防护（防 Zip/Tar Slip）
            for m in tar.getmembers():
                t = (dst / m.name).resolve()
                if t.is_relative_to(dst.resolve()):
                    tar.extract(m, dst)
    elif src.name.lower().endswith(".zip"):
        with zipfile.ZipFile(src, "r") as z:
            for member in z.infolist():
                t = (dst / member.filename).resolve()
                if t.is_relative_to(dst.resolve()):
                    z.extract(member, dst)

    # 寻找包含 matrix/matrix 或 steps 的实际根目录
    for root, dirs, files in os.walk(dst):
        r_path = Path(root)
        if (r_path / "matrix" / "matrix").is_file() or (r_path / "steps").is_dir():
            return r_path

    return dst


def parse_odb_matrix(odb_root: Path) -> dict[str, str]:
    """解析 matrix/matrix 提取层名与类型映射。"""
    mat_file = odb_root / "matrix" / "matrix"
    layers = {}
    if not mat_file.is_file():
        return layers

    txt = mat_file.read_text(encoding="utf-8", errors="replace")
    layer_blocks = re.findall(r"LAYER\s*\{([^}]+)\}", txt)
    for blk in layer_blocks:
        name_m = re.search(r"NAME\s*=\s*(\S+)", blk)
        type_m = re.search(r"TYPE\s*=\s*(\S+)", blk)
        if name_m and type_m:
            layers[name_m.group(1).lower()] = type_m.group(1).lower()

    return layers


def _parse_lines_to_polygon(
    lines: list[tuple[float, float, float, float]], tol: float = 0.5
) -> Polygon | None:
    """将 ODB++ 线段闭合重构为有效 Polygon（带端点容差链式缝合）。"""
    if not lines:
        return None
    line_geoms = [
        LineString([(x1, y1), (x2, y2)]) for x1, y1, x2, y2 in lines if (x1, y1) != (x2, y2)
    ]
    if not line_geoms:
        return None

    # 尝试直接 polygonize
    polys = list(polygonize(line_geoms))
    if polys:
        return max(polys, key=lambda p: p.area)

    # 容差首尾缝合
    snapped = []
    for g in line_geoms:
        pts = list(g.coords)
        snapped.append(
            LineString(
                [
                    (round(pts[0][0] / tol) * tol, round(pts[0][1] / tol) * tol),
                    (round(pts[1][0] / tol) * tol, round(pts[1][1] / tol) * tol),
                ]
            )
        )
    polys2 = list(polygonize(snapped))
    if polys2:
        return max(polys2, key=lambda p: p.area)

    # 保底：外轮廓最小外接凸包缓冲
    union = unary_union(line_geoms)
    hull = union.convex_hull
    return hull if isinstance(hull, Polygon) and hull.area > 0 else None


def parse_odb_profile(step_dir: Path, scale: float = 1.0) -> Polygon | None:
    """从 step 目录解析 profile 文件或 outline features 提取板框多边形。"""
    lines: list[tuple[float, float, float, float]] = []

    # 1. 尝试 steps/<step>/profile 文件
    prof_file = step_dir / "profile"
    if prof_file.is_file():
        txt = prof_file.read_text(encoding="utf-8", errors="replace")
        # 匹配 ODB++ 线段记录: OB x y ... L x y / L x1 y1 x2 y2
        for m in re.finditer(r"L\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", txt):
            x1, y1, x2, y2 = (float(v) * scale for v in m.groups())
            lines.append((x1, y1, x2, y2))
        if lines:
            poly = _parse_lines_to_polygon(lines)
            if poly:
                return poly

    # 2. 尝试 layers/profile/features 或 layers/outline/features
    for cand in ("profile", "outline", "board", "route"):
        feat = step_dir / "layers" / cand / "features"
        if feat.is_file():
            txt = feat.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"L\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", txt):
                x1, y1, x2, y2 = (float(v) * scale for v in m.groups())
                lines.append((x1, y1, x2, y2))
            poly = _parse_lines_to_polygon(lines)
            if poly:
                return poly

    return None


def parse_odb_drills(
    step_dir: Path, matrix: dict[str, str], scale: float = 1.0
) -> list[tuple[float, float, float]]:
    """从 drill 钻孔层特征文件中提取钻孔点位及直径。"""
    drills: list[tuple[float, float, float]] = []
    layers_dir = step_dir / "layers"
    if not layers_dir.is_dir():
        return drills

    # 找出所有 drill 类型或带 drill/drl 名字的层
    drill_layers = [
        d.name
        for d in layers_dir.iterdir()
        if d.is_dir()
        and (
            matrix.get(d.name.lower()) == "drill"
            or any(k in d.name.lower() for k in ("drill", "drl", "thru_hole", "npth", "pth"))
        )
    ]

    for lyr in drill_layers:
        feat = layers_dir / lyr / "features"
        if not feat.is_file():
            continue
        txt = feat.read_text(encoding="utf-8", errors="replace")

        # 读取符号工具字典: $tool_num round <dia>
        syms: dict[str, float] = {}
        for sm in re.finditer(r"\$([0-9]+)\s+r(?:ound)?\s+([-\d.]+)", txt, re.IGNORECASE):
            syms[sm.group(1)] = float(sm.group(2)) * scale

        # 匹配钻孔/焊盘特征: P x y sym_num ...
        for pm in re.finditer(r"P\s+([-\d.]+)\s+([-\d.]+)\s+([0-9]+)", txt):
            x = float(pm.group(1)) * scale
            y = float(pm.group(2)) * scale
            dia = syms.get(pm.group(3), 1.0)
            drills.append((round(x, 3), round(y, 3), round(dia, 3)))

    return drills


def parse_odb_eda_components(step_dir: Path, scale: float = 1.0) -> list[ODBComponent]:
    """从 steps/<step>/eda/data 解析真实元器件贴装位置、封装及高度。"""
    eda_file = step_dir / "eda" / "data"
    if not eda_file.is_file():
        return []

    txt = eda_file.read_text(encoding="utf-8", errors="replace")
    components: list[ODBComponent] = []

    # 封装库字典: PKG <pkg_name> ... PITCH / XMIN / YMIN / XMAX / YMAX
    pkg_dims: dict[str, tuple[float, float, float]] = {}  # pkg -> (w, h, height)
    pkg_blocks = re.findall(r"PKG\s+([^\n]+)\n(.*?)(?=\nPKG|\nCMP|\Z)", txt, re.DOTALL)
    for name, blk in pkg_blocks:
        name = name.strip()
        # 匹配外包围轮廓或 Pitch
        xmin = re.search(r"XMIN=([-\d.]+)", blk)
        xmax = re.search(r"XMAX=([-\d.]+)", blk)
        ymin = re.search(r"YMIN=([-\d.]+)", blk)
        ymax = re.search(r"YMAX=([-\d.]+)", blk)
        h_m = re.search(r"H(?:EIGHT)?=([-\d.]+)", blk)

        w = (float(xmax.group(1)) - float(xmin.group(1))) * scale if xmin and xmax else 2.5
        h = (float(ymax.group(1)) - float(ymin.group(1))) * scale if ymin and ymax else 1.5
        h_val = float(h_m.group(1)) * scale if h_m else 1.5
        pkg_dims[name] = (max(w, 0.5), max(h, 0.5), max(h_val, 0.5))

    # 解析 CMP 记录: CMP <index> <pkg_name> <part_name> <x> <y> <rot> <mirror>
    cmp_re = re.compile(
        r"CMP\s+(\d+)\s+(\S+)\s+(\S+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([TB01MF])",
        re.IGNORECASE,
    )
    for m in cmp_re.finditer(txt):
        _idx, pkg, part, xs, ys, rots, mirr = m.groups()
        x = float(xs) * scale
        y = float(ys) * scale
        rot = float(rots)
        # mirror: B, T, M, F (B/M 代表底面)
        is_bottom = mirr.upper() in ("B", "M", "1")
        side = "BSide" if is_bottom else "FSide"

        ref = part
        w, h, height = pkg_dims.get(pkg, (2.0, 1.2, 1.2))

        # 尝试从随后的 PRP 属性块捕获精确 Reference 和 Height
        components.append(
            ODBComponent(
                ref=ref,
                part_name=part,
                pkg_name=pkg,
                x=x,
                y=y,
                rotation=rot,
                side=side,
                w=w,
                h=h,
                height=height,
            )
        )

    return components


def parse_odb_package(input_path: str | Path) -> ODBData:
    """全流程解析 ODB++ 工程或压缩归档。

    返回标准 ODBData 数据结构（包含板框 board_poly、钻孔 drills、元件 components）。
    """
    inp = Path(input_path)
    tmp_dir = None
    try:
        if inp.is_file():
            tmp_dir = Path(tempfile.mkdtemp(prefix="odb-unpack-"))
            root = extract_odb_archive(inp, tmp_dir)
        else:
            root = inp

        matrix = parse_odb_matrix(root)
        steps_dir = root / "steps"
        step_dir = None
        step_name = "pcb"

        if steps_dir.is_dir():
            candidates = list(steps_dir.iterdir())
            if candidates:
                # 优先选择名为 pcb / board / main 的 step
                chosen = next(
                    (c for c in candidates if c.name.lower() in ("pcb", "board", "main")),
                    candidates[0],
                )
                step_dir = chosen
                step_name = chosen.name

        if step_dir is None:
            return ODBData(step_name="unknown")

        # 单位检测 (检查 misc/info 或 fonts/etc, 缺省 MM)
        scale = 1.0
        info_file = root / "misc" / "info"
        if info_file.is_file():
            info_txt = info_file.read_text(encoding="utf-8", errors="replace").upper()
            if "UNITS=INCH" in info_txt or "UNITS=IN" in info_txt:
                scale = 25.4  # 英寸换算为毫米

        poly = parse_odb_profile(step_dir, scale=scale)
        drills = parse_odb_drills(step_dir, matrix, scale=scale)
        components = parse_odb_eda_components(step_dir, scale=scale)

        log.info(
            f"✅ ODB++ 解析完成: step={step_name}, 板框={poly is not None}, "
            f"钻孔={len(drills)} 个, 元件={len(components)} 个"
        )

        return ODBData(
            step_name=step_name,
            board_poly=poly,
            drills=drills,
            components=components,
            matrix_layers=matrix,
            unit="INCH" if scale == 25.4 else "MM",
        )
    finally:
        if tmp_dir and tmp_dir.is_dir():
            shutil.rmtree(tmp_dir, ignore_errors=True)

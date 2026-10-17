"""无头自动化工厂制造交付包与密码学校验流水线 (Headless Factory CAM & Checksums Pipeline).

工业背景与自动化生产基准：
- 适配真实 macOS 个人开发者终端与外部 Linux 生产服务器 (Headless Docker/CI/CD)：
  在现代智能代工厂 (EMS) 与远程 Linux 制造服务器中，CAM 处理完全脱离 GUI 与浏览器交互。
  流水线必须支持全自动批处理执行，并输出符合 IATF 16949 / ISO 9001 质量追溯标准的
  「单包全要素交付件 (Single Factory Package)」：
  1. `fixture_cam.dxf`: 完整全图层 CAM 制造图纸；
  2. `cnc_setup_sheet.md`: G54 工件坐标系与刀具梯装夹单；
  3. `cnc_toolpath.nc`: RS-274 数控切削代码；
  4. `quotation_bom.md`: 大板排料利用率与阶梯商务报价单；
  5. `maintenance_card.md`: 车间张贴版预防性保养点检卡；
  6. `outgoing_qc_release.md`: ISO 2859-1 Level II AQL 抽样放行单；
  7. `MANIFEST.sha256`: 交付包内全文件的 SHA-256 密码学防篡改校验清单。
"""

from __future__ import annotations

import hashlib
import io
import logging
import zipfile
from dataclasses import asdict, dataclass, field
from typing import Any

log = logging.getLogger("fixture-factory-pipeline")


@dataclass
class FactoryDeliverable:
    filename: str
    size_bytes: int
    sha256: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FactoryReleasePackage:
    job_id: str
    material_key: str
    drc_passed: bool
    drc_rules_checked: int
    total_deliverables: int
    package_zip_bytes: int
    manifest_sha256_text: str
    deliverables: list[FactoryDeliverable] = field(default_factory=list)
    iso_standard: str = "ISO 9001 & IATF 16949 Manufacturing Release Traceability"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["deliverables"] = [deliv.to_dict() for deliv in self.deliverables]
        return d


def _compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_factory_release_package(
    job_id: str,
    dxf_bytes: bytes,
    setup_sheet_md: str,
    quotation_md: str,
    maintenance_md: str,
    qc_release_md: str,
    gcode_nc: str = "",
    material_key: str = "durostone",
    drc_passed: bool = True,
    drc_rules_checked: int = 63,
) -> tuple[FactoryReleasePackage, bytes]:
    """打包全要素工程交付物，生成密码学 SHA256 校验清单，并输出工厂 Release ZIP。"""
    zip_buf = io.BytesIO()
    files_to_pack: dict[str, tuple[bytes, str]] = {
        "fixture_cam.dxf": (dxf_bytes, "AutoCAD R2010 完整 CAM 图层图纸"),
        "cnc_setup_sheet.md": (setup_sheet_md.encode("utf-8"), "G54 工件坐标系与刀具准备单"),
        "quotation_bom.md": (quotation_md.encode("utf-8"), "大板排料利用率与商务报价单"),
        "maintenance_card.md": (maintenance_md.encode("utf-8"), "治具预防性清洁与寿命保养卡"),
        "outgoing_qc_release.md": (qc_release_md.encode("utf-8"), "ISO 2859-1 Level II AQL 抽样放行单"),
    }
    if gcode_nc:
        files_to_pack["cnc_toolpath.nc"] = (gcode_nc.encode("utf-8"), "RS-274 工业数控切削代码")

    deliverables: list[FactoryDeliverable] = []
    manifest_lines = [f"# FACTORY RELEASE CHECKSUMS (JOB: {job_id})", "# SHA-256 HASH                     FILENAME"]

    # 1. 计算各文件 SHA-256 并生成校验账本
    for fname, (content_bytes, desc) in sorted(files_to_pack.items()):
        sha = _compute_sha256(content_bytes)
        manifest_lines.append(f"{sha}  {fname}")
        deliverables.append(
            FactoryDeliverable(
                filename=fname,
                size_bytes=len(content_bytes),
                sha256=sha,
                description=desc,
            )
        )

    manifest_text = "\n".join(manifest_lines) + "\n"
    files_to_pack["MANIFEST.sha256"] = (manifest_text.encode("utf-8"), "密码学防篡改校验清单")

    # 2. 压缩打包
    with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname, (content_bytes, _) in files_to_pack.items():
            zf.writestr(fname, content_bytes)

    zip_bytes = zip_buf.getvalue()

    pkg = FactoryReleasePackage(
        job_id=job_id,
        material_key=material_key,
        drc_passed=drc_passed,
        drc_rules_checked=drc_rules_checked,
        total_deliverables=len(files_to_pack),
        package_zip_bytes=len(zip_bytes),
        manifest_sha256_text=manifest_text,
        deliverables=deliverables,
    )

    return pkg, zip_bytes

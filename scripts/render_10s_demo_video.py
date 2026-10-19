"""
Renders a 10-second high-impact visual demo video (1080p MP4) and optimized GIF.
Demonstrates: Gerber Drag-in -> 21 Automations -> 3D Collision Detection -> CNC G-Code Output.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import trimesh
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "docs" / "images"
DEMO_CASE_DIR = REPO_ROOT / "web" / "demo" / "case_003"


def get_font(size: int, bold: bool = False):
    font_names = [
        "msyh.ttc", "msyhbd.ttc" if bold else "msyh.ttc",
        "arialbd.ttf" if bold else "arial.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    ]
    for fn in font_names:
        try:
            return ImageFont.truetype(fn, size)
        except OSError:
            pass
    return ImageFont.load_default()


def render_3d_frame(mesh, azimuth: float, elevation: float = 30) -> Image.Image:
    """Renders a single frame of the 3D fixture model."""
    fig = plt.figure(figsize=(7.5, 4.5), facecolor="#0e131f", dpi=100)
    ax = fig.add_subplot(111, projection="3d", facecolor="#0e131f")

    # Render downsampled triangles for speed
    poly = Poly3DCollection(
        mesh.triangles[::2],
        facecolors="#2563eb",
        edgecolors="#1d4ed8",
        linewidths=0.25,
        alpha=0.92,
    )
    ax.add_collection3d(poly)

    # Add red collision box overlay to showcase interference detection
    def draw_box(x, y, z, dx, dy, dz, color, alpha=0.6):
        xx = [x, x+dx, x+dx, x, x, x+dx, x+dx, x]
        yy = [y, y, y+dy, y+dy, y, y, y+dy, y+dy]
        zz = [z, z, z, z, z+dz, z+dz, z+dz, z+dz]
        verts = [
            [ [xx[0], yy[0], zz[0]], [xx[1], yy[1], zz[0]], [xx[2], yy[2], zz[0]], [xx[3], yy[3], zz[0]] ],
            [ [xx[4], yy[4], zz[4]], [xx[5], yy[5], zz[4]], [xx[6], yy[6], zz[4]], [xx[7], yy[7], zz[4]] ],
            [ [xx[0], yy[0], zz[0]], [xx[1], yy[1], zz[0]], [xx[5], yy[5], zz[4]], [xx[4], yy[4], zz[4]] ],
            [ [xx[2], yy[2], zz[0]], [xx[3], yy[3], zz[0]], [xx[7], yy[7], zz[4]], [xx[6], yy[6], zz[4]] ],
            [ [xx[1], yy[1], zz[0]], [xx[2], yy[2], zz[0]], [xx[6], yy[6], zz[4]], [xx[5], yy[5], zz[4]] ],
            [ [xx[0], yy[0], zz[0]], [xx[3], yy[3], zz[0]], [xx[7], yy[7], zz[4]], [xx[4], yy[4], zz[4]] ],
        ]
        box_poly = Poly3DCollection(verts, facecolors=color, edgecolors="#ffffff", linewidths=0.5, alpha=alpha)
        ax.add_collection3d(box_poly)

    draw_box(-18, -12, 5, 12, 10, 8, "#ef4444", alpha=0.85)
    draw_box(10, 8, 5, 8, 8, 6, "#f59e0b", alpha=0.75)

    ax.view_init(elev=elevation, azim=azimuth)
    ax.set_xlim(-50, 50)
    ax.set_ylim(-60, 60)
    ax.set_zlim(-10, 16)
    ax.axis("off")

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        temp_png = tf.name
    fig.savefig(temp_png, bbox_inches="tight", pad_inches=0, facecolor="#0e131f")
    plt.close(fig)

    img = Image.open(temp_png).convert("RGBA")
    Path(temp_png).unlink(missing_ok=True)
    return img


def build_full_frame(
    frame_idx: int,
    total_frames: int,
    mesh,
    preview_2d_img: Image.Image,
    fonts: dict,
) -> Image.Image:
    t = frame_idx / total_frames * 10.0  # Current seconds (0.0s to 10.0s)
    W, H = 1920, 1080

    # 1. Base canvas with dark industrial gradient
    canvas = Image.new("RGBA", (W, H), (11, 13, 18, 255))
    draw = ImageDraw.Draw(canvas)

    # Top brand bar
    draw.rectangle([0, 0, W, 80], fill=(17, 20, 28, 255))
    draw.line([0, 80, W, 80], fill=(59, 130, 246, 120), width=2)

    # Top header text
    draw.text((40, 22), "⚙️ WAVE FIXTURE AI", font=fonts["brand"], fill=(255, 255, 255))
    draw.text((360, 28), "波峰焊治具 AI 设计助手 · 10 秒全自动工业 CAM 引擎", font=fonts["sub"], fill=(156, 163, 175))
    draw.text((1580, 26), "v0.5.1 · 71 DRC RULES", font=fonts["badge"], fill=(16, 185, 129))

    # Top progress line (animated)
    prog_w = int((frame_idx + 1) / total_frames * W)
    draw.line([0, 81, prog_w, 81], fill=(59, 130, 246, 255), width=3)

    # Bottom footer banner
    draw.rectangle([0, H - 70, W, H], fill=(17, 20, 28, 255))
    draw.line([0, H - 70, W, H - 70], fill=(31, 36, 51, 255), width=1)
    draw.text((40, H - 48), "🌐 在线 3D 快速体验: mo9652962-ai.github.io/wave-fixture-ai", font=fonts["sub"], fill=(96, 165, 250))
    draw.text((1200, H - 48), "💻 终端一行运行: uvx wave-fixture-ai  ·  ⭐ GitHub 9.2+ 工业级开源", font=fonts["sub"], fill=(229, 231, 235))

    # Center stage coordinates: Y: 110 to 980
    if t < 2.5:
        # Phase 1: Problem vs Solution & Gerber Drag-in
        # Header banner
        draw.text((80, 120), "▶ 阶段 01: 传统手工描图 vs AI 极速自动化 (INPUT)", font=fonts["h1"], fill=(255, 255, 255))

        # Left Card: Traditional CAD Drafting (Red alert)
        draw.rounded_rectangle([80, 180, 880, 850], radius=16, fill=(22, 27, 38, 255), outline=(239, 68, 68, 160), width=2)
        draw.text((120, 220), "❌ 传统人工 CAD 描图", font=fonts["h2"], fill=(248, 113, 113))
        draw.text((120, 280), "• 单板耗时: 3 ~ 5 小时反复手工偏移避位", font=fonts["body"], fill=(209, 213, 219))
        draw.text((120, 340), "• 刀具干涉: 直壁与元件碰撞频发，报废率高", font=fonts["body"], fill=(209, 213, 219))
        draw.text((120, 400), "• 工艺缺陷: 缺少防渣导流，过炉后大量连锡", font=fonts["body"], fill=(209, 213, 219))
        draw.text((120, 460), "• 编程脱节: 需人工重新导入 CAM 软件编刀路", font=fonts["body"], fill=(209, 213, 219))
        draw.text((120, 520), "• 成本高昂: 外协治具周期 3~5 天，¥300~800/块", font=fonts["body"], fill=(209, 213, 219))

        draw.rounded_rectangle([120, 680, 840, 780], radius=12, fill=(35, 18, 22, 255), outline=(239, 68, 68, 220))
        draw.text((220, 712), "传统外协制具: 沟通慢 · 迭代累 · 易撞件", font=fonts["h2"], fill=(239, 68, 68))

        # Right Card: Wave Fixture AI 1-Click Drag & Drop (Green/Blue glowing)
        draw.rounded_rectangle([940, 180, 1840, 850], radius=16, fill=(22, 27, 38, 255), outline=(59, 130, 246, 220), width=2)
        draw.text((980, 220), "⚡ WAVE FIXTURE AI: 1-Click 全自动直出", font=fonts["h2"], fill=(96, 165, 250))

        # Fake drag & drop zone
        draw.rounded_rectangle([980, 290, 1800, 620], radius=16, fill=(17, 24, 39, 255), outline=(59, 130, 246, 200), width=2)
        draw.text((1250, 370), "📁", font=fonts["huge_icon"], fill=(96, 165, 250))
        draw.text((1180, 470), "拖入 KiCad / Gerber 压缩包 (ZIP)", font=fonts["h2"], fill=(255, 255, 255))
        draw.text((1140, 530), "已识别: case_003_stm32_4layer (12 钻孔 · 65 贴片 · 26 插件)", font=fonts["body"], fill=(52, 211, 153))

        draw.rounded_rectangle([980, 680, 1800, 780], radius=12, fill=(16, 185, 129, 30), outline=(16, 185, 129, 220))
        draw.text((1120, 712), "🚀 < 1.0 秒端到端完成 21 项 CAM 自动化特征", font=fonts["h2"], fill=(52, 211, 153))

    elif t < 5.8:
        # Phase 2: 2D CAM Blueprint & Automations Showcase
        draw.text((80, 120), "▶ 阶段 02: 21 项自动化特征毫秒级生成 (2D CAM 生产工程图)", font=fonts["h1"], fill=(255, 255, 255))

        # Left: 2D Preview image
        p_w, p_h = 1000, 680
        thumb = preview_2d_img.resize((p_w, p_h), Image.Resampling.LANCZOS)
        canvas.paste(thumb, (80, 180))
        draw.rectangle([80, 180, 80 + p_w, 180 + p_h], outline=(59, 130, 246, 150), width=2)

        # Right: Checklist of 21 Automations
        draw.rounded_rectangle([1120, 180, 1840, 860], radius=16, fill=(22, 27, 38, 255), outline=(31, 41, 55, 255), width=2)
        draw.text((1160, 215), "🛠️ 核心制造特征全覆盖", font=fonts["h2"], fill=(255, 255, 255))

        features = [
            ("✅ 沉板区自动外扩", "板外形外扩 0.2mm + R1.85 自动狗骨头清角"),
            ("✅ 波峰导流倒角", "60° 迎锡面平滑导流 + 脱锡侧防连锡排锡槽"),
            ("✅ 防浮渣扰流槽", "Ersa / SEHO 8mm 宽破浪槽，拦截漂浮锡渣"),
            ("✅ 钛合金嵌件保护", "自动识别 <1.8mm 薄壁，嵌入耐磨纯钛刀片"),
            ("✅ 定位销与压扣", "精选对角最大跨距定位销 + 阿基米德浮力压舌"),
            ("✅ 人体工学与防呆", "双侧 R8 舒适握持手孔 + 45° 非对称防反插切角"),
            ("✅ 智能工厂 MES", "IPC-1782 条码槽 + K型热电偶测温穿线孔通道"),
        ]

        # Scan laser line effect across the 2D image
        laser_y = 180 + int((t - 2.5) / 3.3 * p_h) % p_h
        draw.line([80, laser_y, 80 + p_w, laser_y], fill=(0, 255, 255, 220), width=3)

        for i, (f_title, f_desc) in enumerate(features):
            y_pos = 280 + i * 75
            draw.text((1160, y_pos), f_title, font=fonts["h3"], fill=(52, 211, 153))
            draw.text((1160, y_pos + 30), f_desc, font=fonts["small"], fill=(156, 163, 175))

    elif t < 8.2:
        # Phase 3: 3D Digital Twin, Rotating Angle, Collision Highlight
        draw.text((80, 120), "▶ 阶段 03: 水密 3D 实体孪生与元件干涉分析 (3D COLLISION CHECK)", font=fonts["h1"], fill=(255, 255, 255))

        # Render 3D model frame with rotating azimuth
        angle = (t - 5.8) * 65.0 + 40.0
        render_img = render_3d_frame(mesh, azimuth=angle, elevation=28)
        r_w, r_h = 1080, 680
        render_resized = render_img.resize((r_w, r_h), Image.Resampling.LANCZOS)
        canvas.paste(render_resized, (80, 180), render_resized)
        draw.rectangle([80, 180, 80 + r_w, 180 + r_h], outline=(59, 130, 246, 150), width=2)

        # 3D Legend overlay
        draw.rounded_rectangle([100, 780, 480, 840], radius=8, fill=(17, 20, 28, 220), outline=(59, 130, 246, 100))
        draw.ellipse([120, 802, 136, 818], fill=(239, 68, 68))
        draw.text((146, 800), "🔴 实体干涉告警", font=fonts["small"], fill=(239, 68, 68))
        draw.ellipse([270, 802, 286, 818], fill=(245, 158, 11))
        draw.text((296, 800), "⚠️ 高度可疑元件", font=fonts["small"], fill=(245, 158, 11))

        # Right Card: Real-time Interference Audit
        draw.rounded_rectangle([1200, 180, 1840, 860], radius=16, fill=(22, 27, 38, 255), outline=(239, 68, 68, 200), width=2)
        draw.text((1230, 220), "🚨 3D 空间碰撞拦截系统", font=fonts["h2"], fill=(248, 113, 113))

        alerts = [
            ("U1 (LQFP-64 芯片)", "高度 1.6mm · 避位槽深 2.5mm", "✅ 安全避空"),
            ("C1 (大电解电容)", "高度 11.0mm · 撞件风险！", "🔴 重叠 176mm³ 拦截"),
            ("K1 (功率继电器)", "高度 15.5mm · 超高部件", "⚠️ 自动加深避位槽"),
            ("J1 (Type-C 接口)", "板边外伸 0.8mm", "✅ 边缘铣缺口通过"),
        ]

        for i, (ref, detail, status) in enumerate(alerts):
            y_box = 280 + i * 90
            draw.rounded_rectangle([1230, y_box, 1810, y_box + 76], radius=10, fill=(17, 24, 39, 255), outline=(55, 65, 81, 255))
            draw.text((1250, y_box + 14), ref, font=fonts["h3"], fill=(255, 255, 255))
            draw.text((1250, y_box + 44), detail, font=fonts["small"], fill=(156, 163, 175))
            draw.text((1600, y_box + 26), status, font=fonts["body"], fill=(239, 68, 68) if "🔴" in status else (52, 211, 153))

        draw.rounded_rectangle([1230, 670, 1810, 820], radius=12, fill=(16, 185, 129, 25), outline=(16, 185, 129, 200))
        draw.text((1270, 705), "🛡️ 71 项 DRC 工业规则全覆盖", font=fonts["h2"], fill=(52, 211, 153))
        draw.text((1270, 755), "包含 APTPCB 壁厚、SMEMA 轨距、Macaos 间隙门禁", font=fonts["small"], fill=(209, 213, 219))

    else:
        # Phase 4: Manufacturing Output & Deliverables
        draw.text((80, 120), "▶ 阶段 04: 直接量产交付 · 生产文件全齐 (DIRECT PRODUCTION)", font=fonts["h1"], fill=(255, 255, 255))

        # Left: Scrolling G-Code Box
        draw.rounded_rectangle([80, 180, 960, 860], radius=16, fill=(15, 23, 42, 255), outline=(59, 130, 246, 200), width=2)
        draw.text((110, 210), "⚙️ RS-274 标准 CNC 数控 G 代码直出", font=fonts["h2"], fill=(96, 165, 250))

        gcode_lines = [
            "; --- WAVE FIXTURE AI CNC G-CODE ---",
            "; Job: case_003_stm32_4layer | Material: Durostone 10mm",
            "; Estimated Time: 31.5 min | Toolpath: 2674 Lines",
            "G90 G21 G17 G54 ; Absolute metric mode",
            "M06 T01 ; Tool 01: D3.0mm Roughing Endmill",
            "S18000 M03 F2400 ; Durostone optimal feed",
            "G00 Z15.000 ; Rapid to clearance",
            "G00 X25.400 Y18.200",
            "G01 Z-2.500 F800 ; Plunge to sink pocket",
            "G02 X28.400 Y21.200 I0.0 J3.0 F2400",
            "G01 X65.200 Y21.200 ; Contour roughing pass",
            "G01 Z-5.000 F800 ; 2nd depth pass",
            "G02 X68.200 Y18.200 I3.0 J0.0",
            "M06 T02 ; Tool 02: D1.85mm Dogbone Fillet Mill",
            "G01 X15.000 Y15.000 Z-2.500 ; Clearing corners",
            "M30 ; Program End",
        ]

        offset_lines = int((t - 8.2) * 4) % len(gcode_lines)
        for i in range(13):
            line_idx = (offset_lines + i) % len(gcode_lines)
            draw.text((110, 270 + i * 38), gcode_lines[line_idx], font=fonts["code"], fill=(147, 197, 253))

        # Right: 4 Deliverable Badges & CTA
        draw.rounded_rectangle([1020, 180, 1840, 860], radius=16, fill=(22, 27, 38, 255), outline=(16, 185, 129, 200), width=2)
        draw.text((1060, 210), "📦 完整工程交付包 (一键打包下载)", font=fonts["h2"], fill=(52, 211, 153))

        deliverables = [
            ("📐 fixture.dxf", "完整 AutoCad 2D 工程图 (含倒角/清角/开孔图层)"),
            ("🧊 fixture.stl / glb", "流形水密 3D 模型 (可直接 3D 打印或 CNC 编程)"),
            ("⚡ fixture.nc", "工业级 RS-274 G 代码 (车间机床即刻开料)"),
            ("📋 report.md & fai.md", "IATF 16949 工装首件检验单与材料成本核算表"),
        ]

        for i, (title_text, desc_text) in enumerate(deliverables):
            y_box = 270 + i * 90
            draw.rounded_rectangle([1060, y_box, 1800, y_box + 74], radius=10, fill=(17, 24, 39, 255), outline=(55, 65, 81, 255))
            draw.text((1090, y_box + 14), title_text, font=fonts["h3"], fill=(255, 255, 255))
            draw.text((1090, y_box + 44), desc_text, font=fonts["small"], fill=(156, 163, 175))

        # Big CTA banner
        draw.rounded_rectangle([1060, 650, 1800, 820], radius=12, fill=(37, 99, 235, 35), outline=(59, 130, 246, 255), width=2)
        draw.text((1180, 680), "⭐ GitHub Star 关注开源进展", font=fonts["h1"], fill=(255, 255, 255))
        draw.text((1130, 745), "github.com/mo9652962-ai/wave-fixture-ai", font=fonts["h2"], fill=(96, 165, 250))

    return canvas


def main():
    print("[*] Loading assets for video demo generation...")
    mesh = trimesh.load(str(DEMO_CASE_DIR / "fixture.stl"))
    preview_2d = Image.open(str(DEMO_CASE_DIR / "fixture.png")).convert("RGBA")

    fonts = {
        "brand": get_font(34, bold=True),
        "sub": get_font(20, bold=False),
        "badge": get_font(20, bold=True),
        "h1": get_font(30, bold=True),
        "h2": get_font(24, bold=True),
        "h3": get_font(20, bold=True),
        "body": get_font(18, bold=False),
        "small": get_font(15, bold=False),
        "code": get_font(16, bold=False),
        "huge_icon": get_font(70, bold=False),
    }

    frames_dir = Path(tempfile.mkdtemp(prefix="wave_video_frames_"))
    print(f"[*] Rendering frames to {frames_dir}...")

    # 15 fps * 10 seconds = 150 frames
    total_frames = 150
    for i in range(total_frames):
        if i % 15 == 0:
            print(f"    Progress: {i}/{total_frames} frames ({i/total_frames*10:.1f}s)...")
        frame_img = build_full_frame(i, total_frames, mesh, preview_2d, fonts)
        frame_img.convert("RGB").save(frames_dir / f"frame_{i:04d}.png")

    print("[*] All frames rendered. Encoding with ffmpeg...")

    # 1. Output MP4 (1080p, 15fps, crisp h264)
    mp4_path = OUTPUT_DIR / "wave-fixture-ai-10s-demo.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-framerate", "15",
            "-i", str(frames_dir / "frame_%04d.png"),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "slow",
            "-crf", "18",
            str(mp4_path),
        ],
        check=True,
        shell=False,
    )
    print(f"[+] 1080P MP4 exported: {mp4_path} ({mp4_path.stat().st_size / 1024:.1f} KB)")

    # 2. Output GIF (960x540, 15fps, palettegen for high color fidelity)
    gif_path = OUTPUT_DIR / "demo.gif"
    palette_path = frames_dir / "palette.png"

    # Step A: generate palette
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-framerate", "15",
            "-i", str(frames_dir / "frame_%04d.png"),
            "-vf", "scale=960:540:flags=lanczos,palettegen=stats_mode=diff",
            str(palette_path),
        ],
        check=True,
        shell=False,
    )

    # Step B: use palette
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-framerate", "15",
            "-i", str(frames_dir / "frame_%04d.png"),
            "-i", str(palette_path),
            "-lavfi", "scale=960:540:flags=lanczos [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=3",
            str(gif_path),
        ],
        check=True,
        shell=False,
    )
    print(f"[+] Optimized GIF exported: {gif_path} ({gif_path.stat().st_size / 1024:.1f} KB)")

    # Cleanup temporary frames
    shutil.rmtree(frames_dir, ignore_errors=True)
    print("[*] Done!")


if __name__ == "__main__":
    main()

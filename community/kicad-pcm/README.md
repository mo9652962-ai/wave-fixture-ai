# KiCad 官方 PCM (Plugin and Content Manager) 插件发布与安装套件

本目录包含 **Wave Fixture AI** 面向 KiCad 官方插件与内容管理器（PCM）的完整插件包、标准规范元数据与自动化构建流水线。

---

## 1. 插件特性与架构概述

- **官方 Identifier**: `com.github.mo9652962-ai.wave-fixture-ai`
- **支持版本**: KiCad 8.0 / 9.0 / 10.0（跨 Windows、macOS、Linux 三大平台）
- **核心功能**:
  - 集成于 KiCad PCB 编辑器（Pcbnew）顶栏快捷工具条，带专属 64×64 高对比度彩色图标；
  - 自动识别当前激活的 `.kicad_pcb` 板卡尺寸、长宽边界、焊盘数与走线拓扑；
  - 一键在浏览器调起 **3D 治具空间工作台**，实时查看沉板槽清角、60° 波峰导流倒角、Ersa 防浮渣破浪槽与 71 项 DRC 门禁；
  - 提示工程师复制本地离线启动命令（`uvx wave-fixture-ai`），100% 保护企业私有图纸安全。

---

## 2. 目录规范结构

```text
community/kicad-pcm/
├── metadata.json              # 符合官方 schemas/v1.json 规范的元数据
├── README.md                  # 本文档：构建、测试与 GitLab 上架说明
├── plugins/                   # 插件源码目录（解压即用）
│   ├── __init__.py            # 包导出入口
│   ├── action_wave_fixture.py # Pcbnew ActionPlugin 核心实现 (带 wx 对话框与上下文提取)
│   └── icon.png               # 64×64 标准透明底 PNG 图标
└── dist/                      # 自动化构建输出目录 (git 忽略)
    ├── wave-fixture-ai-kicad-pcm-v0.5.1.zip
    └── kicad-addons-repo/     # 直接对应 upstream GitLab 仓库结构的提交包
        └── packages/
            └── com.github.mo9652962-ai.wave-fixture-ai/
                └── metadata.json
```

---

## 3. 自动化打包与校验 (Build & Validate)

运行自动化打包脚本：
```bash
uv run python scripts/build_kicad_pcm_package.py
```

该脚本将自动执行以下严密工序：
1. 校验 `metadata.json` 语法、schema 必填字段与 `identifier` 规范；
2. 校验 `icon.png` 格式（PNG 格式、1:1 正方形、有效像素）；
3. 压缩生成干净的发行版 ZIP 包；
4. 真实计算 `download_sha256`、`download_size`（压缩字节）与 `install_size`（解压字节）；
5. 自动回填至 `metadata.json`，杜绝人工计算误差；
6. 在 `dist/kicad-addons-repo/` 导出对齐官方 GitLab 仓库路径的镜像树。

---

## 4. 本地安装与开发测试 (Local Testing)

在向官方仓库提 PR 前，建议在本地 KiCad 实例中安装测试：

### 4.1 手动复制插件
将 `plugins/` 目录复制到 KiCad 用户脚本目录：
- **Windows**: `%APPDATA%\kicad\8.0\scripting\plugins\wave_fixture_ai\`
- **Linux**: `~/.local/share/kicad/8.0/scripting/plugins/wave_fixture_ai/`
- **macOS**: `~/Library/Preferences/kicad/8.0/scripting/plugins/wave_fixture_ai/`

### 4.2 通过 KiCad PCM 界面直接安装 ZIP 包
1. 打开 KiCad 主界面 → 点击 **Plugin and Content Manager (插件与内容管理器)**；
2. 点击界面底部的 **Install from File... (从文件安装...)**；
3. 选择 `community/kicad-pcm/dist/wave-fixture-ai-kicad-pcm-v0.5.1.zip`；
4. 点击 Apply Pending Changes，重启或打开 Pcbnew，顶栏即可看到专属波峰焊图标。

---

## 5. 提交至 KiCad 官方 Addon 仓库 (Upstream Submission)

KiCad 官方 Addon 采用 GitLab Merge Request 机制进行社区审核：
- **官方仓库**: [https://gitlab.com/kicad/addons/metadata](https://gitlab.com/kicad/addons/metadata)

### 提交三步：
1. **Fork 仓库**: 在 GitLab 上 Fork `kicad/addons/metadata` 到您的个人账号；
2. **复制包定义**:
   将生成的 `community/kicad-pcm/dist/kicad-addons-repo/packages/com.github.mo9652962-ai.wave-fixture-ai/` 整个目录复制并提交至您的 Fork 分支；
3. **提交 Merge Request**:
   - **MR Title**: `Add Wave Fixture AI plugin (v0.5.1)`
   - **MR Description**:
     ```markdown
     ### Package Summary
     - **Identifier**: `com.github.mo9652962-ai.wave-fixture-ai`
     - **Name**: Wave Fixture AI
     - **Category**: Manufacturing
     - **License**: MIT
     - **Description**: Automated wave soldering pallet and selective soldering fixture CAM engine with 3D clearance preview, 71 DRC manufacturing rules, and direct CNC G-code toolpath generation.
     - **Repository**: https://github.com/mo9652962-ai/wave-fixture-ai
     - **Package ZIP**: Tested and verified with KiCad 8.0/9.0.
     ```

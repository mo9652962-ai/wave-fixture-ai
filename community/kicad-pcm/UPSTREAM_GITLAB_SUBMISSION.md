# KiCad 官方 PCM 插件中心 (GitLab Upstream) 提交指南

本文档指导如何将 **Wave Fixture AI** 提交至 KiCad 官方唯一的插件元数据仓库，完成全球官方插件中心收录。

---

## 1. 提交目标与官方规范

- **官方仓库**: [https://gitlab.com/kicad/addons/metadata](https://gitlab.com/kicad/addons/metadata)
- **官方规范**: [schemas/v1.json](https://gitlab.com/kicad/addons/metadata/-/raw/master/schemas/v1.json)
- **我们的包标识符 (Identifier)**: `com.github.mo9652962-ai.wave-fixture-ai`
- **发行版包位置**: `https://github.com/mo9652962-ai/wave-fixture-ai/releases/download/v0.5.2/wave-fixture-ai-kicad-pcm-v0.5.2.zip`
- **验证指纹 (SHA256)**: `7eaa563b852f6ca9824305ceacb811a9bb50fb4f42f582c3203003050f8d4798`

---

## 2. 已经自动生成的提交文件

在本地执行 `uv run python scripts/build_kicad_pcm_package.py` 后，已为您在以下目录导出了与官方 GitLab 仓库结构 100% 对应的提交文件夹：

```text
community/kicad-pcm/dist/kicad-addons-repo/
└── packages/
    └── com.github.mo9652962-ai.wave-fixture-ai/
        ├── metadata.json
        └── icon.png
```

---

## 3. 极简提交步骤 (3 步完成)

### 第一步：在 GitLab 上 Fork 官方仓库
1. 使用浏览器登录 GitLab，打开：`https://gitlab.com/kicad/addons/metadata`
2. 点击右上角 **Fork**，Fork 到您的个人账号下（如 `gitlab.com/<your-username>/metadata`）。

### 第二步：添加包文件并提交
在终端克隆您的 Fork 仓库，将生成的包目录复制进去：

```bash
# 1. 克隆您的 GitLab Fork 仓库
git clone https://gitlab.com/<your-gitlab-username>/metadata.git kicad-addons-upstream
cd kicad-addons-upstream

# 2. 新建分支
git checkout -b add-wave-fixture-ai-plugin

# 3. 复制生成的包定义到 packages/ 目录下
# 目标路径: packages/com.github.mo9652962-ai.wave-fixture-ai/
cp -r /c/Users/31954/dev/repo-review/wave-fixture-ai/community/kicad-pcm/dist/kicad-addons-repo/packages/com.github.mo9652962-ai.wave-fixture-ai packages/

# 4. 提交并推送到您的 GitLab
git add packages/com.github.mo9652962-ai.wave-fixture-ai
git commit -m "Add Wave Fixture AI plugin package (v0.5.2)"
git push -u origin add-wave-fixture-ai-plugin
```

### 第三步：发起 Merge Request (MR)
打开您的 GitLab Fork 页面，点击 **Create merge request**：
- **Title**: `Add Wave Fixture AI plugin (v0.5.2)`
- **Description**: 直接复制以下内容：

```markdown
### Package Information
- **Name**: Wave Fixture AI
- **Identifier**: `com.github.mo9652962-ai.wave-fixture-ai`
- **Category**: Manufacturing
- **License**: MIT
- **KiCad Compatibility**: `>=8.0.0` (Verified on KiCad 8.0 & 9.0)
- **Repository**: https://github.com/mo9652962-ai/wave-fixture-ai
- **Download URL**: https://github.com/mo9652962-ai/wave-fixture-ai/releases/download/v0.5.2/wave-fixture-ai-kicad-pcm-v0.5.2.zip
- **SHA256**: `7eaa563b852f6ca9824305ceacb811a9bb50fb4f42f582c3203003050f8d4798`

### Description
Wave Fixture AI is an open-source automated wave soldering pallet and selective solder fixture CAM engine. 
This action plugin allows engineers to inspect their board layout, calculate pallet clearance dimensions, and launch the 3D fixture workspace directly from within KiCad PCB Editor (Pcbnew).
```

---

## 4. 审核与官方上线后效果
官方团队合并该 MR 后，KiCad 官方维护的全球中心源将自动更新索引。全球所有使用 KiCad 8/9/10 的工程师打开自带的 **PCM 插件管理器**，在默认界面搜索 “Wave Fixture” 或在 “Manufacturing” 分类下即可直接点击 **Install** 安装！

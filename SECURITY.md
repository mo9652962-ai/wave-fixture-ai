# 安全政策 (Security Policy)

## 支持的版本 (Supported Versions)

| 版本 (Version) | 支持状态 (Status) |
|:---|:---|
| 最新主分支 (main) | ✅ 持续维护与安全修复 (Actively supported) |

## 安全设计原则 (Security Design)

WaveFixture AI 面向工业制造与自动化 CAD 流程，坚持高可靠性与防御性设计：

1. **防御性几何与文件解析**：用户上传的 PCB Gerber (RS-274X) 与 Excellon 钻孔文件被严格视为不可信输入。通过 `gerbonara` 解析，杜绝任何 `eval` 或代码执行路径；内置死循环与奇异几何退化保护。
2. **本地优先与隔离处理**：Web 界面上传文件仅保存在本地隔离的临时目录中，并设定自动清理策略；所有几何布尔运算（`shapely` / `trimesh` / `manifold`）均在本地沙箱完成，不向任何云端上传工程机密。
3. **确定性参数调节**：自然语言参数调整模块采用严格的正则词法状态机解析，无大模型自由发挥带来的制造参数漂移与短路碰撞。
4. **供应链透明**：通过 OpenSSF Scorecard 持续监控供应链与 GitHub Actions 依赖安全。

## 报告安全漏洞 (Reporting a Vulnerability)

如果你在 WaveFixture AI 中发现了潜在安全漏洞（如任意文件读写、恶意 Gerber 解析崩溃、DoS 拒绝服务等）：

- **请勿公开提交 Issue**。
- 请直接通过 GitHub 发送私密安全通知，或联系维护者：`mo9652962-ai@users.noreply.github.com`。
- 请在报告中提供：
  - 漏洞简要描述与影响范围
  - 触发异常的最小样例 Gerber 文件或复现步骤
  - 建议的修复方式

### 处理承诺
- 我们将在 **48 小时内** 确认并展开技术评估。
- 修复发布后在更新日志中公开鸣谢。

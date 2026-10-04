# 贡献指南 (Contributing Guide)

感谢你关注并参与 **WaveFixture AI**（波峰焊治具 AI 设计助手）的开源建设！

无论是完善制造自动化工序、新增生产 DRC 规则、补充真实板卡测试集，还是改进文档与多语言翻译，我们都非常欢迎。

## 快速开始 (Quickstart)

```bash
# 推荐使用 Python 3.10+
git clone https://github.com/mo9652962-ai/wave-fixture-ai.git
cd wave-fixture-ai

# 安装开发依赖
pip install -e ".[dev]"
```

## 运行测试与一致性守卫 (Testing & Verification)

在提交任何更改之前，请确保所有测试在本地通过：

```bash
# 运行完整测试套件（232 项测试）
pytest tests/ -q

# 运行文档与代码一致性防漂移守卫
pytest tests/test_doc_consistency.py -v
```

> **注意**：本项目内建了严格的 `test_doc_consistency.py`。如果你新增或修改了 DRC 规则、自然语言调节参数或材料预设，必须同步更新 `README.md`、`README.en.md` 与 `llms.txt` 中声明的数量，否则一致性守卫将阻断提交。

## 贡献方向 (Contribution Areas)

1. **新增 DRC 制造安全规则**：在 `drc.py` 中增加新的合规检查项，并附带出处标准（如 IPC 标准、行业常见规范）。
2. **贡献真实板卡金样回归用例**：在 `cases/` 目录下补充合法的 Gerber 测试集，并在 `tests/` 中编写 Golden Sample 回归测试（IoU ≥ 0.9）。
3. **数控加工与制造导出优化**：改进 `cnc_gcode.py` 的落料进给速度、清角刀路或生产工单排版。

## 提交规范 (Commit & PR)

- 提交信息遵循 Conventional Commits：`feat: ...` / `fix: ...` / `docs: ...` / `test: ...`
- 严禁提交个人隐私信息、真实商业机密板卡、或未授权的外部闭源资产。

## 变更说明 (Description)

简要说明本次 PR 的背景、修改内容及动机。
Briefly describe the context, changes, and motivation.

## 关联 Issue (Related Issues)

- Closes #
- Fixes #

## 自查清单 (Checklist)

- [ ] 已在本地运行单元测试并通过：`pytest tests/ -q` (232 passed)
- [ ] 若增改 DRC 规则或调节参数，已同步更新所有文档并运行 `pytest tests/test_doc_consistency.py` 验证防漂移
- [ ] 零私有凭据或泄漏（严格遵循隐私与合规规范）
- [ ] 新增功能已补充对应单元测试或真实板卡回归用例

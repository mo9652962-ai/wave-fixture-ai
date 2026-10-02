.PHONY: help test cov lint fix run build golden clean

help:
	@echo "Wave Fixture AI — 开发命令"
	@echo "  make test      跑 160 项测试"
	@echo "  make cov       测覆盖率（门槛 80% 棘轮）"
	@echo "  make lint      代码规范检查（ruff）"
	@echo "  make fix       自动修复代码规范"
	@echo "  make run       启动 Web 服务（默认 8000 端口）"
	@echo "  make golden    跑真实板黄金回归（cases/ 下 3 块板）"
	@echo "  make build     构建 wheel 与 sdist（自动校验前端资源）"
	@echo "  make clean     清理构建与临时文件"

test:
	uv run pytest -q

cov:
	uv run pytest -q --cov=fixture_phase1 --cov=fixture_phase2 --cov=fixture_3d \
	  --cov=interference --cov=nl_adjust --cov=drc --cov=golden --cov=review \
	  --cov=pin_select --cov=web_server --cov=ci_drc_gate --cov-fail-under=80

lint:
	uv run ruff check .

fix:
	uv run ruff check . --fix

run:
	uv run python web_server.py --port 8000

golden:
	uv run pytest tests/test_golden_case*.py -v

build:
	uv build
	@python -c "import glob,zipfile,sys; n=zipfile.ZipFile(glob.glob('dist/*.whl')[-1]).namelist(); sys.exit('wheel 缺少前端') if not any(x.endswith('index.html') for x in n) else print('wheel 校验通过 ✓')"

clean:
	rm -rf dist/ build/ *.egg-info/ .pytest_cache/ .ruff_cache/ output/ fixture-out/

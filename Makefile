.PHONY: install lint fmt test build deploy clean uninstall

install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest -v

build: lint test
	./build.sh

deploy:
	./build.sh --install

clean:
	rm -rf dist build __pycache__ .pytest_cache .ruff_cache *.egg-info

uninstall:
	rm -rf /Applications/FolderSync.app
	rm -f ~/.foldersync.json ~/.foldersync-history.json ~/foldersync.log
	@echo "FolderSync uninstalled."

"""Every ```python block in the README and docs/ is executed, so the docs cannot rot.
Blocks in one file share a namespace and run top to bottom."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
FILES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
FENCE = re.compile(r"^```python\n(.*?)^```", re.S | re.M)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_python_blocks_run(path):
    blocks = FENCE.findall(path.read_text())
    assert blocks, f"{path.name} has no python examples"
    ns: dict = {"__name__": "docs"}
    for i, code in enumerate(blocks, 1):
        exec(compile(code, f"{path.name}[block {i}]", "exec"), ns)

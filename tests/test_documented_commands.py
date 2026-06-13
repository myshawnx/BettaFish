import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def _pytest_paths(text: str) -> set[str]:
    return set(re.findall(r"tests/test_[A-Za-z0-9_]+\.py", text))


def test_quickstart_no_key_pytest_list_matches_ci():
    ci_tests = _pytest_paths(_read(".github/workflows/ci.yml"))
    quickstart_tests = _pytest_paths(_read("docs/QUICKSTART.md"))

    assert ci_tests
    assert ci_tests.issubset(quickstart_tests)


def test_quickstart_documents_registered_mcp_tools():
    quickstart = _read("docs/QUICKSTART.md")

    from MCPServer.tools import TOOL_REGISTRY

    for tool_name in TOOL_REGISTRY:
        assert f"`{tool_name}`" in quickstart


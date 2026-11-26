"""AST checks for layer rules that import-linter cannot express."""
import ast
import sys
from pathlib import Path

# Every Supabase/PostgREST query or RPC starts from one of these client entrypoints.
PERSISTENCE_ENTRYPOINTS = {"table", "schema", "rpc", "from_", "execute"}


def _layer_files(*layers):
    """Python files under any `<layers>` directory of a module, at any depth."""
    for path in Path("app/modules").rglob("*.py"):
        if any(part in layers for part in path.parent.parts):
            yield path


def _inner_layer_files():
    yield from _layer_files("domain", "application")


def test_domain_and_application_never_query_persistence_directly():
    # Persistence goes through module-owned ports implemented in infrastructure.
    offenders = []
    for path in _inner_layer_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in PERSISTENCE_ENTRYPOINTS):
                offenders.append(f"{path}:{node.lineno} .{node.func.attr}()")
    assert not offenders, offenders


def test_module_domain_layer_imports_only_standard_library_and_domain():
    for path in _layer_files("domain"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = ([node.module] if isinstance(node, ast.ImportFrom) and node.module
                       else [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            for module in modules:
                root = module.split(".")[0]
                # Stdlib, pydantic, module domain values and module contracts.
                assert (root in sys.stdlib_module_names or root == "pydantic"
                        or module.startswith("app.kernel.")
                        or module.startswith("app.modules.")
                        and (".domain" in module or module.endswith(".contracts"))), (path, module)

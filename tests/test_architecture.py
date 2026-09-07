"""La regla de dependencias de `backend/__init__.py`, como test (no la detecta el linter).

Criterios:
  AC-AR1  las importaciones van en UNA direccion: entradas → dominio → integraciones → core.
          El dominio nunca importa una integracion; `conversations` nunca importa `tickets`;
          las integraciones no importan dominio; `core` no importa nada de `backend` salvo
          `core`.
  AC-AR2  las variables de entorno se leen SOLO en `core/config.py` (y en los dos sitios que
          necesitan saber si corren dentro de una Lambda): asi un `.env` no puede quedar
          "invisible" para un modulo que lea `os.environ` por su cuenta.
  AC-AR3  los helpers que viven en `core` no se vuelven a definir por ahi: un `def normalize`
          o un `def _is_condition_failure` nuevo fuera de `core` es la señal de que alguien
          copio en vez de importar (auditoria 2026-09-06).

Puro: recorre los archivos con `ast`, sin importar nada del backend.
"""

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"

# A quien puede importar cada paquete de `backend` (ademas de si mismo y de `core`).
ALLOWED = {
    "api": {"conversations", "tickets", "advisors", "agent", "catalog", "notifications", "images"},
    "workers": {"conversations", "tickets", "advisors", "agent", "catalog", "notifications",
                "images"},
    "tickets": {"conversations"},
    "conversations": set(),
    "advisors": set(),
    "agent": set(),
    "catalog": set(),
    "notifications": set(),
    "images": set(),
    "core": set(),
}

# Los unicos archivos que pueden leer `os.environ` / `os.getenv` directamente.
ENV_READERS = {
    "core/config.py",  # Settings: la UNICA fuente de configuracion
    "core/aws.py",  # credenciales dummy de dynamodb-local
    "api/dev_auth.py",  # ¿estoy dentro de una Lambda? (AWS_LAMBDA_FUNCTION_NAME)
}

# Nombres que ya viven en `core` y no deben volver a definirse fuera.
CORE_ONLY_DEFINITIONS = {
    "normalize": "core/text.py",
    "strip_accents": "core/text.py",
    "_is_condition_failure": "core/dynamo.py (is_condition_failure)",
    "is_condition_failure": "core/dynamo.py",
    "query_up_to": "core/dynamo.py",
    "deterministic_id": "core/ids.py",
    "from_dynamo": "core/dynamo.py",
}


def _modules() -> list[tuple[str, ast.Module]]:
    found = []
    for path in sorted(BACKEND.rglob("*.py")):
        relative = path.relative_to(BACKEND).as_posix()
        found.append((relative, ast.parse(path.read_text(encoding="utf-8"), filename=relative)))
    return found


def _package_of(relative: str) -> str:
    return relative.split("/", 1)[0] if "/" in relative else "backend"


def _backend_imports(tree: ast.Module) -> set[str]:
    """Paquetes de `backend` que importa el modulo (`backend.agent.rag` → `agent`)."""
    packages: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("backend"):
            parts = node.module.split(".")
            if len(parts) > 1:
                packages.add(parts[1])
            else:
                packages.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("backend."):
                    packages.add(alias.name.split(".")[1])
    return packages


@pytest.mark.parametrize("relative,tree", _modules(), ids=lambda x: x if isinstance(x, str) else "")
def test_las_dependencias_van_en_una_sola_direccion(relative, tree):
    package = _package_of(relative)
    if package == "backend":
        return
    allowed = ALLOWED[package] | {package, "core"}
    forbidden = _backend_imports(tree) - allowed
    assert not forbidden, (
        f"{relative} importa {sorted(forbidden)}: {package} solo puede importar "
        f"{sorted(allowed)} (regla de backend/__init__.py)"
    )


@pytest.mark.parametrize("relative,tree", _modules(), ids=lambda x: x if isinstance(x, str) else "")
def test_el_entorno_se_lee_solo_en_config(relative, tree):
    if relative in ENV_READERS:
        return
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and node.attr in {"environ", "getenv"}
        ):
            pytest.fail(
                f"{relative}:{node.lineno} lee os.{node.attr}; la configuracion se lee de "
                "core.config.get_settings() (RNF-007)"
            )


@pytest.mark.parametrize("relative,tree", _modules(), ids=lambda x: x if isinstance(x, str) else "")
def test_lo_que_vive_en_core_no_se_vuelve_a_definir(relative, tree):
    if relative.startswith("core/"):
        return
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in CORE_ONLY_DEFINITIONS:
            pytest.fail(
                f"{relative}:{node.lineno} define `{node.name}`, que ya vive en "
                f"{CORE_ONLY_DEFINITIONS[node.name]}: importarlo, no copiarlo"
            )

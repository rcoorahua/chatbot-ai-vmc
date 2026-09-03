"""Smoke test del ARTEFACTO Lambda real (DETAILS.md §4.1, ultimo pendiente del Paso 1).

Corre DESPUES de `cdk synth`, no antes: necesita los assets bundleados en cdk.out/ (Docker).
Por eso vive fuera de `pytest tests -q` (que corre sin Docker, antes del synth, en el job
`synth` de CI) y se invoca aparte como script, ya con cdk.out/ listo.

Importa cada handler con el asset como UNICO entry en sys.path (`python -S`, cwd=asset dir, sin
site-packages): si el import solo funciona porque el checkout completo esta en PYTHONPATH -- el
bug real (`ModuleNotFoundError: backend` en cold start, invisible para `cdk synth` porque nunca
importa el handler) -- esto falla igual que en Lambda real.
"""

import json
import subprocess
import sys
from pathlib import Path

CDK_OUT = Path(__file__).resolve().parent.parent / "cdk.out"
STAGE = "stage"

HANDLERS = [
    "backend.api.main.handler",
    "backend.workers.ai_worker.handler",
    "backend.workers.notify_worker.handler",
]


def _asset_dir_for_handler(template: dict, handler: str) -> Path:
    for resource in template["Resources"].values():
        props = resource.get("Properties", {})
        if resource["Type"] == "AWS::Lambda::Function" and props.get("Handler") == handler:
            asset_hash = props["Code"]["S3Key"].rsplit(".", 1)[0]
            return CDK_OUT / f"asset.{asset_hash}"
    raise AssertionError(f"Ninguna AWS::Lambda::Function usa el handler {handler!r}")


def main() -> None:
    template_path = CDK_OUT / f"subastin-{STAGE}.template.json"
    if not template_path.exists():
        raise SystemExit(
            f"No existe {template_path} -- correr `cdk synth -c stage={STAGE}` antes de este smoke."
        )
    template = json.loads(template_path.read_text())

    for handler in HANDLERS:
        module = handler.rsplit(".", 1)[0]
        asset_dir = _asset_dir_for_handler(template, handler)
        result = subprocess.run(
            [sys.executable, "-S", "-c", f"import {module}"],
            cwd=asset_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"import {module} fallo desde el asset real {asset_dir.name}:\n{result.stderr}"
            )
        print(f"ok: {module} importa desde el asset real ({asset_dir.name})")


if __name__ == "__main__":
    main()

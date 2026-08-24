"""Lambda `worker-notify` — consumidor de SQS `notifications`.

Envia la notificacion de Slack al generarse un handoff/ticket, sin esperar a que un asesor tome
el caso (RF-028). Aislada del pipeline IA: si Slack cae, solo esta cola se atrasa.

BLOQUEADO POR: D-016 (canal, contenido minimo, enlace profundo, re-alertas).
"""


def handler(event: dict, context) -> dict:
    failures: list[dict[str, str]] = []
    for record in event["Records"]:
        try:
            _notify(record["body"])
        except Exception:  # noqa: BLE001
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def _notify(body: str) -> None:
    # TODO: POST al webhook de Slack (secreto en Secrets Manager). No implementar sin cerrar D-016.
    raise NotImplementedError

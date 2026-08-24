"""Smoke tests del esqueleto: los modulos importan y la API expone /health.

Los tests reales llegan con cada fase (skill `testing`): cada RF implementado trae el test de
su criterio de aceptacion.
"""

from fastapi.testclient import TestClient

from backend.api.main import app


def test_health_responde_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_workers_importan_y_devuelven_formato_sqs():
    from backend.workers import ai_worker, notify_worker

    # Batch vacio: ningun record que procesar → sin fallos, formato exacto de SQS.
    assert ai_worker.handler({"Records": []}, None) == {"batchItemFailures": []}
    assert notify_worker.handler({"Records": []}, None) == {"batchItemFailures": []}

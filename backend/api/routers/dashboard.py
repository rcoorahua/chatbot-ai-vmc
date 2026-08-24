"""Dashboard operativo para CSMs/asesores. Autenticado con Cognito (JWT authorizer).

Cubrira (RF-047..049 — endpoints concretos POR DEFINIR):
- metricas numericas de operacion: volumen, pendientes, en atencion, cerrados, tiempos de espera
- SIN configuracion tecnica (RF-049) y SIN costos IA en el MVP (la tabla AIUsage se alimenta
  desde el dia 1 pero no se expone aqui)

BLOQUEADO POR: D-013 (metricas exactas).
"""

from fastapi import APIRouter

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# TODO: endpoints por definir — no implementar sin cerrar D-013.

"""Modelo Pydantic Ticket (PLAN.md §4) con la taxonomía de `tickets/taxonomy.py`.

Qué es un ticket y qué NO, después de D-029 (2026-09-02):
- la **conversación escalada** (el caso del autenticado o la conversación del anónimo) es
  donde se CHATEA: mensajes, formulario, notas de sistema;
- el **ticket** es el registro OPERATIVO de ese mismo caso: de qué tipo es, qué categoría,
  qué prioridad, qué datos faltan y cómo se resolvió. Es lo que un asesor filtra y prioriza,
  y lo que el dashboard cuenta (RF-048).

Relación **1:1 con la conversación escalada** (`conversation_id`, único por ticket abierto).
No es la relación 1:N de D-017: con D-029 cada caso ES una conversación aparte, así que "N
tickets por usuario" se cumple con N casos, cada uno con su ticket. Un usuario puede tener
varios tickets abiertos a la vez; el tope lo aplica D-029 sobre los casos.

`problem_type`, `category`, `priority` y `tags` son **propuesta** (D-008/D-009 abiertas):
nacen de las reglas y el asesor los confirma. `classification_source` guarda quién decidió,
que es el dato con el que se mide si la propuesta sirve antes de cerrarla.
"""

from enum import StrEnum
from typing import Any

from backend.core.dynamo_model import DynamoModel
from backend.tickets.taxonomy import Category, Priority, ProblemType, TicketStatus


class ClassificationSource(StrEnum):
    """Quién puso el `problem_type` actual. `RULES` = lo sugirió `taxonomy.suggest` a partir
    del formulario; `ADVISOR` = una persona lo confirmó o corrigió."""

    RULES = "RULES"
    ADVISOR = "ADVISOR"


class Ticket(DynamoModel):
    ticket_id: str
    conversation_id: str
    user_type: str = "AUTHENTICATED"
    user_id: str | None = None
    user_email: str | None = None

    status: TicketStatus = TicketStatus.PENDING
    # Defaults permisivos a propósito: las filas anteriores a esta taxonomía (dataset de
    # pruebas, tickets creados antes de cerrar D-008) siguen siendo válidas y atendibles.
    problem_type: ProblemType = ProblemType.OTHER
    category: Category = Category.GENERAL
    priority: Priority = Priority.MEDIUM
    tags: list[str] = []
    classification_source: ClassificationSource = ClassificationSource.RULES
    # Qué regla disparó (None = ninguna, quedó OTHER). Mide cuánto clasifica la propuesta.
    classification_rule: str | None = None

    # Asunto y detalle del formulario de handoff (D-029).
    title: str | None = None
    description: str | None = None
    # RF-024: datos mínimos del tipo. `missing_data` es lo que el asesor todavía debe pedir;
    # `collected_data` lo que ya registró. Se recalculan juntos al reclasificar.
    collected_data: dict[str, Any] = {}
    missing_data: list[str] = []

    handoff_reason: str | None = None
    assigned_advisor_id: str | None = None
    assigned_at: str | None = None
    resolution: str | None = None
    closed_by: str | None = None

    created_at: str
    updated_at: str
    closed_at: str | None = None

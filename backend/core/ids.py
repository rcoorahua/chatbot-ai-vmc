"""Ids deterministas (DETAILS.md §4.4 / Paso 5).

Derivar el id de la entidad de su clave natural (`uuid5(namespace, clave)`) en vez de sortearlo
es lo que hace atomica la regla "una sola fila por X": dos requests casi simultaneos calculan
el MISMO id y la creacion condicional (`attribute_not_exists(pk)`) deja pasar solo a uno, sin
depender de consultar un GSI eventualmente consistente antes de crear. Lo usan la conversacion
del usuario autenticado (D-002/D-003), el ticket de una conversacion escalada (RF-023) y el
asesor por `sub` de Cognito (RF-006).

Cada modulo conserva su propio namespace: cambiarlo "perderia" las filas existentes (siguen en
la tabla, pero nadie las buscaria por ese id).
"""

import uuid


def deterministic_id(namespace: uuid.UUID, key: str) -> str:
    return str(uuid.uuid5(namespace, key))

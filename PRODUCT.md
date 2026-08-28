# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Asesores humanos de VMC (rol único en el MVP: `ADVISOR`, acceso por invitación + Cognito). Usan
el panel durante su turno para: triar la bandeja de conversaciones derivadas por la IA, tomar un
caso de forma explícita y atómica, responder al usuario, y vigilar el volumen operativo desde el
dashboard. Es una herramienta de trabajo interna, no una superficie de cara al comprador final de
VMC — el comprador solo ve el widget de chat (`widget/`), fuera de este panel.

## Product Purpose

Subastín reemplaza a Intercom como atención al cliente de VMC (vmcsubastas.com, subasta de autos).
Un chatbot con IA (Gemini) resuelve preguntas frecuentes con RAG sobre el Centro de Ayuda y el
catálogo HERALD; cuando no puede resolver, deriva ("handoff") a un asesor humano. Este panel es la
mitad humana de ese flujo: donde el asesor ve, toma y cierra los casos que la IA no pudo resolver
sola. Éxito = que un asesor pueda triar la cola y responder sin fricción, con contexto suficiente
(resumen de IA, motivo de derivación, datos del usuario) para no repetir preguntas que el bot ya
hizo.

## Positioning

A diferencia de una bandeja de soporte genérica, Subastín ya filtró y resumió el caso con IA antes
de que el asesor lo vea (clasificación + resumen + motivo de derivación), y el usuario conserva
una única conversación permanente con VMC (no un ticket nuevo cada vez) — el asesor entra a un hilo
con historial real, no a un caso aislado.

## Operating Context

- MVP en construcción: hoy el panel corre sobre datos mock (`src/lib/mock-data.ts`); no hay
  backend real conectado todavía (fase F1 del backend implementada, pipeline de IA y F5 de
  handoff pendientes — ver `../CLAUDE.md`).
- El asesor trabaja con **1 caso pendiente a la vez** de forma seria: tomar un caso es una acción
  explícita y atómica (RF-029), no un efecto de abrir el hilo; mientras no lo toma, es de solo
  lectura y cualquier otro asesor puede tomarlo primero.
- La bandeja combina señales de urgencia: tiempo de espera, no leídos, si ya tiene asesor
  asignado. El dashboard es la vista de arriba (volumen, pendientes, en atención, espera
  promedio) — mismas conversaciones, otro grosor de información.
- Uso probablemente de escritorio primero (trabajo de turno, texto largo), pero el layout ya
  tiene breakpoints mobile activos (RF-047) — no se puede asumir solo desktop.
- Reingesta de vuelta al mock/dev tras cada reinicio de contenedores (contexto del repo, no del
  panel en sí).

## Capabilities and Constraints

- Rol único `ADVISOR` en el MVP (RF-007); sin roles de supervisor/admin en esta fase.
- Máximo 1 conversación activa por usuario final, máximo 5 tickets activos por usuario (D-002) —
  el asesor puede ver varios tickets abiertos de la misma persona en el mismo hilo.
- Métricas exactas del dashboard **sin definir** (D-013 abierta) — el set actual (volumen,
  pendientes, en atención, cerradas, casos derivados, espera promedio) es un mínimo tomado del
  spec, no el final.
- Campos de usuario visibles en el panel contextual **sin definir en su totalidad** (D-010
  abierta) — hoy solo nombre/correo/empresa/ID VMC porque son los únicos que existen en el
  modelo de datos.
- Sin canal de notificación push nativo del navegador: la actualización es por polling (TD-001,
  2.5s hilo abierto / 15s cerrado).
- Datos VMC (perfil del comprador) son de **solo lectura** desde este panel (RF-051).

## Brand Commitments

- Nombre del producto/asistente: **Subastín**. Identidad visual: sistema de diseño **Concorde**
  de VMC/Subastop (`src/concorde/`) — tipografía Plus Jakarta Sans, paleta con violeta "vault"
  (`#8460E5`/`#3B1782` como acento primario/marca), naranja (`#ED8936`, estados de espera/alerta)
  y teal (`#00AEB1`, estado "en atención"). Estos tokens y los primitivos ya traídos (Button,
  Input, Table, AvatarZone, TabSelector) son el vocabulario visual a **reciclar**, no a
  reemplazar — así lo pidió el usuario explícitamente para este trabajo de UX.
- Fondo de página `#f7f7fb`, texto principal `#191C1C` — ya establecidos en `globals.css`.

## Evidence on Hand

- Único activo real: el código y los componentes Concorde ya integrados. No hay research de
  usuario, entrevistas a asesores ni benchmarks — cualquier afirmación sobre "lo que el asesor
  necesita" en trabajo futuro debe basarse en el spec (RF/AC de `REQUERIMENTS.md`) y en el
  comportamiento ya implementado, no inventarse.
- Los comentarios en cada página (`RF-xxx`, `D-xxx`) documentan qué está resuelto y qué sigue
  abierto — son la fuente de verdad más confiable dentro del propio código.

## Product Principles

1. La IA hace el primer filtro; el asesor nunca debería repetir trabajo que el bot ya hizo
   (resumen, motivo, clasificación) — la UI debe exponer ese contexto de inmediato, no esconderlo.
2. Tomar un caso es una acción deliberada y visible, nunca implícita — la UI debe dejar clarísimo
   quién es dueño de cada conversación en todo momento.
3. La urgencia (espera, no leídos, pendiente sin tomar) es la señal más importante de la bandeja
   y del dashboard — debe ganarle a cualquier otro adorno visual en jerarquía.
4. El sistema de diseño Concorde es la identidad de marca compartida con el resto de VMC/Subastop
   — se extiende y se le saca más partido, no se fragmenta con un estilo paralelo.
5. Es una herramienta de trabajo de uso repetido y prolongado (turnos), no una superficie de
   marketing — la velocidad de escaneo y la baja fatiga visual pesan más que el impacto de una
   primera impresión.

## Accessibility & Inclusion

Sin requisito específico de producto documentado más allá de los estándares generales ya
aplicados en el código (`focus-visible`, contraste corregido en QA previa — commit
`57fa5f0`). Mantener ese nivel; no se ha establecido un estándar formal (WCAG AA, etc.) por
decisión de negocio.

"""Backend Subastin — monolito modular desplegado en Lambdas (PLAN.md §2-3).

Regla de dependencias EN UNA SOLA DIRECCION (igual que la v0, hace imposible el import circular):

    api/ · workers/                  ← ENTRADAS (HTTP y SQS): componen, sin logica de negocio
        │
        ▼
    conversations ◄── tickets        ← DOMINIO (tickets importa conversations, JAMAS al reves)
    advisors                           advisors es hoja de dominio
        │
        ▼
    agent · catalog · notifications · images   ← INTEGRACIONES hoja: no importan dominio;
        │                                        reciben/devuelven datos planos
        ▼
    core                             ← config, clients AWS, auth: no importa a nadie

- El dominio NUNCA llama a una integracion: la composicion (p.ej. el pipeline IA) vive en la
  entrada que la necesita (workers/ai_worker.py), porque cada flujo tiene UN solo consumidor.
- Cada repository es el UNICO lugar que conoce claves/GSIs de su tabla.
- Forma de cada tipo de paquete: el DOMINIO lleva `models.py` (Pydantic), `repository.py`
  (claves/GSIs) y `service.py` (reglas), mas modulos puros como `forms.py` o `taxonomy.py`;
  una INTEGRACION son modulos sueltos que reciben y devuelven datos planos (`client.py` cuando
  envuelve un SDK); una ENTRADA es `main.py` + `routers/` o un `*_worker.py`. `core` guarda lo
  transversal (config, clientes AWS, auth, reloj, jobs, llm, observabilidad) y las libs que
  varios importan: `text` (normalizar, lexicos), `ids` (uuid5), `dynamo` (modelo base y
  transacciones), `metadata` (contrato de `Message.metadata` con el widget) y `counters`
  (tabla RateLimits). Antes de escribir un helper `_foo`, buscar ahi.
"""

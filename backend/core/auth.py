"""Dependencies de identidad para FastAPI.

- get_chat_user(): identidad del widget — VMC autenticado o sesion anonima.
  BLOQUEADO POR D-001 (mecanismo VMC↔Subastin) y D-018 (sesion anonima). NO implementar antes.
- get_advisor(): el JWT ya lo valido el authorizer de Cognito EN API GATEWAY (T1); aqui solo se
  leen los claims del event (request.scope) y se resuelve el advisor via advisors.repository
  (GSI cognito_sub).

RNF-005: jamas confiar en un user_id enviado libremente por el frontend.
"""

# TODO F1/F5: dependencies — definir al cerrar D-001.

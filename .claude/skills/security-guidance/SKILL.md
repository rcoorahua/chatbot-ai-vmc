---
name: security-guidance
description: Guía de seguridad de Subastín y documentación del hook PreToolUse que bloquea anti-patrones (command injection, XSS, eval, pickle, shell=True, workflows de GitHub Actions inseguros) antes de escribirlos. Usar al tocar código sensible (auth, identidad, presigned URLs, workers, workflows), al recibir un aviso del hook de seguridad, o cuando se mencione seguridad, vulnerabilidad, inyección o XSS.
---

# Security Guidance (hook + reglas del repo)

## El hook (ya instalado)

`.claude/hooks/security_reminder_hook.py` corre como **PreToolUse** antes de cada Edit/Write
(wiring en `.claude/settings.json`). Si el contenido a escribir contiene un anti-patrón
conocido, bloquea la escritura una vez y muestra la advertencia; en el mismo archivo+regla+sesión
no vuelve a molestar. Origen: plugin MIT de David Dworken (via alirezarezvani/claude-skills),
adaptado: se quitó el substring genérico `.format(` (falso positivo masivo en Python; aquí no
hay SQL) y se dejó el resto verbatim.

Patrones: workflows de GitHub Actions con `${{ }}` de inputs no confiables · `exec`/`execSync`
· `new Function` · `eval(` · `dangerouslySetInnerHTML` · `document.write` · `.innerHTML =` ·
`pickle` · `os.system` · `shell=True` · f-string SQL · `yaml.load` sin SafeLoader.

Si el hook bloquea algo legítimo: justificarlo con un comentario `# SAFETY: <por qué es seguro
aquí>` en el archivo y reintentar (la segunda pasa). Deshabilitar el hook solo con permiso
explícito del usuario (`ENABLE_SECURITY_REMINDER=0`).

## Reglas de seguridad propias de Subastín (el hook NO las ve — aplicarlas al diseñar)

1. **RNF-005**: jamás confiar en `user_id` u otra identidad enviada por el frontend; la
   identidad viene del mecanismo D-001 (VMC) o del JWT de Cognito validado por API Gateway.
2. **RF-051/052**: datos VMC solo lectura; el bot nunca expone información financiera,
   documentos, datos internos ni de otros usuarios. Todo campo nuevo visible requiere D-010.
3. **Secretos**: solo Secrets Manager en AWS y `.env` (no versionado) en dev. Nunca en código,
   logs, outputs de CDK ni variables de entorno en claro de las Lambdas.
4. **Presigned URLs** (images/): expiración corta, `Content-Type` y tamaño máximo validados al
   firmar (D-005), bucket con Block Public Access — nunca URLs públicas permanentes.
5. **Frontend**: renderizar mensajes de chat como texto (nunca HTML crudo — los usuarios y el
   bot escriben contenido no confiable); enlaces con `rel="noopener"`.
6. **Workers**: tratar el body de SQS como no confiable (validar con Pydantic antes de usar).
7. **Logs**: sin PII innecesaria (correos completos, tokens); ids sí, contenido sensible no.

## Cuándo escalar al usuario

Cualquier cambio que toque autenticación, autorización, manejo de PII o el contrato de
identidad D-001 se consulta antes de implementarse (regla de autonomía acotada de la skill
`spec-driven`).

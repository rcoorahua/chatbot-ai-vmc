"""images — imagenes del chat en S3 (RF-040..043). Integracion HOJA.

Presigned URL de subida (con limites de tamano/tipo → D-005), presigned GET para visualizar,
metadata para Messages.attachment (la imagen JAMAS va a DynamoDB). Resize/compresion para IA
→ D-015 (RNF-008: no enviar originales innecesariamente a la IA).
"""

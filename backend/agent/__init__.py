"""agent — todo lo de IA (heredero de `agente` de la v0, expandido al pipeline del MVP).

Integracion HOJA: como en la v0, NO importa dominio — recibe el historial como lista de dicts
planos y devuelve resultados; la conversion y la composicion las hace quien lo llama
(workers/ai_worker.py). Duenio tambien de la tabla AIUsage (registra sus propias ejecuciones).

Piezas: classifier (Haiku), writer (Gemini), rag (Pinecone), prompts, usage.
"""

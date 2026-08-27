"""Sube a Pinecone los chunks generados por `scripts.helpcenter_fetch`.

    python -m scripts.helpcenter_upload
    python -m scripts.helpcenter_upload --verify "cuanto es la comision"
    python -m scripts.helpcenter_upload --replace      # borra el namespace antes de subir

Requiere `PINECONE_API_KEY` en `.env` (en AWS: Secrets Manager). No usa Gemini ni Anthropic:
el indice tiene **embedding integrado**, asi que Pinecone convierte el texto en vectores.

Crea el indice si no existe, con el mismo modelo que espera `backend/agent/rag.py`. Que lo cree
este script y no una consola web evita el error silencioso de consultar un indice creado con
otro modelo de embeddings.

`--replace` existe porque el upsert es aditivo: si una pregunta del Centro de Ayuda cambia de
texto, su id cambia y el vector viejo se queda en el indice respondiendo con contenido
desactualizado. Para un refresco completo conviene borrar el namespace y volver a subir.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS_PATH = ROOT / "data" / "helpcenter" / "chunks.json"

# Tope de registros por llamada de la inferencia integrada de Pinecone.
BATCH_SIZE = 96
EMBEDDING_MODEL = "multilingual-e5-large"


def _settings():
    # Import perezoso: el script se puede leer y testear sin cargar el backend entero.
    from backend.core.config import get_settings

    return get_settings()


def _records(chunks: list[dict]) -> list[dict]:
    """Chunks al formato de `upsert_records`: `id` + `text` + los campos que la busqueda pide.

    `text` se llama asi porque es el campo que el `field_map` del indice embebe; renombrarlo
    dejaria los registros sin vector.
    """
    records = []
    for chunk in chunks:
        chunk_id, text = chunk.get("id"), (chunk.get("text") or "").strip()
        if not chunk_id or not text:
            continue
        records.append(
            {
                "id": chunk_id,
                "text": text[:30_000],  # limite por documento de la inferencia integrada
                "topic": chunk.get("topic", ""),
                "source_url": chunk.get("source_url", ""),
                "has_numeric_data": bool(chunk.get("has_numeric_data", False)),
            }
        )
    return records


def _ensure_index(pinecone, index_name: str):
    if not pinecone.has_index(index_name):
        print(f"Creando el indice '{index_name}' con el modelo {EMBEDDING_MODEL}...")
        pinecone.create_index_for_model(
            name=index_name,
            cloud="aws",
            region="us-east-1",  # misma region que el resto del stack
            embed={"model": EMBEDDING_MODEL, "field_map": {"text": "text"}},
        )
        # El indice tarda unos segundos en aceptar escrituras despues de crearse.
        import time

        for _ in range(30):
            if pinecone.describe_index(index_name).status.get("ready"):
                break
            time.sleep(2)
    return pinecone.Index(index_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sube el Centro de Ayuda a Pinecone")
    parser.add_argument("--verify", nargs="?", const="cuanto es la comision", default=None,
                        help="Consulta de prueba al terminar (imprime los scores)")
    parser.add_argument("--replace", action="store_true",
                        help="Borra el namespace antes de subir (refresco completo)")
    args = parser.parse_args()

    settings = _settings()
    if not settings.pinecone_api_key:
        sys.exit("Falta PINECONE_API_KEY en .env")
    if not CHUNKS_PATH.exists():
        sys.exit(f"No existe {CHUNKS_PATH}. Ejecuta antes: python -m scripts.helpcenter_fetch")

    chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8")).get("chunks", [])
    records = _records(chunks)
    if not records:
        sys.exit("No hay chunks que subir.")

    from pinecone import Pinecone

    pinecone = Pinecone(api_key=settings.pinecone_api_key)
    index = _ensure_index(pinecone, settings.pinecone_index_name)
    namespace = settings.pinecone_namespace

    if args.replace:
        print(f"Borrando el namespace '{namespace}'...")
        try:
            index.delete(delete_all=True, namespace=namespace)
        except Exception as error:  # noqa: BLE001 — si el namespace aun no existe, seguir
            print(f"  (nada que borrar: {error})")

    for start in range(0, len(records), BATCH_SIZE):
        batch = records[start : start + BATCH_SIZE]
        index.upsert_records(namespace=namespace, records=batch)
        print(f"Subidos {min(start + BATCH_SIZE, len(records))}/{len(records)}")

    print(f"\nListo: {len(records)} chunks en '{settings.pinecone_index_name}' / '{namespace}'.")

    if args.verify:
        _verify(args.verify, settings)


def _verify(question: str, settings) -> None:
    """Consulta de prueba. Imprime los scores para poder calibrar RAG_MIN_SCORE con datos.

    El umbral por defecto es una estimacion; el rango real depende del modelo y del contenido,
    y solo se conoce mirando estas cifras.
    """
    from backend.agent import rag

    rag.reset_index()
    print(f"\nConsulta de prueba: {question!r}")
    fragments = rag.search(question, min_score=0.0)  # sin corte: interesa el rango completo
    if not fragments:
        print("  sin resultados")
        return
    for fragment in fragments:
        print(f"  {fragment.score:.3f}  {fragment.topic[:60]}")
    print(
        f"\nRAG_MIN_SCORE actual: {settings.rag_min_score}. "
        f"Ajustalo en .env si el corte no separa lo relevante de lo que no lo es."
    )


if __name__ == "__main__":
    main()

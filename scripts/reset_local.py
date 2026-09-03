"""Reinicia el entorno local a un estado limpio SIN tocar los contenedores de Docker: trunca
(borra y recrea) las 6 tablas de DynamoDB, purga las 2 colas de SQS y vuelve a cargar el
dataset de prueba.

    python -m scripts.reset_local

Hace lo mismo que `docker compose restart` + `local_setup` + `seed_data`, pero sin reiniciar
los contenedores: mas rapido (no hay que esperar a que dynamodb-local y localstack vuelvan a
levantar) y no interrumpe nada que dependa de que sigan arriba.

NO hace falta reiniciar el worker de IA (`python -m scripts.run_ai_worker`): no guarda estado
entre jobs (cada uno vive y muere en `_process`, backend/workers/ai_worker.py), y un job para
una conversacion que ya no existe se loguea como aviso y se descarta sin reintentar. Purgar la
cola aqui es solo para no ver esos avisos de jobs viejos en su terminal.
"""

from botocore.exceptions import ClientError

from scripts.local_setup import (
    cliente_dynamo,
    cliente_sqs,
    crear_colas_y_bucket,
    crear_tablas,
    definiciones_de_tabla,
    nombres_de_cola,
)
from scripts.seed_data import cargar


def borrar_tablas(verbose: bool = True) -> None:
    """Borra las 6 tablas si existen. Idempotente, igual que crear_tablas."""
    cliente = cliente_dynamo()
    for definicion in definiciones_de_tabla():
        nombre = definicion["TableName"]
        try:
            cliente.delete_table(TableName=nombre)
            cliente.get_waiter("table_not_exists").wait(TableName=nombre)
            if verbose:
                print(f"  tabla borrada: {nombre}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                if verbose:
                    print(f"  tabla no existia: {nombre}")
            else:
                raise


def purgar_colas(verbose: bool = True) -> None:
    """Vacia ai-jobs y notifications, incluidos los mensajes retrasados (DelaySeconds, D-020)
    que `receive_message` no puede ver y por eso el worker tampoco puede drenar por su cuenta.
    """
    try:
        sqs = cliente_sqs()
    except Exception as e:  # noqa: BLE001 — LocalStack caido no debe tumbar el reset de Dynamo
        if verbose:
            print(f"  AVISO: no se pudo conectar a SQS ({type(e).__name__}); se omiten las colas")
        return
    for cola in nombres_de_cola():
        try:
            url = sqs.get_queue_url(QueueName=cola)["QueueUrl"]
            sqs.purge_queue(QueueUrl=url)
            if verbose:
                print(f"  cola purgada: {cola}")
        except ClientError as e:
            codigo = e.response["Error"]["Code"]
            if codigo == "AWS.SimpleQueueService.NonExistentQueue":
                if verbose:
                    print(f"  cola no existia todavia: {cola}")
            elif codigo == "AWS.SimpleQueueService.PurgeQueueInProgress":
                # Limite real de SQS: una purga por minuto por cola. Si se corre el reset dos
                # veces seguidas muy rapido, la segunda cae aqui — no es un error, sigue vacia.
                if verbose:
                    print(f"  cola {cola}: purgada hace poco (limite de 60s de SQS), sigue vacia")
            else:
                if verbose:
                    print(f"  AVISO: no se pudo purgar {cola} ({codigo})")


def main() -> None:
    print("Reiniciando el entorno local (sin tocar Docker)...")
    borrar_tablas()
    crear_tablas()
    crear_colas_y_bucket(verbose=False)  # ya quedaron listas arriba si no existian
    purgar_colas()
    cargar()
    print("Listo: tablas recreadas, colas purgadas y dataset de prueba cargado de nuevo.")


if __name__ == "__main__":
    main()

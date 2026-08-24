"""Clients boto3 (DynamoDB, SQS, S3) creados una vez a nivel de modulo (se reusan entre
invocaciones de la Lambda). `endpoint_url` solo se pasa cuando Settings lo trae (dev local:
dynamodb-local:8001, localstack:4566); en AWS queda None y boto3 resuelve solo.
"""

# TODO F1: factories de clients/resources — definir al arrancar la implementacion.

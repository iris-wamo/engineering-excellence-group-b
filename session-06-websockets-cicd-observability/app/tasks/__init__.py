"""Background task definitions and Celery workers.

Task modules are registered through `include=[...]` in app.core.celery_app, so nothing is
imported here: importing any app.tasks.* module must not build the Celery app eagerly.
"""

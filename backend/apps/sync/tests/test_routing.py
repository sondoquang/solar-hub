"""Routing queue Celery: task do người dùng bấm đi queue "interactive",
task nền (beat) rơi về queue mặc định "periodic" — xem CELERY_TASK_ROUTES."""

import pytest

from config.celery import app

INTERACTIVE = [
    "apps.sync.tasks.push_all_products",
    "apps.sync.tasks.push_products_batch_task",
    "apps.sync.tasks.pull_all_categories",
    "apps.sync.tasks.pull_categories_batch_task",
]
PERIODIC = [
    "apps.sync.tasks.poll_all_orders",
    "apps.sync.tasks.poll_sites_batch_task",
    "apps.monitoring.tasks.check_all_sites",
    "apps.monitoring.tasks.check_hosting_task",
]


@pytest.mark.parametrize("name", INTERACTIVE)
def test_user_triggered_sync_routes_to_interactive(name):
    assert app.amqp.router.route({}, name)["queue"].name == "interactive"


@pytest.mark.parametrize("name", PERIODIC)
def test_background_tasks_route_to_periodic_default(name):
    assert app.amqp.router.route({}, name)["queue"].name == "periodic"

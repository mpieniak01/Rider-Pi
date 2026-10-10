"""Inventory the instantiated Flask rules without invoking any runtime handler."""

import json
from pathlib import Path

from services.api_core.contract_registry import contract_for
from services.api_server import app


def test_actual_routes_have_domain_contracts_and_export_inventory():
    rows = []
    for rule in app.url_map.iter_rules():
        contract = contract_for(rule.rule)
        rows.append(
            {
                "rule": rule.rule,
                "methods": sorted(rule.methods),
                "endpoint": rule.endpoint,
                "contract_id": contract.name,
                "contract_version": contract.version,
            }
        )
        if rule.rule.startswith(("/api/", "/svc", "/vision/", "/camera/", "/face/")):
            assert contract.name != "rider.http", rule.rule
    output = Path("/tmp/rider-pi-contract-routes.json")
    output.write_text(json.dumps(sorted(rows, key=lambda row: row["rule"]), indent=2), encoding="utf-8")
    paths = {row["rule"] for row in rows}
    assert {"/api/vision/obst", "/vision/obst", "/api/logic/catalog", "/api/services/graph"} <= paths


def test_negotiated_404_and_unknown_version_do_not_reach_real_handlers():
    with app.test_client() as client:
        headers = {"Accept": "application/vnd.rider.api+json;version=1"}
        response = client.get("/api/not-a-route", headers=headers)
        assert response.status_code == 404 and response.get_json()["error"]["code"] == "not_found"
        response = client.post(
            "/api/safety", json={"action": "arm"}, headers={"Accept": "application/vnd.rider.api+json;version=99"}
        )
        assert response.status_code == 406

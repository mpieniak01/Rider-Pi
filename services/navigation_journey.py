"""Explicit continuous journey admission, reusing bounded trial preparation."""

from __future__ import annotations

from services.navigation_trial import NavigationTrial, TrialError, validate_request


def validate_journey_request(payload, now):
    if (
        not isinstance(payload, dict)
        or type(payload.get("journey_version")) is not int
        or payload["journey_version"] != 1
        or type(payload.get("operator_control_version")) is not int
        or payload["operator_control_version"] != 1
        or not isinstance(payload.get("panel_id"), str)
        or not payload["panel_id"].strip()
    ):
        raise TrialError("navigation_journey_invalid", 400)
    if any(char.isspace() for char in str(payload.get("request_id", ""))):
        raise TrialError("navigation_journey_invalid", 400)
    body = validate_request({key: value for key, value in payload.items() if key != "journey_version"}, now)
    return {**body, "journey_version": 1}


class NavigationJourney(NavigationTrial):
    def start(self, payload):
        from services.navigation_trial_preparation import TrialPreparation

        body = validate_journey_request(payload, self.wall())
        accepted_at = self.clock()
        arrival = self.safety()
        return TrialPreparation(self, body, arrival, accepted_at).run()

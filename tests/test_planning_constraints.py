from __future__ import annotations

import unittest

from app.core.planning_constraints import (
    compatibility_preferences,
    constraint_directive,
    constraints_for_prompt,
)
from app.planning.nodes import finalize_node
from app.planning.runtime_worker import snapshot_to_state
from app.planning.schemas import TravelPlanState


class PlanningConstraintPipelineTests(unittest.TestCase):
    def test_snapshot_maps_dates_budget_and_structured_constraints(self):
        snapshot = {
            "query": "东京三日游",
            "destination": "东京",
            "start_date": "2026-09-01",
            "end_date": "2026-09-03",
            "days": 3,
            "trip_budget": "5000 元",
            "effective_constraints": [{
                "id": "memory:f1", "fact_id": "f1", "category": "dietary_requirement",
                "value_text": "避开花生", "polarity": "require", "source": "long_term_memory",
            }],
            "constraint_coverage": [{
                "constraint_id": "memory:f1", "fact_id": "f1",
                "category": "dietary_requirement", "status": "unverified",
                "stages": ["meal_search", "meal_recommend"],
            }],
        }
        state = snapshot_to_state(snapshot)
        self.assertEqual(state.travel_start_date.isoformat(), "2026-09-01")
        self.assertEqual(state.trip_budget, "5000 元")
        self.assertEqual(state.effective_constraints[0]["fact_id"], "f1")

    def test_compatibility_projection_feeds_existing_planner_fields(self):
        fields = compatibility_preferences([
            {"category": "attraction_preference", "value_text": "喜欢博物馆", "polarity": "prefer"},
            {"category": "dietary_requirement", "value_text": "避开花生", "polarity": "require"},
            {"category": "accessibility_need", "value_text": "尽量少走楼梯", "polarity": "prefer"},
        ])
        self.assertEqual(fields["attraction_preference"], "优先考虑：喜欢博物馆")
        self.assertEqual(fields["food_preference"], "必须满足：避开花生")
        self.assertEqual(fields["habit_preference"], "优先考虑：尽量少走楼梯")

    def test_avoid_constraint_becomes_an_explicit_planning_directive(self):
        constraint = {
            "category": "attraction_preference", "value_text": "老门东",
            "polarity": "avoid", "source": "long_term_memory",
        }
        self.assertEqual(constraint_directive(constraint), "必须避开：老门东")
        self.assertIn("必须避开：老门东", constraints_for_prompt([constraint]))
        fields = compatibility_preferences([constraint])
        self.assertEqual(fields["attraction_preference"], "必须避开：老门东")

    def test_final_plan_preserves_coverage_and_does_not_pretend_to_search_hotels(self):
        state = TravelPlanState(
            query="京都两日游", destination="京都", days=2,
            effective_constraints=[{
                "id": "memory:hotel", "fact_id": "hotel", "category": "accommodation_preference",
                "value_text": "偏好安静住宿", "polarity": "prefer", "source": "long_term_memory",
            }],
            constraint_coverage=[{
                "constraint_id": "memory:hotel", "fact_id": "hotel",
                "category": "accommodation_preference", "status": "advisory", "stages": ["finalize"],
            }],
        )
        plan = finalize_node(state)["final_plan"]
        self.assertEqual(plan["constraint_coverage"][0]["status"], "advisory")
        self.assertIn("未接入酒店搜索", plan["planning_notes"][0])
        self.assertNotIn("hotel", plan)


if __name__ == "__main__":
    unittest.main()

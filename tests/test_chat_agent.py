from __future__ import annotations

import unittest
import json
from pathlib import Path

from pydantic import ValidationError

from app.chat.graph import dialogue_agent_node
from app.chat.models import DialogueDecision, DialogueUnderstandingError
from app.chat.prompts import dialogue_messages


class FakeStructuredLlm:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class ChatAgentTests(unittest.IsolatedAsyncioTestCase):
    def _context(self, message="明天南京3日游"):
        return {
            "today": "2026-07-23",
            "timezone": "Asia/Shanghai",
            "current_message": message,
            "history": [],
            "planning_brief": None,
            "available_targets": [],
            "explicit_target": {"run_id": None, "itinerary_id": None},
        }

    def test_decision_schema_rejects_unknown_actions_and_fields(self):
        with self.assertRaises(ValidationError):
            DialogueDecision.model_validate({"intent": "invent_action", "reply": "x"})
        with self.assertRaises(ValidationError):
            DialogueDecision.model_validate(
                {"intent": "general_chat", "reply": "x", "untrusted": True}
            )

    def test_prompt_tells_the_model_not_to_repeat_missing_field_questions(self):
        system, _human = dialogue_messages(self._context("不告诉你"))
        self.assertIn("不得原样重复上一轮的追问", system[1])
        self.assertIn("brief_patch 为空", system[1])

    def test_chinese_dialogue_evaluation_fixture_has_actionable_semantics(self):
        cases = json.loads(
            (Path(__file__).parent / "data" / "dialogue_eval_cases.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertGreaterEqual(len(cases), 8)
        for case in cases:
            with self.subTest(case=case["name"]):
                decision = DialogueDecision(
                    intent=case["intent"], reply="测试回复", brief_patch=case["patch"]
                )
                self.assertEqual(decision.intent, case["intent"])
                self.assertEqual(
                    decision.brief_patch.model_dump(exclude_none=True), case["patch"]
                )

    async def test_one_structured_llm_decision_drives_nanjing_trip(self):
        llm = FakeStructuredLlm([
            {
                "intent": "create_plan",
                "reply": "好的，我先整理南京三日游。",
                "brief_patch": {
                    "destination": "南京",
                    "start_date": "2026-07-24",
                    "end_date": "2026-07-26",
                    "days": 3,
                },
            }
        ])
        result = await dialogue_agent_node({"dialogue_context": self._context()}, llm=llm)
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(result["decision"]["intent"], "create_plan")
        self.assertEqual(result["decision"]["brief_patch"]["destination"], "南京")
        self.assertEqual(result["decision"]["brief_patch"]["start_date"], "2026-07-24")

    async def test_chinese_natural_language_contracts_preserve_structured_semantics(self):
        """Lock down the semantic contracts supplied by the structured LLM.

        These cases deliberately use Chinese expressions that a keyword or regex
        classifier is likely to mishandle.  The fake model represents the
        provider's validated structured answer; this test verifies that the
        dialogue graph sends the complete trusted context once and preserves all
        semantic fields without replacing them with local text heuristics.
        """
        cases = [
            {
                "name": "省略介词与相对日期",
                "message": "明天南京3日游",
                "decision": {
                    "intent": "create_plan",
                    "reply": "我先整理从明天开始的南京三日游需求。",
                    "brief_patch": {
                        "destination": "南京",
                        "start_date": "2026-07-24",
                        "end_date": "2026-07-26",
                        "days": 3,
                    },
                },
            },
            {
                "name": "口语节日日期",
                "message": "国庆前一天去泉州，玩四天",
                "decision": {
                    "intent": "create_plan",
                    "reply": "已记下 9 月 30 日出发的泉州四日游。",
                    "brief_patch": {
                        "destination": "泉州",
                        "start_date": "2026-09-30",
                        "end_date": "2026-10-03",
                        "days": 4,
                    },
                },
            },
            {
                "name": "多轮补充不丢失已有字段",
                "message": "预算三千，吃清淡一点",
                "context": {
                    "history": [
                        {"role": "user", "content": "帮我做南京三日游"},
                        {"role": "assistant", "content": "好的，先记录南京三日游。"},
                    ],
                    "planning_brief": {
                        "id": "brief-nanjing",
                        "status": "collecting",
                        "data": {"destination": "南京", "days": 3},
                    },
                },
                "decision": {
                    "intent": "update_brief",
                    "reply": "已补充预算和饮食偏好，南京三日游信息会保留。",
                    "brief_patch": {"budget": "3000元左右", "food_preference": "清淡"},
                },
            },
            {
                "name": "纠正目的地只覆盖被纠正字段",
                "message": "不去南京了，改成都",
                "context": {
                    "planning_brief": {
                        "id": "brief-nanjing",
                        "status": "collecting",
                        "data": {"destination": "南京", "days": 3, "budget": "3000元左右"},
                    },
                },
                "decision": {
                    "intent": "update_brief",
                    "reply": "好的，目的地改为成都，其余需求不变。",
                    "brief_patch": {"destination": "成都"},
                },
            },
            {
                "name": "旅行咨询不创建规划需求",
                "message": "十月适合去云南吗？",
                "decision": {
                    "intent": "travel_qa",
                    "reply": "适合，十月云南天气舒适，但早晚温差较大。",
                },
            },
            {
                "name": "拒绝补充日期时不重复追问",
                "message": "不告诉你",
                "context": {
                    "history": [
                        {"role": "assistant", "content": "请问什么时候出发，玩几天呢？"},
                    ],
                    "planning_brief": {
                        "id": "brief-yunnan",
                        "status": "collecting",
                        "data": {"destination": "云南"},
                        "missing_fields": ["start_date", "end_date"],
                    },
                },
                "decision": {
                    "intent": "general_chat",
                    "reply": "没关系，云南这趟需求我会保留；等你愿意再定日期时告诉我就行。现在也可以聊聊云南怎么玩。",
                },
            },
            {
                "name": "已有行程的自然语言修改",
                "message": "第三天下午留给休息",
                "context": {
                    "available_targets": [
                        {
                            "run_id": "run-nanjing",
                            "itinerary_id": "itinerary-nanjing",
                            "kind": "travel_plan",
                            "status": "succeeded",
                            "destination": "南京",
                        }
                    ],
                },
                "decision": {
                    "intent": "modify_itinerary",
                    "reply": "好的，会把第三天下午调整为休息时间。",
                    "target": {"itinerary_id": "itinerary-nanjing"},
                    "modification_notes": "第三天下午留给休息，不安排景点或交通。",
                },
            },
            {
                "name": "唯一任务的停止控制",
                "message": "把正在规划的那个停掉",
                "context": {
                    "available_targets": [
                        {
                            "run_id": "run-active",
                            "itinerary_id": None,
                            "kind": "travel_plan",
                            "status": "running",
                            "destination": "南京",
                        }
                    ],
                },
                "decision": {
                    "intent": "run_control",
                    "reply": "好的，正在进行的南京规划会停止。",
                    "target": {"run_id": "run-active"},
                    "run_action": "cancel",
                },
            },
            {
                "name": "多个任务时必须澄清",
                "message": "把刚才那个停掉",
                "context": {
                    "available_targets": [
                        {"run_id": "run-nanjing", "itinerary_id": None, "kind": "travel_plan", "status": "running", "destination": "南京"},
                        {"run_id": "run-chengdu", "itinerary_id": None, "kind": "travel_plan", "status": "running", "destination": "成都"},
                    ],
                },
                "decision": {
                    "intent": "unclear",
                    "reply": "目前有两个规划任务，请告诉我要停止哪一个。",
                    "clarification": {
                        "field": "target",
                        "question": "要停止南京规划还是成都规划？",
                        "options": ["南京规划", "成都规划"],
                    },
                    "requires_confirmation": True,
                },
            },
        ]

        for case in cases:
            with self.subTest(case=case["name"]):
                context = self._context(case["message"])
                context.update(case.get("context", {}))
                llm = FakeStructuredLlm([case["decision"]])

                result = await dialogue_agent_node({"dialogue_context": context}, llm=llm)

                self.assertEqual(len(llm.calls), 1)
                self.assertIn(case["message"], llm.calls[0][-1][1])
                self.assertIn("available_targets", llm.calls[0][-1][1])
                for key, expected in case["decision"].items():
                    actual = result["decision"][key]
                    if key in {"brief_patch", "target"}:
                        actual = {
                            field: value for field, value in actual.items() if value is not None
                        }
                    self.assertEqual(actual, expected)

    async def test_invalid_structured_response_gets_one_repair_attempt(self):
        llm = FakeStructuredLlm([
            {"intent": "not-valid", "reply": "x"},
            {"intent": "travel_qa", "reply": "十月的云南昼夜温差会比较大。"},
        ])
        result = await dialogue_agent_node({"dialogue_context": self._context("十月适合去云南吗？")}, llm=llm)
        self.assertEqual(result["decision"]["intent"], "travel_qa")
        self.assertEqual(len(llm.calls), 2)
        self.assertIn("重新输出", llm.calls[1][-1][1])

    async def test_two_failures_raise_safe_error_without_rule_fallback(self):
        llm = FakeStructuredLlm([RuntimeError("provider down"), None])
        with self.assertRaises(DialogueUnderstandingError) as raised:
            await dialogue_agent_node({"dialogue_context": self._context()}, llm=llm)
        self.assertEqual(raised.exception.public_message, "这条消息暂时没有理解成功，请重试")
        self.assertEqual(len(llm.calls), 2)

    async def test_connection_failure_has_actionable_public_message(self):
        class APIConnectionError(RuntimeError):
            pass

        llm = FakeStructuredLlm([APIConnectionError("offline"), APIConnectionError("offline")])
        with self.assertRaises(DialogueUnderstandingError) as raised:
            await dialogue_agent_node({"dialogue_context": self._context()}, llm=llm)
        self.assertEqual(raised.exception.public_code, "llm_connection_failed")
        self.assertIn("网络或代理", raised.exception.public_message)

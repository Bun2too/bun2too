import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from evals.produce import execute, visible_completion, ROLES, isolation_environment


def content():
    return dict(campaign_plan='Synthetic educational campaign', requirements='Ground every claim',
        creative_brief='Concept only, not a rendered image', engineering_plan='Proposed schema checks',
        delivery_plan='Requires policy approval; no real publishing in this fixture',
        measurement_plan='Metrics are unavailable, not zero', blockers=[],
        articles=[dict(title='Schema validation and workflow review',
            body='The synthetic Example Relay 1.2 release adds JSON-schema validation and a manual approval step. '
                 'These features support reviewing workflow changes. Business results and certification are not supplied. '
                 'Operators should distinguish validation from evidence of business impact.',
            source_urls=['https://research.example.invalid/relay-1-2'])],
        posts=[dict(channel='facebook', text='Consider evidence and manual approval when reviewing workflow changes. #AI #Workflows #Data')])


def fake_builder(brief, record_task, social_only=False, record_event=None, evaluation_observer=None):
    from crewai_agents.app.models import MarketingArtifact
    flow = 'social' if social_only else 'scheduled' if brief.get('publishing_context', {}).get('scheduled') else 'manual'
    for role in ROLES[flow]:
        record_event('task_planned', agent=role, prompt='Synthetic task', expected_output='Structured deliverable')
    def kickoff():
        for role in ROLES[flow]:
            value = content() if role == 'delivery' else dict(approved_for_publication=role in {'editor', 'tester'},
                summary='Review grounded in supplied evidence', decisions=[], evidence=[], assumptions=[], risks=[],
                work_items=[], deliverable=json.dumps(content()))
            record_event('agent_started', agent=role)
            evaluation_observer(role, json.dumps(value), 'completed')
            record_task(role, json.dumps(value), value)
            record_event('agent_finished', agent=role, status='completed')
        return SimpleNamespace(pydantic=MarketingArtifact.model_validate(content()))
    return SimpleNamespace(kickoff=kickoff)


class EvaluationHarnessTests(unittest.TestCase):
    def test_real_workflows_and_publication_guards_with_offline_completions(self):
        for suite in ('component', 'trajectory'):
            for flow in ROLES:
                with self.subTest(suite=suite, flow=flow), patch.dict(os.environ, **isolation_environment(),
                        LLM_MODEL='openai/fixture-model', OPENAI_API_KEY='fixture-provider-key'):
                    result = execute(flow, suite, crew_factory=fake_builder)
                self.assertEqual([check for check in result['checks'] if not check['passed']], [])
                self.assertEqual(len(result['calls']), len(ROLES[flow]))
                self.assertNotIn('fixture-provider-key', json.dumps(result))

    def test_completion_selection_never_exports_reasoning(self):
        value = json.dumps(content())
        from crewai_agents.app.models import MarketingArtifact
        self.assertEqual(visible_completion('<think>private hidden reasoning ' + value + '</think>Final Answer: ' + value, 'delivery'), MarketingArtifact.model_validate(content()).model_dump())
        self.assertIsNone(visible_completion('<think>' + value + '</think>', 'delivery'))
        self.assertIsNone(visible_completion('Malformed or tool-only completion', 'writer'))

    def test_actual_pinned_model_adapter_calls_are_observed_and_production_is_opt_in(self):
        import httpx
        from openai import OpenAI
        from crewai_agents.app.crews import build_crew
        observed = []
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, **isolation_environment(),
                LLM_MODEL='gpt-4.1', OPENAI_API_KEY='fixture-provider-key', MODEL_ROUTING_ENABLED='false', CREWAI_STORAGE_DIR=directory), \
                patch('crewai_core.token_manager.TokenManager._get_secure_storage_path', return_value=Path(directory)):
            crew = build_crew({'channels': ['facebook']}, lambda *args: None,
                              evaluation_observer=lambda role, output, status: observed.append((role, output, status)))
            llm = crew.agents[0].llm
            def respond(request):
                return httpx.Response(200, json={'id':'fixture', 'object':'chat.completion', 'created':1,
                    'model':'fixture', 'choices':[{'index':0, 'message':{'role':'assistant', 'content':'visible completion'}, 'finish_reason':'stop'}]})
            llm._client = OpenAI(api_key='fixture-key', http_client=httpx.Client(transport=httpx.MockTransport(respond)))
            self.assertEqual(llm.call('fixture task'), 'visible completion')
            self.assertEqual(llm.call('format retry'), 'visible completion')
            self.assertEqual(observed, [('product_owner','visible completion','completed')]*2)
            normal = build_crew({'channels': ['facebook']}, lambda *args: None)
            self.assertNotEqual(normal.agents[0].llm.call.__name__, 'evaluated_call')

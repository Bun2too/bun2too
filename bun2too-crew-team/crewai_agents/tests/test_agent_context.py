import unittest
from crewai_agents.app.crews import role_context
from crewai_agents.app.model_routing import ROLES


class AgentContextTests(unittest.TestCase):
    def test_every_runtime_role_has_nonempty_context(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.assertTrue(role_context(role).strip())

    def test_external_input_cannot_select_arbitrary_file(self):
        with self.assertRaises(ValueError): role_context('../.env')

import unittest
from scripts.check_deployment import check


class DeploymentChecks(unittest.TestCase):
    def env(self, branch='qa'):
        target = 'production' if branch == 'main' else 'qa'
        return dict(GITHUB_REF_NAME=branch, DEPLOY_ENVIRONMENT=target,
                    TF_WORKSPACE='bun2too-' + target, TF_CLOUD_ORGANIZATION='example',
                    RAILWAY_API_TOKEN='test-token', TF_API_TOKEN='test-hcp',
                    POSTGRES_PASSWORD='test-password', RAILWAY_PROJECT_ID='project',
                    RAILWAY_ENVIRONMENT_ID=target, POSTGRES_SERVICE_ID='postgres',
                    CREWAI_SERVICE_ID='crewai')

    def request(self, url, token, payload=None):
        if 'app.terraform.io' in url:
            return {'data': {'attributes': {'execution-mode': 'local'}}}
        return {'data': {'project': {
            'environments': {'edges': [{'node': {'id': name, 'name': name}} for name in ['production', 'qa']]},
            'services': {'edges': [{'node': {'id': name}} for name in ['postgres', 'crewai']]},
        }}}

    def test_both_branches(self):
        for branch in ['main', 'qa']:
            check(self.env(branch), self.request)

    def test_qa_cannot_target_production(self):
        env = self.env()
        env['RAILWAY_ENVIRONMENT_ID'] = 'production'
        with self.assertRaisesRegex(ValueError, 'does not match'):
            check(env, self.request)

    def test_missing_secret_and_wrong_workspace(self):
        for key, value in [('POSTGRES_PASSWORD', '  '), ('RAILWAY_API_TOKEN', ''),
                           ('TF_WORKSPACE', 'bun2too-production')]:
            env = self.env()
            env[key] = value
            with self.assertRaises(ValueError):
                check(env, self.request)

    def test_unexpected_branch(self):
        with self.assertRaisesRegex(ValueError, 'mapping'):
            check(self.env('feature'), self.request)

    def test_foreign_service(self):
        env = self.env()
        env['CREWAI_SERVICE_ID'] = 'other-project-service'
        with self.assertRaisesRegex(ValueError, 'do not belong'):
            check(env, self.request)

    def test_remote_execution_rejected(self):
        def remote(*args):
            return {'data': {'attributes': {'execution-mode': 'remote'}}}
        with self.assertRaisesRegex(ValueError, 'Local'):
            check(self.env(), remote)


if __name__ == '__main__':
    unittest.main()

import unittest
import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from scripts.check_deployment import check, check_postgres_variables, request_json


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

    def test_http_errors_identify_api_and_status_without_secrets(self):
        for provider in ['HCP', 'Railway']:
            for status in [401, 403, 404, 429, 500]:
                def request(url, token, payload=None):
                    if provider == 'Railway' and 'app.terraform.io' in url:
                        return self.request(url, token, payload)
                    raise HTTPError(url, status, 'sensitive-response', {}, None)

                with self.subTest(provider=provider, status=status):
                    with self.assertRaisesRegex(ValueError, f'{provider}.*HTTP {status}') as exc:
                        check(self.env(), request)
                    self.assertNotIn('sensitive-response', str(exc.exception))

    def test_unexpected_responses_identify_api(self):
        for provider in ['HCP', 'Railway']:
            for response in [None, [], {}, {'data': None}]:
                def request(url, token, payload=None):
                    if provider == 'Railway' and 'app.terraform.io' in url:
                        return self.request(url, token, payload)
                    return response

                with self.subTest(provider=provider, response=response):
                    with self.assertRaisesRegex(ValueError, f'{provider}.*(JSON response|lookup failed)'):
                        check(self.env(), request)

    def test_missing_execution_mode_is_identified(self):
        with self.assertRaisesRegex(ValueError, "HCP.*missing field 'execution-mode'"):
            check(self.env(), lambda *args: {'data': {'attributes': {}}})

    def test_network_and_json_failures_do_not_leak_details(self):
        for error, expected in [
            (URLError('sensitive-response'), 'network/TLS/DNS'),
            (TimeoutError('sensitive-response'), 'timeout'),
            (json.JSONDecodeError('sensitive-response', 'secret-body', 0), 'not valid JSON'),
        ]:
            with self.subTest(error=type(error).__name__):
                with patch('scripts.check_deployment.urlopen', side_effect=error):
                    with self.assertRaisesRegex(ValueError, f'HCP.*{expected}') as exc:
                        check(self.env())
                self.assertNotIn('sensitive-response', str(exc.exception))
                self.assertNotIn('secret-body', str(exc.exception))

    def test_request_transport_matches_documented_curl(self):
        response = io.StringIO('{"data": {}}')
        with patch('scripts.check_deployment.urlopen', return_value=response) as open_url:
            request_json('https://app.terraform.io/api/v2/organizations/example/workspaces/bun2too-qa',
                         'test-hcp')
            request = open_url.call_args.args[0]
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(request.get_header('Authorization'), 'Bearer test-hcp')
        response = io.StringIO('{"data": {}}')
        payload = {'query': 'query($id: String!) { project(id: $id) { id } }',
                   'variables': {'id': 'project'}}
        with patch('scripts.check_deployment.urlopen', return_value=response) as open_url:
            request_json('https://backboard.railway.com/graphql/v2', 'test-token', payload)
            request = open_url.call_args.args[0]
            self.assertEqual(request.get_method(), 'POST')
            self.assertEqual(request.get_header('Authorization'), 'Bearer test-token')
            self.assertEqual(json.loads(request.data), payload)

    def test_progress_does_not_print_credentials(self):
        output = io.StringIO()
        with redirect_stdout(output):
            check(self.env(), self.request)
        self.assertIn('Passed HCP', output.getvalue())
        self.assertIn('Passed Railway', output.getvalue())
        for secret in ['test-token', 'test-hcp', 'test-password']:
            self.assertNotIn(secret, output.getvalue())

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

    def test_postgres_password_readback_scoped_to_selected_environment(self):
        for branch in ['main', 'qa']:
            env = self.env(branch)

            def request(url, token, payload):
                self.assertEqual(token, env['RAILWAY_API_TOKEN'])
                self.assertEqual(payload['variables'], {
                    'projectId': env['RAILWAY_PROJECT_ID'],
                    'environmentId': env['RAILWAY_ENVIRONMENT_ID'],
                    'serviceId': env['POSTGRES_SERVICE_ID'],
                })
                self.assertNotIn(env['POSTGRES_PASSWORD'], str(payload))
                return {'data': {'variablesForServiceDeployment': {
                    'POSTGRES_PASSWORD': env['POSTGRES_PASSWORD']}}}

            check_postgres_variables(env, request)

    def test_missing_empty_or_mismatched_railway_password(self):
        for password in [None, '', '  ', 'wrong-password']:
            with self.subTest(password=password), self.assertRaises(ValueError) as exc:
                check_postgres_variables(self.env(), lambda *args: {
                    'data': {'variablesForServiceDeployment': {'POSTGRES_PASSWORD': password}}})
            self.assertNotIn('wrong-password', str(exc.exception))
            self.assertNotIn(self.env()['POSTGRES_PASSWORD'], str(exc.exception))

    def test_postgres_api_errors_do_not_expose_response(self):
        for result in [
            {'errors': [{'message': 'sensitive-response'}], 'data': None},
            {'data': {'variablesForServiceDeployment': None}},
            {'data': {'variablesForServiceDeployment': 'sensitive-response'}},
        ]:
            with self.assertRaisesRegex(ValueError, 'lookup failed') as exc:
                check_postgres_variables(self.env(), lambda *args: result)
            self.assertNotIn('sensitive-response', str(exc.exception))

    def test_postgres_readback_requires_local_secret(self):
        env = self.env()
        env['POSTGRES_PASSWORD'] = ''
        with self.assertRaisesRegex(ValueError, 'Missing POSTGRES_PASSWORD'):
            check_postgres_variables(env, lambda *args: self.fail('must not call API'))


if __name__ == '__main__':
    unittest.main()

import json
import unittest
from unittest.mock import Mock, MagicMock
from scripts import deploy_n8n, report_deployment, check_deployment_scope


class WorkflowDeploymentTests(unittest.TestCase):
    def env(self):
        return dict(N8N_BASE_URL='https://n8n.example', N8N_API_KEY='secret', CREWAI_BASE_URL='https://crew.example',
                    N8N_MARKETING_CREDENTIAL_ID='credential-id', DEPLOY_ENVIRONMENT='qa', N8N_ACTIVATE_WORKFLOWS='true')

    def test_create_links_error_handler_and_activates_only_schedule(self):
        calls=[]
        saved={}
        def api(base,key,path,method='GET',payload=None):
            calls.append((path,method,payload))
            if path.startswith('/workflows?'): return {'data':[]}
            if method=='GET': return saved[path.split('/')[-1]]
            if path.endswith('/activate'):
                saved[path.split('/')[-2]]['active']=True
                return {}
            if method=='POST' and path=='/workflows':
                key='error-id' if 'errors' in payload['name'] else 'main-id'
                saved[key]=dict(payload,id=key,active=False)
                return {'id':key}
            return {}
        deploy_n8n.deploy(self.env(),api)
        creates=[c[2] for c in calls if c[:2]==('/workflows','POST')]
        self.assertEqual(len(creates),2)
        self.assertEqual(creates[1]['settings']['errorWorkflow'],'error-id')
        self.assertEqual([c[0] for c in calls if c[0].endswith('/activate')],['/workflows/main-id/activate'])
        self.assertNotIn('__CREWAI',json.dumps(creates))
        self.assertNotIn('secret',json.dumps(creates))
        for workflow in creates:
            names={n['name'] for n in workflow['nodes']}
            for source, outputs in workflow['connections'].items():
                self.assertIn(source,names)
                for output in outputs['main']:
                    for edge in output: self.assertIn(edge['node'],names)

    def test_update_deactivates_before_replacing_and_does_not_duplicate(self):
        calls=[]
        saved={}
        def api(base,key,path,method='GET',payload=None):
            calls.append((path,method))
            if path.startswith('/workflows?'):
                return {'data':[{'name':'Bun2too marketing errors (qa)','id':'error','active':False},
                                {'name':'[qa] Marketing daily operations','id':'main','active':True}]}
            if method=='GET': return saved[path.split('/')[-1]]
            if method=='PUT':
                key=path.split('/')[-1];saved[key]=dict(payload,id=key,active=False)
                return {'id':key}
            if path.endswith('/activate'): saved[path.split('/')[-2]]['active']=True
            return {}
        deploy_n8n.deploy(self.env(),api)
        self.assertNotIn(('/workflows','POST'),calls)
        self.assertLess(calls.index(('/workflows/main/deactivate','POST')), calls.index(('/workflows/main','PUT')))

    def test_activation_success_response_but_inactive_readback_fails(self):
        saved={}
        def api(base,key,path,method='GET',payload=None):
            if path.startswith('/workflows?'): return {'data':[]}
            if method=='GET': return saved[path.split('/')[-1]]
            if path=='/workflows':
                key='error' if 'errors' in payload['name'] else 'main'
                saved[key]=dict(payload,id=key,active=False)
                return {'id':key}
            return {}  # Simulate a successful activation request that did not activate.
        with self.assertRaisesRegex(ValueError,'not active'):
            deploy_n8n.deploy(self.env(),api)

    def test_full_deploy_rejects_missing_workflow_configuration(self):
        with self.assertRaisesRegex(ValueError,'N8N_API_KEY'):
            check_deployment_scope.check({'DEPLOY_OPERATION':'deploy'})
        env=dict(self.env(),MARKETING_API_KEY='test-key')
        self.assertIn('verified active',check_deployment_scope.check(env))
        env['N8N_ACTIVATE_WORKFLOWS']='false'
        with self.assertRaisesRegex(ValueError,'scheduled operation'):check_deployment_scope.check(env)
        env['N8N_ACTIVATE_WORKFLOWS']='true';env['MARKETING_DEPLOY_ENABLED']='false'
        with self.assertRaisesRegex(ValueError,'legacy'):check_deployment_scope.check(env)

    def test_explicit_infrastructure_and_import_do_not_require_app_secrets(self):
        for operation in ('infrastructure-only','import-state'):
            self.assertIn('does not install',check_deployment_scope.check({'DEPLOY_OPERATION':operation}))

    def test_rejects_missing_configuration_before_network_calls(self):
        request=Mock()
        with self.assertRaises(ValueError): deploy_n8n.deploy({},request)
        request.assert_not_called()

    def test_render_handles_literal_quotes_without_injecting_json(self):
        result=deploy_n8n.render({'name':'__DEPLOY_ENVIRONMENT__','settings':{},'nodes':[]},'https://example','id','qa"test','America/Chicago')
        self.assertEqual(result['name'],'qa"test')

    def test_ci_telemetry_excludes_environment_secrets(self):
        send=MagicMock();send.return_value.__enter__.return_value.status=202
        report_deployment.report({'DD_API_KEY':'dd-secret','TF_API_TOKEN':'tf-secret','DEPLOY_STATUS':'success'},send)
        request=send.call_args.args[0]
        self.assertNotIn(b'secret',request.data)
        self.assertIn(b'success',request.data)


if __name__ == '__main__': unittest.main()

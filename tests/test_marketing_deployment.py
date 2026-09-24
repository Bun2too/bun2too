import json
import unittest
from unittest.mock import Mock, MagicMock
from scripts import deploy_n8n, report_deployment


class WorkflowDeploymentTests(unittest.TestCase):
    def env(self):
        return dict(N8N_BASE_URL='https://n8n.example', N8N_API_KEY='secret', CREWAI_BASE_URL='https://crew.example',
                    N8N_MARKETING_CREDENTIAL_ID='credential-id', DEPLOY_ENVIRONMENT='qa', N8N_ACTIVATE_WORKFLOWS='true')

    def test_create_links_error_handler_and_activates_only_schedule(self):
        calls=[]
        def api(base,key,path,method='GET',payload=None):
            calls.append((path,method,payload))
            if method=='GET': return {'data':[]}
            if method=='POST' and path=='/workflows': return {'id': 'error-id' if 'errors' in payload['name'] else 'main-id'}
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
        def api(base,key,path,method='GET',payload=None):
            calls.append((path,method))
            if method=='GET':
                return {'data':[{'name':'Bun2too marketing errors (qa)','id':'error','active':False},
                                {'name':'[qa] Marketing daily operations','id':'main','active':True}]}
            return {'id': 'error' if 'errors' in (payload or {}).get('name','') else 'main'}
        deploy_n8n.deploy(self.env(),api)
        self.assertNotIn(('/workflows','POST'),calls)
        self.assertLess(calls.index(('/workflows/main/deactivate','POST')), calls.index(('/workflows/main','PUT')))

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

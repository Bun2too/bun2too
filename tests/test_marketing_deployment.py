import json
import unittest
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock, MagicMock
from scripts import deploy_n8n, report_deployment, check_deployment_scope


class WorkflowDeploymentTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required to execute n8n code nodes offline')
    def test_workflow_passes_results_then_fails_on_business_failure(self):
        workflow = json.loads((Path(__file__).resolve().parents[1] / 'n8n/marketing-operations.json').read_text())
        for operation in ('Generate daily campaign', 'Publish approved content', 'Collect Facebook results'):
            recorder = next(n for n in workflow['nodes'] if n['name'] == 'Record ' + operation)
            guard = next(n for n in workflow['nodes'] if n['name'] == 'Check ' + operation + ' outcome')
            expression = recorder['parameters']['jsonBody'][3:-3].strip()
            program = '''
const assert = require('node:assert/strict');
const data = JSON.parse(process.argv[1]);
const record = new Function('$json', '$execution', '$workflow', 'return (' + data.expression + ')');
const body = JSON.parse(record({status:'failed', run_id:'campaign-1'}, {id:516}, {name:'Marketing'}));
assert.equal(body.result.run_id, 'campaign-1');
assert.equal(body.result.status, 'failed');
assert.equal(body.operation, data.operation);
const guard = new Function('$input', data.code);
const input = result => ({first:()=>({json:result}), all:()=>[{json:result}]});
assert.throws(()=>guard(input({failed:true, reason:'Generation failed', run_ids:['campaign-1']})), /Generation failed.*campaign-1/);
assert.equal(guard(input({failed:false})).length, 1);
'''
            result = subprocess.run(['node', '-e', program, json.dumps({'expression': expression,
                'operation': operation, 'code': guard['parameters']['jsCode']})], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_credential_is_created_with_actual_key_and_reused_on_next_deploy(self):
        env = dict(self.env(), MARKETING_API_KEY='private-marketing-key', N8N_MARKETING_CREDENTIAL_ID='MARKETING_API_KEY')
        request = Mock(side_effect=[{'data': []}, {'id': 'actual-id'}])
        credential_id = deploy_n8n.marketing_credential(env, 'https://n8n.example', 'api-key', request)
        self.assertEqual(credential_id, 'actual-id')
        payload = request.call_args.args[4]
        self.assertEqual(payload['data'], {'name': 'Authorization', 'value': 'Bearer private-marketing-key'})
        self.assertEqual(payload['type'], 'httpHeaderAuth')
        request = Mock(side_effect=[{'data': [{'id': 'actual-id', 'name': 'Bun2too Marketing API (qa)', 'type': 'httpHeaderAuth'}]}, {}])
        self.assertEqual(deploy_n8n.marketing_credential(env, 'https://n8n.example', 'api-key', request), 'actual-id')
        self.assertEqual(request.call_args.args[2:4], ('/credentials/actual-id', 'PATCH'))

    def test_placeholder_without_key_fails_instead_of_installing_broken_reference(self):
        with self.assertRaisesRegex(ValueError, 'secret name is not a credential ID'):
            deploy_n8n.marketing_credential({'N8N_MARKETING_CREDENTIAL_ID': 'MARKETING_API_KEY'}, '', '', Mock())

    def env(self):
        return dict(N8N_BASE_URL='https://n8n.example', N8N_API_KEY='secret', CREWAI_BASE_URL='https://crew.example',
                    N8N_MARKETING_CREDENTIAL_ID='credential-id', DEPLOY_ENVIRONMENT='qa', N8N_ACTIVATE_WORKFLOWS='true')

    def test_create_links_error_handler_and_activates_only_schedule(self):
        calls=[]
        saved={}
        def api(base,key,path,method='GET',payload=None):
            calls.append((path,method,payload))
            if path.startswith('/credentials?'): return {'data': []}
            if path == '/credentials': return {'id': 'created-header-id'}
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
        deploy_n8n.deploy(dict(self.env(), MARKETING_API_KEY='private-marketing-key', N8N_MARKETING_CREDENTIAL_ID='MARKETING_API_KEY'),api)
        creates=[c[2] for c in calls if c[:2]==('/workflows','POST')]
        self.assertEqual(len(creates),2)
        self.assertEqual(creates[1]['settings']['errorWorkflow'],'error-id')
        self.assertEqual([c[0] for c in calls if c[0].endswith('/activate')],['/workflows/main-id/activate'])
        self.assertNotIn('__CREWAI',json.dumps(creates))
        self.assertNotIn('secret',json.dumps(creates))
        self.assertNotIn('private-marketing-key',json.dumps(creates))
        for workflow in creates:
            for node in workflow['nodes']:
                if 'httpHeaderAuth' in node.get('credentials', {}):
                    self.assertEqual(node['credentials']['httpHeaderAuth']['id'], 'created-header-id')
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

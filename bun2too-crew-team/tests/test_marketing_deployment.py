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
                key='error-id' if 'errors' in payload['name'] else ('health-id' if 'service health' in payload['name'] else 'main-id')
                saved[key]=dict(payload,id=key,active=False)
                return {'id':key}
            return {}
        deploy_n8n.deploy(dict(self.env(), MARKETING_API_KEY='private-marketing-key', N8N_MARKETING_CREDENTIAL_ID='MARKETING_API_KEY'),api)
        creates=[c[2] for c in calls if c[:2]==('/workflows','POST')]
        self.assertEqual(len(creates),3)
        self.assertEqual(creates[1]['settings']['errorWorkflow'],'error-id')
        self.assertEqual([c[0] for c in calls if c[0].endswith('/activate')],['/workflows/main-id/activate', '/workflows/health-id/activate'])
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
                                {'name':'[qa] Marketing daily operations','id':'main','active':True},
                                {'name':'Marketing service health (qa)','id':'health','active':True}]}
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


class OperationalWorkflowTests(unittest.TestCase):
    def test_optional_fallback_credentials_are_rendered_without_tokens(self):
        template = json.loads((Path(__file__).resolve().parents[1] / 'n8n/00-error-handler.json').read_text())
        env = {'ALERT_SLACK_CHANNEL': 'C123', 'ALERT_EMAIL_FROM': 'alerts@example.com', 'ALERT_EMAIL_TO': 'bun2too@gmail.com'}
        payload = deploy_n8n.render_alerts(template, {'slack':'slack-id','smtp':'smtp-id'}, env)
        serialized = json.dumps(payload)
        self.assertNotIn('__ALERT_', serialized)
        self.assertIn('slack-id', serialized)
        self.assertIn('smtp-id', serialized)
        self.assertEqual(next(n for n in payload['nodes'] if n['name']=='Record failure')['onError'], 'continueRegularOutput')
        for node in payload['nodes']:
            if 'fallback notification' in node['name']:
                self.assertEqual(node['onError'], 'continueRegularOutput')

    def test_no_fallback_nodes_reference_missing_credentials(self):
        template = json.loads((Path(__file__).resolve().parents[1] / 'n8n/00-error-handler.json').read_text())
        payload = deploy_n8n.render_alerts(template, {}, {})
        self.assertEqual(len(payload['nodes']), 2)
        names = {n['name'] for n in payload['nodes']}
        for outputs in payload['connections'].values():
            for edges in outputs['main']:
                for edge in edges:
                    self.assertIn(edge['node'], names)

    def test_alert_credentials_use_encrypted_store_only(self):
        request = Mock(side_effect=[{'data': []}, {'id': 'slack-credential'}, {'id': 'smtp-credential'}])
        env = {'ALERT_SLACK_BOT_TOKEN': 'private-slack', 'ALERT_SLACK_CHANNEL':'C123',
               'SMTP_HOST':'smtp.example.com','SMTP_PASSWORD':'private-smtp','ALERT_EMAIL_FROM':'alerts@example.com',
               'ALERT_EMAIL_TO':'bun2too@gmail.com'}
        result = deploy_n8n.alert_credentials(env, 'https://n8n.example', 'api-key', request)
        self.assertEqual(result, {'slack':'slack-credential','smtp':'smtp-credential'})
        self.assertEqual(request.call_args_list[1].args[4]['data']['value'], 'Bearer private-slack')
        self.assertEqual(request.call_args_list[2].args[4]['type'], 'smtp')

    @unittest.skipUnless(shutil.which('node'), 'Node is required for n8n JavaScript checks')
    def test_fallback_dedupes_channels_independently_and_detects_watchdog_failure(self):
        root = Path(__file__).resolve().parents[1]
        error = json.loads((root/'n8n/00-error-handler.json').read_text())
        operations = json.loads((root/'n8n/marketing-operations.json').read_text())
        codes = {n['name']: n['parameters']['jsCode'] for n in error['nodes']+operations['nodes']+json.loads((root/'n8n/service-health.json').read_text())['nodes'] if n['type']=='n8n-nodes-base.code'}
        program = r'''
const assert = require('node:assert/strict');
const codes = JSON.parse(process.argv[1]);
const input = data => ({first:()=>({json:data}),all:()=>[{json:data}]});
const source = {workflow:{id:'daily',name:'Daily'},execution:{lastNodeExecuted:'Generate daily campaign',id:'123'}};
const select = name => input(source);
let state = {};
const prepare = new Function('$input','$','$getWorkflowStaticData',codes['Prepare independent fallback']);
assert.deepEqual(prepare(input({recorded:true,notifications_managed:true}),select,()=>state),[]);
const notice = prepare(input({error:'API unavailable'}),select,()=>state)[0].json;
assert.ok(notice.text.includes('Primary alert service unavailable'));
const gate = name => new Function('$input','$getWorkflowStaticData',codes[name]);
const slack = gate('Gate slack fallback')(input(notice),()=>state)[0].json;
const remember = new Function('$input','$','$getWorkflowStaticData',codes['Remember Slack fallback']);
remember(input({ok:false}),()=>input(slack),()=>state);
assert.equal(gate('Gate slack fallback')(input(notice),()=>state).length,1);
remember(input({ok:true}),()=>input(slack),()=>state);
assert.equal(gate('Gate slack fallback')(input(notice),()=>state).length,0);
assert.equal(gate('Gate email fallback')(input(notice),()=>state).length,1);
const health = new Function('$input',codes['Check operational health']);
assert.throws(()=>health(input({enabled:false})),/watchdog/);
assert.throws(()=>health(input({enabled:true,watchdog:{at:new Date().toISOString()},notifications:{enabled:true,configured:{slack:true},deliveries:{'slack:exhausted':1}}})),/alert delivery/);
assert.equal(health(input({enabled:true,watchdog:{at:new Date().toISOString()},notifications:{enabled:true,configured:{slack:true},deliveries:{}}})).length,1);
'''
        result = subprocess.run(['node','-e',program,json.dumps(codes)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_ci_notification_config_reuses_runtime_secret_without_unrelated_fields(self):
        env = deploy_n8n.notification_environment({'MARKETING_RUNTIME_CONFIG': json.dumps({
            'ALERT_SLACK_BOT_TOKEN':'private-slack','ALERT_SLACK_CHANNEL':'C123',
            'OPENAI_API_KEY':'private-provider'}), 'ALERT_SLACK_CHANNEL':'C456'})
        self.assertEqual(env['ALERT_SLACK_BOT_TOKEN'],'private-slack')
        self.assertEqual(env['ALERT_SLACK_CHANNEL'],'C456')
        self.assertNotIn('OPENAI_API_KEY',env)
        with self.assertRaises(ValueError):
            deploy_n8n.notification_environment({'MARKETING_RUNTIME_CONFIG':'[]'})

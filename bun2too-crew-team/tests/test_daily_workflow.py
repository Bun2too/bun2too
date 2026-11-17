import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DailyWorkflowTests(unittest.TestCase):
    def test_daily_plan_is_bounded_and_preserves_publication_gates(self):
        workflow = json.loads((ROOT/'n8n/marketing-operations.json').read_text())
        code = next(n['parameters']['jsCode'] for n in workflow['nodes'] if n['name'] == 'Plan daily continuation')
        program = r'''
const assert = require('node:assert/strict');
const plan = new Function('$input','$','$runIndex',JSON.parse(process.argv[1]));
const base = {id:'today',publish_after:new Date(Date.now()+3600000).toISOString(),publish_before:new Date(Date.now()+7200000).toISOString()};
const check = (run,index=0) => plan({first:()=>({json:{...base,...run}})},()=>({first:()=>({json:{run_id:'today'}})}),index)[0].json;
assert.equal(check({status:'running'}).pending,true);
assert.equal(check({status:'failed',retryable:true}).pending,true);
assert.throws(()=>check({status:'running'},5),/six checks/);
for (const status of ['awaiting_review','failed','publication_unknown','publication_failed','blocked']) {
 assert.throws(()=>check({status}),/intervention/);
}
assert.equal(check({status:'published'}).publish,false);
const ready=check({status:'approved'},5);
assert.equal(ready.publish,true);
assert.equal(ready.publish_at,base.publish_after);
assert.throws(()=>check({status:'approved',id:'other'}),/identity/);
assert.throws(()=>check({status:'approved',publish_before:new Date(Date.now()-1000).toISOString()}),/expired/);
assert.throws(()=>check({status:'approved',publish_after:'invalid'}),/Invalid publication/);
'''
        result = subprocess.run(['node','-e',program,json.dumps(code)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_schedule_volume_and_no_publish_retries(self):
        workflow = json.loads((ROOT/'n8n/marketing-operations.json').read_text())
        health = json.loads((ROOT/'n8n/service-health.json').read_text())
        schedules = [n['parameters']['rule']['interval'][0]['expression'] for n in workflow['nodes']+health['nodes'] if n['type'].endswith('scheduleTrigger')]
        self.assertCountEqual(schedules,['5 8 * * *','45 7 * * *','15 */6 * * *'])
        publish = next(n for n in workflow['nodes'] if n['name']=='Publish approved content')
        self.assertFalse(publish.get('retryOnFail',False))
        connections=workflow['connections']
        self.assertEqual(connections['Wait until publication time']['main'][0][0]['node'],'Publish approved content')
        self.assertEqual(connections['Generation still pending']['main'][0][0]['node'],'Wait for generation')

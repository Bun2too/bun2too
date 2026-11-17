import test from "node:test";
import assert from "node:assert/strict";
import {judgeConfiguration, judgePayload, parseJudgeGrade} from "./core.mjs";
const env={AI_EVAL_JUDGE_URL:"https://api.openai.com/v1",AI_EVAL_JUDGE_API_KEY:"fixture-judge-key",AI_EVAL_JUDGE_MODEL:"fixture-judge-model"};
test("OpenAI base URLs resolve to Chat Completions with compatible parameters",()=>{
 const config=judgeConfiguration(env),body=judgePayload({input:"Fixture",output:"Answer"},"Facts",config);
 assert.equal(config.url.href,"https://api.openai.com/v1/chat/completions");
 assert.equal(body.max_completion_tokens,1000);assert.equal(body.store,false);assert.ok(!("max_tokens" in body));
 assert.throws(()=>judgeConfiguration({...env,AI_EVAL_JUDGE_API_KEY:["Bearer","fixture-key"].join(" ")}));
});
test("judge wire format normalization preserves strict numeric score requirements",()=>{
 const scores={relevance:0.5,faithfulness:0.5,task_completion:0.5};
 const wrap=value=>({choices:[{message:{content:JSON.stringify(value)}}]});
 for(const value of [{scores},{...scores}])assert.deepEqual(parseJudgeGrade(wrap(value)).scores,scores);
 for(const value of [{relevance:1,faithfulness:1},{...scores,task_completion:"1"},{...scores,relevance:2},{scores:null,...scores}])assert.throws(()=>parseJudgeGrade(wrap(value)));
});

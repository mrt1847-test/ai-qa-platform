const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function model(snapshot){const c={window:{},crypto:require('node:crypto').webcrypto};vm.runInNewContext(fs.readFileSync('src/aiqa/web/static/definition_model.js','utf8'),c);return c.window.aiqaDefinitionModel(snapshot);}
function source(recorded=[]){return {definition:{raw_text:'주문 확인',objective:'조회',preconditions:['로그인'],variables:{amount:'10000',object:{nested:['한글']}},secret_refs:{},steps:[{id:'s1',instruction:'첫 단계',point:[10,20],expected:[{id:'c1',kind:'text',expected:'주문'}]},{id:'s2',instruction:'두 번째',point:null,expected:[]}],final_expected:[],path_policy:{must_use:[],forbidden:[]}},settings:{target_kind:'web',future_option:'keep'},recorded_steps:recorded,expected_head:'old'};}
test('friendly variable edits preserve untouched complex values settings and recorded evidence',()=>{
 const m=model(source([{action_id:'tap-1',point:[10,20]}]));m.setVariable('amount','amount','int','12000');const b=m.serialize();
 assert.equal(b.definition.variables.amount,12000);
 assert.equal(JSON.stringify(b.definition.variables.object),'{"nested":["한글"]}');
 assert.equal(b.settings.future_option,'keep');assert.equal(b.recorded_steps[0].action_id,'tap-1');assert.equal(b.definition.steps[0].expected[0].id,'c1');
});
test('definition reorder keeps identifiers coordinates and expected checks',()=>{
 const m=model(source());m.moveStep(1,0);const b=m.serialize();assert.equal(b.definition.steps[1].id,'s1');assert.equal(b.definition.steps[1].point[0],10);assert.equal(b.definition.steps[1].expected[0].id,'c1');
});
test('recorded actions cannot be silently reordered by definition editing',()=>{
 const m=model(source([{action_id:'tap-1'}]));assert.throws(()=>m.moveStep(0,1));assert.equal(m.serialize().definition.steps[0].id,'s1');
});

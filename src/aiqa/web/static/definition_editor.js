(function(){
  var form=document.getElementById('definition-form');if(!form)return;
  var model=window.aiqaDefinitionModel(JSON.parse(document.getElementById('definition-snapshot').textContent));
  var head=document.getElementById('expected-head').value||null,locked=(model.data.recorded_steps||[]).length>0;
  var variableRows=Object.keys(model.data.definition.variables).map(function(name){var val=model.data.definition.variables[name];return {name:name,kind:typeof val==='boolean'?'bool':typeof val==='number'?'number':typeof val==='string'?'string':'complex',value:val};});
  var secretRows=Object.keys(model.data.definition.secret_refs).map(function(name){return {name:name,ref:model.data.definition.secret_refs[name]};}),choices=[];
  function element(tag,attrs,text){var n=document.createElement(tag);Object.keys(attrs||{}).forEach(function(k){n.setAttribute(k,attrs[k]);});if(text!==undefined)n.textContent=text;return n;}
  function changed(){form.dispatchEvent(new Event('input',{bubbles:true}));}
  function button(text,fn){var n=element('input',{type:'button',value:text,class:'quiet'});n.addEventListener('click',fn);return n;}
  function input(tag,name,label,value,onInput){var wrap=element('label',{},label),n=element(tag,{name:name});n.value=value;wrap.appendChild(n);n.addEventListener('input',function(){onInput(n.value);});return {wrap:wrap,node:n};}
  function drawVariables(){
    var root=document.getElementById('definition-variables');root.replaceChildren();
    variableRows.forEach(function(row,i){
      var tr=element('tr'),key=element('td'),type=element('td'),value=element('td'),actions=element('td');
      key.appendChild(input('input','variables.'+i+'.name','변수 '+(i+1)+' 이름',row.name,function(v){row.name=v;}).wrap);
      var select=element('select',{name:'variables.'+i+'.type','aria-label':(i+1)+'번째 변수 종류'});
      [['string','문자'],['number','숫자'],['int','정수'],['bool','참/거짓'],['complex','복합 값 · 원본 유지']].forEach(function(pair){select.appendChild(element('option',{value:pair[0]},pair[1]));});select.value=row.kind;select.disabled=row.kind==='complex';
      select.addEventListener('change',function(){row.kind=select.value;drawVariables();changed();});type.appendChild(select);
      if(row.kind==='bool'){
        var bool=element('select',{name:'variables.'+i+'.value','aria-label':row.name+' 값'});[['true','참'],['false','거짓']].forEach(function(pair){bool.appendChild(element('option',{value:pair[0]},pair[1]));});bool.value=String(row.value);bool.addEventListener('change',function(){row.value=bool.value;});value.appendChild(bool);
      }else{var field=input('input','variables.'+i+'.value',row.name+' 값',row.kind==='complex'?JSON.stringify(row.value):String(row.value),function(v){row.value=v;});field.node.readOnly=row.kind==='complex';value.appendChild(field.wrap);}
      actions.appendChild(button((i+1)+'번째 변수 삭제',function(){variableRows.splice(i,1);drawVariables();changed();}));
      [key,type,value,actions].forEach(function(td){tr.appendChild(td);});root.appendChild(tr);
    });
  }
  function drawSecrets(){
    var root=document.getElementById('definition-secret-refs');root.replaceChildren();
    secretRows.forEach(function(row,i){
      var line=element('div',{class:'column-row'});line.appendChild(input('input','secret_refs.'+i+'.name','참조 변수 이름',row.name,function(v){row.name=v;}).wrap);
      var label=element('label',{},'저장된 참조'),select=element('select',{name:'secret_refs.'+i+'.ref'});select.appendChild(element('option',{value:''},'참조 선택'));
      var available=choices.slice();if(row.ref&&!available.some(function(c){return c.ref_id===row.ref.ref_id&&c.revision===row.ref.revision;}))available.push(Object.assign({name:'저장된 참조'},row.ref));
      available.forEach(function(ref,index){var option=element('option',{value:String(index)},ref.name+' · v'+ref.revision);if(ref.availability&&ref.availability!=='available')option.disabled=true;select.appendChild(option);if(row.ref&&row.ref.ref_id===ref.ref_id&&row.ref.revision===ref.revision)select.value=String(index);});
      select.addEventListener('change',function(){var picked=available[Number(select.value)];row.ref=select.value===''?null:{project_id:picked.project_id,ref_id:picked.ref_id,revision:picked.revision};});label.appendChild(select);line.appendChild(label);line.appendChild(button('참조 삭제',function(){secretRows.splice(i,1);drawSecrets();changed();}));root.appendChild(line);
    });
  }
  function drawChecks(root,checks,prefix,readOnly){
    root.replaceChildren();checks.forEach(function(check,index){
      var line=element('div',{class:'check-row'}),field=input('textarea',prefix+'.'+index+'.expected','검증 '+(index+1)+' 기대 값',check.expected,function(v){check.expected=v;});field.node.rows=2;field.node.readOnly=readOnly;line.appendChild(field.wrap);line.appendChild(element('small',{},check.kind==='text'?'화면 텍스트 검증':'저장된 유형 · '+check.kind));
      if(!readOnly)line.appendChild(button('검증 삭제',function(){checks.splice(index,1);drawChecks(root,checks,prefix,readOnly);changed();}));root.appendChild(line);
    });
  }
  function newCheck(){return {id:crypto.randomUUID(),kind:'text',expected:''};}
  function drawSteps(){
    var root=document.getElementById('definition-steps');root.replaceChildren();
    model.data.definition.steps.forEach(function(step,i){
      var card=element('article',{class:'definition-step'}),bar=element('div',{class:'section-heading'});bar.appendChild(element('h3',{},'단계 '+(i+1)));
      if(!locked){var actions=element('div',{class:'actions'});[['위로',i-1],['아래로',i+1]].forEach(function(pair){var b=button('단계 '+(i+1)+' '+pair[0],function(){model.moveStep(i,pair[1]);drawSteps();changed();});b.disabled=pair[1]<0||pair[1]>=model.data.definition.steps.length;actions.appendChild(b);});actions.appendChild(button('단계 '+(i+1)+' 삭제',function(){model.data.definition.steps.splice(i,1);drawSteps();changed();}));bar.appendChild(actions);}card.appendChild(bar);
      var instruction=input('textarea','steps.'+i+'.instruction','수행 의도',step.instruction,function(v){step.instruction=v;});instruction.node.rows=2;instruction.node.readOnly=locked;card.appendChild(instruction.wrap);
      var checks=element('div');card.appendChild(checks);drawChecks(checks,step.expected,'steps.'+i+'.expected',locked);
      if(!locked)card.appendChild(button('단계 '+(i+1)+' 검증 추가',function(){step.expected.push(newCheck());drawChecks(checks,step.expected,'steps.'+i+'.expected',false);changed();}));root.appendChild(card);
    });
  }
  function read(){
    var body=model.serialize(),definition=body.definition,fields={};
    definition.raw_text=form.elements.raw_text.value;definition.objective=form.elements.objective.value;
    [['preconditions',definition.preconditions],['must_use',definition.path_policy.must_use],['forbidden',definition.path_policy.forbidden]].forEach(function(pair){var raw=form.elements.namedItem(pair[0]).value;if(raw!==pair[1].join('\n')){var lines=raw.split('\n').map(function(s){return s.trim();}).filter(Boolean);if(pair[0]==='preconditions')definition.preconditions=lines;else definition.path_policy[pair[0]]=lines;}});
    var temporary=window.aiqaDefinitionModel(body);temporary.data.definition.variables={};
    variableRows.forEach(function(row,i){try{temporary.setVariable(null,row.name.trim(),row.kind,row.value);}catch(error){fields['variables.'+i+'.'+error.field]=[error.message];}});definition.variables=temporary.data.definition.variables;
    definition.secret_refs=Object.create(null);secretRows.forEach(function(row,i){if(!row.name.trim()||Object.prototype.hasOwnProperty.call(definition.secret_refs,row.name))fields['secret_refs.'+i+'.name']=['참조 이름은 비어 있거나 중복될 수 없습니다.'];else if(!row.ref)fields['secret_refs.'+i+'.ref']=['저장된 참조를 선택해 주세요.'];else definition.secret_refs[row.name]=row.ref;});
    if(Object.keys(fields).length){var error=new Error('입력을 확인해 주세요.');error.fields=fields;throw error;}
    return body;
  }
  drawVariables();drawSecrets();drawSteps();drawChecks(document.getElementById('definition-final-checks'),model.data.definition.final_expected,'final_expected',false);
  document.getElementById('recorded-step-hint').hidden=!locked;document.getElementById('add-definition-step').disabled=locked;
  document.getElementById('add-variable').addEventListener('click',function(){variableRows.push({name:'variable'+(variableRows.length+1),kind:'string',value:''});drawVariables();changed();});
  document.getElementById('add-secret-reference').addEventListener('click',function(){secretRows.push({name:'secret'+(secretRows.length+1),ref:null});drawSecrets();changed();});
  document.getElementById('add-definition-step').addEventListener('click',function(){if(locked)return;model.data.definition.steps.push({id:crypto.randomUUID(),instruction:'',expected:[],point:null});drawSteps();changed();});
  document.getElementById('add-final-check').addEventListener('click',function(){model.data.definition.final_expected.push(newCheck());drawChecks(document.getElementById('definition-final-checks'),model.data.definition.final_expected,'final_expected',false);changed();});
  window.aiqaForms.register(form,{read:read,persist:function(body,key){return window.aiqaRequest(form.action,{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(Object.assign({},body,{expected_head:head,parent_version_id:head}))});},onConflict:function(body){if(body.server_snapshot)window.aiqaCompareConflict(form,Object.assign({},body.server_snapshot.definition,{settings:body.server_snapshot.settings,recorded_steps:body.server_snapshot.recorded_steps}),Object.assign({},read().definition,{settings:read().settings,recorded_steps:read().recorded_steps}),function(){head=body.server.version_id;document.getElementById('expected-head').value=head;});},onSaved:function(body){head=body.id;document.getElementById('expected-head').value=head;form.querySelector('[data-conflict-comparison]').hidden=true;var note=document.getElementById('readiness');if(note)note.textContent='초안 v'+body.revision+'을 저장했습니다. 변경된 버전의 시범·검토 상태를 확인하세요.';}});
  function preview(){try{document.getElementById('definition-preview').textContent=JSON.stringify(read().definition,null,2);}catch(_){document.getElementById('definition-preview').textContent='입력을 완성하면 원본을 확인할 수 있습니다.';}}form.addEventListener('input',preview);form.addEventListener('change',preview);preview();
  var project=/\/projects\/([^/]+)/.exec(form.action)[1];window.aiqaRequest('/api/v1/projects/'+project+'/secret-refs',{method:'GET'}).then(function(response){return response.ok?response.json():{refs:[]};}).then(function(body){choices=body.refs||[];drawSecrets();}).catch(function(){});
})();

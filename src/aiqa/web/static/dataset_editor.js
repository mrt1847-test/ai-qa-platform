(function(){
  var form=document.getElementById('dataset-form');if(!form)return;
  var snapshot=JSON.parse(document.getElementById('dataset-snapshot').textContent)||{};
  var columns=(snapshot.row_schema||{columns:[{name:'amount',type:'string'}]}).columns.map(function(c){return {name:c.name,type:c.type};});
  var rows=(snapshot.rows||[{id:crypto.randomUUID(),values:{amount:''}}]).map(function(r){return {id:r.id,cells:columns.map(function(c){return r.values[c.name];})};});
  function element(tag,attrs,text){var n=document.createElement(tag);Object.keys(attrs||{}).forEach(function(k){n.setAttribute(k,attrs[k]);});if(text!==undefined)n.textContent=text;return n;}
  function changed(){form.dispatchEvent(new Event('input',{bubbles:true}));}
  function button(label,fn){var b=element('input',{type:'button',value:label,class:'quiet'});b.addEventListener('click',fn);return b;}
  function draw(){
    var controls=document.getElementById('dataset-columns');controls.replaceChildren();
    columns.forEach(function(col,i){
      var row=element('div',{class:'column-row'});
      var label=element('label',{},'열 이름 ');var name=element('input',{name:'columns.'+i+'.name','aria-label':'열 '+(i+1)+' 이름'});name.value=col.name;
      name.addEventListener('input',function(){col.name=name.value;});name.addEventListener('change',function(){drawRows();changed();});label.appendChild(name);row.appendChild(label);
      var typeLabel=element('label',{},'값 종류 ');var select=element('select',{name:'columns.'+i+'.type','aria-label':'열 '+(i+1)+' 종류'});
      [['string','문자'],['int','정수'],['bool','참/거짓']].forEach(function(pair){select.appendChild(element('option',{value:pair[0]},pair[1]));});select.value=col.type;
      select.addEventListener('change',function(){col.type=select.value;drawRows();changed();});typeLabel.appendChild(select);row.appendChild(typeLabel);
      row.appendChild(button('열 삭제',function(){
        var hasValues=rows.some(function(r){return r.cells[i]!=='' && r.cells[i]!==undefined;});
        if(hasValues&&!window.confirm('이 열의 입력 값을 초안에서 삭제할까요? 저장된 과거 데이터는 유지됩니다.'))return;
        columns.splice(i,1);rows.forEach(function(r){r.cells.splice(i,1);});draw();changed();
      }));controls.appendChild(row);
    });drawRows();
  }
  function drawRows(){
    var table=document.getElementById('dataset-rows');table.replaceChildren();
    var head=element('thead');var line=element('tr');line.appendChild(element('th',{scope:'col'},'행'));
    columns.forEach(function(c){line.appendChild(element('th',{scope:'col'},c.name||'이름 없음'));});line.appendChild(element('th',{scope:'col'},'동작'));head.appendChild(line);table.appendChild(head);
    var body=element('tbody');
    rows.forEach(function(row,i){
      var tr=element('tr');tr.appendChild(element('th',{scope:'row'},String(i+1)));
      columns.forEach(function(col,j){
        var cell=element('td');var input=element(col.type==='bool'?'select':'input',{name:'rows.'+i+'.values.'+col.name,'aria-label':(i+1)+'행 '+col.name});
        if(col.type==='bool'){[['','선택'],['true','참'],['false','거짓']].forEach(function(pair){input.appendChild(element('option',{value:pair[0]},pair[1]));});}
        else input.type='text';
        input.value=row.cells[j]===undefined?'':String(row.cells[j]);
        input.addEventListener('input',function(){row.cells[j]=input.value;});input.addEventListener('change',function(){row.cells[j]=input.value;});
        cell.appendChild(input);tr.appendChild(cell);
      });
      var actions=element('td');actions.appendChild(button((i+1)+'행 삭제',function(){rows.splice(i,1);drawRows();changed();}));tr.appendChild(actions);body.appendChild(tr);
    });table.appendChild(body);
  }
  form.querySelector('[data-add-column]').addEventListener('click',function(){columns.push({name:'column'+(columns.length+1),type:'string'});rows.forEach(function(r){r.cells.push('');});draw();changed();});
  form.querySelector('[data-add-row]').addEventListener('click',function(){rows.push({id:crypto.randomUUID(),cells:columns.map(function(){return '';})});drawRows();changed();});
  function read(){
    var fields={};var seen={};
    var mapped=columns.map(function(c,i){var name=c.name.trim();if(!name||seen[name])fields['columns.'+i+'.name']=['열 이름은 비어 있거나 중복될 수 없습니다.'];seen[name]=true;return {name:name,type:c.type};});
    var data=rows.map(function(r,i){
      var values=Object.create(null);
      mapped.forEach(function(c,j){
        var value=r.cells[j]===undefined?'':r.cells[j];
        if(c.type==='int'){if(!/^-?\d+$/.test(String(value))||!Number.isSafeInteger(Number(value)))fields['rows.'+i+'.values.'+c.name]=['정수를 입력해 주세요.'];else value=Number(value);}
        if(c.type==='bool'){if(value!==true&&value!==false&&value!=='true'&&value!=='false')fields['rows.'+i+'.values.'+c.name]=['참 또는 거짓을 선택해 주세요.'];else value=value===true||value==='true';}
        values[c.name]=value;
      });return {id:r.id,values:values};
    });
    if(!columns.length)fields.columns=['열을 하나 이상 추가해 주세요.'];if(!rows.length)fields.rows=['행을 하나 이상 추가해 주세요.'];
    var secret=form.elements.namedItem('secret_ref').value;
    var payload={name:form.elements.namedItem('name').value.trim(),case_id:form.elements.namedItem('case_id').value||null,row_schema:{columns:mapped},rows:data,secret_ref:secret?JSON.parse(secret):null};
    if(!payload.name)fields.name=['이름을 입력해 주세요.'];
    // read must remain available while editing; validation runs at submit.
    return {payload:payload,fields:fields};
  }
  draw();
  var search=document.getElementById('dataset-case-search'),find=document.getElementById('dataset-find-case'),more=document.getElementById('dataset-more-cases'),caseStatus=document.getElementById('dataset-case-status'),caseCursor=null,caseQuery='',searching=false;
  async function searchCases(append){
    if(searching)return;searching=true;find.disabled=more.disabled=true;
    if(!append){caseQuery=search.value;caseCursor=null;}
    try{var url='/api/v1/projects/'+form.dataset.project+'/cases?limit=100&q='+encodeURIComponent(caseQuery)+(caseCursor?'&cursor='+encodeURIComponent(caseCursor):'');var response=await window.aiqaRequest(url,{method:'GET'}),body=await response.json();if(!response.ok)throw Error('search');var select=form.elements.namedItem('case_id'),chosen=select.value;
      if(!append)Array.from(select.options).forEach(function(option){if(option.value&&option.value!==chosen)option.remove();});
      (body.items||[]).forEach(function(item){if(Array.from(select.options).some(function(option){return option.value===item.case_id;}))return;var option=document.createElement('option');option.value=item.case_id;option.textContent=item.name+' · '+item.case_id.slice(0,8);select.appendChild(option);});select.value=chosen;caseCursor=body.next_cursor;more.hidden=!caseCursor;caseStatus.textContent='검색 결과 '+body.total+'개 · 연결할 케이스를 위 선택란에서 고르세요.';
    }catch(_){caseStatus.textContent='케이스를 찾지 못했습니다. 현재 선택은 유지됩니다.';}finally{searching=false;find.disabled=more.disabled=false;}
  }
  find.addEventListener('click',function(){searchCases(false);});more.addEventListener('click',function(){searchCases(true);});
  var handle=window.aiqaForms.register(form,{read:function(){return read().payload;},persist:function(payload,key){
    var errors=read().fields;if(Object.keys(errors).length){return Promise.resolve({ok:false,status:422,json:function(){return Promise.resolve({error:{fields:errors}});}});}
    var endpoint=form.action+(form.dataset.datasetId?'/'+encodeURIComponent(form.dataset.datasetId)+'/revisions':'');
    return window.aiqaRequest(endpoint,{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(payload)});
  },onSaved:function(body){
    form.dataset.datasetId=body.dataset_id;
    form.elements.namedItem('name').readOnly=true;
    window.aiqaAssetSaved({id:body.dataset_id,name:form.elements.namedItem('name').value,href:'?dataset='+encodeURIComponent(body.dataset_id),detail:'v'+body.revision+' · '+rows.length+'행'});
    document.getElementById('dataset-version').textContent='저장본 v'+body.revision+' · '+rows.length+'행';
    history.replaceState(null,'',location.pathname+'?dataset='+encodeURIComponent(body.dataset_id));
  },successMessage:function(body){return '데이터 v'+body.revision+'을 저장했습니다.';}});
})();

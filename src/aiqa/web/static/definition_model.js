/* Editable definition state. Recorded procedure edits keep their separate boundary. */
(function(){
  function clone(value){return JSON.parse(JSON.stringify(value));}
  window.aiqaDefinitionModel=function(snapshot){
    var data=clone(snapshot);
    function problem(message,field){var error=new Error(message);error.field=field;throw error;}
    return {data:data,serialize:function(){var body=clone(data);delete body.expected_head;delete body.parent_version_id;return body;},
      setVariable:function(oldName,name,kind,value){
        if(!name.trim())problem('변수 이름을 입력해 주세요.','name');
        if(name!==oldName&&Object.prototype.hasOwnProperty.call(data.definition.variables,name))problem('같은 이름의 변수가 있습니다.','name');
        var parsed=value;
        if(kind==='int'){if(!/^-?\d+$/.test(String(value))||!Number.isSafeInteger(Number(value)))problem('정수를 입력해 주세요.','value');parsed=Number(value);}
        if(kind==='number'){if(String(value).trim()===''||!Number.isFinite(Number(value)))problem('숫자를 입력해 주세요.','value');parsed=Number(value);}
        if(kind==='bool'){if(![true,false,'true','false'].includes(value))problem('참 또는 거짓을 선택해 주세요.','value');parsed=value===true||value==='true';}
        if(kind==='string')parsed=String(value);
        if(oldName!==null&&oldName!==name)delete data.definition.variables[oldName];
        Object.defineProperty(data.definition.variables,name,{value:clone(parsed),writable:true,enumerable:true,configurable:true});
      },moveStep:function(from,to){
        if((data.recorded_steps||[]).length)problem('녹화된 절차는 단계 편집에서 새 버전으로 수정해 주세요.','steps');
        var steps=data.definition.steps;if(from<0||to<0||from>=steps.length||to>=steps.length)return;
        steps.splice(to,0,steps.splice(from,1)[0]);
      }};
  };
})();

/* Navigation coordinates dirty forms before project-session acquisition. */
(function(){
  'use strict';
  var permitted=false, awaiting=null;
  function dirty(){return window.aiqaForms ? window.aiqaForms.dirty() : [];}
  function ask(handles){
    var dialog=document.getElementById('unsaved-dialog');
    if(!dialog)return Promise.resolve('cancel');
    var active=document.activeElement;
    var canSave=handles.every(function(h){return h.saveBeforeLeave!==false;});
    var save=dialog.querySelector('[data-leave-choice="save"]');
    var note=dialog.querySelector('[data-leave-note]');
    if(save)save.hidden=!canSave;
    if(note)note.textContent=canSave?'입력한 내용을 저장한 뒤 이동할 수 있습니다.':'검토 의견·반려는 해당 화면에서 직접 제출하세요. 이동 중 자동으로 제출하지 않습니다.';
    return new Promise(function(resolve){
      dialog.addEventListener('close',function(){if(active&&active.focus)active.focus();resolve(dialog.returnValue||'cancel');},{once:true});
      dialog.returnValue='cancel';dialog.showModal();
    });
  }
  window.aiqaNavigate=function(url){
    if(awaiting)return awaiting;
    var target=new URL(url,window.location.href);
    if(target.origin!==window.location.origin || !/^https?:$/.test(target.protocol))return Promise.resolve();
    var handles=dirty();
    var decision=handles.length?ask(handles):Promise.resolve('discard');
    awaiting=decision.then(async function(choice){
      if(choice==='cancel')return;
      if(choice==='save'){
        if(handles.some(function(h){return h.saveBeforeLeave===false;}))return;
        for(var i=0;i<handles.length;i++){if(!await handles[i].save()||handles[i].isDirty())return;}
      }
      permitted=true;
      var project=/^\/ui\/projects\/([0-9a-f-]{36})(?:\/|$)/i.exec(target.pathname);
      try {
        if(project&&window.aiqaOpenProject)await window.aiqaOpenProject(project[1],target.href);
        else window.location.assign(target.href);
      }catch(_){permitted=false;var note=document.querySelector('[data-save-message]');if(note)note.textContent='연결을 확인해 주세요. 입력은 유지됩니다.';}
    }).finally(function(){awaiting=null;});
    return awaiting;
  };
  var dialog=document.getElementById('unsaved-dialog');
  if(dialog){
    dialog.querySelectorAll('[data-leave-choice]').forEach(function(button){button.addEventListener('click',function(){dialog.close(button.dataset.leaveChoice);});});
  }
  window.addEventListener('beforeunload',function(event){if(!permitted&&dirty().length){event.preventDefault();event.returnValue='';}});
  document.addEventListener('click',function(event){
    var link=event.target.closest&&event.target.closest('a[href]');
    if(!link||event.defaultPrevented||event.ctrlKey||event.metaKey||event.shiftKey||link.target==='_blank'||link.hasAttribute('download'))return;
    var target=new URL(link.href,window.location.href);
    if(target.origin!==window.location.origin || (target.pathname===location.pathname&&target.search===location.search))return;
    event.preventDefault();window.aiqaNavigate(target.href);
  });
  document.addEventListener('submit',function(event){
    var form=event.target;
    if(event.defaultPrevented||String(form.method).toLowerCase()!=='get'||!dirty().length)return;
    event.preventDefault();
    var url=new URL(form.action,location.href);url.search=new URLSearchParams(new FormData(form)).toString();window.aiqaNavigate(url.href);
  });
  var scrollKey='aiqa.scroll:'+location.pathname+location.search;
  // Only a history return restores a list; new detail/edit pages start at top.
  var entry=window.performance&&window.performance.getEntriesByType('navigation')[0];
  if(entry&&entry.type==='back_forward'){
    var saved=window.sessionStorage.getItem(scrollKey);if(saved)window.scrollTo(0,Number(saved));
  }
  window.addEventListener('scroll',function(){window.sessionStorage.setItem(scrollKey,String(window.scrollY));});
})();

(function(){
  window.aiqaAssetSaved=function(info){
    var list=document.querySelector('[data-asset-list]');if(!list)return;
    var empty=list.querySelector('[data-empty-assets]');if(empty)empty.remove();
    var link=Array.from(list.querySelectorAll('[data-asset-id]')).find(function(node){return node.dataset.assetId===info.id;});
    if(!link){link=document.createElement('a');link.className='list-card';link.dataset.assetId=info.id;list.appendChild(link);}
    link.href=info.href;link.replaceChildren();
    var title=document.createElement('strong');title.textContent=info.name;
    var meta=document.createElement('span');meta.textContent=info.detail;
    link.appendChild(title);link.appendChild(meta);
  };
})();

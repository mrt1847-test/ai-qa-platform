(function(){
  // Explicit commands retain an unacknowledged request; no automatic retry.
  window.aiqaCommand=function(send){
    var pending=null,inflight=null;
    return {pending:function(){return pending!==null;},send:function(payload){
      var serialized=JSON.stringify(payload);
      if(pending&&pending.body!==serialized)return Promise.reject(new Error('pending command needs confirmation first'));
      if(inflight)return inflight;
      if(!pending)pending={body:serialized,key:crypto.randomUUID()};
      var request=pending;
      inflight=(async function(){
        try{var response=await send(JSON.parse(request.body),request.key);if(response.clone)await response.clone().json();pending=null;return response;}
        finally{inflight=null;}
      })();return inflight;
    }};
  };
})();

/* Disposable, synthetic UI fixtures. No credentials, device control, or model calls. */
(() => {
  const day = offset => { const d = new Date(); d.setDate(d.getDate() + offset); return d.toISOString(); };
  const plans = {
    login: [
      ['tap','로그인 화면 열기','로그인 버튼 선택',0,1,'tap(x=112, y=284)'],
      ['type','테스트 계정 입력','저장된 합성 계정 참조로 입력',1,2,'type(secret_ref="demo-account") · value=[MASKED]'],
      ['swipe','로그인 영역 확인','위로 스와이프하여 버튼 확인',2,3,'swipe(from=[110,305], to=[110,160], duration_ms=600)'],
      ['tap','로그인 버튼 누르기','사용자 화면으로 전환',3,4,'tap(target="로그인")'],
      ['check','사용자 이름 검증','QA Tester 표시 확인',4,5,'assert_text(expected="QA Tester")']
    ],
    cart: [
      ['tap','상품 상세 열기','테스트 상품을 선택',0,1,'tap(target="Everyday Tote")'],
      ['swipe','구매 영역 확인','아래 구매 영역으로 이동',1,2,'swipe(from=[110,305], to=[110,160], duration_ms=600)'],
      ['tap','장바구니에 추가','합성 상품 1개 추가',2,3,'tap(target="장바구니 담기")'],
      ['tap','장바구니 열기','추가된 상품 화면으로 이동',3,4,'tap(target="장바구니")'],
      ['check','수량과 상품 확인','상품 1개 표시 확인',4,5,'assert_text(expected="Everyday Tote × 1")']
    ]
  };
  const makeActions = (scenario='login',count=5,reviewed=false,fail=false) => plans[scenario].slice(0,count).map((a,i) => ({
    id:`A${String(i+1).padStart(3,'0')}`, type:a[0], title:a[1], intent:a[2], before:a[3], after:a[4],
    command:a[5], capturedAt:day(0), duration:230+i*170, evidence:'ready', reviewed:reviewed?'reviewed':null,
    result:fail&&i===4?'FAIL':a[0]==='check'?'PASS':null, fail:fail&&i===4,
    hash:`sha256:demo-${scenario}-${i+1}-sanitized`, log:`[OBSERVED] ${a[1]}\n[COMMAND] ${a[5]}\n[DELIVERED] exit=0\n[CAPTURE] before=ready after=ready · redaction=demo-mask-v1\n${a[0]==='check'?'[ORACLE] '+(fail?'FAIL · 기대값과 관측값의 불일치':'PASS · expectation matched'):'[QA] not_run · command delivery is not a QA verdict'}`
  }));
  const version=(n,opts={})=>({n,createdAt:day(-2),definition:'정상 테스트 계정으로 로그인한 후 사용자 이름이 QA Tester로 표시되는지 검증한다.',expected:'사용자 이름이 QA Tester로 표시된다.',scenario:'login',target:'android',resource:'Galaxy S24 · USB',url:'https://demo-shop.example.test',app:'com.example.demostore',account:'demo-account · 합성 계정',data:'정상 계정 A',reset:'앱 기본 화면에서 시작',limit:600,source:`REC-${String(n+16).padStart(3,'0')}`,base:null,reason:'최초 녹화',outcome:'completed',storage:'stored',procedure:'complete',status:'needs_review',actions:makeActions(),trial:null,approval:null,...opts});
  const approve=(v,id)=>{v.status='approved';v.approval={id,status:'valid',at:day(-3),actor:'김 QA',reason:'저장된 동작 및 시범 증거 확인'};v.actions=makeActions(v.scenario,5,true);v.trial={id:'RUN-TRIAL-SEED',result:'PASS',actions:makeActions(v.scenario,5,true)};return v;};
  function seed(){
    const v2=approve(version(2), 'APP-001');
    const v4=version(4,{source:'REC-019',base:2,reason:'로그인 버튼 위치 변경에 맞춰 재녹화',trial:{id:'RUN-TRIAL-018',result:'PASS',actions:makeActions()},createdAt:day(-1)});
    const w2=version(2,{scenario:'cart',target:'web',resource:'이 PC · Chromium',definition:'상품을 장바구니에 담고 Everyday Tote 상품이 수량 1개로 표시되는지 검증한다.',expected:'Everyday Tote 상품의 수량이 1이다.',app:'Demo Store Web',source:'REC-020',actions:makeActions('cart')});
    const incomplete=version(2,{source:'REC-021',outcome:'interrupted',procedure:'incomplete',actions:makeActions('login',2),reason:'연결 중단 — 부분 기록 보존'});
    incomplete.actions[1].evidence='missing';
    const logout=approve(version(2,{scenario:'login',target:'web',resource:'이 PC · Chromium',definition:'웹에서 정상 테스트 계정으로 로그인한 뒤 사용자 이름이 QA Tester로 표시되는지 검증한다.',expected:'사용자 이름이 QA Tester로 표시된다.',app:'Demo Store Web',source:'REC-022'}),'APP-002');
    const search=approve(version(2,{target:'android',scenario:'cart',definition:'모바일 앱에서 상품을 장바구니에 담고 Everyday Tote 상품이 수량 1개로 표시되는지 검증한다.',expected:'Everyday Tote 상품의 수량이 1이다.',source:'REC-023'}),'APP-003');
    const cases=[
      {id:'AUT-041',project:'SHOP',name:'정상 계정 로그인 검증',folder:'로그인',tags:['핵심','P0'],target:'android',current:2,latest:4,versions:[v2,v4],archived:false},
      {id:'AUT-052',project:'SHOP',name:'장바구니 상품 추가',folder:'장바구니',tags:['구매','P1'],target:'web',current:null,latest:2,versions:[w2],archived:false},
      {id:'AUT-060',project:'SHOP',name:'모바일 로그인 · 미완성',folder:'로그인',tags:['재녹화 필요'],target:'android',current:null,latest:2,versions:[incomplete],archived:false},
      {id:'AUT-067',project:'SHOP',name:'웹 정상 계정 로그인 검증',folder:'로그인',tags:['회귀'],target:'web',current:2,latest:2,versions:[logout],archived:false},
      {id:'AUT-071',project:'SHOP',name:'모바일 장바구니 상품 확인',folder:'장바구니',tags:['핵심'],target:'android',current:2,latest:2,versions:[search],archived:false}
    ];
    const item=(id,cid,ver,result,index)=>({id,caseId:cid,version:ver,name:cases.find(c=>c.id===cid).name,target:cases.find(c=>c.id===cid).target,approvalId:cases.find(c=>c.id===cid).versions.find(v=>v.n===ver).approval?.id||null,data:'정상 계정 A',build:'demo-store 1.12.0',model:'GUI demo · 고정 모의 결과',verification:cases.find(c=>c.id===cid).versions.find(v=>v.n===ver).definition,scenario:cases.find(c=>c.id===cid).versions.find(v=>v.n===ver).scenario,status:'completed',result,duration:30+index*3,actions:makeActions(cases.find(c=>c.id===cid).versions.find(v=>v.n===ver).scenario,5,false,result==='FAIL'),analysis:[],fingerprint:`${cid}:same-intent:${cases.find(c=>c.id===cid).target}:data-A:build-1.12:model-demo`});
    const r12=['PASS','FAIL','PASS','PASS','BLOCKED','PASS','FAIL','PASS','PASS','NOT_RUN'].map((r,i)=>item(`ITEM-12-${i+1}`,i%3===0?'AUT-067':'AUT-041',2,r,i));
    r12.forEach((i,n)=>{i.data=`합성 데이터 ${n+1}`;i.fingerprint+=`:row-${n+1}`;if(['BLOCKED','NOT_RUN'].includes(i.result)){i.actions=[];i.duration=null;}});
    const runs=[
      {id:'RUN-012',project:'SHOP',name:'릴리스 1.12 · 핵심 회귀',purpose:'regression',source:'suite',suiteId:'SUITE-01',suiteRevision:1,createdAt:day(-1),status:'completed',items:r12,policy:'continue',mockResult:'PASS',original:null},
      {id:'RUN-011',project:'SHOP',name:'정상 계정 로그인 · 단독',purpose:'regression',source:'single',createdAt:day(-2),status:'completed',items:[item('ITEM-11-1','AUT-041',2,'PASS',0)],policy:'continue',original:null},
      {id:'RUN-010',project:'SHOP',name:'검색·로그인 점검',purpose:'regression',source:'selection',createdAt:day(-3),status:'completed',items:[item('ITEM-10-1','AUT-071',2,'PASS',0),item('ITEM-10-2','AUT-041',2,'FAIL',1)],policy:'continue',original:null}
    ];
    return {schema:1,project:'SHOP',projects:[{id:'SHOP',name:'Demo Store',description:'Web · Android 통합 QA 샘플'}],cases,runs,suites:[{id:'SUITE-01',project:'SHOP',name:'핵심 사용자 흐름',description:'모바일 · 웹 로그인 · 장바구니',revision:1,entries:[{caseId:'AUT-041',version:2},{caseId:'AUT-067',version:2},{caseId:'AUT-071',version:2}],history:[]}],tcs:[],recording:null,counters:{case:72,recording:24,run:19,approval:4,suite:2},settings:{retention:30,details:90,quota:20},audit:[{at:day(-1),message:'AUT-041 v4 재녹화 저장 · 기존 승인 v2 유지'},{at:day(-1),message:'RUN-012 완료 · 10개 항목 / PASS 6 / FAIL 2'},{at:day(-2),message:'AUT-052 v2 녹화 저장 · 완료 후 검토 대기'}]};
  }
  window.QADemo={seed,makeActions,plans,version};
})();


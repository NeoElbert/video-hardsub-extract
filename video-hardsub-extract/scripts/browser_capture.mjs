// Browser-assisted acquisition over the DevTools protocol (own profile, own port).
// Only public work metadata/media addresses cross stdout in-memory; never cookies.
import fs from 'node:fs';
import {createRequire} from 'node:module';
const req=JSON.parse(fs.readFileSync(0,'utf8'));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const adapter=createRequire(import.meta.url)(req.adapter);
const adapterCode=fs.readFileSync(req.adapter,'utf8');
const posts=new Map();let ended=false,apiError='',pageCount=0,requestMid='';
function ingest(data,url='') {
  if(req.platform==='douyin') {
    if(/aweme\/post/.test(url)) {
      const u=new URL(url),sec=u.searchParams.get('sec_user_id')||u.searchParams.get('sec_uid');
      if(req.mode==='author'&&sec&&sec!==new URL(req.url).pathname.split('/')[2])return;
      pageCount++;if(data.status_code&&data.status_code!==0)apiError='抖音作品列表暂不可用，请检查登录或网页提示。';
      if(data.has_more===0||data.has_more===false)ended=true;
    }
    adapter.walk(data,p=>posts.set(p.postId,p),'浏览器实际作品响应',14);
  } else if(/x\/space\/.*arc\/search/.test(url)) {
    const u=new URL(url);if(req.mode==='author'&&u.searchParams.get('mid')!==requestMid)return;
    pageCount++;if(data.code)apiError=`B站列表返回 ${data.code}，请检查原页面。`;
    for(const p of data?.data?.list?.vlist||[])posts.set(p.bvid,{postId:p.bvid,sourceUrl:`https://www.bilibili.com/video/${p.bvid}`,title:p.title,author:{name:p.author,id:String(p.mid)},likeCount:null,likePrecision:'unknown',kind:'video'});
    const pg=data?.data?.page;if(!data.code&&pg&&pg.pn*pg.ps>=pg.count)ended=true;
  }
}
async function main(){
  const info=await(await fetch(`http://127.0.0.1:${req.port}/json/version`)).json();
  const ws=new WebSocket(info.webSocketDebuggerUrl),pending=new Map();let n=0,sid,target;
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});
  function send(method,params={},session=sid){return new Promise((resolve,reject)=>{
    const id=++n,timer=setTimeout(()=>{pending.delete(id);reject(new Error(`浏览器命令超时：${method}`))},15000);
    pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params,...(session?{sessionId:session}:{})}));
  })}
  const bodies=new Map(),media=new Set();let tasks=[];
  ws.onmessage=event=>{
    const m=JSON.parse(event.data);
    if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);clearTimeout(p.timer);if(m.error)p.reject(new Error(m.error.message));else p.resolve(m.result);return}
    if(m.sessionId!==sid)return;
    if(m.method==='Network.responseReceived'){
      const p=m.params,u=p.response.url;
      if(req.platform==='bilibili'&&/x\/space\/.*arc\/search/.test(u)&&p.response.status>=400)apiError=`B站作者列表返回 HTTP ${p.response.status}。请打开B站专用浏览器检查登录或原网页提示，再重试；没有取得列表不代表作者没有作品。`;
      if(/aweme\/(post|detail)|x\/space\/.*arc\/search/.test(u)&&p.response.mimeType?.includes('json'))bodies.set(p.requestId,u);
      if((p.type==='Media'||/^video\//.test(p.response.mimeType))&&/^https:\/\//.test(u))media.add(u);
    }
    if(m.method==='Network.loadingFinished'&&bodies.has(m.params.requestId)){
      const id=m.params.requestId,url=bodies.get(id);bodies.delete(id);
      const task=send('Network.getResponseBody',{requestId:id}).then(r=>{const text=r.base64Encoded?Buffer.from(r.body,'base64').toString():r.body;try{ingest(JSON.parse(text),url)}catch{}}).catch(()=>{});
      tasks.push(task);
    }
  };
  const evaluate=async expression=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error('原页面数据暂不可读取，请打开登录浏览器检查。');
    return r.result?.value;
  };
  try{
    target=(await send('Target.createTarget',{url:'about:blank'},null)).targetId;
    sid=(await send('Target.attachToTarget',{targetId:target,flatten:true},null)).sessionId;
    await send('Network.enable');await send('Page.enable');
    requestMid=req.platform==='bilibili'&&req.mode==='author'?new URL(req.url).pathname.split('/').filter(Boolean)[0]:'';
    await send('Page.navigate',{url:req.url});
    let state={};
    for(let i=0;i<20;i++){
      await sleep(1000);
      state=await evaluate(`(()=>{const vs=[...document.querySelectorAll('video')].sort((a,b)=>{const x=a.getBoundingClientRect(),y=b.getBoundingClientRect();return y.width*y.height-x.width*x.height});const v=vs[0];if(v){v.muted=true;v.play().catch(()=>{})}return {url:location.href,title:document.title,duration:v&&Number.isFinite(v.duration)?v.duration:0,src:v?.currentSrc||'',text:document.body?.innerText?.slice(0,400)||''}})()`);
      const final=new URL(state.url||req.url);
      if(!['douyin.com','bilibili.com','b23.tv'].some(d=>final.hostname===d||final.hostname.endsWith('.'+d)))throw new Error('页面跳转到其他站点，已停止提取。');
      if(req.mode==='author'){if(i>=5)break}
      else if(state.duration>0&&i>=5)break;
    }
    if(req.platform==='douyin'){
      const found=await evaluate(`${adapterCode};(()=>{const out=[];const emit=p=>out.push(p);for(const r of [window._ROUTER_DATA,window.__INITIAL_STATE__,window.__NEXT_DATA__])try{NeoDouyinExtract.walk(r,emit,'页面作品数据',14)}catch{};for(const el of document.querySelectorAll('script[type="application/json"],script#RENDER_DATA')){try{let t=el.textContent;try{t=decodeURIComponent(t)}catch{};NeoDouyinExtract.walk(JSON.parse(t),emit,'页面JSON',14)}catch{}}return out})()`);
      for(const p of found||[])posts.set(p.postId,p);
    }
    if(req.mode==='author'){
      let still=0,turns=0,last=posts.size;
      while(!ended&&still<4&&(!req.pages||turns<req.pages)){
        await evaluate(`(()=>{const els=[...document.querySelectorAll('*')].filter(e=>e.scrollHeight>e.clientHeight+200&&e.clientHeight>250&&getComputedStyle(e).overflowY!=='hidden');const sc=els.sort((a,b)=>b.clientHeight-a.clientHeight)[0];if(sc)sc.scrollTop=sc.scrollHeight;window.scrollTo(0,document.body.scrollHeight);return true})()`);
        await sleep(2200);await Promise.all(tasks);tasks=[];
        still=posts.size===last?still+1:0;last=posts.size;turns++;
        if(apiError)break;
      }
      let list=[...posts.values()].filter(p=>p.kind==='video');
      if(req.platform==='douyin'){
        const author=new URL(req.url).pathname.split('/')[2];
        list=list.filter(p=>p.author?.url&&new URL(p.author.url).pathname.split('/')[2]===author);
      }else{
        for(const p of list){
          const data=await evaluate(`fetch('https://api.bilibili.com/x/web-interface/view?bvid=${p.postId}',{credentials:'include'}).then(r=>r.json())`);
          if(data?.code===0&&String(data.data.owner?.mid)===requestMid){p.likeCount=data.data.stat?.like??null;p.likePrecision=Number.isSafeInteger(p.likeCount)?'exact':'unknown'}
          await sleep(120);
        }
      }
      console.log(JSON.stringify({status:'ok',mode:'author',posts:list.map(p=>({id:p.postId,url:p.sourceUrl,title:p.caption||p.title,author:p.author?.name,likes:p.likeCount,precision:p.likePrecision})),complete:ended&&!apiError,pages:pageCount,message:apiError||(ended?'已观察到列表末页。':'未观察到明确末页，仅展示已取得的作品。')}));
      return;
    }
    await Promise.all(tasks);
    if(req.platform==='bilibili'){
      const data=await evaluate(`(async()=>{
        let video=window.__INITIAL_STATE__?.videoData,play=window.__playinfo__?.data;
        const bvid=location.pathname.match(/video\\/(BV[A-Za-z0-9]+)/)?.[1];
        if(!video&&bvid){const r=await fetch('https://api.bilibili.com/x/web-interface/view?bvid='+bvid,{credentials:'include'}).then(r=>r.json());if(r.code===0)video=r.data}
        const part=Number(new URL(location.href).searchParams.get('p')||1);
        const cid=video?.pages?.find(x=>x.page===part)?.cid||video?.cid;
        if(!play&&video?.bvid&&cid){const r=await fetch('https://api.bilibili.com/x/player/playurl?bvid='+video.bvid+'&cid='+cid+'&qn=127&fnval=4048&fourk=1',{credentials:'include'}).then(r=>r.json());if(r.code===0)play=r.data}
        return {video,play,url:location.href}
      })()`);
      const v=data?.video,play=data?.play;
      if(!v?.bvid||!play)throw new Error('B站没有提供可用播放数据，请检查专用浏览器是否能正常播放。');
      if(v.is_upower_exclusive||v.rights?.is_cooperation===1&&v.duration===0)throw new Error('此作品需要额外权限，请在原站确认可完整播放。');
      const dash=play.dash,part=Number(new URL(state.url||req.url).searchParams.get('p')||1),selected=v.pages?.find(x=>x.page===part);
      console.log(JSON.stringify({status:'ok',platform:'bilibili',id:v.bvid+'_p'+part,title:v.title+(v.pages?.length>1?' · '+(selected?.part||'第'+part+'P'):''),author:v.owner?.name,authorUrl:v.owner?.mid?'https://space.bilibili.com/'+v.owner.mid:'',likes:v.stat?.like,duration:selected?.duration||v.duration,url:`https://www.bilibili.com/video/${v.bvid}`+(part>1?'?p='+part:''),
        videoUrls:dash?(dash.video||[]).flatMap(x=>[x.baseUrl||x.base_url,...(x.backupUrl||x.backup_url||[])]): (play.durl||[]).flatMap(x=>[x.url,...(x.backup_url||[])]),
        audioUrls:dash?(dash.audio||[]).flatMap(x=>[x.baseUrl||x.base_url,...(x.backupUrl||x.backup_url||[])]):[],separate:!!dash,multiPart:(play.durl?.length||0)>1}));
    }else{
      const id=new URL(state.url||req.url).pathname.match(/\/(?:video|note)\/(\d+)/)?.[1]||new URL(req.url).searchParams.get('modal_id')||new URL(req.url).pathname.match(/\/video\/(\d+)/)?.[1];
      if(!id)throw new Error('未解析出单条抖音作品，请提供该视频的分享链接。');
      const expected=new URL(req.url).pathname.match(/\/video\/(\d+)/)?.[1];
      if(expected&&expected!==id)throw new Error('页面跳转到了另一条作品，已停止，避免下载错片。');
      const p=posts.get(id);if(p?.restricted)throw new Error('页面显示付费或预览作品，请在原站确认权限。');
      const perf=await evaluate(`performance.getEntriesByType('resource').map(x=>x.name).filter(x=>/douyinvod|mime_type=video|mime_type=audio/.test(x))`);
      const observed=[...new Set([state.src,...media,...(perf||[])].filter(x=>/^https:\/\//.test(x||'')))];
      const structured=(p?.media||[]).flatMap(m=>m.urls||[]);
      const videos=[...new Set([...structured,...observed.filter(x=>!/mime_type=audio|media-audio/.test(x))])];
      const audios=observed.filter(x=>/mime_type=audio|media-audio/.test(x));
      if(!videos.length&&!audios.length)throw new Error('未取得媒体地址，请检查专用浏览器登录、验证码或播放状态。');
      console.log(JSON.stringify({status:'ok',platform:'douyin',id,title:p?.caption||p?.title||state.title,author:p?.author?.name||'',authorUrl:p?.author?.url||'',likes:p?.likeCount??null,
        duration:(p?.media?.[0]?.durationMs||0)/1000||state.duration,url:`https://www.douyin.com/video/${id}`,videoUrls:videos,audioUrls:audios,separate:false}));
    }
  }finally{
    if(target)try{await send('Target.closeTarget',{targetId:target},null)}catch{}
    for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error('浏览器连接已关闭'))}pending.clear();ws.close();
  }
}
main().catch(e=>{console.log(JSON.stringify({status:'error',error:e.message}));process.exitCode=1});

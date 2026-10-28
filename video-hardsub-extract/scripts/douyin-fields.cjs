/* Original field adapter. Reads already available public work data, not cookies. */
(function (scope) {
  'use strict';
  const urls = obj => (Array.isArray(obj) ? obj : obj?.url_list || obj?.urlList || (obj?.url ? [obj.url] : []))
    .filter(x=>typeof x==='string' && /^(https:)?\/\//.test(x)).map(x=>x.startsWith('//')?'https:'+x:x).slice(0,8);
  const pick = (obj, snake, camel) => obj?.[snake] ?? obj?.[camel];
  function normalize(raw, evidence='页面作品数据') {
    const id = String(pick(raw,'aweme_id','awemeId') ?? raw?.itemId ?? '');
    if (!/^\d{10,24}$/.test(id)) return null;
    const desc = raw.desc ?? raw.description;
    const images = raw.images || raw.image_post_info?.images || raw.imagePostInfo?.images;
    const video = raw.video;
    if (!images?.length && !video) return null;
    const imageType = [68,150].includes(Number(pick(raw,'aweme_type','awemeType')));
    if (imageType && !images?.length) return null; // Never accept a gallery cover as a video.
    const kind = images?.length ? 'images' : 'video';
    const author = raw.author || raw.authorInfo || {};
    const sec = pick(author,'sec_uid','secUid') || '';
    const media = kind==='images' ? images.map(im=>({urls:urls(im.display_image || im.displayImage || im),width:im.width,height:im.height,quality:'页面图集地址'})) : [{
      urls:urls(video.play_addr || video.playAddr || video.playAddrH264),width:video.width,height:video.height,
      durationMs:video.duration || raw.duration,quality:'页面播放地址（未去水印）'}];
    if(media.some(m=>!m.urls.length)) return null;
    const created = pick(raw,'create_time','createTime');
    const caption = typeof desc==='string' ? desc : '';
    const likes = raw.statistics?.digg_count ?? raw.statistics?.diggCount ?? raw.stats?.diggCount;
    const exactLikes = (typeof likes === 'number' && Number.isSafeInteger(likes) && likes >= 0) || (typeof likes === 'string' && /^\d{1,12}$/.test(likes));
    const stats=raw.statistics||raw.stats||{},checkedAt=new Date().toISOString();
    const interactions={checkedAt,kind:'collection'};
    for(const [name,snake,camel] of [['likes','digg_count','diggCount'],['comments','comment_count','commentCount'],['favorites','collect_count','collectCount'],['shares','share_count','shareCount']]){
      const v=pick(stats,snake,camel),exact=(typeof v==='number'&&Number.isSafeInteger(v)&&v>=0)||(typeof v==='string'&&/^\d{1,12}$/.test(v));
      interactions[name]={value:exact?Number(v):null,raw:String(v??''),precision:exact?'exact':'unknown',evidence:'页面作品 statistics.'+snake};
    }
    const topics=(raw.text_extra||raw.textExtra||[]).map(t=>t.hashtag_name||t.hashtagName).filter(Boolean);
    return {postId:id,sourcePlatform:'douyin',sourceUrl:`https://www.douyin.com/${kind==='images'?'note':'video'}/${id}`,
      author:{name:author.nickname || author.nickName || '',id:String(author.uid || author.unique_id || author.uniqueId || ''),url:sec?`https://www.douyin.com/user/${sec}`:''},
      title: raw.item_title || raw.itemTitle || '', caption,
      captionStatus:typeof desc==='string'?(desc.length?'complete':'empty'):'missing',captionEvidence:evidence,
      likeCount:exactLikes?Number(likes):null,likePrecision:exactLikes?'exact':'unknown',likeRaw:String(likes??''),
      likeEvidence:exactLikes?'页面作品 statistics.digg_count 字段':'未取得准确点赞数',likeCheckedAt:new Date().toISOString(),
      tags:topics.length?topics:[...caption.matchAll(/#[^\s#，。！？；：、,.!?;:]+/gu)].map(x=>x[0]),interactions,kind,expectedMediaCount:media.length,media,
      publishedAt:created && Number.isFinite(Number(created)) ? new Date(Number(created)*1000).toISOString() : '',
      restricted:!!(raw.is_paid || raw.isPaid || raw.is_series_paid || raw.isSeriesPaid || raw.is_preview || raw.isPreview || raw.paid_video_info?.pay_status===0)};
  }
  function walk(root, emit, evidence, maxDepth=9, observe) {
    const seen = new WeakSet(); let budget=18000;
    function visit(value,depth) {
      if(!value || typeof value!=='object' || depth>maxDepth || --budget<0 || seen.has(value)) return;
      seen.add(value);
      try {
        const id=String(pick(value,'aweme_id','awemeId')??value.itemId??'');
        if(observe&&/^\d{10,24}$/.test(id))observe({postId:id,fields:Object.keys(value).slice(0,60),
          authorFields:Object.keys(value.author||value.authorInfo||{}).slice(0,40),
          videoFields:Object.keys(value.video||{}).slice(0,40)});
        const post=normalize(value,evidence); if(post) {emit(post);return;}
      } catch {}
      for(const key of Object.keys(value)) {
        if(['return','stateNode','_owner','alternate','session','cookie','token','userInfo','user_info'].includes(key)) continue;
        try {if(typeof value[key]==='object')visit(value[key],depth+1);} catch {}
      }
    }
    visit(root,0);
  }
  scope.NeoDouyinExtract = {normalize,walk};
  if(typeof module!=='undefined')module.exports={normalize,walk};
})(typeof window==='undefined'?globalThis:window);

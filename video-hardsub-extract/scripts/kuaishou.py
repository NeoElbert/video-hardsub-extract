"""Read the public mobile share page's single photo object; no account or cookie export."""
import json
import re
from urllib.parse import urlsplit
from urllib.request import Request,urlopen

UA='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'


def resolve(url):
    with urlopen(Request(url,headers={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}),timeout=25) as response:
        final=response.url
        page=response.read().decode('utf-8')
    host=urlsplit(final).hostname or ''
    if not any(host==d or host.endswith('.'+d) for d in ('kuaishou.com','gifshow.com','chenzhongtech.com')):
        raise ValueError('快手分享页跳转到了其他站点。')
    original=re.search(r'/(?:short-video|fw/photo)/([A-Za-z0-9_-]+)',url)
    resolved=re.search(r'/(?:short-video|fw/photo)/([A-Za-z0-9_-]+)',final)
    if not resolved or (original and original.group(1)!=resolved.group(1)):
        raise ValueError('无法确认快手目标作品身份。')
    match=re.search(r'window\.INIT_STATE\s*=\s*',page)
    if not match:
        title=re.findall(r'<title>(.*?)</title>',page)
        raise ValueError(f'快手页面没有公开作品数据，可能需要登录或页面已变化。host={host}, bytes={len(page)}, title={title}')
    state,_=json.JSONDecoder().raw_decode(page[match.end():])
    photos=[]
    for value in state.values():
        if isinstance(value,dict) and isinstance(value.get('photo'),dict):
            photo=value['photo']
            if photo.get('mainMvUrls'): photos.append(photo)
    if len(photos)!=1: raise ValueError('分享页没有唯一的视频作品，未选择推荐内容。')
    photo=photos[0]
    urls=[v['url'] for v in photo['mainMvUrls'] if isinstance(v,dict) and v.get('url')]
    if not urls: raise ValueError('快手作品没有可用的视频地址。')
    return dict(id=resolved.group(1),numeric_id=str(photo.get('photoId','')),
                title=photo.get('caption',''),extractor='kuaishou-share',
                duration=photo.get('duration'),urls=urls,headers={'User-Agent':UA,'Referer':final})

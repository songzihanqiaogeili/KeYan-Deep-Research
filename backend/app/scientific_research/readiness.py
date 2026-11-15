"""Non-generating local Ollama check; remote configuration is not a health claim."""
import os
from urllib.parse import urlsplit
import httpx


async def model_status():
    model=os.environ.get('SCIENTIFIC_LLM_MODEL')
    configured=bool(model and os.environ.get('SCIENTIFIC_LLM_API_KEY'))
    value={'model_configured':configured,'model':model if configured else None,
           'model_ready':None,'model_status':'configured' if configured else 'unconfigured',
           'model_message':'模型已配置；尚未检查远程服务可用性。' if configured else '尚未配置真实模型，可先体验合成演示。'}
    if not configured: return value
    endpoint=urlsplit(os.environ.get('SCIENTIFIC_LLM_BASE_URL') or '')
    if endpoint.hostname not in {'127.0.0.1','localhost','::1'} or endpoint.port!=11434:
        return value
    try:
        async with httpx.AsyncClient(timeout=2,trust_env=False,follow_redirects=False) as client:
            response=await client.get(f'{endpoint.scheme}://{endpoint.netloc}/api/tags')
            response.raise_for_status()
            names={p.get('name') or p.get('model') for p in response.json()['models']}
        exists=model in names or (':' not in model and model+':latest' in names)
        value.update(model_ready=exists,model_status='ready' if exists else 'model_missing',
            model_message=('本机 Ollama 已启动，模型可用：'+model if exists else
                           'Ollama 中未找到模型 '+model+'。请确认模型已安装及模型存储目录正确；系统不会自动下载。'))
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        value.update(model_ready=False,model_status='unavailable',
                     model_message='无法连接本机 Ollama。请先启动 Ollama，再重新连接科研工作台。')
    return value

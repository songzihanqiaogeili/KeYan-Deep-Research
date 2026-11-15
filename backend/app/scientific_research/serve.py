"""Run the local single-user scientific workbench."""
import argparse
import os
import threading
import webbrowser
from pathlib import Path


def main():
    from .config import load_project_env, local_access_token
    load_project_env()
    import uvicorn
    from .webapp import create_app
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--open-existing',action='store_true',help='Open an already running workbench without starting another worker')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Port must be 1024–65535')
    os.environ['SCIENTIFIC_LOCAL_TOKEN'] = local_access_token(args.data_dir)
    url = f'http://127.0.0.1:{args.port}'
    if args.open_existing:
        import json
        import urllib.request
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url+'/healthz',timeout=3) as response:
            if json.load(response).get('service')!='scientific-research-workbench':
                parser.error('This port does not host the scientific workbench')
        token=os.environ.get('SCIENTIFIC_LOCAL_TOKEN')
        webbrowser.open(f'{url}/#access_token={token}' if token else url)
        return
    app = create_app(data_dir=args.data_dir)
    print(f'\nScientific Research Workbench: {url}', flush=True)
    print(f'Local access token: {app.state.access_token}', flush=True)
    print('Use Ctrl+C to stop. Running tasks become interrupted; resume explicitly in the UI.\n', flush=True)
    if args.open:
        timer = threading.Timer(1.5, lambda: webbrowser.open(f'{url}/#access_token={app.state.access_token}'))
        timer.daemon = True
        timer.start()
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')


if __name__ == '__main__':
    main()

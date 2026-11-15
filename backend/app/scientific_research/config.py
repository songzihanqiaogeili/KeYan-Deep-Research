"""Optional project-local scientific settings; explicit process settings win."""
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
ALLOWED=frozenset({'SCIENTIFIC_LLM_API_KEY','SCIENTIFIC_LLM_MODEL','SCIENTIFIC_LLM_BASE_URL',
                   'SCIENTIFIC_LOCAL_TOKEN','SCIENTIFIC_DATA_DIR','SCIENTIFIC_LLM_TIMEOUT',
                   'SCIENTIFIC_EMBEDDING_MODEL','SCIENTIFIC_EMBEDDING_BASE_URL',
                   'SCIENTIFIC_LANGSMITH_ENABLED','LANGSMITH_API_KEY','LANGSMITH_PROJECT',
                   'LANGSMITH_ENDPOINT'})


def load_project_env(path=None):
    path=Path(path) if path is not None else ROOT/'.env.scientific'
    if not path.is_file():
        return
    if path.stat().st_size>65536:
        raise ValueError('Scientific settings file exceeds 64 KiB')
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key,value=line.split('=',1)
        key,value=key.strip(),value.strip()
        if key not in ALLOWED:
            continue
        if len(value)>=2 and value[0]==value[-1] and value[0] in {'"',"'"}:
            value=value[1:-1]
        else:
            value=value.split(' #',1)[0].rstrip()
        os.environ.setdefault(key,value)


def local_access_token(data_dir=None):
    """Keep launcher authentication stable across local process restarts."""
    explicit = os.environ.get('SCIENTIFIC_LOCAL_TOKEN')
    if explicit:
        return explicit
    import secrets
    directory = Path(data_dir or os.environ.get('SCIENTIFIC_DATA_DIR') or ROOT/'backend'/'data'/'scientific')
    directory.mkdir(parents=True, exist_ok=True)
    path = directory/'.access-token'
    if not path.exists():
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'w', encoding='ascii') as stream:
                stream.write(secrets.token_urlsafe(32))
    token = path.read_text(encoding='ascii').strip()
    if len(token) < 24 or len(token) > 256:
        raise ValueError('Invalid local access token file')
    return token

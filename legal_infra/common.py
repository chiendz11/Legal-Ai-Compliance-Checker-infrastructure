"""Local state, scoped kubectl calls and source/image identity helpers."""

import hashlib
import json
import os
import re
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import yaml

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / '.local'
CONTRACT = json.loads((ROOT / 'contracts/local-platform.json').read_text())
LOCK = json.loads((ROOT / 'versions/platform.lock.json').read_text())
CONTEXT = CONTRACT['context']
NAMESPACE = CONTRACT['namespace']


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def private_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(value)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save(path, value):
    private_write(path, json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def run(command, *, capture=False, stdin=None, cwd=None, env=None):
    result = subprocess.run(command, input=stdin, text=True, capture_output=capture,
                            check=True, cwd=cwd, env=env)
    return result.stdout if capture else None


def settings():
    result = load(PRIVATE / 'settings.json')
    if result.get('schema_version') != '1.0.0':
        raise ValueError('Unsupported local settings version')
    return result


def checkout(kind):
    path = (ROOT / settings()[kind + '_checkout']).resolve(strict=True)
    if kind == 'gitops':
        if (path / 'contracts/local-platform.json').read_bytes() != (ROOT / 'contracts/local-platform.json').read_bytes():
            raise ValueError('GitOps checkout has a different local platform contract')
    elif not (path / 'backend/src/legal_checker/main.py').is_file():
        raise ValueError('Application checkout is not Legal AI Compliance Checker')
    return path


def owner():
    marker = load(PRIVATE / 'cluster-owner.json')
    if marker.get('context') != CONTEXT or marker.get('config_sha256') != sha(PRIVATE / 'k3d.yaml'):
        raise ValueError('Cluster ownership/config changed; do not adopt it automatically')
    data = yaml.safe_load((PRIVATE / 'kubeconfig').read_text())
    contexts = {item['name']: item['context'] for item in data['contexts']}
    clusters = {item['name']: item['cluster'] for item in data['clusters']}
    selected = contexts[CONTEXT]
    if clusters[selected['cluster']]['server'] != CONTRACT['api_server']:
        raise ValueError('Private kubeconfig must target the fixed Legal Checker loopback API')
    return marker


def kube_command(*arguments, namespace=NAMESPACE):
    owner()
    if namespace not in {NAMESPACE, CONTRACT['argocd_namespace']}:
        raise ValueError('Namespace is outside the local contract')
    return ['kubectl', '--kubeconfig', str(PRIVATE / 'kubeconfig'), '--context', CONTEXT,
            '--namespace', namespace, *arguments]


def kube(*arguments, capture=False, stdin=None, namespace=NAMESPACE):
    return run(kube_command(*arguments, namespace=namespace), capture=capture, stdin=stdin)


def apply(documents, *, namespace=NAMESPACE):
    # Never put secret values in process arguments or committed manifests.
    return kube('apply', '-f', '-', namespace=namespace,
                stdin=yaml.safe_dump_all(documents, sort_keys=False))


def source_identity(path):
    revision = run(['git', '-C', str(path), 'rev-parse', 'HEAD'], capture=True).strip()
    dirty = bool(run(['git', '-C', str(path), 'status', '--porcelain'], capture=True).strip())
    names = run(['git', '-C', str(path), 'ls-files', '-z', '--cached', '--others',
                 '--exclude-standard'], capture=True).split('\0')
    digest = hashlib.sha256()
    for name in sorted(set(names) - {''}):
        file = path / name
        value = os.readlink(file).encode() if file.is_symlink() else (
            file.read_bytes() if file.is_file() else b'<deleted>')
        digest.update(name.encode() + b'\0' + hashlib.sha256(value).digest())
    return {'git_sha': revision, 'dirty': dirty, 'snapshot_sha256': digest.hexdigest()}


def image_receipt():
    result = load(PRIVATE / 'backend-image.json')
    identity = result['image_id']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', identity):
        raise ValueError('Missing real Docker image identity')
    if result['image'] != 'legal-local/backend:image-' + identity[7:]:
        raise ValueError('Image alias differs from its recorded Docker identity')
    return result


def imported_image():
    result = image_receipt()
    if result.get('imported_cluster_id') != owner()['cluster_id']:
        raise ValueError('Import this image into the current cluster before using it')
    return result


def database_url(host='postgres', port=5432):
    credentials = load(PRIVATE / 'credentials.json')
    database = CONTRACT['database']
    return (f"postgresql://{quote(database['user'], safe='')}:{quote(credentials['postgres_password'], safe='')}"
            f"@{host}:{port}/{database['name']}")


def free_port(port):
    with socket.socket() as stream:
        stream.bind(('127.0.0.1', port))


@contextmanager
def database_forward():
    port = CONTRACT['ports']['postgres']
    free_port(port)
    process = subprocess.Popen(kube_command('port-forward', '--address=127.0.0.1',
                               'service/postgres', f'{port}:5432'),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError('PostgreSQL port-forward exited before it was ready')
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.5)
        else:
            raise TimeoutError('PostgreSQL port-forward did not become ready')
        yield database_url('127.0.0.1', port)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

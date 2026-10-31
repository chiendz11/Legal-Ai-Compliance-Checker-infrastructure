"""Authoring is separate from execution: every cluster/build/data operation is explicit."""

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .common import (CONTRACT, CONTEXT, LOCK, NAMESPACE, PRIVATE, ROOT, apply,
                     checkout, database_forward, database_url, image_receipt,
                     imported_image, kube, load, owner,
                     private_write, run, save, settings, sha, source_identity)


def initialize(_):
    PRIVATE.mkdir(mode=0o700, exist_ok=True)
    os.chmod(PRIVATE, 0o700)
    (PRIVATE / 'storage').mkdir(exist_ok=True)
    for name, value in {
        'settings.json': load(ROOT / 'config/settings.example.json'),
        'credentials.json': {'postgres_password': secrets.token_hex(24),
                             'redis_password': secrets.token_hex(24)},
    }.items():
        if not (PRIVATE / name).exists():
            save(PRIVATE / name, value)
    rendered = (ROOT / 'config/k3d.yaml').read_text().replace(
        '__K3S_IMAGE__', LOCK['images']['k3s']).replace(
        '__LOCAL_STORAGE__', str((PRIVATE / 'storage').resolve()))
    path = PRIVATE / 'k3d.yaml'
    if path.exists() and path.read_text() != rendered:
        raise ValueError('Existing local cluster config differs; review before replacing it')
    if not path.exists():
        private_write(path, rendered)
    print('Private settings/config ready; no cluster has been created or changed')


def up(_):
    if not (PRIVATE / 'settings.json').exists():
        raise ValueError('Run init first')
    actual = run(['k3d', 'version'], capture=True)
    if 'v' + LOCK['k3d_version'] not in actual:
        raise ValueError('Install the k3d version recorded in versions/platform.lock.json')
    clusters = json.loads(run(['k3d', 'cluster', 'list', '--output', 'json'], capture=True))
    if any(item['name'] == CONTRACT['cluster_name'] for item in clusters):
        owner()
        print('Existing cluster belongs to this bootstrap; no recreation performed')
        return
    if (PRIVATE / 'cluster-owner.json').exists():
        raise ValueError('Owned cluster disappeared; preserve/restore state before a fresh bootstrap')
    run(['k3d', 'cluster', 'create', '--config', str(PRIVATE / 'k3d.yaml')])
    config = run(['k3d', 'kubeconfig', 'get', CONTRACT['cluster_name']], capture=True)
    private_write(PRIVATE / 'kubeconfig', config)
    save(PRIVATE / 'cluster-owner.json', {'context': CONTEXT, 'cluster_id': str(uuid.uuid4()),
                                         'config_sha256': sha(PRIVATE / 'k3d.yaml')})
    owner()
    print('Created only the Legal Checker cluster and private kubeconfig')


def install_secrets(_):
    owner()
    for namespace in (NAMESPACE, CONTRACT['argocd_namespace']):
        apply([{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {
            'name': namespace, 'labels': {'legal-checker.io/bootstrap-owner': 'infrastructure'}}}])
    credentials = load(PRIVATE / 'credentials.json')
    database = CONTRACT['database']
    for name, values in {
        database['secret']: {'POSTGRES_USER': database['user'], 'POSTGRES_DB': database['name'],
                             'POSTGRES_PASSWORD': credentials['postgres_password'],
                             'DATABASE_URL': database_url()},
        'legal-redis': {'password': credentials['redis_password']},
    }.items():
        apply([{'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': name, 'namespace': NAMESPACE},
                'type': 'Opaque', 'stringData': values}])
    print('Local secrets applied; existing private credentials were preserved')


def install_argocd(_):
    install_secrets(None)
    pin = LOCK['argocd']
    with urllib.request.urlopen(pin['url'], timeout=30) as response:
        raw = response.read(3_000_001)
    if hashlib.sha256(raw).hexdigest() != pin['sha256']:
        raise ValueError('Argo installer checksum differs from its recorded pin')
    documents = list(yaml.safe_load_all(raw))

    def pinned_images(value):
        if isinstance(value, dict):
            if isinstance(value.get('image'), str):
                value['image'] = pin['images'][value['image']]
            for item in value.values():
                pinned_images(item)
        elif isinstance(value, list):
            for item in value:
                pinned_images(item)

    pinned_images(documents)
    kube('apply', '--server-side', '--field-manager=legal-local-bootstrap', '-f', '-',
         namespace=CONTRACT['argocd_namespace'], stdin=yaml.safe_dump_all(documents))
    for target in ('deployment/argocd-server', 'deployment/argocd-repo-server',
                   'statefulset/argocd-application-controller'):
        kube('rollout', 'status', target, '--timeout=300s', namespace=CONTRACT['argocd_namespace'])
    print('Argo installed; no GitOps Applications were attached or synchronized')


def attach_gitops(_):
    config = settings()
    remote = config['gitops_repository']
    parsed = urlsplit(remote or '')
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not parsed.path.endswith('.git')):
        raise ValueError('Set a real published HTTPS .git repository URL in private settings first')
    branch = config['gitops_revision']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', branch) or '..' in branch:
        raise ValueError('Use an explicit Git branch name')
    gitops = checkout('gitops')
    if run(['git', '-C', str(gitops), 'status', '--porcelain'], capture=True).strip():
        raise ValueError('Review/commit/push GitOps before attaching Argo')
    local_sha = run(['git', '-C', str(gitops), 'rev-parse', 'HEAD'], capture=True).strip()
    remote_tip = run(['git', 'ls-remote', remote, 'refs/heads/' + branch], capture=True).split()
    if not remote_tip or remote_tip[0] != local_sha:
        raise ValueError('Published branch does not match the reviewed GitOps checkout')
    project = {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'AppProject',
               'metadata': {'name': 'legal-checker-local', 'namespace': 'argocd'},
               'spec': {'sourceRepos': [remote], 'destinations': [
                   {'server': 'https://kubernetes.default.svc', 'namespace': NAMESPACE}],
                   'clusterResourceWhitelist': [],
                   'namespaceResourceBlacklist': [{'group': '', 'kind': 'Secret'},
                     {'group': 'argoproj.io', 'kind': 'Application'},
                     {'group': 'argoproj.io', 'kind': 'AppProject'}]}}
    applications = [project]
    for name, path in CONTRACT['applications'].items():
        sync_policy = {
            'automated': {'prune': False, 'selfHeal': True},
            'syncOptions': ['CreateNamespace=false', 'FailOnSharedResource=true'],
        }
        applications.append({'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application',
             'metadata': {'name': 'legal-checker-' + name, 'namespace': 'argocd'},
             'spec': {'project': 'legal-checker-local',
                      'source': {'repoURL': remote, 'targetRevision': branch, 'path': path},
                      'destination': {'server': 'https://kubernetes.default.svc', 'namespace': NAMESPACE},
                      'syncPolicy': sync_policy}})
    apply(applications, namespace='argocd')
    print('Two Applications attached in AUTOMATED sync mode (Argo CD will auto-sync GitOps commits)')


def build(args):
    source = checkout('app')
    before = source_identity(source)
    if before['dirty'] and not args.allow_dirty:
        raise ValueError('Commit app changes first, or explicitly use --allow-dirty for local-only evidence')
    temporary = 'legal-local/backend:build-' + before['snapshot_sha256'][:16]
    run(['docker', 'build', '--file', str(source / 'backend/Dockerfile'), '--tag', temporary,
         '--label', 'org.opencontainers.image.revision=' + before['git_sha'], str(source)])
    if source_identity(source) != before:
        raise ValueError('Application source changed during build; no receipt was written')
    identity = json.loads(run(['docker', 'image', 'inspect', temporary], capture=True))[0]['Id']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', identity):
        raise ValueError('Docker did not return an actual image ID')
    alias = 'legal-local/backend:image-' + identity[7:]
    run(['docker', 'tag', identity, alias])
    save(PRIVATE / 'backend-image.json', {'schema_version': '1.0.0', 'image': alias,
         'image_id': identity, 'source': before, 'dockerfile_sha256': sha(source / 'backend/Dockerfile')})
    print('Built backend image; private receipt records the real Docker ID and source snapshot')


def import_image(_):
    receipt = image_receipt()
    marker = owner()
    actual = json.loads(run(['docker', 'image', 'inspect', receipt['image']], capture=True))[0]['Id']
    if actual != receipt['image_id']:
        raise ValueError('Local image tag no longer matches its receipt')
    run(['k3d', 'image', 'import', '--cluster', CONTRACT['cluster_name'], receipt['image']])
    receipt['imported_context'] = CONTEXT
    receipt['imported_cluster_id'] = marker['cluster_id']
    save(PRIVATE / 'backend-image.json', receipt)


def migrate(_):
    receipt = imported_image()
    job = yaml.safe_load((checkout('gitops') / 'operations/migrations/job.yaml').read_text())
    name = 'legal-db-migrate-' + secrets.token_hex(4)
    job['metadata'].update(name=name, namespace=NAMESPACE)
    job['spec']['template']['spec']['containers'][0]['image'] = receipt['image']
    apply([job])
    try:
        kube('wait', '--for=condition=complete', 'job/' + name, '--timeout=600s')
    finally:
        kube('logs', 'job/' + name)
    save(PRIVATE / 'migration.json', {'job': name, 'image_id': receipt['image_id'],
                                      'cluster_id': owner()['cluster_id']})


def seed(args):
    source = checkout('app')
    receipt = imported_image()
    if source_identity(source) != receipt['source']:
        raise ValueError('Seed code must match the source used to build the imported image')
    manifest = load(source / 'configs/dataset_dev_validation.json')
    workbook = Path(args.workbook).expanduser().resolve(strict=True)
    if manifest['distribution'] != 'DEV_VALIDATION' or workbook.name != manifest['workbook']:
        raise ValueError('Use the pinned DEV_VALIDATION workbook, never MASTER/TEST answers')
    if sha(workbook) != manifest['required_files'][workbook.name]:
        raise ValueError('DEV_VALIDATION workbook checksum differs from the app manifest')
    python = source / '.venv/bin/python'
    if not python.is_file():
        raise ValueError('Create the app .venv and install backend[dev] before seeding')
    program = '''import json,os,sys
from pathlib import Path
from devtools.database_seed import read_workbook,seed_database
from legal_checker.modules.legal_knowledge.repository import Knowledge
result=seed_database(os.environ['DATABASE_URL'],read_workbook(Path(sys.argv[1])))
knowledge=Knowledge(os.environ['DATABASE_URL'])
print(json.dumps({'seed_result':result,'knowledge_snapshot_sha256':knowledge.sha256}))
'''
    with database_forward() as url:
        result = json.loads(run([str(python), '-c', program, str(workbook)], capture=True,
                            cwd=source, env={**os.environ, 'DATABASE_URL': url}))
    if result['knowledge_snapshot_sha256'] != manifest['knowledge_snapshot_sha256']:
        raise ValueError('Seeded knowledge hash differs; review data instead of enabling backend')
    save(PRIVATE / 'seed.json', {'schema_version': '1.0.0', 'cluster_id': owner()['cluster_id'],
         'image_id': receipt['image_id'], 'workbook_sha256': sha(workbook),
         'distribution': 'DEV_VALIDATION', **result})
    print('Seed recorded with app-owned importer; backend remains disabled in GitOps')


def prepare(args):
    if args.target == 'backend':
        imported_image()
        if args.redis:
            raise ValueError('--redis applies only to prepare platform')
    gitops = checkout('gitops')
    command = [sys.executable, '-m', 'legal_gitops.release', args.target]
    if args.target == 'backend':
        command += ['--image-receipt', str(PRIVATE / 'backend-image.json'),
                    '--seed-receipt', str(PRIVATE / 'seed.json')]
    elif args.redis:
        command.append('--redis')
    run(command, cwd=gitops)
    print('Prepared GitOps files only; review/commit/push and sync explicitly')


def forward(args):
    targets = {'backend': ('service/legal-backend', 8000, NAMESPACE),
               'postgres': ('service/postgres', 5432, NAMESPACE),
               'redis': ('service/redis', 6379, NAMESPACE),
               'argocd': ('service/argocd-server', 443, 'argocd')}
    target, remote, namespace = targets[args.target]
    local = CONTRACT['ports'][args.target]
    kube('port-forward', '--address=127.0.0.1', target, f'{local}:{remote}', namespace=namespace)


def status(_):
    kube('get', 'pods,services,pvc')
    kube('get', 'applications', namespace='argocd')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    functions = {'init': initialize, 'up': up, 'secrets': install_secrets,
                 'install-argocd': install_argocd, 'attach-gitops': attach_gitops,
                 'import-image': import_image, 'migrate': migrate, 'status': status}
    for name, function in functions.items():
        commands.add_parser(name).set_defaults(function=function)
    child = commands.add_parser('build-image')
    child.add_argument('--allow-dirty', action='store_true')
    child.set_defaults(function=build)
    child = commands.add_parser('seed')
    child.add_argument('--workbook', required=True)
    child.set_defaults(function=seed)
    child = commands.add_parser('prepare')
    child.add_argument('target', choices=['platform', 'backend'])
    child.add_argument('--redis', action='store_true', help='Enable optional Redis in platform desired state')
    child.set_defaults(function=prepare)
    child = commands.add_parser('forward')
    child.add_argument('target', choices=['backend', 'postgres', 'redis', 'argocd'])
    child.set_defaults(function=forward)
    args = parser.parse_args()
    try:
        args.function(args)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, str(error) + '\n')

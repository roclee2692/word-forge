#!/usr/bin/env python3
"""fastpip.py: 网络慢时安装 wordseg.py 的依赖（只用标准库，装依赖之前就能跑）。

  1. 测速选源：同时请求 PyPI 官方和几个国内镜像，按响应时间挑最快的索引来解析依赖。
  2. 解析：让 pip 自己算出要装哪些包（pip install --dry-run --report），拿到文件路径和 sha256。
  3. 多源竞速 + 分段下载：每个文件切成 1 MB 的段放进队列，几个线程从不同镜像同时拉，
     快的源自然多拿段；队列空了，闲着的线程会换一个源把最慢的那段再下一遍，谁先完成算谁的。
  4. 断点续传：已完成的段记在 <文件>.part.json，中断后重跑只补缺的段。
  5. 校验 sha256 后，用 pip install --no-index 从本地目录安装。

用法：  python3 fastpip.py wordfreq cmudict [--dest DIR] [-- 其他 pip install 参数]
依赖：  无（标准库 + 当前解释器自带的 pip）
"""
import sys, os, json, time, hashlib, threading, subprocess, tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor

MIRRORS = [   # (名字, simple 索引, packages 根路径)
    ('pypi',    'https://pypi.org/simple',                              'https://files.pythonhosted.org/packages'),
    ('tuna',    'https://pypi.tuna.tsinghua.edu.cn/simple',             'https://pypi.tuna.tsinghua.edu.cn/packages'),
    ('aliyun',  'https://mirrors.aliyun.com/pypi/simple',               'https://mirrors.aliyun.com/pypi/packages'),
    ('tencent', 'https://mirrors.cloud.tencent.com/pypi/simple',        'https://mirrors.cloud.tencent.com/pypi/packages'),
    ('huawei',  'https://repo.huaweicloud.com/repository/pypi/simple',  'https://repo.huaweicloud.com/repository/pypi/packages'),
    ('ustc',    'https://mirrors.ustc.edu.cn/pypi/simple',              'https://mirrors.ustc.edu.cn/pypi/packages'),
]
CHUNK = 1 << 20          # 每段 1 MB
PROBE = 256 << 10        # 测速时每个源先拉 256 KB
WORKERS = 8
TIMEOUT = 20

def log(*a): print('[fastpip]', *a, file=sys.stderr, flush=True)

def get(url, rng=None, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={'User-Agent': 'fastpip/1.0', **({'Range': f'bytes={rng[0]}-{rng[1]}'} if rng else {})})
    return urllib.request.urlopen(req, timeout=timeout)

# ---------- 1. 测速选索引 ----------
def fastest_index(pkg):
    def probe(m):
        t = time.time()
        try:
            with get(f'{m[1]}/{pkg}/', timeout=10) as r: r.read()
            return time.time() - t, m
        except Exception:
            return None
    with ThreadPoolExecutor(len(MIRRORS)) as ex:
        ok = sorted(x for x in ex.map(probe, MIRRORS) if x)
    if not ok: sys.exit('[fastpip] 所有索引都连不上')
    log('索引响应：' + '  '.join(f'{m[0]} {t:.1f}s' for t, m in ok))
    return ok[0][1]

# ---------- 2. 让 pip 解析依赖 ----------
def resolve(pkgs, index, extra):
    rep = os.path.join(tempfile.mkdtemp(), 'report.json')
    cmd = [sys.executable, '-m', 'pip', 'install', '--dry-run', '--quiet', '--report', rep, '-i', index[1], *pkgs, *extra]
    subprocess.run(cmd, check=True)
    out = []
    for it in json.load(open(rep))['install']:
        d = it['download_info']; url = d['url']
        h = d.get('archive_info', {}).get('hashes', {}).get('sha256') or d.get('archive_info', {}).get('hash', '').partition('=')[2]
        out.append((url.rsplit('/', 1)[1], url.split('/packages/', 1)[1] if '/packages/' in url else None, url, h))
    return out

# ---------- 3. 对单个文件测速：各源下载第一段，记下速度和文件大小 ----------
def rank_sources(rel, url):
    def probe(m):
        u = f'{m[2]}/{rel}'; t = time.time()
        try:
            with get(u, (0, PROBE - 1)) as r:
                if r.status != 206: return None              # 不支持 Range 的源不参与分段
                data = r.read(); size = int(r.headers['Content-Range'].rsplit('/', 1)[1])
            return len(data) / max(time.time() - t, 1e-3), m[0], u, size, data
        except Exception:
            return None
    cands = [m for m in MIRRORS] if rel else []
    with ThreadPoolExecutor(max(1, len(cands))) as ex:
        ok = sorted((x for x in ex.map(probe, cands) if x), reverse=True)
    if not ok:                                               # 都不支持 Range：退化为整文件单源
        return [(0, 'direct', url, None, b'')]
    best = ok[0][0]
    ok = [x for x in ok if x[0] >= best / 8]                 # 比最快源慢 8 倍以上的直接淘汰
    log('  源速度：' + '  '.join(f'{x[1]} {x[0]/1024:.0f}KB/s' for x in ok))
    return ok

# ---------- 4. 多源分段下载 + 断点续传 ----------
def fetch(name, rel, url, sha, dest):
    path = os.path.join(dest, name)
    if os.path.exists(path) and (not sha or sha256(path) == sha):
        log(f'{name} 已在缓存'); return path
    log(f'{name}')
    srcs = rank_sources(rel, url)
    size = srcs[0][3]
    if size is not None and size <= PROBE:                   # 小文件：测速时已经整个下完了
        with open(path + '.part', 'wb') as f: f.write(srcs[0][4])
        return finish(path, sha)
    if size is None:                                         # 单源整文件
        with get(url, timeout=120) as r, open(path + '.part', 'wb') as f:
            while b := r.read(1 << 16): f.write(b)
        return finish(path, sha)
    part, state = path + '.part', path + '.part.json'
    n = (size + CHUNK - 1) // CHUNK
    done = set()
    if os.path.exists(part) and os.path.getsize(part) == size and os.path.exists(state):
        st = json.load(open(state))
        if st.get('size') == size and st.get('sha') == sha: done = set(st['done'])
        if done: log(f'  续传：已有 {len(done)}/{n} 段')
    else:
        with open(part, 'wb') as f: f.truncate(size)
    lock = threading.Lock()
    todo = [i for i in range(n) if i not in done]
    inflight, hedged, fails, t0 = {}, set(), {}, time.time()
    got, aborted = [0], [False]

    def save():
        tmp = state + '.tmp'
        json.dump({'size': size, 'sha': sha, 'done': sorted(done)}, open(tmp, 'w')); os.replace(tmp, state)

    def take(wid):
        with lock:
            if todo:
                i = todo.pop(0); inflight[i] = time.time(); return i, wid
            # 队列空了：挑最久没完成、还没被重复下载过的段，换个源再下一遍（对冲慢源拖尾）
            old = sorted((t, i) for i, t in inflight.items() if i not in hedged and i not in done)
            if old:
                i = old[0][1]; hedged.add(i); return i, wid + 1
            return None, wid

    def work(wid):
        while True:
            i, k = take(wid)
            if i is None: return
            lo, hi = i * CHUNK, min(size, (i + 1) * CHUNK) - 1
            for a in range(len(srcs)):                       # 失败就轮到下一个源
                u = srcs[(k + a) % len(srcs)][2]
                try:
                    with get(u, (lo, hi)) as r:
                        data = r.read()
                    if r.status != 206 or len(data) != hi - lo + 1: raise IOError('长度不对')
                    break
                except Exception:
                    data = None
            if data is None:                                 # 所有源都失败：放回队列稍后重试，同一段最多 5 轮
                with lock:
                    fails[i] = fails.get(i, 0) + 1
                    if fails[i] >= 5: aborted[0] = True; todo.clear(); return
                    inflight.pop(i, None); hedged.discard(i)
                    if i not in done: todo.append(i)
                time.sleep(1); continue
            with lock:
                if i in done: continue
                with open(part, 'r+b') as f: f.seek(lo); f.write(data)
                done.add(i); inflight.pop(i, None); got[0] += len(data); save()
                if len(done) % 8 == 0 or len(done) == n:
                    sp = got[0] / max(time.time() - t0, 1e-3)
                    log(f'  {len(done)}/{n} 段  {sp/1024:.0f} KB/s')

    # 线程按源分配：最快的源分到的线程最多，但每个源至少一个
    with ThreadPoolExecutor(WORKERS) as ex:
        for f in [ex.submit(work, w % len(srcs) if w < len(srcs) else 0) for w in range(WORKERS)]: f.result()
    if aborted[0]: sys.exit(f'[fastpip] {name} 有分段在所有源都下载失败，已下的 {len(done)}/{n} 段保留，重跑可续传')
    os.remove(state)
    return finish(path, sha)

def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        while b := f.read(1 << 20): h.update(b)
    return h.hexdigest()

def finish(path, sha):
    got = sha256(path + '.part')
    if sha and got != sha:
        os.remove(path + '.part'); sys.exit(f'[fastpip] {os.path.basename(path)} sha256 不匹配，已删除，重跑会重新下载')
    os.replace(path + '.part', path); return path

if __name__ == '__main__':
    argv = sys.argv[1:]
    extra = argv[argv.index('--') + 1:] if '--' in argv else []
    argv = argv[:argv.index('--')] if '--' in argv else argv
    dest = os.path.expanduser('~/.cache/fastpip')
    if '--dest' in argv:
        i = argv.index('--dest'); dest = argv[i + 1]; del argv[i:i + 2]
    pkgs = argv or ['wordfreq', 'cmudict']
    os.makedirs(dest, exist_ok=True)
    idx = fastest_index(pkgs[0])
    log(f'用 {idx[0]} 解析依赖')
    files = resolve(pkgs, idx, extra)
    if not files: log('都已安装'); sys.exit(0)
    for name, rel, url, sha in files: fetch(name, rel, url, sha, dest)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--find-links', dest, *pkgs, *extra], check=True)
    log('完成')

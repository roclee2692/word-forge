#!/usr/bin/env python3
"""fastpip.py: 网络慢时装 Python 包或下载大文件（只用标准库，装依赖之前就能跑）。

  0. 机器上有 aria2c（开源多源下载器）时优先交给它：所有镜像地址一起给它，多连接分段 + 断点续传 + sha256 校验。
     实测 56 MB 的 wordfreq：aria2c 6 源 730–1686 KB/s，本脚本自带下载器 380–490 KB/s，uv 单镜像约 200 KB/s，pip 直连 17 KB/s。
     下面 3、4 两步是没有 aria2c 时的自带实现。
  1. 解析用 pypi.org：只有它提供 PEP 658 元数据，pip 只拉几 KB 的 .metadata；国内镜像都没有，
     用它们解析会把整个包先下一遍（56 MB 的 wordfreq 就是这样卡住的）。pypi.org 失败才按响应时间换镜像。
  2. 解析：让 pip 自己算出要装哪些包（pip install --dry-run --report），拿到文件路径和 sha256。
  3. 多源竞速 + 分段下载：每个文件切成 1 MB 的段放进队列，几个线程从不同镜像同时拉，
     快的源自然多拿段；队列空了，闲着的线程会换一个源把最慢的那段再下一遍，谁先完成算谁的。
  4. 断点续传：已完成的段记在 <文件>.part.json，中断后重跑只补缺的段。
  5. 校验 sha256 后，用 pip install --no-index 从本地目录安装。

用法：  python3 fastpip.py wordfreq cmudict [--dest DIR] [--no-aria2] [-- 其他 pip install 参数]
        python3 fastpip.py --url URL [URL2 …] [-o 文件名] [--sha256 HEX] [--dest DIR]   # 任意文件，多个 URL = 同一文件的不同镜像
依赖：  无（标准库 + 当前解释器自带的 pip）
"""
import sys, os, json, time, hashlib, threading, subprocess, tempfile, shutil
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
ARIA2 = shutil.which('aria2c')
TIMEOUT = 20

def log(*a): print('[fastpip]', *a, file=sys.stderr, flush=True)

def get(url, rng=None, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={'User-Agent': 'fastpip/1.0', **({'Range': f'bytes={rng[0]}-{rng[1]}'} if rng else {})})
    return urllib.request.urlopen(req, timeout=timeout)

# ---------- 1. 选解析用的索引：pypi.org 优先，其余按响应时间排 ----------
def index_order(pkg):
    def probe(m):
        t = time.time()
        try:
            with get(f'{m[1]}/{pkg}/', timeout=10) as r: r.read()
            return time.time() - t, m
        except Exception:
            return None
    with ThreadPoolExecutor(len(MIRRORS)) as ex:
        ok = sorted(x for x in ex.map(probe, MIRRORS) if x)
    log('索引响应：' + '  '.join(f'{m[0]} {t:.1f}s' for t, m in ok))
    return [MIRRORS[0]] + [m for _, m in ok if m is not MIRRORS[0]]

# ---------- 2. 让 pip 解析依赖 ----------
def resolve(pkgs, indexes, extra):
    rep = os.path.join(tempfile.mkdtemp(), 'report.json')
    for idx in indexes:
        log(f'用 {idx[0]} 解析依赖')
        cmd = [sys.executable, '-m', 'pip', 'install', '--dry-run', '--quiet', '--retries', '2', '--timeout', '20',
               '--report', rep, '-i', idx[1], *pkgs, *extra]
        if subprocess.run(cmd).returncode == 0: break
        log(f'  {idx[0]} 解析失败，换下一个')
    else:
        sys.exit('[fastpip] 所有索引都解析失败')
    out = []
    for it in json.load(open(rep))['install']:
        d = it['download_info']; url = d['url']
        h = d.get('archive_info', {}).get('hashes', {}).get('sha256') or d.get('archive_info', {}).get('hash', '').partition('=')[2]
        rel = url.split('/packages/', 1)[1] if '/packages/' in url else None
        urls = [f'{m[2]}/{rel}' for m in MIRRORS[1:] + MIRRORS[:1]] if rel else [url]   # 镜像在前，官方垫底
        out.append((url.rsplit('/', 1)[1], urls, h))
    return out

# ---------- 3. 对单个文件测速：各源下载第一段，记下速度和文件大小 ----------
def rank_sources(urls):
    def probe(u):
        t = time.time()
        try:
            with get(u, (0, PROBE - 1)) as r:
                if r.status != 206: return None              # 不支持 Range 的源不参与分段
                data = r.read(); size = int(r.headers['Content-Range'].rsplit('/', 1)[1])
            return len(data) / max(time.time() - t, 1e-3), u.split('/')[2], u, size, data
        except Exception:
            return None
    with ThreadPoolExecutor(len(urls)) as ex:
        ok = sorted((x for x in ex.map(probe, urls) if x), key=lambda x: -x[0])
    if not ok:                                               # 都不支持 Range：退化为整文件单源
        return [(0, 'direct', urls[0], None, b'')]
    best = ok[0][0]
    ok = [x for x in ok if x[0] >= best / 8]                 # 比最快源慢 8 倍以上的直接淘汰
    log('  源速度：' + '  '.join(f'{x[1]} {x[0]/1024:.0f}KB/s' for x in ok))
    return ok

# ---------- 4. 多源分段下载 + 断点续传 ----------
def aria2(name, urls, sha, dest):
    cmd = [ARIA2, '-q', '-c', '-x16', '-s16', '-k1M', '--file-allocation=none', '--uri-selector=adaptive',
           '--connect-timeout=10', '--timeout=20', '--max-tries=5', '--retry-wait=1', '-d', dest, '-o', name, *urls]
    if sha: cmd.insert(1, f'--checksum=sha-256={sha}')
    t = time.time()
    ok = subprocess.run(cmd).returncode == 0
    if ok: log(f'  aria2c {len(urls)} 源，{os.path.getsize(os.path.join(dest, name)) / 1024 / max(time.time() - t, 1e-3):.0f} KB/s')
    else: log('  aria2c 失败，改用自带下载器')
    return ok

def aria2_batch(files, dest):        # 一次调用并行下完所有文件：小文件主要耗在建连，串行下很亏
    todo = [f for f in files if not (os.path.exists(os.path.join(dest, f[0])) and not os.path.exists(os.path.join(dest, f[0]) + '.aria2'))]
    if not todo: return
    lst = os.path.join(dest, '.aria2-input.txt')
    with open(lst, 'w') as f:
        for name, urls, sha in todo:
            f.write('\t'.join(urls) + f'\n  out={name}\n' + (f'  checksum=sha-256={sha}\n' if sha else ''))
    t = time.time()
    subprocess.run([ARIA2, '-q', '-c', '-j8', '-x16', '-s16', '-k1M', '--file-allocation=none', '--uri-selector=adaptive',
                    '--connect-timeout=10', '--timeout=20', '--max-tries=5', '--retry-wait=1', '-d', dest, '-i', lst])
    os.remove(lst)
    got = sum(os.path.getsize(os.path.join(dest, n)) for n, _, _ in todo if os.path.exists(os.path.join(dest, n)))
    log(f'aria2c 并行下载 {len(todo)} 个文件，合计 {got / 1024 / max(time.time() - t, 1e-3):.0f} KB/s')

def fetch(name, urls, sha, dest, use_aria2=True):
    path = os.path.join(dest, name)
    if os.path.exists(path) and not os.path.exists(path + '.aria2') and (not sha or sha256(path) == sha):
        log(f'{name} 就绪（sha256 已校验）'); return path
    if os.path.exists(path) and not os.path.exists(path + '.aria2'): os.remove(path)   # 校验不过的旧文件
    log(f'{name}')
    if use_aria2 and ARIA2 and aria2(name, urls, sha, dest): return path
    srcs = rank_sources(urls)
    size = srcs[0][3]
    if size is not None and size <= PROBE:                   # 小文件：测速时已经整个下完了
        with open(path + '.part', 'wb') as f: f.write(srcs[0][4])
        return finish(path, sha)
    if size is None:                                         # 单源整文件
        with get(urls[0], timeout=120) as r, open(path + '.part', 'wb') as f:
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
    use_aria2 = '--no-aria2' not in argv
    if not use_aria2: argv.remove('--no-aria2')
    def opt(k):
        if k not in argv: return None
        i = argv.index(k); v = argv[i + 1]; del argv[i:i + 2]; return v
    out, sha = opt('-o'), opt('--sha256')
    os.makedirs(dest, exist_ok=True)
    if '--url' in argv:                                      # 通用模式：任意文件，多个 URL 视为同一文件的镜像
        argv.remove('--url')
        print(fetch(out or argv[0].rsplit('/', 1)[1].split('?')[0], argv, sha, dest, use_aria2)); sys.exit(0)
    pkgs = argv or ['wordfreq', 'cmudict']
    files = resolve(pkgs, index_order(pkgs[0]), extra)
    if not files: log('都已安装'); sys.exit(0)
    if use_aria2 and ARIA2: aria2_batch(files, dest)
    for name, urls, h in files: fetch(name, urls, h, dest, use_aria2)   # 校验；批量没下成的逐个补
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--find-links', dest, *pkgs, *extra], check=True)
    log('完成')

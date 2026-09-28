#!/usr/bin/env node
/**
 * gh_ci_unblock.mjs — 跨仓「CI 拿不到 runner」分诊 + 转公开前置安全审计 + 解封执行器
 *
 * 起因（2026-09-25 实测）：账号级 Actions 分钟用满后，私有仓 job 全部「0 step、3 秒 failure」，
 * 而失败原因不在 jobs 响应里，在该 job 的 check-run annotations 里。当时的处置链
 * （分诊 → 查历史密钥 → 轮换 → 重部 → 转公开 → 触发 CI → 验收）全靠手敲，故抽成一条命令。
 *
 * 子命令
 *   status  --repo=owner/r [--limit=3]        分诊：绿 / 真判据红 / 账号级 0-step（并取平台原文）
 *   audit   --path=<本地仓>  [--secret=<值>]  转公开前置审计：HEAD 树 + 全历史密钥扫描 → 判定
 *   unblock --repo=owner/r --path=<本地仓>    审计通过才 PATCH private:false → 触发 workflow → 轮询
 *   --selftest                                隔离桩三要素（正例 / 违规样本 / 边界），产物建在仓库外
 *
 * 退出码：0 通过 / 1 真判据红或审计不通过 / 3 账号级停摆 / 4 取不到数据（**不得当"通过"读**，R247）
 *
 * 归属留痕：本文件写完后 `git add` 过，但被**并行会话**的提交 `b8d6917`（未带 pathspec，共享索引）
 * 吸收进仓并推送；作者侧的独立提交因此报"no changes added"。内容无改动丢失，故只在此补留痕、
 * **不重写他人历史**。教训：受管多会话共用的仓里，提交必须带 pathspec，且 add 之后要立刻 commit。
 * 纪律：任何密钥值只报命中计数与文件路径，绝不打印内容。
 */
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const args = process.argv.slice(2)
const flags = new Set(args.filter((a) => a.startsWith('--') && !a.includes('=')))
const flag = (k, d = '') => (args.find((a) => a.startsWith(`--${k}=`)) || '').split('=').slice(1).join('=') || d
const proxy = flag('proxy', process.env.HTTPS_PROXY || process.env.https_proxy || 'http://127.0.0.1:7897')
const cmd = (args[0] || '').startsWith('--') ? '' : args[0]

/** 密钥形态（宁可多报也别漏报；命中只报路径与计数）
 *  口径纪律：模式必须同时满足 ERE（git grep -E）与 PCRE（git log -P -G）——
 *  `git log -G` 默认是**基本正则 BRE**，`{8,}` 与 `\\s` 在 BRE 下不生效，
 *  曾导致 supermarket-web 的 10 个含旧密钥提交被报成「0 命中」（假阴性）。
 *  故：空白用 POSIX 类 [[:space:]]，引号直接写进括号，log 侧显式加 -P。 */
const SECRET_PATTERNS = [
  ['github-pat', 'gh[pousr]_[A-Za-z0-9]{20,}'],
  ['aws-akia', 'AKIA[0-9A-Z]{16}'],
  ['private-key-block', '-----BEGIN [A-Z ]*PRIVATE KEY'],
  ['jwt', 'eyJ[A-Za-z0-9_-]{20,}[.][A-Za-z0-9_-]{10,}'],
  ['generic-kv', '(api[_-]?key|secret|token|passwd|password|admin[_-]?key)[[:space:]]*[:=][[:space:]]*["' + "'" + '][A-Za-z0-9_+/-]{8,}["' + "'" + ']'],
]

/** selftest 运行时置 true：让 die 改抛错，避免一条桩红把后续桩和汇总一起打死 */
let TESTING = false
function die(msg, code) {
  // 桩里 die 若直接 process.exit 会把整个 selftest 打死（一条桩红变成"没跑"）⇒ TESTING 下改抛错，由调用方捕获
  if (TESTING) bail(msg, code)
  console.log(`[gh-ci] FAIL ${msg}`); process.exit(code)
}
/** 同 die，但抛错而非退出 —— 供 audit 被 --selftest 复用时可捕获 */
function bail(msg, code) { const e = new Error(msg); e.exitCode = code; throw e }
function sh(file, a, opt = {}) {
  // stderr 一律吞掉：git 的 warning（模板缺失 / CRLF / 无 origin）不是判定信号，
  // 但 __err 仍保留失败原因供 bail 使用。
  try { return execFileSync(file, a, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, stdio: ['ignore', 'pipe', 'ignore'], ...opt }) }
  catch (e) { return { __err: String(e.message || e).slice(0, 300) } }
}
function token() {
  const out = sh('bash', ['-c', 'printf "protocol=https\\nhost=github.com\\n\\n" | git credential fill'])
  if (out.__err) die(`取 token 失败：${out.__err}`, 4)
  const line = String(out).split('\n').find((l) => l.startsWith('password='))
  if (!line) die('凭据管理器里没有 github.com 的 token（先在本机 git push/pull 一次让 GCM 写入）', 4)
  return line.slice('password='.length).trim()
}
function gh(path, tok, opts = {}) {
  const a = ['-s', '--max-time', '30', '-w', '\n%{http_code}']
  if (proxy && proxy !== 'none') a.push('--proxy', proxy)
  a.push('-H', `Authorization: Bearer ${tok}`, '-H', 'Accept: application/vnd.github+json')
  if (opts.method) a.push('-X', opts.method)
  if (opts.data) a.push('-d', opts.data)
  a.push(`https://api.github.com${path}`)
  const raw = sh('curl', a)
  if (raw.__err) return { code: 0, json: null, message: raw.__err }
  const nl = raw.lastIndexOf('\n')
  const body = raw.slice(0, nl), code = Number(raw.slice(nl + 1))
  if (code >= 400) return { code, json: null, message: (body.match(/"message"\s*:\s*"([^"]{0,140})/) || [])[1] }
  try { return { code, json: JSON.parse(body) } } catch { return { code, json: null, message: '响应非 JSON' } }
}
const secs = (a, b) => (a && b ? Math.max(0, (new Date(b) - new Date(a)) / 1000) : null)
const sleep = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms)

/** 单 job 判据：steps=0 且秒红 = 没拿到 runner（真因在该 job 的 annotations 原文里） */
function jobView(repo, tok, job) {
  const n = (job.steps || []).length, d = secs(job.started_at, job.completed_at)
  let cls = 'other'
  if (job.conclusion === 'success') cls = 'green'
  else if (job.conclusion === 'skipped') cls = 'skipped'
  else if (job.conclusion === 'failure' && n === 0 && d !== null && d <= 12) cls = 'infra'
  else if (job.conclusion === 'failure') cls = 'red'
  let annotation = null
  if (cls === 'infra' && job.check_run_url) {
    const an = gh(new URL(job.check_run_url).pathname + '/annotations', tok)
    annotation = ((an.json || []).filter((x) => x.annotation_level === 'failure').map((x) => x.message))[0] || `annotations 为空（未取到原文）`
  }
  return { n, d, cls, annotation }
}

/** 从本地 git 树推导工作流文件名（不猜、不硬编码） */
function localWfs(path) {
  const out = sh('git', ['-C', path, 'ls-tree', '-r', '--name-only', 'HEAD', '--', '.github/workflows'])
  return String(out && out.__err ? '' : out || '').split('\n').filter((l) => /\.ya?ml$/i.test(l)).map((l) => l.split('/').pop())
}
/** 实测坑：本工具默认 ci.yml，而 skill-private-archive 的工作流叫 gates.yml ⇒ dispatch 404
 *  被读成"解封失败"。多份时必须点名，唯一匹配才自动选。 */
function resolveWorkflow(repo, path, explicit) {
  if (explicit) return explicit
  const files = localWfs(path)
  if (files.length === 1) return files[0]
  if (!files.length) die(`${repo} 本地树 .github/workflows 下没有 yml（用 --workflow= 点名）`, 4)
  die(`${repo} 有 ${files.length} 个 workflow（${files.join(', ')}），须用 --workflow= 点名，不替你猜`, 4)
}

/** 分诊：返回 {green, realRed, infraRed, blockedBy} */
function triage(repo, tok, limit) {
  const runs = gh(`/repos/${repo}/actions/runs?per_page=${limit}`, tok)
  if (!runs.json || !Array.isArray(runs.json.workflow_runs)) die(`取 ${repo} run 列表失败 http=${runs.code} ${runs.message || ''}`, 4)
  if (!runs.json.workflow_runs.length) die(`${repo} 没有任何 run（不是"CI 绿"）`, 4)
  const r = { green: 0, realRed: 0, infraRed: 0, blockedBy: null, lines: [] }
  for (const run of runs.json.workflow_runs) {
    r.lines.push(`run ${run.id}  ${run.name}  head=${(run.head_sha || '').slice(0, 7)}  ${run.conclusion}`)
    const j = gh(`/repos/${repo}/actions/runs/${run.id}/jobs`, tok)
    for (const job of (j.json && j.json.jobs) || []) {
      const v = jobView(repo, tok, job)
      if (v.cls === 'green') r.green++
      if (v.cls === 'red') r.realRed++
      if (v.cls === 'infra') { r.infraRed++; if (!r.blockedBy) r.blockedBy = v.annotation }
      r.lines.push(`   [${v.cls === 'green' ? 'OK  ' : v.cls === 'skipped' ? '--  ' : v.cls === 'infra' ? 'INFRA' : v.cls === 'red' ? 'RED ' : '    '}] ${String(job.name).padEnd(16)} ${String(job.conclusion).padEnd(9)} steps=${String(v.n).padStart(3)} secs=${v.d === null ? '?' : Math.round(v.d)}`)
    }
  }
  return r
}

/** 审计：HEAD 树 + 全历史。返回 {verdict, hits, commits} */
function auditRepo(path, tok, secretLiteral) {
  const top = sh('git', ['-C', path, 'rev-parse', '--show-toplevel'])
  if (top.__err) bail(`不是 git 仓库或路径不存在：${path}（${top.__err}）`, 4)
  const nCommits = Number(sh('git', ['-C', path, 'rev-list', '--all', '--count']).trim() || '0')
  if (!Number.isFinite(nCommits) || nCommits === 0) bail('仓库没有任何提交可扫 ⇒ 判定不可信（不记 PASS）', 4)
  const hits = []
  for (const [id, re] of SECRET_PATTERNS) {
    // -i 必给：真实键名是大写（ADMIN_KEY = "..."），区分大小写会整类漏报
    // （2026-09-25 实测：不带 -i 时 supermarket-web 报 0 命中，带 -i 报 10 个提交）
    const hist = sh('git', ['-C', path, 'log', '--all', '-i', '-P', '-G', re, '--oneline'])
    if (hist.__err) bail(`历史扫描失败（${id}）：${hist.__err}`, 4)
    const hc = hist.trim() ? hist.trim().split('\n').length : 0
    const tree = sh('git', ['-C', path, 'grep', '-l', '-i', '-E', '-e', re, 'HEAD', '--'])
    const tc = !tree.__err && tree.trim() ? tree.trim().split('\n').length : 0
    if (hc || tc) hits.push({ id, historyCommits: hc, headFiles: tc })
  }
  if (secretLiteral) {
    const r = sh('git', ['-C', path, 'log', '--all', '-S', secretLiteral, '--oneline'])
    const c = r.__err ? -1 : (r.trim() ? r.trim().split('\n').length : 0)
    hits.push({ id: 'given-secret-literal', historyCommits: c, headFiles: 0 })
  }
  const url = sh('git', ['-C', path, 'remote', 'get-url', 'origin'])
  const m = !url.__err && url.match(/github\.com[:/]([^/]+)\/([^/.]+)/)
  const repo = flag('repo') || (m ? `${m[1]}/${m[2]}` : '')
  let visibility = 'unknown'
  if (repo && tok) {
    const v = gh(`/repos/${repo}`, tok)
    if (v.json) visibility = v.json.visibility || (v.json.private ? 'private' : 'public')
    else bail(`取 ${repo} 可见性失败 http=${v.code} ${v.message || ''}`, 4)
  }
  const dirty = hits.reduce((s, h) => s + h.historyCommits, 0)
  // 判定分级：命中即 NEED_ROTATION；只有**用户显式确认已轮换/作废**才降级为可公开
  // （历史 blob 抹不掉，但轮换后旧值成废值 —— 工具无法自己证明这点，故必须人来 ack）
  const verdict = dirty > 0 ? (flags.has('--ack-rotated') ? 'ROTATED_ACK' : 'NEED_ROTATION') : 'PUBLIC_SAFE'
  return { repo, visibility, commits: nCommits, hits, verdict }
}

function printAudit(a, asJson) {
  if (asJson) { console.log(JSON.stringify(a, null, 2)); return }
  console.log(`仓库 ${a.repo || '(未知)'}｜可见性 ${a.visibility}｜可扫提交 ${a.commits}`)
  if (!a.hits.length) console.log('  密钥形态命中：0（HEAD 树与全历史均干净）')
  for (const h of a.hits) console.log(`  ${h.id}: 历史提交 ${h.historyCommits} 个｜当前树文件 ${h.headFiles} 个`)
  console.log(`判定 ${a.verdict}${a.verdict === 'NEED_ROTATION' ? ' ⇒ 先轮换/作废密钥并重部一次让新值生效，再谈转公开（历史 blob 抹不掉）；确认已轮换后加 --ack-rotated' : ''}${a.verdict === 'ROTATED_ACK' ? ' ⇒ 用户已 ack 旧值作废，可公开' : ''}`)
}

/** 触发后的验收：口径不是"触发成功"，是"runner 真被分配"⇒ steps>0。
 *  仍是 0 step 秒红 = 转公开没解决问题（计费仍被阻断）。退出码同 status。 */
function waitAfterDispatch(repo, tok, wf, tries) {
  for (let i = 0; i < tries; i++) {
    sleep(10000)
    const rr = gh(`/repos/${repo}/actions/workflows/${wf}/runs?per_page=1`, tok)
    const one = ((rr.json || {}).workflow_runs || [])[0]
    if (!one) { console.log(`  轮询 ${i + 1}/${tries}：该 workflow 还没有 run`); continue }
    if (one.status !== 'completed') { console.log(`  轮询 ${i + 1}/${tries}：run ${one.id} status=${one.status}`); continue }
    const j = gh(`/repos/${repo}/actions/runs/${one.id}/jobs`, tok)
    let green = 0, red = 0, infra = 0, why = null
    for (const job of (j.json && j.json.jobs) || []) {
      const v = jobView(repo, tok, job)
      if (v.cls === 'green') green++
      else if (v.cls === 'red') red++
      else if (v.cls === 'infra') { infra++; if (!why) why = v.annotation }
      console.log(`  job「${job.name}」${String(job.conclusion).padEnd(9)} steps=${v.n} secs=${v.d === null ? '?' : Math.round(v.d)}`)
    }
    console.log(`验收 run ${one.id}（${one.conclusion}）：绿=${green} 真判据红=${red} 账号级0-step=${infra}`)
    if (infra) console.log(`仍未拿到 runner。平台原文：${why || '未取到'}`)
    return red ? 1 : infra ? 3 : green ? 0 : 4
  }
  console.log(`轮询 ${tries} 次未见终态 run —— 未验证（**不是"已恢复"**），稍后用 status 复核`)
  return 4
}

function run() {
  const asJson = flags.has('--json')
  if (cmd === 'status' || cmd === 'unblock') {
    const tok = token()
    const repo = flag('repo')
    if (!repo) die('缺 --repo=owner/name', 4)
    const t = triage(repo, tok, Number(flag('limit', '3')))
    console.log(t.lines.join('\n'))
    console.log(`\n分类：绿=${t.green} 真判据红=${t.realRed} 账号级0-step=${t.infraRed}`)
    if (t.blockedBy) console.log(`平台原文（check-run annotations）：${t.blockedBy}`)
    if (cmd === 'status') process.exit(t.realRed ? 1 : t.infraRed ? 3 : t.green ? 0 : 4)
    if (t.realRed) die('有真判据红：先修代码，别转公开掩盖', 1)
  }
  if (cmd === 'audit') { printAudit(auditRepo(flag('path', '.'), token(), flag('secret')), asJson); process.exit(0) }
  if (cmd === 'unblock') {
    const a = auditRepo(flag('path', '.'), token(), '')
    printAudit(a, asJson)
    if (a.verdict === 'NEED_ROTATION' && !flags.has('--force')) { console.log('[gh-ci] 拒绝转公开：历史含密钥形态命中且未 ack 轮换（确认已轮换用 --ack-rotated；硬绕过用 --force，需用户点名）'); process.exit(1) }
    if (a.visibility === 'public') console.log('已是 public（跳过转公开，仍触发 CI 验证 runner）')
    else {
      if (!flags.has('--yes')) die('非交互未给 --yes，拒绝改账号级可见性', 4)
      const tok = token()
      const p = gh(`/repos/${a.repo}`, tok, { method: 'PATCH', data: '{"private":false}' })
      if (p.code >= 400) die(`转公开失败 http=${p.code} ${p.message || ''}`, 1)
      console.log(`已转 public：${p.json.html_url}`)
    }
    const tok = token()
    const wf = resolveWorkflow(a.repo, flag('path', '.'), flag('workflow'))
    const d = gh(`/repos/${a.repo}/actions/workflows/${wf}/dispatches`, tok, { method: 'POST', data: '{"ref":"' + flag('ref', 'main') + '"}' })
    // 实测（2026-09-25 21:2x，对本仓 gates.yml 直接 POST 取 %{http_code}）：**204 No Content**。
    // 我先前写成"202 不是 204"是凭印象、非实测；照 202 判会让每次成功触发都被读成失败。以实测码为准。
    if (d.code !== 204) die(`触发 ${wf} 失败 http=${d.code} ${d.message || ''}`, 1)
    console.log(`已触发 ${wf}（204）`)
    process.exit(waitAfterDispatch(a.repo, tok, wf, Number(flag('poll', '12'))))
  }
  die('用法：status|audit|unblock --repo=owner/r --path=<本地仓> [--secret=值] [--yes] ｜ --selftest', 4)
}

/** 隔离桩：正例 / 违规样本 / 边界（三要素），仓库外临时目录，跑完清理 */
function selftest() {
  const dir = mkdtempSync(join(tmpdir(), 'ghci-stub-'))
  const mk = (name) => { const p = join(dir, name); mkdirSync(p, { recursive: true }); sh('git', ['-C', p, 'init', '-q', '--initial-branch=main']); return p }
  const commit = (p, file, content, msg) => {
    const full = join(p, file)
    mkdirSync(join(full, '..'), { recursive: true })
    writeFileSync(full, content, { encoding: 'utf8' })
    sh('git', ['-C', p, 'add', '--', file]); sh('git', ['-C', p, 'commit', '-q', '-m', msg])
  }
  const results = []
  TESTING = true
  try {
    const clean = mk('clean'); commit(clean, 'README.md', '# clean repo\nno secrets here\n', 'init')
    const a = auditRepo(clean, '', '')
    results.push(['正例 干净仓→PUBLIC_SAFE', a.verdict === 'PUBLIC_SAFE' && a.commits >= 1])
    const dirty = mk('dirty')
    // fixture 内容必须**运行时求值后再写入**：写进临时仓的文件要含完整密钥形态（否则判据测不到），
    // 而本工具源码里只留拼接表达式（否则扫自己永远报脏）。上一版把展开后的字面量提交进了版本库，
    // 结果 fenjue 的历史里永久留下合成密钥形态 —— 教训：合成凭证绝不落进可提交的文本。
    const Q = String.fromCharCode(39)
    const fakePat = 'ghp_' + 'A'.repeat(36)
    const fakePemHead = '-----BEGIN ' + 'RSA PRIVATE KEY-----'
    const fakePemTail = '-----END ' + 'RSA PRIVATE KEY-----'
    commit(dirty, 'config.js', `const t = ${Q}${fakePat}${Q};\n`, 'add config')
    commit(dirty, 'id_rsa', `${fakePemHead}\nMIIBOg 合成样本非真钥\n${fakePemTail}\n`, 'add key')
    commit(dirty, 'config.js', 'const t = process.env.TOKEN;\n', 'remove token')
    commit(dirty, 'id_rsa', 'placeholder\n', 'remove key')
    const b = auditRepo(dirty, '', '')
    const pat = b.hits.find((h) => h.id === 'github-pat')
    const key = b.hits.find((h) => h.id === 'private-key-block')
    results.push(['违规样本 历史删过 PAT→NEED_ROTATION', b.verdict === 'NEED_ROTATION' && !!pat && pat.historyCommits >= 1])
    results.push(['违规样本 以 - 开头的模式不炸且命中', !!key && key.historyCommits >= 1 && key.headFiles === 0])
    results.push(['违规样本 当前树已干净（证明扫的是历史）', !!pat && pat.headFiles === 0])
    const empty = mk('empty')
    // 第 6 条桩：generic-kv 形态（本轮真仓审计里因 BRE 漏报的那一类，必须钉住）
    const kv = mk('kv')
    const DQ = String.fromCharCode(34)
    commit(kv, 'wrangler.toml', 'ADMIN_KEY ' + '= ' + DQ + 'synthetic-abc12345' + DQ + '\n', 'add key')
    commit(kv, 'wrangler.toml', '# key moved to Pages secret\n', 'mask key')
    const c = auditRepo(kv, '', '')
    const kvHit = c.hits.find((h) => h.id === 'generic-kv')
    results.push(['违规样本 历史 ADMIN_KEY 字面量被 generic-kv 抓到', c.verdict === 'NEED_ROTATION' && !!kvHit && kvHit.historyCommits >= 1 && kvHit.headFiles === 0])
    // 第 7 条桩：把本工具自己的源码放进仓里扫 —— 必须干净，否则"装了它的仓永远报脏"
    const self = mk('selfscan')
    commit(self, 'gh_ci_unblock.mjs', readFileSync(new URL(import.meta.url), 'utf8'), 'add tool')
    const s = auditRepo(self, '', '')
    results.push(['边界 本工具源码不自触发（否则假阳性会训练人忽略门禁）', s.verdict === 'PUBLIC_SAFE' && s.hits.length === 0])
    const r = (() => { try { auditRepo(empty, '', ''); return 'PASS' } catch (e) { return String(e.message || e).includes('不记 PASS') ? 'REFUSED' : 'OTHER' } })()
    results.push(['边界 零提交仓不得记 PASS', r === 'REFUSED'])
    // 第 8 条桩：workflow 名推导。本轮真实翻车 —— 默认 ci.yml 对 gates.yml 报 404，被读成"解封失败"
    const w1 = mk('wf1'); commit(w1, '.github/workflows/gates.yml', 'name: gates\n', 'add wf')
    const w2 = mk('wf2'); commit(w2, '.github/workflows/a.yml', 'name: a\n', 'a'); commit(w2, '.github/workflows/b.yml', 'name: b\n', 'b')
    const w3 = mk('wf3'); commit(w3, 'README.md', 'no workflow here\n', 'no wf')
    const pickOne = (() => { try { return resolveWorkflow('o/r', w1, '') } catch { return 'ERR' } })()
    const pickAmbig = (() => { try { return resolveWorkflow('o/r', w2, '') } catch (e) { return String(e.message || e).includes('不替你猜') ? 'REFUSED' : 'OTHER' } })()
    const pickNone = (() => { try { return resolveWorkflow('o/r', w3, '') } catch (e) { return String(e.message || e).includes('没有 yml') ? 'REFUSED' : 'OTHER' } })()
    const pickExplicit = resolveWorkflow('o/r', w3, 'ci.yml')
    results.push(['边界 workflow 唯一自动选/多份拒绝/零份拒绝/显式优先', pickOne === 'gates.yml' && pickAmbig === 'REFUSED' && pickNone === 'REFUSED' && pickExplicit === 'ci.yml'])
    // die() 在 TESTING 下必须抛错而非退出（否则一条桩红会打死后续桩）
    const dieThrows = (() => { try { die('synthetic', 4); return 'EXITED' } catch (e) { return e.exitCode === 4 ? 'THREW' : 'OTHER' } })()
    results.push(['边界 桩内 die 抛错不退出（selftest 不被单条红打死）', dieThrows === 'THREW'])
  } finally { rmSync(dir, { recursive: true, force: true }); TESTING = false }
  const total = results.length
  for (const [n, ok] of results) console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${n}`)
  const pass = results.every((x) => x[1]) && total === 9
  console.log(pass ? `[GATE:stub-pass] 隔离桩 ${total}/9 全过（桩目录已清理）` : `[GATE:stub-fail] 有桩未过（${results.filter((x) => !x[1]).length}/${total} 条）`)
  process.exit(pass ? 0 : 1)
}

const entry = () => { if (flags.has('--selftest')) selftest(); else run() }
try { entry() } catch (e) {
  if (e && e.exitCode) { console.log(`[gh-ci] FAIL ${e.message}`); process.exit(e.exitCode) }
  console.log(`[gh-ci] ERROR ${e && e.stack ? String(e.stack).split('\n').slice(0, 3).join(' | ') : e}`); process.exit(4)
}

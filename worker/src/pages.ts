const escapeHtml = (value: string): string =>
  value.replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character] ?? character);

export const jsonResponse = (value: unknown, status = 200): Response =>
  new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } });

export const renderGeneratePage = (runId: string): Response => {
  const safeRunId = escapeHtml(runId);
  const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Ayu Running · 生成日报</title><style>body{margin:0;background:#0d1110;color:#f4f7f3;font:16px system-ui,sans-serif}main{max-width:42rem;margin:12vh auto;padding:2rem;border:1px solid #49d17d;border-radius:12px;background:#111817}h1{margin:0 0 1.5rem;color:#49d17d}#state{font-size:1.2rem}small{color:#aab8ae}</style></head><body><main><h1>Ayu Running</h1><p id="state">准备生成</p><p><small>run_id: ${safeRunId}</small></p><p id="details"></p></main><script>const runId=${JSON.stringify(runId)};const state=document.querySelector('#state');const details=document.querySelector('#details');const labels={submitting:'正在提交',queued:'排队中',running:'生成中',success:'日报已生成 · 测试分支写入成功',failure:'生成失败'};const show=(v)=>{state.textContent=labels[v.state]||'准备生成';details.textContent=v.workflowRunId?'workflow run ID: '+v.workflowRunId:'';};const poll=async()=>{try{const r=await fetch('/api/status/'+encodeURIComponent(runId),{cache:'no-store'});if(r.ok){const v=await r.json();show(v);if(v.state==='success'||v.state==='failure')return;}}catch{}setTimeout(poll,3000)};window.addEventListener('load',async()=>{state.textContent=labels.submitting;try{const r=await fetch('/api/generate',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({runId:runId})});const v=await r.json();show(v);}catch{state.textContent='生成失败'}poll()});</script></body></html>`;
  return new Response(html, { headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } });
};

const escapeHtml = (value: string): string =>
  value.replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character] ?? character);

export const jsonResponse = (value: unknown, status = 200): Response =>
  new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' } });

export const renderGeneratePage = (runId: string): Response => {
  const safeRunId = escapeHtml(runId);
  const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Ayu Running · 生成日报</title><style>
  :root{--accent:#56FFA3}*{box-sizing:border-box}body{margin:0;background:#080B09;color:#F2F6F3;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:44rem;margin:9vh auto;padding:32px 24px}header{display:flex;align-items:baseline;justify-content:space-between;border-bottom:1px solid #304038;padding-bottom:18px}header strong{font-size:22px}header span{color:var(--accent)}h1{font-size:34px;margin:36px 0 12px}p{color:#B2C0B8}label{display:block;margin:28px 0 12px}select,button{font:inherit;min-height:48px;padding:10px 14px;border-radius:5px}select{background:#101A14;color:#F2F6F3;border:1px solid #7B9283;min-width:240px;max-width:100%}button{background:var(--accent);color:#080B09;border:0;font-weight:650;cursor:pointer;margin-left:12px}button:disabled,select:disabled{opacity:.6;cursor:wait}:focus-visible{outline:3px solid var(--accent);outline-offset:4px}#state{font-size:20px;color:#F2F6F3;margin-top:32px}small{color:#B2C0B8}a{color:var(--accent)}@media(max-width:520px){main{margin:4vh auto;padding:24px}h1{font-size:29px}select{width:100%;min-width:0}button{width:100%;margin:14px 0 0}}
  </style></head><body><main><header><strong><span>Ayu</span> Running</strong><small>日报生成</small></header><h1>选一个今天的视觉。</h1><p>只生成所选主题，HTML 与下载 PNG 保持同一风格。未完成前，已有报告继续可用。</p><label for="theme">报告主题</label><select id="theme"><option value="black-green">黑绿 · 训练控制台（默认）</option><option value="burgundy">酒红 · 运动手记</option><option value="blue">蓝白 · 训练实验室</option><option value="violet">紫橙 · 运动海报</option></select><button id="generate" type="button">生成日报</button><p id="state" role="status" aria-live="polite">准备生成</p><p><small>run_id: ${safeRunId}</small></p><p id="details"></p></main><script>
  const runId=${JSON.stringify(runId)},state=document.querySelector('#state'),details=document.querySelector('#details'),themeSelect=document.querySelector('#theme'),button=document.querySelector('#generate');
  const labels={submitting:'正在提交',queued:'排队中',running:'生成中',success:'日报已生成',failure:'生成失败'};
  let polling=false;
  const unlock=()=>{button.disabled=false;themeSelect.disabled=false;};
  const show=v=>{state.textContent=labels[v.state]||'准备生成';details.textContent='';if(v.workflowRunId)details.append('workflow run ID: '+v.workflowRunId);if(v.reportUrl){const link=document.createElement('a');link.href=v.reportUrl;link.target='_blank';link.rel='noopener noreferrer';link.textContent='查看日报';details.append(details.textContent?' · ':'',link);}};
  const poll=async()=>{if(!polling)return;try{const r=await fetch('/api/status/'+encodeURIComponent(runId),{cache:'no-store'});if(r.ok){const v=await r.json();show(v);if(v.state==='success'||v.state==='failure'){polling=false;unlock();return;}}}catch{}setTimeout(poll,3000);};
  const generate=async()=>{if(button.disabled)return;button.disabled=true;themeSelect.disabled=true;state.textContent=labels.submitting;details.textContent='';try{const r=await fetch('/api/generate',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({runId,theme:themeSelect.value})});const v=await r.json();if(!r.ok){state.textContent='生成未开始';details.textContent=v.error||'请稍后重试';unlock();return;}show(v);polling=true;poll();}catch{state.textContent='连接失败，请重试';unlock();}};
  button.addEventListener('click',generate);
  const requestedTheme=new URLSearchParams(location.search).get('theme');
  if(['black-green','burgundy','blue','violet'].includes(requestedTheme)){themeSelect.value=requestedTheme;}
  </script></body></html>`;
  return new Response(html, { headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } });
};

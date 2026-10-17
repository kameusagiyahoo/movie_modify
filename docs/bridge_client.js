/* Movie Modify Pages → local Windows/Linux editor hand-off.
   HTTPS GitHub Pages does not fetch HTTP private-network APIs.
   The same /studio/ editor is served by FastAPI on a single local origin.
   Uploads occur ONLY after a direct user click and confirmation. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const native = location.pathname === "/studio/" || location.pathname === "/studio";
  let serverProjectId = null;
  let localFile = null;
  let lastServerSegments = null;
  let lastServerRevision = null;
  let busy = false;
  let transferPaused = false;
  let activeController = null;
  const UPLOAD_KEY="movie-modify-resumable-upload-v1";
  const REMEMBER_KEY = "movie-modify-native-project";
  function remembered() {
    try { return JSON.parse(sessionStorage.getItem(REMEMBER_KEY) || "null"); }
    catch (_err) { return null; }
  }
  function remember() {
    const snap=state();
    if(!snap?.file || !serverProjectId)return;
    try{sessionStorage.setItem(REMEMBER_KEY, JSON.stringify({
      id:serverProjectId, name:snap.file.name, size:snap.file.size,
      modified:snap.file.lastModified, projection:snap.projection,
      duration:snap.duration, baseline:lastServerSegments,
      revision:lastServerRevision
    }));}catch(_err){ /* Restricted browser storage: manual sync still works. */ }
  }

  const editor = () => window.MovieModifyPagesBridge;
  const state = () => editor()?.getState();
  const json = value => JSON.stringify(value);
  const payload = value => ({method: "POST",
    headers: {"Content-Type": "application/json"}, body:json(value)});
  function say(message, error=false) {
    $("bridgeStatus").textContent = message;
    $("bridgeStatus").classList.toggle("error",error);
  }
  function setBusy(value) {
    busy=value;
    ["bridgeSync","bridgeExport","bridgeOpenEditor","bridgePull"].forEach(id=>{
      if ($(id)) $(id).disabled=value;
    });
  }
  async function api(path, opts={}) {
    const response=await fetch(path,{credentials:"same-origin",...opts});
    if(response.status===401) {
      $("bridgeLogin").hidden=false;
      throw Error("PCのアクセス認証が必要です。下のパスフレーズを入力してください。");
    }
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(typeof data.detail==="string" ? data.detail :
      (data.detail?.message||"HTTP "+response.status));
    return data;
  }
  async function waitJob(id, label) {
    for(let attempt=0; attempt<14400; attempt++) {
      const job=await api("/api/jobs/"+encodeURIComponent(id));
      say(label+"： "+(job.state==="queued"?"処理待ち":job.state==="running"?
        "処理中 "+job.progress+"%":"完了"));
      if(job.state==="failed")throw Error(job.error||label+"に失敗しました");
      if(job.state==="done")return;
      await new Promise(resolve=>setTimeout(resolve,1000));
    }
    throw Error(label+"の状態確認がタイムアウトしました");
  }

  function transferIdentity(file, projection) {
    return JSON.stringify({name:file.name,size:file.size,
      modified:file.lastModified,projection});
  }
  function readSession() {
    try {return JSON.parse(sessionStorage.getItem(UPLOAD_KEY)||"null");}
    catch(_err){return null;}
  }
  function saveSession(value) {
    try{sessionStorage.setItem(UPLOAD_KEY,JSON.stringify(value));}
    catch(_err){say("端末の保存領域が無効です。通信切断後の再開には同じ画面が必要です。",true);}
  }
  function forgetSession() {
    try{sessionStorage.removeItem(UPLOAD_KEY);}catch(_err){}
  }
  function showTransferProgress(done,total) {
    const percent=Math.min(100,Math.floor(done/total*1000)/10);
    const bar=$("bridgeProgress");
    if(bar){bar.hidden=false;bar.value=percent;}
    const size=x=>(x/1024**2).toFixed(1)+" MiB";
    say("ローカルPCへ転送中： "+percent.toFixed(1)+"%（"+size(done)+" / "+size(total)+"）");
  }
  async function sendChunks(file, projection) {
    const identity=transferIdentity(file,projection);
    const previous=readSession();
    let session=null;
    if(previous?.identity===identity && previous.id){
      try {
        const saved=await api("/api/uploads/"+previous.id);
        if(saved.size===file.size && saved.filename===file.name &&
           saved.projection===projection && saved.last_modified===file.lastModified)
          session=saved;
      }catch(_err){ /* Expired session: create a new one. */ }
    }
    if(!session){
      session=await api("/api/uploads",payload({filename:file.name,size:file.size,
        projection,last_modified:file.lastModified}));
      saveSession({identity,id:session.id});
    }
    let offset=session.received;
    const chunkSize=4*1024*1024;
    transferPaused=false;
    $("bridgePause").hidden=false;
    try{
      for(let failures=0; offset<file.size;){
        if(transferPaused)throw Error("転送を一時停止しました。後で同じ動画を選んで同期すれば続きから再開できます。");
        showTransferProgress(offset,file.size);
        const end=Math.min(file.size,offset+chunkSize);
        const part=file.slice(offset,end);
        activeController=new AbortController();
        try {
          const accepted=await api("/api/uploads/"+session.id+"/chunk?offset="+offset,{
            method:"PUT",headers:{"Content-Type":"application/octet-stream"},
            body:part,signal:activeController.signal
          });
          offset=accepted.received;
          failures=0;
        }catch(error){
          if(transferPaused)throw Error("転送を一時停止しました。再度「PCに同期」で再開できます。");
          // The response may have been lost after the chunk was stored.
          const check=await api("/api/uploads/"+session.id);
          offset=check.received;
          failures++;
          if(failures>3)throw Error("転送が中断しました。通信状態を確認してもう一度「PCに同期」を押してください。");
          await new Promise(resolve=>setTimeout(resolve,Math.min(2500,failures*500)));
        }finally{activeController=null;}
      }
      showTransferProgress(file.size,file.size);
      const done=await api("/api/uploads/"+session.id+"/complete",{method:"POST"});
      forgetSession();
      return done;
    }finally{
      $("bridgePause").hidden=true;
      activeController=null;
    }
  }

  async function confirmProject() {
    const snapshot=state();
    if(!snapshot?.ready || !snapshot.file) {
      throw Error("先にこの画面で元動画を読み込んでください。");
    }
    if(snapshot.file !== localFile) {
      serverProjectId=null;lastServerSegments=null;lastServerRevision=null;localFile=snapshot.file;
      const saved=remembered();
      if(saved && saved.name===snapshot.file.name && saved.size===snapshot.file.size &&
        saved.modified===snapshot.file.lastModified &&
        saved.projection===snapshot.projection &&
        Math.abs(saved.duration-snapshot.duration)<1) {
        serverProjectId=saved.id;
        lastServerSegments=saved.baseline;
        lastServerRevision=Number.isInteger(saved.revision)?saved.revision:null;
      }
    }
    if(!serverProjectId) {
      const sizeGiB=snapshot.file.size/(1024**3);
      const message="選択した元動画（"+sizeGiB.toFixed(2)+" GiB）を、このPCのMovie Modifyサーバーへ送信します。\n"+
        "送信先："+location.origin+"\n"+
        "外部クラウドには送信しませんが、iPhoneとPC間ではWi-Fi通信します。\n"+
        (sizeGiB>2?"大きい動画のため、Wi-Fi通信や端末のメモリに注意してください。\n":"")+
        "処理を続けますか？";
      if(!window.confirm(message))throw Error("動画の転送をキャンセルしました。");
      const created=await sendChunks(snapshot.file,snapshot.projection);
      serverProjectId=created.project.id;
      lastServerRevision=created.project.edit_revision;
      remember();
      await waitJob(created.job_id,"プレビュー生成");
    }
    const remote=await api("/api/projects/"+serverProjectId);
    if(lastServerRevision===null) {
      // Legacy session storage: resolve the revision only if we have a
      // matching old baseline. Never treat a missing revision as permission.
      if(lastServerSegments!==null && json(remote.segments)===lastServerSegments)
        lastServerRevision=remote.edit_revision;
      else throw Error("PC側の編集版数を確認できません。PC側の編集を取得してください。");
    }
    if(remote.edit_revision!==lastServerRevision) {
      throw Error("別の画面がPCの編集を更新しました。同期を中止しました。PC側の編集を取得してください。");
    }
    const result=await api("/api/projects/"+serverProjectId+"/edits",{
      method:"PUT",headers:{"Content-Type":"application/json"},
      body:json({segments:snapshot.project.segments,expected_revision:lastServerRevision})
    });
    lastServerRevision=result.edit_revision;
    lastServerSegments=json(result.segments);
    remember();
    say("編集内容をPCに同期しました。元動画はPCに保存されています。");
    return serverProjectId;
  }
  async function action(job) {
    if(busy)return;
    setBusy(true);
    try{await job()}catch(error){say(error.message,true)}
    finally{setBusy(false)}
  }
  async function nativeRender() {
    const projectId=await confirmProject();
    const size=$("bridgeSize").value;
    const data=await api("/api/projects/"+projectId+"/render",payload({size}));
    await waitJob(data.job_id,"高品質MP4出力");
    const link=$("bridgeDownload");
    link.href="/api/projects/"+projectId+"/export";
    link.hidden=false;
    say("高品質MP4が完成しました。ダウンロードできます。");
  }
  async function pullFromServer() {
    const snapshot=state();
    if(!serverProjectId && snapshot?.ready && snapshot.file){
      const saved=remembered();
      if(saved && saved.name===snapshot.file.name && saved.size===snapshot.file.size &&
         saved.modified===snapshot.file.lastModified &&
         saved.projection===snapshot.projection &&
         Math.abs(saved.duration-snapshot.duration)<1){
        serverProjectId=saved.id;
        lastServerSegments=saved.baseline;
        lastServerRevision=Number.isInteger(saved.revision)?saved.revision:null;
        localFile=snapshot.file;
      }
    }
    if(!serverProjectId||!snapshot?.ready)throw Error("PC側の編集を読むには、先に同じ元動画を開いてください。");
    if(snapshot.dirty && !confirm("未保存のブラウザ編集をPC側の内容で上書きしますか？"))return;
    const project=await api("/api/projects/"+serverProjectId);
    editor().applyProject(project);
    lastServerSegments=json(project.segments);
    lastServerRevision=project.edit_revision;
    remember();
    say("PC側の画角・カット編集を読み込みました。");
  }
  async function showServerHistory() {
    const snapshot=state();
    if(!snapshot?.ready || !snapshot.file)
      throw Error("まず同じ元動画をこの画面で開いてください。");
    if(!serverProjectId) {
      const saved=remembered();
      if(saved&&saved.name===snapshot.file.name&&saved.size===snapshot.file.size&&
         saved.modified===snapshot.file.lastModified&&
         saved.projection===snapshot.projection&&
         Math.abs(saved.duration-snapshot.duration)<1){
        serverProjectId=saved.id;
        lastServerRevision=Number.isInteger(saved.revision)?saved.revision:null;
        lastServerSegments=saved.baseline;
        localFile=snapshot.file;
      }
    }
    if(!serverProjectId)throw Error("先に動画をPCに同期してください。");
    const listing=await api("/api/projects/"+serverProjectId+"/edit-history");
    const area=$("bridgeServerHistoryList");
    area.replaceChildren();
    for(const item of listing.revisions){
      const button=document.createElement("button");
      button.type="button";
      button.textContent="版 "+item.revision+(item.archived?" · 保存前":" · 最新");
      button.disabled=!item.archived;
      button.onclick=()=>action(async()=>{
        if(lastServerRevision!==listing.current_revision)
          throw Error("PC側の編集版が変わっています。PC側の編集を取得してください。");
        if(!confirm("PCの版 "+item.revision+" の編集内容へ戻しますか？\n現在の編集内容は保存履歴に退避されます。必要ならブラウザのJSONを先に保存してください。"))return;
        const restored=await api("/api/projects/"+serverProjectId+"/restore-revision",
          payload({target_revision:item.revision,expected_revision:lastServerRevision}));
        lastServerRevision=restored.edit_revision;
        lastServerSegments=json(restored.segments);
        remember();
        editor().applyProject(restored);
        say("PCの保存履歴を復元しました。最新の版: "+lastServerRevision);
        await showServerHistory();
      });
      area.append(button);
    }
    say("PCに保存された編集履歴を表示しました。");
  }

  function targetFromInput() {
    const raw=$("bridgeAddress").value.trim();
    const url=new URL(raw.includes("://")?raw:"http://"+raw);
    const host=url.hostname.toLowerCase().replace(/^\[|\]$/g,"");
    const isLocal=host==="localhost" || host==="::1" || host.startsWith("127.") ||
      host.endsWith(".local") || /^192\.168\.\d{1,3}\.\d{1,3}$/.test(host) ||
      /^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(host) ||
      /^172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}$/.test(host);
    if(!["http:","https:"].includes(url.protocol) || !isLocal || url.username || url.password)
      throw Error("接続先にはPCのプライベートIPか localhost を指定してください。");
    url.pathname="/studio/";url.search="";url.hash="";
    return url.href;
  }
  function init() {
    if(!$("bridgePanel"))return;
    $("bridgePages").hidden=native;
    $("bridgeNative").hidden=!native;
    $("bridgeBadge").textContent=native?"PCエンジン接続モード":"ブラウザ単独モード";
    if(native) {
      $("bridgeSync").onclick=()=>action(confirmProject);
      $("bridgePause").onclick=()=>{
        transferPaused=true;
        activeController?.abort();
        say("転送を一時停止しています…");
      };
      $("bridgeExport").onclick=()=>action(nativeRender);
      $("bridgeOpenEditor").onclick=()=>action(async()=>{
        const id=await confirmProject();
        location.assign("/?project="+encodeURIComponent(id));
      });
      $("bridgePull").onclick=()=>action(pullFromServer);
      $("bridgeServerHistory").onclick=()=>action(showServerHistory);
      $("bridgeLoginButton").onclick=()=>action(async()=>{
        const password=$("bridgePassword").value;
        await api("/api/login",payload({password}));
        $("bridgePassword").value="";
        $("bridgeLogin").hidden=true;
        say("ローカルPCとの認証が完了しました。");
      });
      $("bridgeDownload").hidden=true;
      say("PC側のFFmpeg・OpenCVを使うには、動画を開いて「PCに同期」してください。");
    } else {
      $("bridgeOpen").onclick=()=>{
        try {
          const dest=targetFromInput();
          if(state()?.ready && !confirm("別の画面へ移動します。編集内容は自動で引き継がれません。\n先に編集JSONを保存し、PC版で同じ動画とJSONを読み込んでください。続けますか？"))return;
          location.assign(dest);
        } catch(err){say(err.message,true)}
      };
      $("bridgeSaveFirst").onclick=()=>{
        if(!state()?.ready){say("先に動画を読み込んでください。",true);return}
        editor().saveJson();
        say("JSONを保存しました。接続先へ移動後、元動画とJSONを再選択してください。");
      };
      say("この画面は完全にブラウザ内で編集します。PCの機能を使う場合は接続先へ移動します。");
    }
  }
  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",init,{once:true});
  else init();
})();

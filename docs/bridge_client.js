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
  const REMEMBER_KEY = "movie-modify-native-project";
  function remembered() {
    try { return JSON.parse(sessionStorage.getItem(REMEMBER_KEY) || "null"); }
    catch (_err) { return null; }
  }
  function remember() {
    const snap=state();
    if(!snap?.file || !serverProjectId)return;
    sessionStorage.setItem(REMEMBER_KEY, JSON.stringify({
      id:serverProjectId, name:snap.file.name, size:snap.file.size,
      modified:snap.file.lastModified, projection:snap.projection,
      duration:snap.duration, baseline:lastServerSegments,
      revision:lastServerRevision
    }));
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
    if(!response.ok)throw Error(data.detail||"HTTP "+response.status);
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
      const data=new FormData();
      data.append("file",snapshot.file,snapshot.file.name);
      data.append("projection",snapshot.projection);
      say("元動画をローカルPCへ送信中…");
      const created=await api("/api/projects",{method:"POST",body:data});
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
      $("bridgeExport").onclick=()=>action(nativeRender);
      $("bridgeOpenEditor").onclick=()=>action(async()=>{
        const id=await confirmProject();
        location.assign("/?project="+encodeURIComponent(id));
      });
      $("bridgePull").onclick=()=>action(pullFromServer);
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

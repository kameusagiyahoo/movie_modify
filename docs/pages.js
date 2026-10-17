/* Movie Modify GitHub Pages edition. Media never leaves this browser.
   Time and orientation use the same source-time EDL format as the local app. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const video = $('sourceVideo');
  const canvas = $('previewCanvas');
  const surface = $('playerSurface');
  const status = $('status');
  const panels = Array.from(document.querySelectorAll('[data-panel]'));
  let file = null, fileURL = null, duration = 0, projection = 'flat';
  let segments = [], selected = 0, zoom = 1, live = null;
  let loaded = false, dirty = false, draft = null, pendingProject = null;
  let recordBusy = false, exportingURL = null, toastTimer;
  let lastUiTick = 0;
  let editHistory = null;

  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const wrap = v => ((v + 180) % 360 + 360) % 360 - 180;
  const clock = t => {
    t = Math.max(0, Number(t) || 0);
    const h = Math.floor(t / 3600), m = Math.floor(t / 60) % 60, s = Math.floor(t % 60);
    return (h ? `${h}:` : '') + `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };
  const jsonDownload = (object, filename) => downloadBlob(
    new Blob([JSON.stringify(object, null, 2)], {type: 'application/json'}), filename);
  function notify(message, bad = false) {
    status.textContent = message;
    status.classList.remove('hidden');
    status.style.borderColor = bad ? '#e89c9b' : '#6adbc5';
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => status.classList.add('hidden'), 6500);
  }
  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = filename;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
  const fresh = (start, end) => ({start, end, keep:true, yaw:0, pitch:0, fov:90, mode:'manual', keyframes:[], suggested:false});
  function validateSegment(s, prevEnd) {
    const clean = {...fresh(0,0), ...s};
    for (const k of ['start','end','yaw','pitch','fov']) clean[k] = Number(clean[k]);
    if (!['start','end','yaw','pitch','fov'].every(k => Number.isFinite(clean[k])) ||
        clean.start < prevEnd - 0.003 || clean.end > duration + .08 ||
        clean.end - clean.start < .04 || clean.start < 0 ||
        Math.abs(clean.yaw)>180 || Math.abs(clean.pitch)>90 || clean.fov<35 || clean.fov>140 ||
        typeof clean.keep !== 'boolean') throw Error('編集JSONの区間データが無効です');
    clean.start = Math.max(0, clean.start); clean.end = Math.min(duration, clean.end);
    clean.mode = clean.mode === 'follow' ? 'follow' : 'manual';
    if (!Array.isArray(clean.keyframes) || clean.keyframes.length > 20000) throw Error('画角キーフレームが無効です');
    clean.keyframes = clean.keyframes.map(k => {
      const frame = {};
      for(const name of ['time','yaw','pitch','fov']) frame[name] = Number(k[name]);
      if (!Object.values(frame).every(Number.isFinite) || frame.time < clean.start-.005 || frame.time > clean.end+.005 ||
          Math.abs(frame.yaw)>180 || Math.abs(frame.pitch)>90 || frame.fov<35 || frame.fov>140)
        throw Error('画角キーフレームが無効です');
      return frame;
    }).sort((a,b) => a.time-b.time);
    return clean;
  }

  // Timeline snapshots are identical on Pages and Studio. They contain edit
  // instructions only, never File / Blob objects or source video bytes.
  function editorSnapshot() {
    return {segments:segments.map(s=>({...s,keyframes:(s.keyframes||[]).map(k=>({...k}))})),
      selected, time:video.currentTime||0};
  }
  function validateSnapshot(snapshot) {
    if(!snapshot||!Array.isArray(snapshot.segments)||!snapshot.segments.length||
       snapshot.segments.length>5000)throw Error('復元する編集データが不正です');
    let end=0;
    const list=snapshot.segments.map(item=>{
      const seg=validateSegment(item,end);end=seg.end;return seg;
    });
    return {segments:list,selected:clamp(Number(snapshot.selected)||0,0,list.length-1),
      time:clamp(Number(snapshot.time)||0,0,Math.max(0,duration-.01))};
  }
  function setHistoryStatus(state) {
    $('editUndo').disabled=!state.canUndo||recordBusy;
    $('editRedo').disabled=!state.canRedo||recordBusy;
    $('editUndo').title=state.canUndo?'元に戻す：'+state.undoLabel:'元に戻せる操作はありません';
    $('editRedo').title=state.canRedo?'やり直す：'+state.redoLabel:'やり直せる操作はありません';
    const label=$('editSafety');
    if(state.error){label.textContent=state.error;label.classList.add('error');}
    else {label.classList.remove('error');
      label.textContent='編集内容を端末内に自動保存中（元動画は保存されません）';}
    drawEditHistory();
  }
  function drawEditHistory() {
    const area=$('editHistoryList');
    if(!area||!editHistory)return;
    area.replaceChildren();
    const start=Math.max(0,editHistory.entries.length-10);
    editHistory.entries.slice(start).forEach((entry,offset)=>{
      const index=start+offset;
      const b=document.createElement('button');
      b.type='button';
      b.textContent=(index+1)+' · '+entry.label;
      b.className=index===editHistory.cursor?'current':'';
      b.disabled=index===editHistory.cursor||recordBusy;
      b.onclick=()=>{
        if(!editHistory||recordBusy)return;
        applySnapshot(editHistory.goTo(index));
        dirty=true;
        notify('選択した履歴へ移動しました');
      };
      area.append(b);
    });
  }
  function checkpoint(label) {
    if(!loaded||!editHistory)return;
    dirty=true;
    editHistory.checkpoint(editorSnapshot(),label);
  }
  function applySnapshot(snapshot) {
    const safe=validateSnapshot(snapshot);
    segments=safe.segments;selected=safe.selected;draft=null;
    video.currentTime=safe.time;
    renderTimeline();showSegment();updatePlayback(safe.time);
  }
  function undoEdit() {
    if(!loaded||recordBusy||!editHistory)return;
    const before=editHistory.undo();
    if(before){applySnapshot(before);dirty=true;notify('直前の編集を戻しました');}
  }
  function redoEdit() {
    if(!loaded||recordBusy||!editHistory)return;
    const after=editHistory.redo();
    if(after){applySnapshot(after);dirty=true;notify('編集をやり直しました');}
  }
  function initializeHistory(skipRestore=false) {
    const identity={name:file.name,size:file.size,modified:file.lastModified,
      projection,duration,width:video.videoWidth,height:video.videoHeight};
    const key='browser:'+MovieModifyEditHistory.hash(identity);
    editHistory=new MovieModifyEditHistory.EditHistory({
      key,identity,initial:editorSnapshot(),onUpdate:setHistoryStatus
    });
    if(skipRestore){setHistoryStatus(editHistory.state());return;}
    const candidate=editHistory.candidate();
    if(candidate.status==='available') {
      const date=new Date(candidate.savedAt).toLocaleString('ja-JP');
      if(confirm('この動画の編集下書き（'+date+'）があります。復元しますか？\n元動画は保存されていないため、現在選択した素材を使用します。')){
        try{
          const restored=editHistory.restore(candidate.snapshot,validateSnapshot);
          applySnapshot(restored);dirty=true;
          notify('自動保存された編集を復元しました。');
        }catch(error){notify('下書きを検証できません：'+error.message,true);}
      }
    } else if(candidate.status==='invalid'||candidate.status==='conflict') {
      notify('以前の下書きは現在の動画に安全に適用できないため、復元しませんでした。',true);
    }
    setHistoryStatus(editHistory.state());
  }

  function cameraAt(segment,t) {
    if (!segment) return {yaw:0,pitch:0,fov:90};
    const keys = segment.keyframes || [];
    if (!keys.length) return {yaw:segment.yaw,pitch:segment.pitch,fov:segment.fov};
    if (t <= keys[0].time) return keys[0];
    if (t >= keys[keys.length-1].time) return keys[keys.length-1];
    for(let i=1;i<keys.length;i++) {
      const a=keys[i-1], b=keys[i];
      if(t<=b.time) {
        const f=clamp((t-a.time)/Math.max(.001,b.time-a.time),0,1);
        return {yaw:wrap(a.yaw+wrap(b.yaw-a.yaw)*f),pitch:a.pitch+(b.pitch-a.pitch)*f,fov:a.fov+(b.fov-a.fov)*f};
      }
    }
    return keys[keys.length-1];
  }
  function findIndex(t) {
    return segments.findIndex(s => t >= s.start-.003 && t < s.end-.002);
  }
  function selectedAt(t) {
    return segments[findIndex(t)] || segments[selected] || fresh(0,1);
  }
  function viewerPose(t) {
    const seg = selectedAt(t);
    if (draft && Math.abs(draft.time-t)<.1 && segments.indexOf(seg)===selected) return draft;
    return cameraAt(seg,t);
  }
  function teardown() {
    if (live) {live.destroy();live=null;}
    video.pause();
    video.removeAttribute('src'); video.load();
    if (fileURL) URL.revokeObjectURL(fileURL);
    fileURL = null;
    loaded = false;
  }
  async function openVideo(newFile) {
    if (!newFile) return;
    if (recordBusy) return;
    teardown();
    file = newFile;
    projection = $('projection').value;
    $('fileName').textContent = newFile.name;
    $('projectTitle').textContent = newFile.name;
    $('videoInfo').textContent = (projection === 'flat' ? '通常動画' : '360度動画') + ' · 端末内処理';
    $('emptyState').classList.add('hidden');
    fileURL = URL.createObjectURL(newFile);
    video.src = fileURL;
    video.load();
  }
  function onVideoReady() {
    if (!file) return;
    duration = video.duration;
    if (!Number.isFinite(duration) || duration<=0) {
      notify('動画の長さを取得できません。対応形式をご確認ください。',true);return;
    }
    if (projection === 'equirect' && video.videoWidth/video.videoHeight < 1.7) {
      notify('360度動画は横:縦が約2:1の変換済み動画を使ってください。',true); return;
    }
    loaded=true;dirty=false;segments=[fresh(0,duration)];selected=0;draft=null;zoom=1;
    $('durationText').textContent=clock(duration);
    $('totalTime').textContent=clock(duration);
    $('seek').max=duration;
    surface.classList.toggle('flat',projection==='flat');
    surface.classList.toggle('equirect',projection==='equirect');
    if(projection==='equirect') {
      try {
        live = new LivePanoramaPreview(canvas,video,viewerPose,updatePlayback);
        live.onError=err => {if(!recordBusy) notify('360度プレビュー描画エラー: '+err.message,true);};
      } catch(err) {
        notify('この端末はWebGLに対応していません。360度の全景再生へ切り替えます。',true);
        surface.classList.replace('equirect','flat');
      }
    }
    const suppliedProject=!!pendingProject;
    initializeHistory(suppliedProject);
    if (pendingProject) {
      const data = pendingProject;pendingProject=null;
      try{applyProject(data);}catch(err){notify(err.message,true);}
    }
    syncControls();renderTimeline();showSegment();updatePlayback(0);
    $('openFile').textContent='素材を変更';
    $('viewerMode').textContent=projection==='flat'?'スマホなどの通常動画':'360度・16:9画角プレビュー';
    notify('読み込み完了。動画はサーバーに送信されません。');
  }
  function syncControls() {
    const on = loaded && !recordBusy;
    if(editHistory)setHistoryStatus(editHistory.state());
    for(const id of ['playPause','seek','split','toggleKeep','saveJson','saveJsonBottom','exportVideo']) $(id).disabled=!on;
    $('scenery').disabled=!on || projection!=='equirect';
    for(const id of ['yaw','pitch','fov','setKey','resetView']) $(id).disabled=!on || projection!=='equirect';
    $('angleChip').textContent=projection==='equirect'?'360度': '通常動画では無効';
    $('exportSupport').textContent=recordSupport();
  }
  function recordSupport() {
    if (!loaded) return '素材の読込後に書き出し対応を判定します。';
    if(!HTMLCanvasElement.prototype.captureStream || typeof MediaRecorder==='undefined')
      return 'このブラウザは動画の書き出し非対応です。編集JSONを保存し、PC版で出力してください。';
    return '対応ブラウザでは録画形式を自動選択します。長尺動画は等倍速での処理となります。';
  }
  function showSegment() {
    if(!segments.length) return;
    selected=clamp(selected,0,segments.length-1);
    const seg=segments[selected];
    $('selectionInfo').textContent=`区間 ${selected+1}: ${clock(seg.start)} – ${clock(seg.end)}`;
    const kept=segments.reduce((n,s)=>n+(s.keep?s.end-s.start:0),0);
    $('summaryInfo').textContent=`残す ${clock(kept)} / 全体 ${clock(duration)}`;
    $('toggleKeep').textContent=seg.keep?'カット指定':'元に戻して残す';
    const t=clamp(video.currentTime||seg.start,seg.start,seg.end);
    const p=cameraAt(seg,t);
    for(const key of ['yaw','pitch','fov']) {
      $(key).value=p[key];$(key+'Label').textContent=`${Math.round(p[key])}°`;
    }
  }
  function timelineBars() {
    const track=$('timeline');
    track.replaceChildren();
    track.style.width=`${zoom*100}%`;
    segments.forEach((s,i)=>{
      const btn=document.createElement('button');
      btn.type='button';btn.className=`clip ${s.keep?(s.mode==='follow'?'follow':''):'cut'} ${i===selected?'selected':''}`;
      btn.style.width=`${(s.end-s.start)/duration*100}%`;
      btn.title=`${clock(s.start)} – ${clock(s.end)} · ${s.keep?(s.mode==='follow'?'人物追尾':'景色／通常'):'カット'}`;
      const span=document.createElement('span');span.textContent=(s.end-s.start)/duration*zoom>.1?String(i+1):'';
      btn.append(span);
      btn.onclick=e=>{
        const rect=btn.getBoundingClientRect();
        const fraction=clamp((e.clientX-rect.left)/Math.max(1,rect.width),0,1);
        selected=i;draft=null;video.currentTime=clamp(s.start+(s.end-s.start)*fraction,0,duration-.01);
        showSegment();renderTimeline();
      };
      track.append(btn);
    });
    const playhead=document.createElement('div');playhead.className='playhead';playhead.id='playhead';
    track.append(playhead);updatePlayhead();
    $('zoomText').textContent=`${zoom}×`;
    $('zoomIn').disabled=zoom>=16;$('zoomOut').disabled=zoom<=1;
  }
  function renderTimeline() {
    if(!loaded) return;
    timelineBars();
    const area=$('segmentList');area.replaceChildren();
    segments.forEach((s,i)=>{
      const b=document.createElement('button');b.className=`segment-item ${i===selected?'selected':''}`;
      const label=s.keep?(projection==='equirect'?(s.mode==='follow'?'人物追尾':'景色'):'残す'):'カット';
      b.innerHTML=`<b>${i+1}</b><span>${clock(s.start)} – ${clock(s.end)}</span><small>${label}</small>`;
      b.onclick=()=>{selected=i;video.currentTime=s.start;draft=null;renderTimeline();showSegment()};
      area.append(b);
    });
  }
  function updatePlayhead() {
    if(!duration) return;
    const line=$('playhead');if(!line)return;
    line.style.left=`${clamp(video.currentTime/duration,0,1)*100}%`;
  }
  function updatePlayback(t) {
    if(!loaded || recordBusy && video.paused) return;
    const now=performance.now();
    if(now-lastUiTick<90 && !video.paused) return;
    lastUiTick=now;
    $('seek').value=clamp(t,0,duration);$('currentTime').textContent=clock(t);
    $('playPause').textContent=video.paused?'▶ 再生':'Ⅱ 一時停止';
    const index=findIndex(t);
    if(!recordBusy && !video.paused && $('skipCuts').checked && (index<0||!segments[index].keep)) {
      const next=segments.find(s=>s.keep&&s.start>t+.03);
      if(next) {video.currentTime=next.start;return;}
      video.pause();return;
    }
    if(index>=0 && index!==selected){selected=index;draft=null;renderTimeline();showSegment();}
    updatePlayhead();
  }
  function resizeZoom(v) {
    const next=clamp(v,1,16);
    zoom=next;
    if(!loaded)return;
    timelineBars();
    const vp=$('timelineViewport'),width=$('timeline').clientWidth;
    vp.scrollLeft=clamp(video.currentTime/duration,0,1)*width-vp.clientWidth*.5;
  }
  function sliceSegment(seg,start,end) {
    const result={...seg,start,end,keyframes:[]};
    if(seg.keyframes?.length){
      const times=[start,...seg.keyframes.filter(k=>k.time>start&&k.time<end).map(k=>k.time),end];
      result.keyframes=times.map(time=>({time,...cameraAt(seg,time)}));
    }
    return result;
  }
  function splitAt() {
    if(!loaded||recordBusy)return;
    const t=video.currentTime,i=segments.findIndex(s=>t>s.start+.06&&t<s.end-.06);
    if(i<0){notify('区間の内部に再生位置を移動してください。',true);return;}
    const s=segments[i];segments.splice(i,1,sliceSegment(s,s.start,t),sliceSegment(s,t,s.end));
    selected=i+1;draft=null;checkpoint('分割');renderTimeline();showSegment();notify('再生位置で区間を分割しました。');
  }
  function toggleCut() {
    if(!loaded||recordBusy)return;
    segments[selected].keep=!segments[selected].keep;
    checkpoint('残す／カット');renderTimeline();showSegment();
  }
  function selectScenery() {
    if(!loaded||projection!=='equirect'||recordBusy)return;
    const t=video.currentTime;
    let i=segments.findIndex(s=>t>s.start+.06&&t<s.end-.06);
    if(i>=0){const s=segments[i];segments.splice(i,1,sliceSegment(s,s.start,t),sliceSegment(s,t,s.end));selected=i+1;}
    else if(findIndex(t)>=0) selected=findIndex(t);
    const seg=segments[selected],p=cameraAt(seg,t);
    Object.assign(seg,{yaw:p.yaw,pitch:p.pitch,fov:p.fov,mode:'manual',keyframes:[]});
    draft=null;checkpoint('景色に切り替え');renderTimeline();showSegment();switchTab('camera');
    notify('景色の方向をスライダーで指定し、「画角キー追加」を押してください。');
  }
  function updateDraft() {
    if(!loaded||projection!=='equirect')return;
    const values={time:clamp(video.currentTime,segments[selected].start,segments[selected].end),
      yaw:Number($('yaw').value),pitch:Number($('pitch').value),fov:Number($('fov').value)};
    for(const k of ['yaw','pitch','fov']) $(k+'Label').textContent=`${Math.round(values[k])}°`;
    draft=values;
  }
  function addKey() {
    if(!loaded||projection!=='equirect')return;
    const seg=segments[selected];
    const time=clamp(video.currentTime,seg.start,seg.end-.002);
    const pose=draft||{yaw:Number($('yaw').value),pitch:Number($('pitch').value),fov:Number($('fov').value)};
    if(seg.mode==='follow'){seg.mode='manual';seg.keyframes=[];}
    if(!seg.keyframes.length && time>seg.start+.002) seg.keyframes=[{time:seg.start,yaw:seg.yaw,pitch:seg.pitch,fov:seg.fov}];
    seg.keyframes=seg.keyframes.filter(k=>Math.abs(k.time-time)>.004);
    seg.keyframes.push({time,yaw:pose.yaw,pitch:pose.pitch,fov:pose.fov});
    seg.keyframes.sort((a,b)=>a.time-b.time);
    draft=null;checkpoint('画角キー追加');renderTimeline();showSegment();notify('画角キーフレームを追加しました。');
  }
  function resetAngle() {
    if(!loaded||projection!=='equirect')return;
    Object.assign(segments[selected],{yaw:0,pitch:0,fov:90,keyframes:[],mode:'manual'});
    draft=null;checkpoint('画角をリセット');renderTimeline();showSegment();
  }
  function projectJson() {
    return {schema:'movie-modify-pages/v1',name:file?.name||'video',projection,duration,
      source:{name:file?.name||'',size:file?.size||0,modified:file?.lastModified||0,width:video.videoWidth,height:video.videoHeight},
      segments:segments.map(s=>({...s,keyframes:s.keyframes.map(k=>({...k}))}))};
  }
  function saveJson() {
    if(!loaded)return notify('先に動画を読み込んでください。',true);
    jsonDownload(projectJson(),(file?.name||'video').replace(/\.[^.]+$/,'')+'.movie-modify.json');
    dirty=false;notify('編集内容をJSONで保存しました。動画そのものは含まれません。');
  }
  function applyProject(data) {
    if(!loaded){pendingProject=data;notify('JSONを記憶しました。対応する動画を開いてください。');return;}
    const list=data?.segments;
    if(!Array.isArray(list)||list.length<1||list.length>5000)throw Error('有効なsegmentsがありません');
    if(data.projection && data.projection!==projection) throw Error('編集JSONと読み込んだ動画の形式が異なります');
    // Imported JSON may travel from iPhone to Windows/Linux, where its
    // lastModified timestamp (and sometimes filename) can legitimately change.
    // Never silently apply to a different file; ask the user explicitly.
    const mismatch=(data.name&&data.name!==file.name) ||
      (data.source&&(data.source.name!==file.name||
       Number(data.source.size)!==file.size||
       Number(data.source.modified)!==file.lastModified||
       Number(data.source.width)!==video.videoWidth||
       Number(data.source.height)!==video.videoHeight));
    if(mismatch && !confirm('編集JSONと元動画の名前・サイズ・更新日時・解像度のいずれかが一致しません。\\n別の動画への誤適用を避けるため確認してください。\\nこの動画が正しい元素材であることを確認して読込みますか？'))
      throw Error('元動画が一致しないためJSON読込みをキャンセルしました。');
    if(Number.isFinite(Number(data.duration)) && Math.abs(Number(data.duration)-duration)>1)
      throw Error('動画の長さが一致しません。同じ素材を読み込んでください。');
    let end=0;
    const parsed=list.map(s=>{const value=validateSegment(s,end);end=value.end;return value;});
    segments=parsed;selected=0;draft=null;dirty=false;
    checkpoint('JSON読込');
    renderTimeline();showSegment();notify(`${parsed.length}区間の編集情報を読み込みました。`);
  }
  function selectMime() {
    const types=['video/mp4;codecs=avc1.42E01E,mp4a.40.2','video/mp4',
      'video/webm;codecs=vp8,opus','video/webm;codecs=vp8','video/webm'];
    return types.find(t=>MediaRecorder.isTypeSupported(t))||'';
  }
  const seekVideo = to => new Promise((resolve,reject)=>{
    const t=clamp(to,0,Math.max(0,duration-.01));
    if(Math.abs(video.currentTime-t)<.05)return resolve();
    const timer=setTimeout(()=>{cleanup();reject(Error('シークに時間がかかっています'));},16000);
    const done=()=>{cleanup();resolve();};
    function cleanup(){clearTimeout(timer);video.removeEventListener('seeked',done);video.removeEventListener('error',fail);}
    function fail(){cleanup();reject(Error('動画のシークに失敗しました'));}
    video.addEventListener('seeked',done,{once:true});video.addEventListener('error',fail,{once:true});
    video.currentTime=t;
  });
  async function exportRecording() {
    if(!loaded||recordBusy)return;
    if(!HTMLCanvasElement.prototype.captureStream || typeof MediaRecorder==='undefined')
      return notify('このブラウザでは動画を書き出せません。編集JSONを保存してください。',true);
    const kept=segments.filter(s=>s.keep);
    if(!kept.length)return notify('残す区間がありません。',true);
    const message='ブラウザで動画を等倍速録画します。長尺動画では時間がかかり、音声や形式は端末依存です。続けますか？';
    if(!confirm(message))return;
    recordBusy=true;syncControls();video.pause();
    const renderCanvas=projection==='equirect'&&live?canvas:document.createElement('canvas');
    if(renderCanvas!==canvas){renderCanvas.width=960;renderCanvas.height=540;}
    const ctx=renderCanvas!==canvas?renderCanvas.getContext('2d'):null;
    let raf=0,recorder=null,audioCtx=null,blobUrl=null;
    let stopped=false,part=0,transitioning=false,mediaStream;
    const chunks=[];
    try{
      if(ctx){
        const paint=()=>{
          if(stopped)return;
          if(video.readyState>=2){
            ctx.fillStyle='#000';ctx.fillRect(0,0,960,540);
            const scale=Math.min(960/video.videoWidth,540/video.videoHeight);
            const w=video.videoWidth*scale,h=video.videoHeight*scale;
            ctx.drawImage(video,(960-w)/2,(540-h)/2,w,h);
          }
          raf=requestAnimationFrame(paint);
        };paint();
      }
      mediaStream=renderCanvas.captureStream(24);
      // Browser-managed media element audio; no request to a microphone/server.
      try{
        const AudioCtor=window.AudioContext||window.webkitAudioContext;
        if(AudioCtor){
          audioCtx=new AudioCtor();
          const node=audioCtx.createMediaElementSource(video),dest=audioCtx.createMediaStreamDestination();
          node.connect(dest);node.connect(audioCtx.destination);
          dest.stream.getAudioTracks().forEach(track=>mediaStream.addTrack(track));
          await audioCtx.resume();
        }
      }catch(err){notify('音声を録画へ追加できません。映像のみになる可能性があります。',true);}
      const mime=selectMime();
      recorder=new MediaRecorder(mediaStream,mime?{mimeType:mime,videoBitsPerSecond:2500000}:undefined);
      recorder.ondataavailable=e=>{if(e.data&&e.data.size)chunks.push(e.data);};
      const finished=new Promise((resolve,reject)=>{
        recorder.onerror=e=>reject(Error('録画に失敗しました: '+(e.error?.message||'unknown')));
        recorder.onstop=resolve;
      });
      await seekVideo(kept[0].start);
      // MediaRecorder pauses during seeking so dropped source intervals do not
      // produce lengthy still-frame sections in the output.
      recorder.start(1000);
      $('exportVideo').textContent='録画中…';
      await video.play();
      await new Promise((resolve,reject)=>{
        let timer=requestAnimationFrame(async function watch(){
          if(stopped)return;
          if(transitioning){timer=requestAnimationFrame(watch);return;}
          const s=kept[part];
          if(!s){resolve();return;}
          if(video.currentTime>=s.end-.035||video.ended){
            transitioning=true;video.pause();
            if(part+1>=kept.length){resolve();return;}
            try{
              if(recorder.state==='recording'&&recorder.pause)recorder.pause();
              part+=1;
              await seekVideo(kept[part].start);
              if(recorder.state==='paused')recorder.resume();
              await video.play();
            }catch(err){reject(err);return;}
            finally{transitioning=false;}
          }
          timer=requestAnimationFrame(watch);
        });
        const abort=()=>{cancelAnimationFrame(timer);reject(Error('動画の再生に失敗しました'));};
        video.addEventListener('error',abort,{once:true});
      });
      video.pause();
      if(recorder.state!=='inactive')recorder.stop();
      await finished;
      const blob=new Blob(chunks,{type:recorder.mimeType||'video/webm'});
      if(!blob.size)throw Error('録画データが生成されませんでした');
      const ext=(recorder.mimeType||'').includes('mp4')?'mp4':'webm';
      if(exportingURL)URL.revokeObjectURL(exportingURL);
      exportingURL=URL.createObjectURL(blob);
      const download=$('downloadVideo');download.href=exportingURL;
      download.download=(file?.name||'video').replace(/\.[^.]+$/,'')+'-edited.'+ext;
      download.classList.remove('hidden');
      download.textContent=`完成動画を保存 (${(blob.size/1048576).toFixed(1)} MB)`;
      notify('録画が完了しました。音声・画角・区間のつなぎ目を確認してください。');
    }catch(err){
      if(recorder && recorder.state!=='inactive')recorder.stop();
      notify('書き出しできませんでした: '+err.message+'。編集JSONは保存できます。',true);
    }finally{
      stopped=true;cancelAnimationFrame(raf);video.pause();
      mediaStream?.getTracks().forEach(t=>t.stop());
      if(audioCtx)await audioCtx.close().catch(()=>{});
      recordBusy=false;$('exportVideo').textContent='編集動画を書き出す（試験機能）';syncControls();
    }
  }
  function switchTab(name) {
    document.body.dataset.tab=name;
    $('mobileTabs').querySelectorAll('button').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));
  }
  function bind() {
    $('openFile').onclick=()=>{if(matchMedia('(max-width:730px)').matches)document.body.classList.toggle('library-open');else $('fileInput').click();};
    $('closeLibrary').onclick=()=>document.body.classList.remove('library-open');
    $('toggleLibrary').onclick=()=>document.body.classList.toggle('library-open');
    $('fileInput').onchange=e=>{document.body.classList.remove('library-open');openVideo(e.target.files[0]);e.target.value='';};
    $('projection').onchange=()=>{if(loaded){notify('撮影形式の変更には同じ動画を再選択してください。');}};
    video.addEventListener('loadedmetadata',onVideoReady);
    video.addEventListener('error',()=>{if(file)notify('この端末で動画を再生できません。MP4 H.264などをお試しください。',true);});
    video.addEventListener('timeupdate',()=>updatePlayback(video.currentTime));
    video.addEventListener('play',()=>{$('playPause').textContent='Ⅱ 一時停止';});
    video.addEventListener('pause',()=>{$('playPause').textContent='▶ 再生';});
    $('playPause').onclick=async()=>{
      if(video.paused){try{await video.play();}catch(err){notify('再生できません: '+err.message,true);}}
      else video.pause();
    };
    $('seek').oninput=e=>{if(loaded&&!recordBusy){draft=null;video.currentTime=Number(e.target.value);updatePlayback(video.currentTime);showSegment();}};
    $('split').onclick=splitAt;$('toggleKeep').onclick=toggleCut;$('scenery').onclick=selectScenery;
    $('editUndo').onclick=undoEdit;$('editRedo').onclick=redoEdit;
    for(const id of ['yaw','pitch','fov']) $(id).oninput=updateDraft;
    $('setKey').onclick=addKey;$('resetView').onclick=resetAngle;
    $('zoomOut').onclick=()=>resizeZoom(zoom/2);$('zoomIn').onclick=()=>resizeZoom(zoom*2);
    $('saveJson').onclick=saveJson;$('saveJsonBottom').onclick=saveJson;
    $('projectInput').onchange=async e=>{
      const f=e.target.files[0];if(!f)return;
      try{const data=JSON.parse(await f.text());applyProject(data);}
      catch(err){notify('編集JSONの読込に失敗しました: '+err.message,true);}e.target.value='';
    };
    $('exportVideo').onclick=exportRecording;
    $('mobileTabs').querySelectorAll('button').forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));
    $('mobileActions').querySelectorAll('button').forEach(b=>b.onclick=()=>{
      if(b.dataset.action==='split')splitAt();
      if(b.dataset.action==='cut')toggleCut();
      if(b.dataset.action==='scenery')projection==='equirect'?selectScenery():switchTab('timeline');
      if(b.dataset.action==='save')saveJson();
    });
    document.addEventListener('keydown',e=>{
      const typing=e.target.closest('input,button,select,textarea,[contenteditable]');
      if(loaded&&!typing&&(e.metaKey||e.ctrlKey)&&!e.altKey&&e.code==='KeyZ'){
        e.preventDefault();if(e.shiftKey)redoEdit();else undoEdit();return;
      }
      if(loaded&&!typing&&(e.metaKey||e.ctrlKey)&&!e.altKey&&e.code==='KeyY'){
        e.preventDefault();redoEdit();return;
      }
      if(!loaded||typing||e.metaKey||e.ctrlKey||e.altKey)return;
      if(e.code==='Space'){e.preventDefault();$('playPause').click();}
      if(e.code==='KeyS'){e.preventDefault();splitAt();}
      if(e.code==='ArrowLeft'||e.code==='ArrowRight'){
        e.preventDefault();video.currentTime=clamp(video.currentTime+(e.code==='ArrowLeft'?-5:5),0,duration-.01);
      }
    });
    window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
    const vp=$('timelineViewport');let pinch=0,pinchZoom=1;
    vp.addEventListener('touchstart',e=>{
      if(e.touches.length===2){pinch=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);pinchZoom=zoom;}
    },{passive:true});
    vp.addEventListener('touchmove',e=>{
      if(e.touches.length!==2||!pinch)return;
      e.preventDefault();const d=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);
      const target=pinchZoom*d/pinch;
      const levels=[1,2,4,8,16];resizeZoom(levels.reduce((a,b)=>Math.abs(b-target)<Math.abs(a-target)?b:a,1));
    },{passive:false});
    vp.addEventListener('touchend',e=>{if(e.touches.length<2)pinch=0;},{passive:true});
    syncControls();switchTab('timeline');
  }
  // Shared browser edit state. The optional native bridge reads it only
  // after an explicit user action, never in the background.
  window.MovieModifyPagesBridge = {
    getState: () => ({
      ready: loaded, file, projection, duration, dirty,
      project: loaded ? projectJson() : null
    }),
    applyProject,
    saveJson
  };
  bind();
})();
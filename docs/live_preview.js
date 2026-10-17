/* Standalone local WebGL equirectangular panorama renderer. */
(function (global) {
  "use strict";
  const vert = `attribute vec2 position;varying vec2 uv;void main(){uv=(position+1.0)*0.5;gl_Position=vec4(position,0.,1.);}`;
  const frag = `precision highp float;varying vec2 uv;uniform sampler2D panorama;uniform vec3 cameraPose;uniform vec2 fieldOfView;const float PI=3.141592653589793;void main(){vec3 local=normalize(vec3((uv.x-.5)*2.*tan(fieldOfView.x*.5),(uv.y-.5)*2.*tan(fieldOfView.y*.5),1.));float cp=cos(cameraPose.y),sp=sin(cameraPose.y);float cy=cos(cameraPose.x),sy=sin(cameraPose.x);vec3 pitched=vec3(local.x,cp*local.y+sp*local.z,cp*local.z-sp*local.y);vec3 direction=vec3(cy*pitched.x+sy*pitched.z,pitched.y,cy*pitched.z-sy*pitched.x);float longitude=atan(direction.x,direction.z),latitude=asin(clamp(direction.y,-1.,1.));vec2 pos=vec2(fract(.5+longitude/(2.*PI)),.5+latitude/PI);gl_FragColor=texture2D(panorama,pos);}`;
  function compile(gl,type,code) {
    const obj=gl.createShader(type);gl.shaderSource(obj,code);gl.compileShader(obj);
    if(!gl.getShaderParameter(obj,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(obj));
    return obj;
  }
  class LivePanoramaPreview {
    constructor(canvas,video,poseAt,onTick) {
      this.canvas=canvas;this.video=video;this.poseAt=poseAt;this.onTick=onTick;
      this.gl=canvas.getContext('webgl',{alpha:false,antialias:false,preserveDrawingBuffer:false});
      if(!this.gl)throw Error('WebGL is not supported');
      const gl=this.gl,p=gl.createProgram();
      gl.attachShader(p,compile(gl,gl.VERTEX_SHADER,vert));gl.attachShader(p,compile(gl,gl.FRAGMENT_SHADER,frag));gl.linkProgram(p);
      if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(p));
      this.program=p;
      const points=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,points);
      gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
      const at=gl.getAttribLocation(p,'position');gl.enableVertexAttribArray(at);gl.vertexAttribPointer(at,2,gl.FLOAT,false,0,0);
      this.pose=gl.getUniformLocation(p,'cameraPose');this.fov=gl.getUniformLocation(p,'fieldOfView');
      this.tex=gl.createTexture();gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,this.tex);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);
      gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,1,1,0,gl.RGBA,gl.UNSIGNED_BYTE,new Uint8Array([0,0,0,255]));
      gl.useProgram(p);gl.uniform1i(gl.getUniformLocation(p,'panorama'),0);
      this.disposed=false;this.last='';this.tick=this.tick.bind(this);this.frame=requestAnimationFrame(this.tick);
    }
    tick(){
      if(this.disposed)return;
      this.frame=requestAnimationFrame(this.tick);
      if(!this.video.isConnected||!this.canvas.isConnected)return;
      const t=this.video.currentTime||0;
      if(this.onTick)this.onTick(t);
      if(this.video.readyState<2)return;
      const pose=this.poseAt(t),tag=[t.toFixed(3),pose.yaw.toFixed(2),pose.pitch.toFixed(2),pose.fov.toFixed(2)].join(':');
      if(this.video.paused&&this.last===tag)return;
      this.last=tag;
      this.draw(pose);
    }
    draw(pose){
      const gl=this.gl,r=Math.min(window.devicePixelRatio||1,1.5);
      const w=Math.min(1280,Math.max(2,Math.round(this.canvas.clientWidth*r))),h=Math.max(2,Math.round(w*9/16));
      if(this.canvas.width!==w||this.canvas.height!==h){this.canvas.width=w;this.canvas.height=h;}
      gl.viewport(0,0,w,h);gl.useProgram(this.program);gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,this.tex);
      try {gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,this.video);}
      catch(e){this.onError?.(e);return;}
      const rad=Math.PI/180;gl.uniform3f(this.pose,pose.yaw*rad,pose.pitch*rad,0);
      gl.uniform2f(this.fov,pose.fov*rad,pose.fov*9/16*rad);gl.drawArrays(gl.TRIANGLES,0,6);
    }
    destroy(){this.disposed=true;cancelAnimationFrame(this.frame);this.gl.deleteTexture(this.tex);this.gl.deleteProgram(this.program);}
  }
  global.LivePanoramaPreview=LivePanoramaPreview;
})(window);
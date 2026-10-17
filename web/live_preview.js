/* Local WebGL panorama viewport for a stitched 2:1 video.
   No CDN, telemetry, media upload, or third-party runtime dependencies. */
(function (global) {
  "use strict";
  const VERT = [
    "attribute vec2 position;",
    "varying vec2 uv;",
    "void main(){uv=(position+1.0)*0.5;gl_Position=vec4(position,0.0,1.0);}"
  ].join("\n");
  const FRAG = [
    "precision highp float;",
    "varying vec2 uv;",
    "uniform sampler2D panorama;",
    "uniform vec3 cameraPose;",
    "uniform vec2 fieldOfView;",
    "const float PI=3.141592653589793;",
    "void main(){",
    "  vec3 local=normalize(vec3((uv.x-.5)*2.0*tan(fieldOfView.x*.5),",
    "                     (uv.y-.5)*2.0*tan(fieldOfView.y*.5),1.0));",
    "  float cp=cos(cameraPose.y),sp=sin(cameraPose.y);",
    "  float cy=cos(cameraPose.x),sy=sin(cameraPose.x);",
    "  vec3 pitched=vec3(local.x,cp*local.y+sp*local.z,cp*local.z-sp*local.y);",
    "  vec3 direction=vec3(cy*pitched.x+sy*pitched.z,pitched.y,",
    "                      cy*pitched.z-sy*pitched.x);",
    "  float longitude=atan(direction.x,direction.z);",
    "  float latitude=asin(clamp(direction.y,-1.0,1.0));",
    "  vec2 pos=vec2(fract(.5+longitude/(2.0*PI)),.5+latitude/PI);",
    "  gl_FragColor=texture2D(panorama,pos);",
    "}"
  ].join("\n");
  function shader(gl, type, code) {
    const result = gl.createShader(type);
    gl.shaderSource(result, code);
    gl.compileShader(result);
    if (!gl.getShaderParameter(result, gl.COMPILE_STATUS)) {
      throw Error("WebGL shader: " + gl.getShaderInfoLog(result));
    }
    return result;
  }
  class LivePanoramaPreview {
    constructor(canvas, video, poseAt, onTick) {
      this.canvas = canvas;
      this.video = video;
      this.poseAt = poseAt;
      this.onTick = onTick;
      this.disposed = false;
      this.last = "";
      this.frame = 0;
      this.gl = canvas.getContext("webgl", {
        alpha: false, antialias: false, preserveDrawingBuffer: false
      });
      const gl = this.gl;
      if (!gl) throw Error("このブラウザではWebGLを利用できません");
      const program = gl.createProgram();
      gl.attachShader(program, shader(gl, gl.VERTEX_SHADER, VERT));
      gl.attachShader(program, shader(gl, gl.FRAGMENT_SHADER, FRAG));
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        throw Error("WebGL program: " + gl.getProgramInfoLog(program));
      }
      this.program = program;
      gl.useProgram(program);
      const vertices = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, vertices);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
        -1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1
      ]), gl.STATIC_DRAW);
      const at = gl.getAttribLocation(program, "position");
      gl.enableVertexAttribArray(at);
      gl.vertexAttribPointer(at, 2, gl.FLOAT, false, 0, 0);
      this.poseLocation = gl.getUniformLocation(program, "cameraPose");
      this.fovLocation = gl.getUniformLocation(program, "fieldOfView");
      this.texture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, this.texture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA,
                    gl.UNSIGNED_BYTE, new Uint8Array([0,0,0,255]));
      gl.uniform1i(gl.getUniformLocation(program, "panorama"), 0);
      this.loop = this.loop.bind(this);
      this.frame = requestAnimationFrame(this.loop);
    }
    loop() {
      if (this.disposed) return;
      this.frame = requestAnimationFrame(this.loop);
      if (!this.video.isConnected || !this.canvas.isConnected) return;
      const time = this.video.currentTime || 0;
      if (this.onTick) this.onTick(time);
      if (this.video.readyState < 2) return;
      const pose = this.poseAt(time);
      const signature = [time.toFixed(3), pose.yaw.toFixed(2),
                         pose.pitch.toFixed(2), pose.fov.toFixed(2)].join(":");
      if (this.video.paused && signature === this.last) return;
      this.last = signature;
      this.draw(pose);
    }
    draw(pose) {
      const gl = this.gl;
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
      const width = Math.min(1280, Math.max(2, Math.round(this.canvas.clientWidth * ratio)));
      const height = Math.max(2, Math.round(width * 9 / 16));
      if (this.canvas.width !== width || this.canvas.height !== height) {
        this.canvas.width = width;
        this.canvas.height = height;
      }
      gl.viewport(0, 0, width, height);
      gl.useProgram(this.program);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.texture);
      try {
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA,
                      gl.UNSIGNED_BYTE, this.video);
      } catch (err) {
        this.onError?.(err);
        return;
      }
      const radians = Math.PI / 180;
      const horizontal = pose.fov * radians;
      const vertical = pose.fov * 9 / 16 * radians;
      gl.uniform3f(this.poseLocation, pose.yaw * radians, pose.pitch * radians, 0);
      gl.uniform2f(this.fovLocation, horizontal, vertical);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    }
    destroy() {
      this.disposed = true;
      cancelAnimationFrame(this.frame);
      if (this.gl) {
        this.gl.deleteTexture(this.texture);
        this.gl.deleteProgram(this.program);
      }
    }
  }
  global.LivePanoramaPreview = LivePanoramaPreview;
})(window);

/** A photographic parallax effect, not a reconstructed 360° food model. */
export type PhotoScene = {
  move: (x: number, y: number, zoom?: number) => void;
  resize: () => void;
  dispose: () => void;
};

export async function createPhotoScene(
  canvas: HTMLCanvasElement,
  url: string,
  onLost: () => void,
  signal: AbortSignal,
): Promise<PhotoScene> {
  const gl = canvas.getContext('webgl', {
    alpha: false,
    antialias: false,
    depth: false,
    stencil: false,
    powerPreference: 'low-power',
    preserveDrawingBuffer: false,
  });
  if (!gl) throw new Error('WebGL unavailable');
  let disposed = false;
  let frame = 0;
  let texture: WebGLTexture | null = null;
  let vertex: WebGLShader | null = null;
  let fragment: WebGLShader | null = null;
  let program: WebGLProgram | null = null;
  let buffer: WebGLBuffer | null = null;
  const image = new Image();
  const camera = { x: 0, y: 0, zoom: 1 };
  const lost = (event: Event) => {
    event.preventDefault();
    if (!disposed) onLost();
  };
  canvas.addEventListener('webglcontextlost', lost);
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(frame);
    canvas.removeEventListener('webglcontextlost', lost);
    image.onload = image.onerror = null;
    image.src = '';
    gl.deleteTexture(texture);
    gl.deleteBuffer(buffer);
    gl.deleteProgram(program);
    gl.deleteShader(vertex);
    gl.deleteShader(fragment);
    gl.getExtension('WEBGL_lose_context')?.loseContext();
    signal.removeEventListener('abort', dispose);
  };
  signal.addEventListener('abort', dispose, { once: true });
  try {
    await new Promise<void>((resolve, reject) => {
      if (signal.aborted) {
        reject(new DOMException('Aborted', 'AbortError'));
        return;
      }
      const abort = () => reject(new DOMException('Aborted', 'AbortError'));
      signal.addEventListener('abort', abort, { once: true });
      image.onload = () => {
        signal.removeEventListener('abort', abort);
        resolve();
      };
      image.onerror = () => {
        signal.removeEventListener('abort', abort);
        reject(new Error('Photo unavailable'));
      };
      image.src = url;
    });
    if (disposed || signal.aborted) throw new DOMException('Aborted', 'AbortError');
    const shader = (kind: number, source: string) => {
      const result = gl.createShader(kind);
      if (!result) throw new Error('Shader unavailable');
      gl.shaderSource(result, source);
      gl.compileShader(result);
      if (!gl.getShaderParameter(result, gl.COMPILE_STATUS)) {
        gl.deleteShader(result);
        throw new Error('Shader compilation failed');
      }
      return result;
    };
    vertex = shader(
      gl.VERTEX_SHADER,
      `
      attribute vec2 position;
      varying vec2 uv;
      void main() { uv = position * .5 + .5; gl_Position = vec4(position, 0., 1.); }
    `,
    );
    fragment = shader(
      gl.FRAGMENT_SHADER,
      `
      precision mediump float;
      uniform sampler2D photo;
      uniform vec2 cover;
      uniform vec2 movement;
      uniform float zoom;
      varying vec2 uv;
      void main() {
        vec2 p = (uv - .5) * cover / (1.06 * zoom) + .5;
        vec3 original = texture2D(photo, p).rgb;
        // Art-directed shallow relief. It deliberately never reveals unseen surfaces.
        float center = 1. - smoothstep(.12, .64, length((p - .5) * vec2(1., .9)));
        float detail = dot(original, vec3(.2126, .7152, .0722));
        float relief = center * (.72 + detail * .28);
        p += movement * (relief - .25) * .026;
        gl_FragColor = vec4(texture2D(photo, clamp(p, .001, .999)).rgb, 1.);
      }
    `,
    );
    program = gl.createProgram();
    if (!program) throw new Error('Program unavailable');
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('Program linking failed');
    gl.useProgram(program);
    buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW,
    );
    const position = gl.getAttribLocation(program, 'position');
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
    texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
    const cover = gl.getUniformLocation(program, 'cover');
    const movement = gl.getUniformLocation(program, 'movement');
    const zoomLocation = gl.getUniformLocation(program, 'zoom');
    const render = () => {
      frame = 0;
      if (disposed || document.hidden) return;
      const box = canvas.getBoundingClientRect();
      if (!box.width || !box.height || box.bottom < 0 || box.top > innerHeight) return;
      const ratio = Math.min(devicePixelRatio || 1, 1.5, 1400 / box.width, 1000 / box.height);
      const width = Math.max(1, Math.round(box.width * ratio));
      const height = Math.max(1, Math.round(box.height * ratio));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      gl.viewport(0, 0, width, height);
      const aspect = width / height;
      const imageAspect = image.naturalWidth / image.naturalHeight;
      gl.uniform2f(cover, Math.min(1, aspect / imageAspect), Math.min(1, imageAspect / aspect));
      gl.uniform2f(movement, camera.x, camera.y);
      gl.uniform1f(zoomLocation, camera.zoom);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    };
    const schedule = () => {
      if (!disposed && !frame) frame = requestAnimationFrame(render);
    };
    const move = (x: number, y: number, zoom = camera.zoom) => {
      camera.x = Math.max(-1, Math.min(1, x));
      camera.y = Math.max(-1, Math.min(1, y));
      camera.zoom = Math.max(1, Math.min(1.3, zoom));
      schedule();
    };
    schedule();
    return { move, resize: schedule, dispose };
  } catch (error) {
    dispose();
    throw error;
  }
}

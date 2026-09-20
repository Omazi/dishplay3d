package com.dishplay.capture

import android.opengl.GLES11Ext
import android.opengl.GLES20
import android.opengl.GLSurfaceView
import android.opengl.Matrix
import com.google.ar.core.Anchor
import com.google.ar.core.Coordinates2d
import com.google.ar.core.Frame
import com.google.ar.core.Plane
import com.google.ar.core.Session
import com.google.ar.core.TrackingState
import org.json.JSONArray
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import java.util.UUID
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10

/** Original minimal GLES renderer: camera texture, measured points, and a line volume. */
class ArRenderer(
    private val session: () -> Session?,
    private val rotation: () -> Int,
    private val onStatus: (String) -> Unit,
    private val onPhoto: (ByteArray, Int, Int, JSONObject) -> Unit,
    private val onCaptureError: (String) -> Unit,
) : GLSurfaceView.Renderer {
    @Volatile var volumeWidth = 0.30f
    @Volatile var volumeHeight = 0.18f
    @Volatile var volumeDepth = 0.30f
    @Volatile var captureRequested = false
    @Volatile var anchorLocked = false
    @Volatile private var pendingTap: Pair<Float, Float>? = null
    private var anchor: Anchor? = null
    private var segmentId = UUID.randomUUID().toString()
    private var wasTracking = false
    private var textureId = 0
    private var backgroundProgram = 0
    private var geometryProgram = 0
    private var width = 1
    private var height = 1
    private var lastStatusAt = 0L
    private var lastFrameTimestamp = -1L
    private var lastSession: Session? = null
    private val vertices = buffer(floatArrayOf(-1f, -1f, 1f, -1f, -1f, 1f, 1f, 1f))
    private val textureCoordinates = buffer(FloatArray(8))
    private val view = FloatArray(16)
    private val projection = FloatArray(16)
    private val viewProjection = FloatArray(16)
    private val model = FloatArray(16)
    private val modelViewProjection = FloatArray(16)

    fun tap(x: Float, y: Float) { if (!anchorLocked) pendingTap = x to y }

    /** Call on the GL thread. Images from distinct segments must be registered separately. */
    fun interruptTracking() {
        segmentId = UUID.randomUUID().toString(); wasTracking = false
        if (captureRequested) {
            captureRequested = false
            onCaptureError("Capture interrompue pendant la reprise du suivi. Réessayez lorsque le volume est ancré ; les originaux précédents restent conservés.")
        }
    }

    fun resetAnchor() {
        anchor?.detach(); anchor = null; anchorLocked = false; pendingTap = null
        interruptTracking()
    }

    override fun onSurfaceCreated(gl: GL10?, config: EGLConfig?) {
        val textures = IntArray(1)
        GLES20.glGenTextures(1, textures, 0); textureId = textures[0]
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, textureId)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE)
        backgroundProgram = program(
            "attribute vec2 aPosition; attribute vec2 aUv; varying vec2 vUv; void main(){gl_Position=vec4(aPosition,0.0,1.0);vUv=aUv;}",
            "#extension GL_OES_EGL_image_external : require\nprecision mediump float; uniform samplerExternalOES uTexture; varying vec2 vUv; void main(){gl_FragColor=texture2D(uTexture,vUv);}",
        )
        geometryProgram = program(
            "attribute vec3 aPosition; uniform mat4 uMvp; void main(){gl_Position=uMvp*vec4(aPosition,1.0);gl_PointSize=5.0;}",
            "precision mediump float; uniform vec4 uColor; void main(){gl_FragColor=uColor;}",
        )
        lastSession = null
    }

    override fun onSurfaceChanged(gl: GL10?, width: Int, height: Int) {
        this.width = width; this.height = height
        GLES20.glViewport(0, 0, width, height)
    }

    override fun onDrawFrame(gl: GL10?) {
        GLES20.glClearColor(0.14f, 0.17f, 0.14f, 1f)
        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT or GLES20.GL_DEPTH_BUFFER_BIT)
        val current = session() ?: return
        try {
            if (lastSession !== current) { resetAnchor(); lastSession = current }
            current.setCameraTextureName(textureId)
            current.setDisplayGeometry(rotation(), width, height)
            val frame = current.update()
            if (frame.timestamp == 0L) return
            drawBackground(frame)
            if (frame.camera.trackingState != TrackingState.TRACKING) {
                val cancelledCapture = captureRequested
                captureRequested = false
                if (wasTracking) interruptTracking()
                report("Suivi suspendu : ${frame.camera.trackingFailureReason}. Revenez lentement vers la zone photographiée.")
                if (cancelledCapture) { captureRequested = false; onCaptureError("Suivi indisponible. Aucune photo calibrée enregistrée ; vos prises précédentes restent conservées.") }
                return
            }
            wasTracking = true
            pendingTap?.let { (x, y) ->
                pendingTap = null
                if (!anchorLocked) {
                    val hit = frame.hitTest(x, y).firstOrNull { result ->
                        val plane = result.trackable as? Plane
                        plane != null && plane.type == Plane.Type.HORIZONTAL_UPWARD_FACING &&
                            plane.trackingState == TrackingState.TRACKING && plane.isPoseInPolygon(result.hitPose)
                    }
                    if (hit != null) { anchor?.detach(); anchor = hit.createAnchor(); segmentId = UUID.randomUUID().toString() }
                    else report("Aucune table détectée à cet endroit. Déplacez doucement le téléphone puis touchez une surface horizontale.", true)
                }
            }
            frame.camera.getViewMatrix(view, 0)
            frame.camera.getProjectionMatrix(projection, 0, 0.02f, 20f)
            Matrix.multiplyMM(viewProjection, 0, projection, 0, view, 0)
            val activeAnchor = anchor?.takeIf { it.trackingState == TrackingState.TRACKING }
            val measured = ArrayList<Float>(1500)
            val pointMetadata = JSONArray()
            if (activeAnchor != null) {
                val inverse = activeAnchor.pose.inverse()
                val cloud = frame.acquirePointCloud()
                try {
                    val points = cloud.points
                    var index = 0
                    while (index + 3 < points.limit() && measured.size < 1500) {
                        val position = floatArrayOf(points[index], points[index + 1], points[index + 2])
                        val confidence = points[index + 3]
                        val local = inverse.transformPoint(position)
                        if (confidence >= 0.3f && kotlin.math.abs(local[0]) <= volumeWidth / 2f &&
                            local[1] in 0f..volumeHeight && kotlin.math.abs(local[2]) <= volumeDepth / 2f) {
                            measured.addAll(position.toList())
                            if (captureRequested) pointMetadata.put(JSONObject()
                                .put("world", CaptureStore.floats(position)).put("anchorLocal", CaptureStore.floats(local))
                                .put("confidence", confidence.toDouble()))
                        }
                        index += 4
                    }
                } finally { cloud.release() }
                drawGeometry(measured.toFloatArray(), viewProjection, GLES20.GL_POINTS, floatArrayOf(0.42f, 0.75f, 1f, 1f))
                activeAnchor.pose.toMatrix(model, 0)
                Matrix.multiplyMM(modelViewProjection, 0, viewProjection, 0, model, 0)
                drawGeometry(cubeEdges(), modelViewProjection, GLES20.GL_LINES, floatArrayOf(0.83f, 0.94f, 0.60f, 1f))
                report("${measured.size / 3} points de suivi mesurés dans le volume (aperçu clairsemé, pas un modèle).")
            } else report("Déplacez doucement le téléphone, puis touchez la table sous votre assiette pour ancrer le volume.")

            if (captureRequested) {
                captureRequested = false
                if (activeAnchor == null) { onCaptureError("Ancrez le volume sur la table avant de prendre une photo calibrée."); return }
                if (frame.timestamp == lastFrameTimestamp) { onCaptureError("La caméra n’a pas encore fourni une nouvelle image. Réessayez."); return }
                if (capture(frame, activeAnchor, pointMetadata)) {
                    lastFrameTimestamp = frame.timestamp
                    anchorLocked = true
                }
            }
        } catch (error: Exception) {
            val hadCapture = captureRequested
            captureRequested = false
            report("Caméra AR indisponible : ${error.localizedMessage ?: error.javaClass.simpleName}. Le mode photo simple reste disponible.")
            if (hadCapture) onCaptureError("Capture interrompue : ${error.localizedMessage}. Les originaux précédents sont conservés.")
        }
    }

    private fun capture(frame: Frame, activeAnchor: Anchor, points: JSONArray): Boolean {
        try {
            frame.acquireCameraImage().use { image ->
                val cameraPose = frame.camera.pose
                val cameraMatrix = FloatArray(16).also { cameraPose.toMatrix(it, 0) }
                val anchorMatrix = FloatArray(16).also { activeAnchor.pose.toMatrix(it, 0) }
                val relative = FloatArray(16).also { activeAnchor.pose.inverse().compose(cameraPose).toMatrix(it, 0) }
                val intrinsics = frame.camera.imageIntrinsics
                val focal = intrinsics.focalLength; val principal = intrinsics.principalPoint
                val dimensions = intrinsics.imageDimensions
                check(dimensions[0] == image.width && dimensions[1] == image.height) { "La calibration ne correspond pas à l’image CPU." }
                val metadata = JSONObject().put("segmentId", segmentId)
                    .put("frameTimestampNs", frame.timestamp.toString()).put("imageTimestampNs", image.timestamp.toString())
                    .put("trackingState", frame.camera.trackingState.name)
                    .put("displayRotation", rotation()).put("imageRotationAppliedDegrees", 0)
                    .put("cameraToWorld", CaptureStore.floats(cameraMatrix))
                    .put("anchorToWorld", CaptureStore.floats(anchorMatrix))
                    .put("cameraToAnchor", CaptureStore.floats(relative))
                    .put("intrinsics", JSONObject().put("fx", focal[0].toDouble()).put("fy", focal[1].toDouble())
                        .put("cx", principal[0].toDouble()).put("cy", principal[1].toDouble())
                        .put("width", dimensions[0]).put("height", dimensions[1]))
                    .put("volumeMeters", JSONObject().put("width", volumeWidth.toDouble())
                        .put("height", volumeHeight.toDouble()).put("depth", volumeDepth.toDouble()))
                    .put("sparsePoints", points).put("depthFusion", false)
                val bytes = CaptureStore.toNv21(image)
                onPhoto(bytes, image.width, image.height, metadata)
            }
            return true
        } catch (error: Exception) {
            onCaptureError("Image non reçue : ${error.localizedMessage ?: error.javaClass.simpleName}. Réessayez sans déplacer le plat.")
            return false
        }
    }

    private fun drawBackground(frame: Frame) {
        vertices.position(0); textureCoordinates.position(0)
        frame.transformCoordinates2d(Coordinates2d.OPENGL_NORMALIZED_DEVICE_COORDINATES, vertices,
            Coordinates2d.TEXTURE_NORMALIZED, textureCoordinates)
        vertices.position(0); textureCoordinates.position(0)
        GLES20.glDisable(GLES20.GL_DEPTH_TEST); GLES20.glDepthMask(false)
        GLES20.glUseProgram(backgroundProgram)
        val position = GLES20.glGetAttribLocation(backgroundProgram, "aPosition")
        val uv = GLES20.glGetAttribLocation(backgroundProgram, "aUv")
        GLES20.glEnableVertexAttribArray(position); GLES20.glEnableVertexAttribArray(uv)
        GLES20.glVertexAttribPointer(position, 2, GLES20.GL_FLOAT, false, 0, vertices)
        GLES20.glVertexAttribPointer(uv, 2, GLES20.GL_FLOAT, false, 0, textureCoordinates)
        GLES20.glActiveTexture(GLES20.GL_TEXTURE0); GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, textureId)
        GLES20.glUniform1i(GLES20.glGetUniformLocation(backgroundProgram, "uTexture"), 0)
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4)
        GLES20.glDisableVertexAttribArray(position); GLES20.glDisableVertexAttribArray(uv)
        GLES20.glDepthMask(true); GLES20.glEnable(GLES20.GL_DEPTH_TEST)
    }

    private fun drawGeometry(vertices: FloatArray, matrix: FloatArray, mode: Int, color: FloatArray) {
        if (vertices.isEmpty()) return
        GLES20.glUseProgram(geometryProgram)
        val position = GLES20.glGetAttribLocation(geometryProgram, "aPosition")
        GLES20.glEnableVertexAttribArray(position)
        GLES20.glVertexAttribPointer(position, 3, GLES20.GL_FLOAT, false, 0, buffer(vertices))
        GLES20.glUniformMatrix4fv(GLES20.glGetUniformLocation(geometryProgram, "uMvp"), 1, false, matrix, 0)
        GLES20.glUniform4fv(GLES20.glGetUniformLocation(geometryProgram, "uColor"), 1, color, 0)
        GLES20.glLineWidth(2f); GLES20.glDrawArrays(mode, 0, vertices.size / 3)
        GLES20.glDisableVertexAttribArray(position)
    }

    private fun cubeEdges(): FloatArray {
        val w = volumeWidth / 2f; val d = volumeDepth / 2f; val h = volumeHeight
        val corners = arrayOf(floatArrayOf(-w, 0f, -d), floatArrayOf(w, 0f, -d), floatArrayOf(w, 0f, d), floatArrayOf(-w, 0f, d),
            floatArrayOf(-w, h, -d), floatArrayOf(w, h, -d), floatArrayOf(w, h, d), floatArrayOf(-w, h, d))
        val edges = intArrayOf(0, 1, 1, 2, 2, 3, 3, 0, 4, 5, 5, 6, 6, 7, 7, 4, 0, 4, 1, 5, 2, 6, 3, 7)
        return edges.flatMap { corners[it].toList() }.toFloatArray()
    }

    private fun report(text: String, force: Boolean = false) {
        val now = android.os.SystemClock.elapsedRealtime()
        if (force || now - lastStatusAt > 750) { onStatus(text); lastStatusAt = now }
    }

    companion object {
        private fun buffer(data: FloatArray): FloatBuffer = ByteBuffer.allocateDirect(data.size * 4)
            .order(ByteOrder.nativeOrder()).asFloatBuffer().apply { put(data); position(0) }
        private fun program(vertex: String, fragment: String): Int {
            fun shader(type: Int, source: String): Int {
                val id = GLES20.glCreateShader(type); GLES20.glShaderSource(id, source); GLES20.glCompileShader(id)
                val ok = IntArray(1); GLES20.glGetShaderiv(id, GLES20.GL_COMPILE_STATUS, ok, 0)
                check(ok[0] != 0) { GLES20.glGetShaderInfoLog(id) }; return id
            }
            val vertexId = shader(GLES20.GL_VERTEX_SHADER, vertex); val fragmentId = shader(GLES20.GL_FRAGMENT_SHADER, fragment)
            val id = GLES20.glCreateProgram(); GLES20.glAttachShader(id, vertexId); GLES20.glAttachShader(id, fragmentId); GLES20.glLinkProgram(id)
            val ok = IntArray(1); GLES20.glGetProgramiv(id, GLES20.GL_LINK_STATUS, ok, 0)
            GLES20.glDeleteShader(vertexId); GLES20.glDeleteShader(fragmentId)
            check(ok[0] != 0) { GLES20.glGetProgramInfoLog(id) }; return id
        }
    }
}

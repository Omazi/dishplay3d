package com.dishplay.capture

import android.content.Context
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.media.Image
import android.os.Build
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.UUID
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/** Originals and metadata remain private until the user explicitly shares an archive. */
class CaptureStore(private val context: Context) {
    private val root = File(context.filesDir, "captures").apply { mkdirs() }
    private val preferences = context.getSharedPreferences("capture", Context.MODE_PRIVATE)
    var directory: File = preferences.getString("current", null)?.let { File(root, it) }
        ?.takeIf { it.isDirectory } ?: createDirectory()
        private set

    init { preferences.edit().putString("current", directory.name).apply() }

    private fun createDirectory(): File {
        val target = File(root, UUID.randomUUID().toString()).apply { mkdirs() }
        writeAtomic(File(target, "session.json"), JSONObject()
            .put("schema", "dishplay.native-capture.v1")
            .put("id", target.name)
            .put("createdAt", utcNow())
            .put("platform", "android")
            .put("device", "${Build.MANUFACTURER} ${Build.MODEL}")
            .put("androidApi", Build.VERSION.SDK_INT)
            .put("arcoreSdk", "1.56.0")
            .put("reconstruction", "not_run")
            .put("coordinateConventions", JSONObject()
                .put("world", "ARCore right-handed, meters; +Y up; world origin is segment-local")
                .put("camera", "Physical camera-to-world OpenGL pose: +X image-right, +Y image-up, -Z forward")
                .put("image", "Unrotated CPU image. +u right, +v down. Intrinsics refer to this image")
                .put("matrices", "Column-major 4x4; cameraToWorld maps camera to ARCore world")
                .put("segments", "A new segment follows every lifecycle pause, tracking interruption, or anchor replacement; never combine segment poses without registration"))
            .put("limitations", "Sparse tracking features are not a dense surface. No native pairing, upload, reconstruction or scale-quality guarantee.")
            .toString(2))
        return target
    }

    @Synchronized fun newSession(): File {
        directory = createDirectory()
        preferences.edit().putString("current", directory.name).apply()
        return directory
    }

    @Synchronized fun sessions(): List<File> = root.listFiles()?.filter { it.isDirectory }
        ?.sortedByDescending { it.lastModified() } ?: emptyList()

    @Synchronized fun selectSession(target: File) {
        require(target.canonicalFile.parentFile == root.canonicalFile && target.isDirectory)
        directory = target
        preferences.edit().putString("current", directory.name).apply()
    }

    @Synchronized fun count(): Int = directory.listFiles()?.count { it.name.endsWith(".frame.json") } ?: 0

    @Synchronized fun ensureSpace(extraBytes: Long = 0) {
        check(count() < 150) { "150 prises atteintes. Créez une nouvelle série ; les originaux sont conservés." }
        val used = directory.listFiles()?.sumOf { it.length() } ?: 0L
        check(used + extraBytes < 1_073_741_824L) { "La série atteint 1 Go. Exportez-la puis créez une nouvelle série." }
        check(directory.usableSpace > extraBytes + 64L * 1024 * 1024) { "Espace insuffisant. Libérez du stockage puis réessayez." }
    }

    @Synchronized fun saveArFrame(nv21: ByteArray, width: Int, height: Int, metadata: JSONObject) {
        ensureSpace(nv21.size.toLong() * 2)
        val id = UUID.randomUUID().toString()
        val raw = File(directory, "$id.nv21")
        FileOutputStream(raw).use { output -> output.write(nv21); output.fd.sync() }
        val jpeg = File(directory, "$id.jpg")
        FileOutputStream(jpeg).use { output ->
            check(YuvImage(nv21, ImageFormat.NV21, width, height, null)
                .compressToJpeg(Rect(0, 0, width, height), 95, output)) { "Échec de conversion JPEG. Les pixels NV21 restent conservés." }
            output.fd.sync()
        }
        metadata.put("id", id).put("source", "arcore_cpu_camera")
            .put("capturedAt", utcNow())
            .put("width", width).put("height", height)
            .put("original", JSONObject().put("path", raw.name).put("format", "NV21")
                .put("sha256", sha256(raw)).put("bytes", raw.length())
                .put("note", "Lossless planar normalization of YUV_420_888 pixel samples; row padding removed. Not Bayer sensor RAW."))
            .put("photo", JSONObject().put("path", jpeg.name).put("mime", "image/jpeg")
                .put("sha256", sha256(jpeg)).put("bytes", jpeg.length()))
        writeAtomic(File(directory, "$id.frame.json"), metadata.toString(2))
    }

    @Synchronized fun prepareSystemPhoto(): File {
        ensureSpace(25L * 1024 * 1024)
        return File(directory, "${UUID.randomUUID()}.jpg").apply { createNewFile() }
    }

    @Synchronized fun acceptSystemPhoto(photo: File) {
        require(photo.parentFile?.parentFile?.canonicalFile == root.canonicalFile)
        check(photo.length() > 0) { "Aucune photo reçue. Réessayez ; les prises précédentes sont conservées." }
        // Keep the exact camera-app output, including its EXIF rotation. Do not invent calibration.
        val bounds = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
        android.graphics.BitmapFactory.decodeFile(photo.absolutePath, bounds)
        check(bounds.outWidth > 0 && bounds.outHeight > 0) { "Image illisible. Le fichier reçu est conservé pour récupération." }
        writeAtomic(File(photo.parentFile, "${photo.nameWithoutExtension}.frame.json"), JSONObject()
            .put("id", photo.nameWithoutExtension).put("source", "system_camera")
            .put("capturedAt", utcNow()).put("width", bounds.outWidth).put("height", bounds.outHeight)
            .put("segmentId", UUID.randomUUID().toString())
            .put("cameraToWorld", JSONObject.NULL).put("intrinsics", JSONObject.NULL)
            .put("rotation", "Read original EXIF; image bytes are not reoriented")
            .put("original", JSONObject().put("path", photo.name).put("mime", bounds.outMimeType)
                .put("bytes", photo.length()).put("sha256", sha256(photo)))
            .toString(2))
    }

    @Synchronized fun exportArchive(): File {
        check(count() > 0) { "Ajoutez une photo avant l’export." }
        val files = directory.listFiles()?.filter { it.isFile && !it.name.endsWith(".tmp") }
            ?.sortedBy { it.name } ?: emptyList()
        val manifest = JSONObject().put("session", JSONObject(File(directory, "session.json").readText()))
            .put("frames", JSONArray(files.filter { it.name.endsWith(".frame.json") }.map { JSONObject(it.readText()) }))
        val exports = File(context.cacheDir, "exports").apply { mkdirs() }
        val target = File(exports, "dishplay-${directory.name}.zip")
        check(exports.usableSpace > files.sumOf { it.length() } + 64L * 1024 * 1024) { "Espace insuffisant pour préparer l’archive. Les originaux restent dans l’application." }
        val temp = File(exports, "${target.name}.tmp")
        try {
            ZipOutputStream(FileOutputStream(temp).buffered()).use { zip ->
                zip.setLevel(0) // Stream one file at a time; avoid recompressing photos on a phone.
                zip.putNextEntry(ZipEntry("manifest.json")); zip.write(manifest.toString(2).toByteArray()); zip.closeEntry()
                for (file in files) {
                    zip.putNextEntry(ZipEntry(file.name))
                    file.inputStream().buffered().use { it.copyTo(zip, 8192) }
                    zip.closeEntry()
                }
            }
            check(temp.renameTo(target)) { "L’archive n’a pas pu être finalisée." }
            return target
        } finally { temp.delete() }
    }

    companion object {
        private fun utcNow(): String = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", java.util.Locale.US)
            .apply { timeZone = java.util.TimeZone.getTimeZone("UTC") }.format(java.util.Date())
        fun floats(values: FloatArray): JSONArray = JSONArray(values.map { it.toDouble() })
        fun sha256(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().buffered().use { input ->
                val buffer = ByteArray(8192)
                while (true) { val count = input.read(buffer); if (count < 0) break; digest.update(buffer, 0, count) }
            }
            return digest.digest().joinToString("") { "%02x".format(it.toInt() and 255) }
        }
        private fun writeAtomic(file: File, text: String) {
            val temp = File(file.parentFile, "${file.name}.tmp")
            FileOutputStream(temp).use { output -> output.write(text.toByteArray()); output.fd.sync() }
            check(temp.renameTo(file)) { "Métadonnées non enregistrées. Les originaux restent conservés." }
        }

        /** Preserve the actual camera pixels, honoring each plane's row/pixel stride. */
        fun toNv21(image: Image): ByteArray {
            require(image.format == ImageFormat.YUV_420_888)
            require(image.cropRect == Rect(0, 0, image.width, image.height)) { "Recadrage CPU inattendu : capture refusée pour conserver des intrinsics exactes." }
            val width = image.width; val height = image.height
            require(width % 2 == 0 && height % 2 == 0 && width.toLong() * height <= 8_000_000L) { "Résolution CPU non prise en charge (limite 8 MP)." }
            val output = ByteArray(width * height * 3 / 2)
            for (planeIndex in 0..2) {
                val plane = image.planes[planeIndex]; val buffer = plane.buffer.duplicate()
                val start = buffer.position()
                val planeWidth = if (planeIndex == 0) width else width / 2
                val planeHeight = if (planeIndex == 0) height else height / 2
                for (row in 0 until planeHeight) for (column in 0 until planeWidth) {
                    val value = buffer.get(start + row * plane.rowStride + column * plane.pixelStride)
                    val index = if (planeIndex == 0) row * width + column else width * height + row * width + column * 2 + if (planeIndex == 1) 1 else 0
                    output[index] = value
                }
            }
            return output
        }
    }
}

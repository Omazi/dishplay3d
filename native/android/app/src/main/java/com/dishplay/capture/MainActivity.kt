package com.dishplay.capture

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.opengl.GLSurfaceView
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.view.Gravity
import android.view.MotionEvent
import android.view.Surface
import android.view.View
import android.view.WindowInsets
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.SeekBar
import android.widget.TextView
import androidx.core.content.FileProvider
import com.google.ar.core.ArCoreApk
import com.google.ar.core.Config
import com.google.ar.core.Session
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class MainActivity : Activity() {
    private lateinit var store: CaptureStore
    private lateinit var surface: GLSurfaceView
    private lateinit var renderer: ArRenderer
    private lateinit var status: TextView
    private lateinit var summary: TextView
    private lateinit var captureButton: Button
    private lateinit var arButton: Button
    private lateinit var fallbackButton: Button
    private lateinit var exportButton: Button
    private lateinit var newButton: Button
    private lateinit var historyButton: Button
    private val dimensionControls = ArrayList<SeekBar>()
    private val writer = Executors.newSingleThreadExecutor()
    private val busy = AtomicBoolean(false)
    private val mainHandler = Handler(Looper.getMainLooper())
    @Volatile private var arSession: Session? = null
    private var arRunning = false
    private var wantAr = false
    private var installRequested = false
    private var resumed = false
    private var permissionAction = ""
    private var pendingPhoto: File? = null
    private var messageUntil = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = CaptureStore(this)
        pendingPhoto = savedInstanceState?.getString("pendingPhoto")?.let(::File)
        permissionAction = savedInstanceState?.getString("permissionAction") ?: ""
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        buildInterface()
        refreshSummary()
        showMessage("Photos réelles, conservées sur cet appareil. Activez le guidage AR si disponible, ou utilisez l’appareil photo simple.")
    }

    private fun buildInterface() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.rgb(248, 248, 242))
            setPadding(dp(16), dp(10), dp(16), dp(12))
        }
        if (Build.VERSION.SDK_INT >= 30) root.setOnApplyWindowInsetsListener { view, insets ->
            val bars = insets.getInsets(WindowInsets.Type.systemBars())
            view.setPadding(dp(16) + bars.left, dp(10) + bars.top, dp(16) + bars.right, dp(12) + bars.bottom)
            insets
        } else root.fitsSystemWindows = true
        root.addView(text("dishplay.  /  Capture", 25f, true))
        summary = text("", 12f)
        root.addView(summary)
        status = text("", 14f).apply {
            minHeight = dp(74)
            setPadding(0, dp(8), 0, dp(8))
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        root.addView(status)

        renderer = ArRenderer(
            session = { arSession },
            rotation = { if (Build.VERSION.SDK_INT >= 30) display?.rotation ?: Surface.ROTATION_0 else @Suppress("DEPRECATION") windowManager.defaultDisplay.rotation },
            onStatus = { message -> runOnUiThread { if (System.currentTimeMillis() > messageUntil && arRunning) status.text = message } },
            onPhoto = { bytes, width, height, metadata ->
                writer.execute {
                    try {
                        store.saveArFrame(bytes, width, height, metadata)
                        runOnUiThread { showMessage("Photo et mesures enregistrées. Déplacez-vous légèrement, puis prenez la vue suivante."); refreshSummary() }
                    } catch (error: Exception) {
                        runOnUiThread { showMessage(error.localizedMessage ?: "Échec d’enregistrement. Les prises précédentes sont conservées.") }
                    } finally { busy.set(false); runOnUiThread { updateControls() } }
                }
            },
            onCaptureError = { message -> busy.set(false); runOnUiThread { showMessage(message); updateControls() } },
        )
        surface = GLSurfaceView(this).apply {
            setEGLContextClientVersion(2)
            preserveEGLContextOnPause = true
            setRenderer(renderer)
            renderMode = GLSurfaceView.RENDERMODE_CONTINUOUSLY
            contentDescription = "Caméra AR. Touchez la table sous le plat pour ancrer le volume."
            setOnTouchListener { view, event ->
                if (event.action == MotionEvent.ACTION_UP) { renderer.tap(event.x, event.y); view.performClick() }
                true
            }
        }
        root.addView(surface, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f).apply {
            topMargin = dp(5); bottomMargin = dp(8)
        })
        root.addView(text("L’assiette reste immobile. Faites le tour à plusieurs hauteurs. Ne retournez pas le plat.", 12f))
        dimensionControl(root, "Largeur", 30) { renderer.volumeWidth = it }
        dimensionControl(root, "Hauteur", 18) { renderer.volumeHeight = it }
        dimensionControl(root, "Profondeur", 30) { renderer.volumeDepth = it }
        val row1 = row(); val row2 = row()
        arButton = button("Activer le guidage AR") { if (arRunning) { wantAr = false; pauseAr(); showMessage("Caméra en pause. Vos prises sont conservées.") } else requestCamera("ar") }
        captureButton = button("Prendre une photo") {
            if (arRunning && busy.compareAndSet(false, true)) { renderer.captureRequested = true; updateControls() }
        }
        row1.addView(arButton, weighted()); row1.addView(captureButton, weighted())
        fallbackButton = button("Photo simple") { requestCamera("photo") }
        exportButton = button("Exporter ZIP") { exportCapture() }
        row2.addView(fallbackButton, weighted()); row2.addView(exportButton, weighted())
        root.addView(row1); root.addView(row2)
        val row3 = row()
        newButton = button("Nouvelle série") {
            if (busy.get()) return@button
            wantAr = false; pauseAr()
            try {
                store.newSession(); renderer.anchorLocked = false; surface.queueEvent { renderer.resetAnchor() }
                showMessage("Nouvelle série créée. Les précédentes restent accessibles via Mes séries.")
            } catch (error: Exception) { showMessage(error.localizedMessage ?: "La nouvelle série n’a pas pu être créée. Les précédentes sont conservées.") }
            refreshSummary(); updateControls()
        }
        historyButton = button("Mes séries") { chooseSession() }
        row3.addView(newButton, weighted()); row3.addView(historyButton, weighted())
        root.addView(row3)
        root.addView(text("Aperçu clairsemé réel · Aucune reconstruction dans cette app · Aucune association de compte", 10f))
        setContentView(root)
        surface.onPause()
        updateControls()
    }

    private fun dimensionControl(root: LinearLayout, label: String, initialCm: Int, changed: (Float) -> Unit) {
        val row = row()
        val value = text("$label : $initialCm cm", 12f)
        row.addView(value, LinearLayout.LayoutParams(dp(112), dp(41)))
        val slider = SeekBar(this).apply {
            max = 95; progress = initialCm - 5
            contentDescription = "$label du volume, de 5 à 100 centimètres"
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(seekBar: SeekBar?, progress: Int, fromUser: Boolean) {
                    value.text = "$label : ${progress + 5} cm"
                    changed((progress + 5) / 100f)
                }
                override fun onStartTrackingTouch(seekBar: SeekBar?) {}
                override fun onStopTrackingTouch(seekBar: SeekBar?) {}
            })
        }
        dimensionControls.add(slider)
        row.addView(slider, LinearLayout.LayoutParams(0, dp(41), 1f)); root.addView(row)
    }

    private fun requestCamera(action: String) {
        if (busy.get()) return
        permissionAction = action
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.CAMERA), CAMERA_PERMISSION)
        } else if (action == "ar") { wantAr = true; enableAr() } else launchSystemCamera()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != CAMERA_PERMISSION) return
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
            if (permissionAction == "ar") { wantAr = true; enableAr() } else launchSystemCamera()
        } else showMessage("Caméra refusée. Autorisez-la dans les réglages Android puis réessayez. Les prises déjà enregistrées restent exportables.")
    }

    private fun enableAr(attempt: Int = 0) {
        if (!resumed || !wantAr || arRunning) return
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) return
        try {
            val apk = ArCoreApk.getInstance()
            val availability = apk.checkAvailability(this)
            if (availability.isTransient && attempt < 8) {
                showMessage("Vérification du support ARCore…")
                mainHandler.postDelayed({ enableAr(attempt + 1) }, 250)
                return
            }
            if (!availability.isSupported) {
                wantAr = false
                showMessage("Guidage AR indisponible sur cet appareil. Le bouton Photo simple utilise votre appareil photo sans poses ni aperçu spatial.")
                return
            }
            if (arSession == null) {
                if (apk.requestInstall(this, !installRequested) == ArCoreApk.InstallStatus.INSTALL_REQUESTED) {
                    installRequested = true
                    showMessage("Terminez l’installation de Google Play Services pour AR, puis revenez dans DishPlay.")
                    return
                }
                val created = Session(this)
                try {
                    created.configure(Config(created).apply {
                        planeFindingMode = Config.PlaneFindingMode.HORIZONTAL
                        focusMode = Config.FocusMode.AUTO
                        depthMode = Config.DepthMode.DISABLED
                        updateMode = Config.UpdateMode.LATEST_CAMERA_IMAGE
                    })
                    arSession = created
                } catch (error: Exception) { created.close(); throw error }
            }
            arSession?.resume()
            arRunning = true
            surface.queueEvent { renderer.interruptTracking() }
            surface.onResume()
            showMessage("Cadrez la table et déplacez doucement le téléphone. Touchez la table pour placer le volume autour du plat.")
            updateControls()
        } catch (error: Exception) {
            wantAr = false; installRequested = false; pauseAr()
            showMessage("Le guidage AR n’a pas démarré : ${error.localizedMessage ?: error.javaClass.simpleName}. Utilisez Photo simple ou réessayez.")
        }
    }

    private fun pauseAr() {
        if (renderer.captureRequested) { renderer.captureRequested = false; busy.set(false) }
        surface.queueEvent { renderer.interruptTracking() }
        surface.onPause() // Pause rendering before pausing ARCore: no update() on a paused session.
        if (arRunning) {
            try { arSession?.pause() } catch (_: Exception) { }
        }
        arRunning = false
        updateControls()
    }

    @Suppress("DEPRECATION")
    private fun launchSystemCamera() {
        wantAr = false; pauseAr()
        try {
            val photo = store.prepareSystemPhoto()
            val uri = FileProvider.getUriForFile(this, "$packageName.files", photo)
            val intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE).apply {
                putExtra(MediaStore.EXTRA_OUTPUT, uri)
                clipData = ClipData.newRawUri("Photo DishPlay", uri)
                addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            if (intent.resolveActivity(packageManager) == null) { photo.delete(); showMessage("Aucune application appareil photo disponible."); return }
            pendingPhoto = photo
            startActivityForResult(intent, SYSTEM_PHOTO)
        } catch (error: Exception) { showMessage("Impossible d’ouvrir l’appareil photo : ${error.localizedMessage}") }
    }

    @Deprecated("The platform camera intent uses Activity's supported result callback on API 24+")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != SYSTEM_PHOTO) return
        val photo = pendingPhoto ?: return
        pendingPhoto = null
        if (resultCode != RESULT_OK) {
            if (photo.length() == 0L) photo.delete()
            showMessage("Prise annulée. Les photos précédentes sont conservées.")
            return
        }
        busy.set(true); updateControls()
        writer.execute {
            try {
                store.acceptSystemPhoto(photo)
                runOnUiThread { showMessage("Photo originale enregistrée. Mode simple : aucune pose ni calibration inventée."); refreshSummary() }
            } catch (error: Exception) { runOnUiThread { showMessage(error.localizedMessage ?: "Photo non reçue.") } }
            finally { busy.set(false); runOnUiThread { updateControls() } }
        }
    }

    private fun exportCapture() {
        if (!busy.compareAndSet(false, true)) return
        wantAr = false; pauseAr(); updateControls()
        showMessage("Préparation de l’archive, un fichier à la fois. Les originaux restent dans l’application.")
        writer.execute {
            try {
                val archive = store.exportArchive()
                runOnUiThread {
                    if (isFinishing || isDestroyed) return@runOnUiThread
                    val uri = FileProvider.getUriForFile(this, "$packageName.files", archive)
                    val intent = Intent(Intent.ACTION_SEND).apply {
                        type = "application/zip"; putExtra(Intent.EXTRA_STREAM, uri)
                        clipData = ClipData.newRawUri("Capture DishPlay", uri)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    startActivity(Intent.createChooser(intent, "Exporter les originaux DishPlay"))
                    showMessage("Archive prête. Après extraction, les JPEG peuvent être importés dans la capture web. Aucune synchronisation automatique n’est effectuée.")
                }
            } catch (error: Exception) { runOnUiThread { showMessage(error.localizedMessage ?: "Export indisponible. Les originaux restent conservés.") } }
            finally { busy.set(false); runOnUiThread { updateControls() } }
        }
    }

    private fun chooseSession() {
        if (busy.get()) return
        val sessions = store.sessions()
        val labels = sessions.map { file ->
            val count = file.listFiles()?.count { it.name.endsWith(".frame.json") } ?: 0
            "${file.name.take(8)} · $count photo(s)${if (file == store.directory) " · actuelle" else ""}"
        }.toTypedArray()
        AlertDialog.Builder(this).setTitle("Séries conservées sur cet appareil")
            .setItems(labels) { _, index ->
                wantAr = false; pauseAr(); store.selectSession(sessions[index])
                renderer.anchorLocked = false
                surface.queueEvent { renderer.resetAnchor() }
                refreshSummary(); updateControls()
                showMessage("Série ouverte. Une nouvelle capture AR utilisera un segment distinct. Exportez pour conserver une copie hors de l’appareil.")
            }.setNegativeButton("Fermer", null).show()
    }

    private fun refreshSummary() {
        summary.text = "Série ${store.directory.name.take(8)} · ${store.count()} / 150 photos · originaux privés"
    }

    private fun updateControls() {
        if (!::captureButton.isInitialized || isDestroyed) return
        val available = !busy.get()
        captureButton.isEnabled = available && arRunning
        captureButton.text = if (busy.get()) "Enregistrement…" else "Prendre une photo"
        arButton.isEnabled = available
        arButton.text = if (arRunning) "Mettre en pause" else "Activer le guidage AR"
        fallbackButton.isEnabled = available
        exportButton.isEnabled = available && store.hasOriginals()
        newButton.isEnabled = available
        historyButton.isEnabled = available
        dimensionControls.forEach { it.isEnabled = available && !renderer.anchorLocked }
    }

    private fun showMessage(message: String) {
        if (isDestroyed) return
        status.text = message
        messageUntil = System.currentTimeMillis() + 4500
    }

    override fun onResume() {
        super.onResume(); resumed = true
        if (wantAr) enableAr()
    }

    override fun onPause() {
        resumed = false; pauseAr()
        super.onPause()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        pendingPhoto?.let { outState.putString("pendingPhoto", it.absolutePath) }
        outState.putString("permissionAction", permissionAction)
        super.onSaveInstanceState(outState)
    }

    override fun onDestroy() {
        mainHandler.removeCallbacksAndMessages(null)
        surface.onPause()
        arSession?.close(); arSession = null
        writer.shutdown() // Allow already accepted original writes to complete.
        super.onDestroy()
    }

    private fun text(value: String, size: Float, bold: Boolean = false): TextView = TextView(this).apply {
        text = value; textSize = size; setTextColor(Color.rgb(37, 40, 36))
        if (bold) setTypeface(typeface, android.graphics.Typeface.BOLD)
        gravity = Gravity.CENTER_VERTICAL
    }
    private fun button(label: String, click: () -> Unit): Button = Button(this).apply {
        text = label; textSize = 11f; isAllCaps = false; minHeight = dp(44)
        setOnClickListener { click() }
    }
    private fun row() = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
    private fun weighted() = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    companion object {
        private const val CAMERA_PERMISSION = 100
        private const val SYSTEM_PHOTO = 101
    }
}

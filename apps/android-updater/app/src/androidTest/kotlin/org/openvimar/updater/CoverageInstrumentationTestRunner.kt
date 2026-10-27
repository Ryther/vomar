package org.openvimar.updater

import android.os.Build
import android.os.Bundle
import android.test.InstrumentationTestRunner
import java.io.File

/** Preserve the existing JUnit3 suite while exporting AGP's real JaCoCo data.
 * The platform runner only knows EMMA. Coverage collection is emulator-only. */
@Suppress("DEPRECATION")
class CoverageInstrumentationTestRunner : InstrumentationTestRunner() {
    private var collectCoverage = false
    private var coveragePath: String? = null

    override fun onCreate(arguments: Bundle) {
        collectCoverage = arguments.getString("coverage") == "true"
        coveragePath = arguments.getString("coverageFile")
        if (collectCoverage) {
            check(Build.HARDWARE in setOf("ranchu", "goldfish")) { "Coverage instrumentation requires an emulator" }
        }
        super.onCreate(Bundle(arguments).apply { putString("coverage", "false") })
    }

    override fun finish(resultCode: Int, results: Bundle) {
        if (collectCoverage) {
            val runtime = Class.forName("org.jacoco.agent.rt.RT", true, targetContext.classLoader)
            val getAgent = runtime.getMethod("getAgent")
            val data = getAgent.returnType.getMethod("getExecutionData", Boolean::class.javaPrimitiveType)
                .invoke(getAgent.invoke(null), false) as ByteArray
            check(data.isNotEmpty()) { "JaCoCo produced no execution data" }
            // Android creates the app-owned external root through Context.
            // A focused journey may never request screenshots/external files;
            // coverage must not depend on another test preparing that root.
            targetContext.getExternalFilesDir(null)
            val destination = coveragePath?.let(::File) ?: File(targetContext.filesDir, "coverage.ec")
            val parent = requireNotNull(destination.absoluteFile.parentFile)
            check(parent.isDirectory || parent.mkdirs()) { "Coverage directory unavailable: $parent" }
            destination.writeBytes(data)
            results.putString("coverageFilePath", destination.absolutePath)
        }
        super.finish(resultCode, results)
    }
}

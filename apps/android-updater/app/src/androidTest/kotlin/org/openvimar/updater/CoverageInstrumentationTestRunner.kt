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
            val destination = coveragePath?.let(::File) ?: File(targetContext.filesDir, "coverage.ec")
            destination.parentFile?.mkdirs()
            destination.writeBytes(data)
            results.putString("coverageFilePath", destination.absolutePath)
        }
        super.finish(resultCode, results)
    }
}

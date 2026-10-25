// Export deterministic function and direct-call inventories.
// @category Vimar30805

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;
import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

public class ExportFunctions extends GhidraScript {
    private record Edge(Address caller, Address callee, Address callsite) {}

    private static String hex(Address address) {
        return String.format("0x%08x", address.getUnsignedOffset());
    }

    private static String clean(String value) {
        return value.replace("\\", "\\\\")
            .replace("\t", "\\t")
            .replace("\r", "\\r")
            .replace("\n", "\\n");
    }

    @Override
    protected void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length != 1) {
            throw new IllegalArgumentException("expected: output_directory");
        }
        Path outputDirectory = Path.of(arguments[0]);
        Files.createDirectories(outputDirectory);

        List<Function> functions = new ArrayList<>();
        currentProgram.getFunctionManager().getFunctions(true).forEachRemaining(functions::add);
        functions.sort(Comparator.comparingLong(
            function -> function.getEntryPoint().getUnsignedOffset()
        ));

        List<Edge> edges = new ArrayList<>();
        Set<String> seenEdges = new LinkedHashSet<>();
        for (Function caller : functions) {
            for (Instruction instruction : currentProgram.getListing()
                    .getInstructions(caller.getBody(), true)) {
                for (Reference reference : instruction.getReferencesFrom()) {
                    if (!reference.getReferenceType().isCall()) continue;
                    Function callee = currentProgram.getFunctionManager()
                        .getFunctionAt(reference.getToAddress());
                    if (callee == null) continue;
                    Edge edge = new Edge(
                        caller.getEntryPoint(), callee.getEntryPoint(), instruction.getAddress()
                    );
                    String key = hex(edge.caller()) + ":" + hex(edge.callee()) + ":"
                        + hex(edge.callsite());
                    if (seenEdges.add(key)) edges.add(edge);
                }
            }
        }
        edges.sort(Comparator
            .comparingLong((Edge edge) -> edge.caller().getUnsignedOffset())
            .thenComparingLong(edge -> edge.callee().getUnsignedOffset())
            .thenComparingLong(edge -> edge.callsite().getUnsignedOffset()));

        try (BufferedWriter writer = Files.newBufferedWriter(
                outputDirectory.resolve("functions.tsv"), StandardCharsets.UTF_8)) {
            writer.write("address\tname\tsize\tthunk\tentry\tcallers\tcallees\n");
            for (Function function : functions) {
                int callers = function.getCallingFunctions(monitor).size();
                int callees = function.getCalledFunctions(monitor).size();
                writer.write(hex(function.getEntryPoint()) + "\t"
                    + clean(function.getName()) + "\t"
                    + function.getBody().getNumAddresses() + "\t"
                    + function.isThunk() + "\t"
                    + currentProgram.getSymbolTable().isExternalEntryPoint(
                        function.getEntryPoint()) + "\t"
                    + callers + "\t" + callees + "\n");
            }
        }

        try (BufferedWriter writer = Files.newBufferedWriter(
                outputDirectory.resolve("call_edges.tsv"), StandardCharsets.UTF_8)) {
            writer.write("caller\tcallee\tcallsite\n");
            for (Edge edge : edges) {
                writer.write(hex(edge.caller()) + "\t" + hex(edge.callee()) + "\t"
                    + hex(edge.callsite()) + "\n");
            }
        }
    }
}

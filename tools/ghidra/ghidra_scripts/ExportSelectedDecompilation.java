// Export deterministic decompilation for explicitly configured addresses.
// @category Vimar30805

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class ExportSelectedDecompilation extends GhidraScript {
    private record Target(String target, String label, long address) {}
    private record Result(String label, long address, String status, String file) {}

    private static final Pattern TARGET_PATTERN = Pattern.compile(
        "\\{\\s*\"target\"\\s*:\\s*\"([^\"]+)\"\\s*,\\s*"
        + "\"label\"\\s*:\\s*\"([a-z0-9_]+)\"\\s*,\\s*"
        + "\"address\"\\s*:\\s*\"(0x[0-9a-fA-F]+)\"\\s*,\\s*"
        + "\"classification\"\\s*:\\s*\"([^\"]+)\"\\s*,\\s*"
        + "\"evidence\"\\s*:\\s*\"([^\"]+)\"\\s*\\}"
    );

    private static String hex(long address) {
        return String.format("0x%08x", address);
    }

    private static String normalize(String text) {
        String[] lines = text.replace("\r\n", "\n").replace('\r', '\n').split("\n", -1);
        StringBuilder output = new StringBuilder();
        for (String line : lines) {
            output.append(line.replaceFirst("\\s+$", "")).append('\n');
        }
        while (output.length() > 1 && output.charAt(output.length() - 2) == '\n') {
            output.deleteCharAt(output.length() - 1);
        }
        return output.toString();
    }

    private static List<Target> readTargets(Path path, String selectedTarget) throws Exception {
        String json = Files.readString(path, StandardCharsets.UTF_8);
        Matcher matcher = TARGET_PATTERN.matcher(json);
        List<Target> targets = new ArrayList<>();
        while (matcher.find()) {
            String target = matcher.group(1);
            if (target.equals(selectedTarget)) {
                targets.add(new Target(target, matcher.group(2), Long.decode(matcher.group(3))));
            }
        }
        if (targets.isEmpty()) {
            throw new IllegalArgumentException("no decompilation targets for " + selectedTarget);
        }
        targets.sort(Comparator.comparingLong(Target::address).thenComparing(Target::label));
        return targets;
    }

    @Override
    protected void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length != 3) {
            throw new IllegalArgumentException("expected: output_directory target configuration");
        }
        Path directory = Path.of(arguments[0]).resolve("decompilation");
        List<Target> targets = readTargets(Path.of(arguments[2]), arguments[1]);
        Files.createDirectories(directory);

        DecompInterface decompiler = new DecompInterface();
        if (!decompiler.openProgram(currentProgram)) {
            throw new IllegalStateException("unable to initialize decompiler");
        }
        List<Result> results = new ArrayList<>();
        try {
            for (Target target : targets) {
                Address address = currentProgram.getAddressFactory()
                    .getDefaultAddressSpace().getAddress(target.address());
                Function function = currentProgram.getFunctionManager().getFunctionAt(address);
                if (function == null) {
                    if (disassemble(address)) {
                        createFunction(address, target.label());
                        function = currentProgram.getFunctionManager().getFunctionAt(address);
                    }
                    if (function == null) {
                        results.add(new Result(target.label(), target.address(), "not_a_function", ""));
                        continue;
                    }
                }
                DecompileResults decompiled = decompiler.decompileFunction(function, 60, monitor);
                if (!decompiled.decompileCompleted() || decompiled.getDecompiledFunction() == null) {
                    String message = decompiled.getErrorMessage().toLowerCase();
                    String status = message.contains("timeout") ? "timeout" : "decompiler_error";
                    results.add(new Result(target.label(), target.address(), status, ""));
                    continue;
                }
                String filename = target.label() + "-" + hex(target.address()) + ".c";
                String code = normalize(decompiled.getDecompiledFunction().getC());
                Files.writeString(directory.resolve(filename), code, StandardCharsets.UTF_8);
                results.add(new Result(target.label(), target.address(), "success", filename));
            }
        }
        finally {
            decompiler.dispose();
        }

        try (BufferedWriter writer = Files.newBufferedWriter(
                directory.resolve("index.tsv"), StandardCharsets.UTF_8)) {
            writer.write("label\taddress\tstatus\tfile\n");
            for (Result result : results) {
                writer.write(result.label() + "\t" + hex(result.address()) + "\t"
                    + result.status() + "\t" + result.file() + "\n");
            }
        }
    }
}
